"""Phase 3 edge-triggered live/degraded pipeline coordinator."""

from __future__ import annotations

import os
import time
from threading import RLock
from uuid import uuid4

from backend.app.adapters import (
    AdapterError,
    InteractionSource,
    ModelSource,
    PerceptionSource,
    Phase3Settings,
    Step3Adapter,
    StepAudioAdapter,
    VisionAdapter,
    VisionObservation,
    fixed_step3_fallback,
)
from backend.app.demo_media import SyntheticSceneCatalog
from backend.app.orchestrator import InvalidOperation, Orchestrator, SessionState
from backend.app.schemas.events import NetworkScope
from backend.app.schemas.music import BrowserPlaybackReport, BrowserPlaybackReportStatus
from backend.app.schemas.speech import (
    AssistantReply,
    AssistantReplySource,
    TTSPlaybackStatus,
)
from backend.app.schemas.step3 import StateLabel
from backend.app.state_machine import DemoState


FALLBACK_TRANSCRIPT = "今天有点累"
DEMO_AUDIO_FILENAME = "spark_today_tired_zh_cn.wav"
FALLBACK_REPLIES = {
    StateLabel.PHYSICAL_FATIGUE: "听起来你今天身体确实有些疲惫，先让自己慢下来休息一会儿吧。",
    StateLabel.EMOTIONAL_LOW: "谢谢你说明现在心情有些低落，我会陪你慢一点，不急着做决定。",
    StateLabel.OTHER: "谢谢你说明自己的状态，我们可以按你舒服的节奏继续。",
}


class LiveCoordinator:
    def __init__(
        self,
        orchestrator: Orchestrator,
        *,
        settings: Phase3Settings | None = None,
        vision: VisionAdapter | None = None,
        audio: StepAudioAdapter | None = None,
        step3: Step3Adapter | None = None,
        scenes: SyntheticSceneCatalog | None = None,
        confirmation_samples: int = 2,
    ) -> None:
        self.orchestrator = orchestrator
        self.settings = settings or Phase3Settings.from_environment()
        self.vision = vision or VisionAdapter(
            self.settings.camera_index, self.settings.video_path
        )
        self.audio = audio or StepAudioAdapter(
            self.settings.stepaudio_url, self.settings.stepaudio_filename
        )
        self.step3 = step3 or Step3Adapter(self.settings.step3_url)
        self.scenes = scenes or SyntheticSceneCatalog()
        self.confirmation_samples = max(1, confirmation_samples)
        self.current_session_id: str | None = None
        self._confirmed_present = False
        self._candidate_present: bool | None = None
        self._candidate_count = 0
        self._lock = RLock()
        self.last_visual_attempt: dict[str, object] | None = None

    def health(self) -> dict[str, object]:
        return {
            "mode": "LIVE_WITH_SAFE_FALLBACKS",
            "deployment": {
                "backend": os.environ.get(
                    "SPARK_DEPLOYMENT_TARGET", "LOCAL_WORKSTATION"
                ),
                "console_access": os.environ.get(
                    "SPARK_CONSOLE_ACCESS", "LOCAL_DIRECT"
                ),
            },
            "components": [
                self.vision.health().as_dict(),
                self.audio.health().as_dict(),
                self.step3.health().as_dict(),
                *self.orchestrator.phase4_health(),
            ],
            "raw_media_persisted": False,
            "synthetic_scene_bundled": True,
            "last_visual_attempt": self.last_visual_attempt,
        }

    def analyze_synthetic_scene(
        self, scene_id: str, city_code: str = "310000"
    ) -> tuple[dict[str, object], SessionState | None]:
        """Run one real Step3-VL call against an allowlisted Demo image."""

        attempt_id = f"perception-{uuid4().hex}"
        started = time.monotonic()
        with self._lock:
            try:
                scene = self.scenes.get(scene_id)
                if scene is None:
                    raise AdapterError("DEMO_SCENE_NOT_FOUND", "Demo scene is not allowlisted")
                image, content_type = self.scenes.read_image(scene_id)
                output, model_latency_ms = self.step3.perceive_image(
                    image, content_type
                )
            except AdapterError as error:
                latency_ms = max(0, round((time.monotonic() - started) * 1000))
                self.last_visual_attempt = {
                    "attempt_id": attempt_id,
                    "scene_id": scene_id,
                    "status": "FAILED",
                    "error": error.code,
                    "latency_ms": latency_ms,
                    "session_unchanged": True,
                }
                raise

            perception_source = (
                PerceptionSource.SYNTHETIC_IMAGE
                if scene.synthetic
                else PerceptionSource.DEMO_IMAGE
            )
            observation: dict[str, object] = {
                "attempt_id": attempt_id,
                "scene_id": scene_id,
                "synthetic": scene.synthetic,
                "perception_source": perception_source.value,
                "model_source": ModelSource.STEP3.value,
                "network_scope": NetworkScope.LOCAL.value,
                "person_present": output.person_present,
                "scene_type": output.scene_type.value,
                "scene_summary": output.scene_summary,
                "confidence": output.confidence,
                "confidence_kind": "MODEL_SELF_REPORTED_UNCALIBRATED",
                "evidence": list(output.evidence),
                "latency_ms": model_latency_ms,
                "raw_request_persisted": False,
                "raw_response_persisted": False,
            }
            self.last_visual_attempt = {
                "attempt_id": attempt_id,
                "scene_id": scene_id,
                "status": "SUCCEEDED",
                "person_present": output.person_present,
                "latency_ms": model_latency_ms,
            }

            session: SessionState | None = None
            if self.current_session_id is not None:
                candidate = self.orchestrator.get_session(self.current_session_id)
                if candidate.active:
                    session = candidate
                else:
                    self.current_session_id = None

            if output.person_present:
                if session is None:
                    session = self.orchestrator.begin_live_session(
                        perception_source=perception_source.value,
                        degraded_reasons=[],
                        visual_perception=output,
                        visual_scene_id=scene_id,
                        wait_for_fixed_text=True,
                        city_code=city_code,
                    )
                    self.current_session_id = session.session_id
                else:
                    session.visual_perception = output
                    session.visual_scene_id = scene_id
                    session.person_present = True
                session.component_health["STEP3_VISION"] = {
                    "available": True,
                    "status": "SUCCEEDED",
                    "latency_ms": model_latency_ms,
                }
                self._record_synthetic_vision_call(session, observation, "PERSON_APPEARED")
            elif session is not None:
                session.visual_perception = output
                session.visual_scene_id = scene_id
                session.component_health["STEP3_VISION"] = {
                    "available": True,
                    "status": "SUCCEEDED",
                    "latency_ms": model_latency_ms,
                }
                self._record_synthetic_vision_call(session, observation, "PERSON_DISAPPEARED")
                self.orchestrator.reset_session(session.session_id)
                self.current_session_id = None

            return observation, session

    def poll(self, city_code: str = "310000") -> tuple[VisionObservation, SessionState | None]:
        with self._lock:
            observation = self.vision.observe()
            if observation.person_present == self._candidate_present:
                self._candidate_count += 1
            else:
                self._candidate_present = observation.person_present
                self._candidate_count = 1

            if (
                self._candidate_count >= self.confirmation_samples
                and observation.person_present != self._confirmed_present
            ):
                self._confirmed_present = observation.person_present
                if observation.person_present:
                    session = self.orchestrator.begin_live_session(
                        perception_source=observation.source.value,
                        degraded_reasons=list(observation.degraded_reasons)
                        + (["VISION_STATIC_FALLBACK"] if observation.degraded else []),
                        city_code=city_code,
                    )
                    self.current_session_id = session.session_id
                    session.component_health["VISION"] = {
                        "available": True,
                        "status": observation.source.value,
                        "latency_ms": observation.latency_ms,
                    }
                    self._record_vision_event(session, observation, "PERSON_APPEARED")
                    self._run_asr(session, observation.jpeg)
                elif self.current_session_id is not None:
                    session = self.orchestrator.get_session(self.current_session_id)
                    if session.active:
                        self._record_vision_event(session, observation, "PERSON_DISAPPEARED")
                        self.orchestrator.reset_session(session.session_id)
                    self.current_session_id = None

            session = (
                self.orchestrator.get_session(self.current_session_id)
                if self.current_session_id is not None
                else None
            )
            return observation, session

    def submit_fallback_transcript(self, session_id: str, text: str) -> SessionState:
        if text != FALLBACK_TRANSCRIPT:
            raise InvalidOperation("live transcript must be the fixed synthetic Demo phrase")
        session = self.orchestrator.get_session(session_id)
        if session.interaction_source != "TEXT_FALLBACK_PENDING":
            raise InvalidOperation("session is not waiting for text fallback")
        self.orchestrator.audit_log.record(
            session_id=session_id,
            event_type="TEXT_FALLBACK_INPUT",
            payload={"text_code": "FIXED_TIREDNESS_PHRASE", "synthetic": True},
            status="ACCEPTED",
            source_agent="text-fallback",
        )
        return self._run_step3(
            session,
            transcript=text,
            interaction_source=InteractionSource.TEXT_FALLBACK,
            jpeg=None,
        )

    def run_speech_demo(self, session_id: str) -> SessionState:
        """Transcribe only the server-owned fixed synthetic WAV."""

        session = self.orchestrator.get_session(session_id)
        if session.runtime_mode != "LIVE" or session.state is not DemoState.LISTENING:
            raise InvalidOperation("LIVE session is not waiting for synthetic speech")
        if self.audio.filename != DEMO_AUDIO_FILENAME:
            raise InvalidOperation("fixed synthetic StepAudio asset is not configured")
        self.orchestrator.audit_log.record(
            session_id=session_id,
            event_type="SYNTHETIC_SPEECH_DEMO_REQUESTED",
            payload={
                "asset_code": "FIXED_TODAY_TIRED_ZH_CN",
                "synthetic": True,
                "microphone_used": False,
                "raw_audio_persisted": False,
            },
            status="ACCEPTED",
            source_agent="live-coordinator",
            network_scope=NetworkScope.LOCAL,
        )
        self._run_asr(session, None)
        return session

    def clarify(self, session_id: str, answer: StateLabel) -> SessionState:
        """Retained only as a compatibility guard for the disabled route."""

        session = self.orchestrator.get_session(session_id)
        if session.selected_state is not None and session.assistant_reply is not None:
            return session
        raise InvalidOperation("STATE_CONFIRMATION_DISABLED")

    def _respond_and_prepare(self, session: SessionState) -> SessionState:
        """Generate wording for the selected state, then create pending actions."""

        if session.selected_state is None:
            raise InvalidOperation("selected state is required before a LIVE response")
        answer = StateLabel(session.selected_state.label.value)
        preferences, _ = self.orchestrator.reaction_memory_context()
        reply_style = str(preferences.reply_style.value)
        started = time.monotonic()
        try:
            result = self.audio.respond(answer.value, reply_style)
            reply = AssistantReply(
                text=result.text,
                source=AssistantReplySource.STEPAUDIO,
                latency_ms=result.latency_ms,
            )
            status = "SUCCEEDED"
            reason = None
        except AdapterError as error:
            latency = max(0, round((time.monotonic() - started) * 1000))
            source = (
                AssistantReplySource.STEP3_FALLBACK
                if session.model_source == "STEP3"
                else AssistantReplySource.RULE_FALLBACK
            )
            reply = AssistantReply(
                text=FALLBACK_REPLIES[answer],
                source=source,
                latency_ms=latency,
            )
            status = "DEGRADED"
            reason = error.code
            if error.code not in session.degraded_reasons:
                session.degraded_reasons.append(error.code)
        session.component_health["STEPAUDIO_RESPONSE"] = {
            "available": reply.source is AssistantReplySource.STEPAUDIO,
            "status": status,
            "latency_ms": reply.latency_ms,
        }
        self.orchestrator.audit_log.record(
            session_id=session.session_id,
            event_type="STEPAUDIO_RESPONSE_CALL",
            payload={
                "response_source": reply.source.value,
                "selected_state": answer.value,
                "state_source": "MODEL_TOP_CANDIDATE",
                "user_confirmed": False,
                "reply_style": reply_style,
                "reply_characters": len(reply.text),
                "degraded_reason": reason,
                "full_reply_persisted": False,
                "history_sent": False,
                "raw_audio_sent": False,
            },
            status=status,
            source_agent="stepaudio-adapter",
            network_scope=NetworkScope.LOCAL,
            latency_ms=reply.latency_ms,
        )
        self.orchestrator.set_live_assistant_reply(session.session_id, reply)
        return self.orchestrator.prepare_selected_live_actions(session.session_id)

    def synthesize_reply_wav(self, session_id: str) -> tuple[bytes, int]:
        session = self.orchestrator.get_session(session_id)
        if session.runtime_mode != "LIVE" or session.assistant_reply is None:
            raise InvalidOperation("assistant reply is required before TTS")
        try:
            wav, latency_ms = self.audio.synthesize_wav(session.assistant_reply.text)
        except AdapterError as error:
            self.orchestrator.set_tts_playback(
                session_id, TTSPlaybackStatus.FAILED, reason=error.code
            )
            self.orchestrator.audit_log.record(
                session_id=session_id,
                event_type="STEPAUDIO_TTS_GENERATED",
                payload={
                    "status": "FAILED",
                    "reason": error.code,
                    "raw_audio_persisted": False,
                    "reply_text_persisted": False,
                },
                status="DEGRADED",
                source_agent="stepaudio-adapter",
                network_scope=NetworkScope.LOCAL,
            )
            raise
        self.orchestrator.set_tts_playback(
            session_id,
            TTSPlaybackStatus.READY,
            latency_ms=latency_ms,
        )
        self.orchestrator.audit_log.record(
            session_id=session_id,
            event_type="STEPAUDIO_TTS_GENERATED",
            payload={
                "status": "READY",
                "audio_bytes": len(wav),
                "raw_audio_persisted": False,
                "reply_text_persisted": False,
            },
            status="SUCCEEDED",
            source_agent="stepaudio-adapter",
            network_scope=NetworkScope.LOCAL,
            latency_ms=latency_ms,
        )
        return wav, latency_ms

    def report_tts_playback(
        self, session_id: str, report: BrowserPlaybackReport
    ) -> SessionState:
        status = (
            TTSPlaybackStatus.STARTED
            if report.status is BrowserPlaybackReportStatus.STARTED
            else TTSPlaybackStatus.FAILED
        )
        reason = report.reason.value if report.reason is not None else None
        session = self.orchestrator.set_tts_playback(
            session_id, status, reason=reason
        )
        self.orchestrator.audit_log.record(
            session_id=session_id,
            event_type="BROWSER_TTS_PLAYBACK",
            payload={
                "playback_status": status.value,
                "failure_reason": reason,
                "audibility_confirmed": False,
                "audio_persisted": False,
            },
            status=status.value,
            source_agent="windows-browser",
            network_scope=NetworkScope.LOCAL,
        )
        return session

    def reset(self, session_id: str) -> SessionState:
        with self._lock:
            session = self.orchestrator.reset_session(session_id)
            if self.current_session_id == session_id:
                self.current_session_id = None
                self._confirmed_present = False
                self._candidate_present = None
                self._candidate_count = 0
            return session

    def close(self) -> None:
        self.vision.close()
        self.orchestrator.close()

    def _run_asr(self, session: SessionState, jpeg: bytes | None) -> None:
        started = time.monotonic()
        try:
            transcript = self.audio.transcribe()
        except AdapterError as error:
            latency = max(0, round((time.monotonic() - started) * 1000))
            self.orchestrator.audit_log.record(
                session_id=session.session_id,
                event_type="STEPAUDIO_ASR_CALL",
                payload={
                    "transcript_persisted": False,
                    "degraded_reason": error.code,
                    "text_fallback_available": True,
                },
                status="DEGRADED",
                source_agent="stepaudio-adapter",
                network_scope=NetworkScope.LOCAL,
                latency_ms=latency,
            )
            self.orchestrator.mark_live_asr_fallback(session.session_id, error.code)
            session.component_health["ASR"] = {
                "available": False,
                "status": error.code,
                "latency_ms": latency,
            }
            return
        session.component_health["ASR"] = {
            "available": True,
            "status": "SUCCEEDED",
            "latency_ms": transcript.latency_ms,
        }
        self.orchestrator.audit_log.record(
            session_id=session.session_id,
            event_type="STEPAUDIO_ASR_CALL",
            payload={"transcript_persisted": False, "text_fallback_available": False},
            status="SUCCEEDED",
            source_agent="stepaudio-adapter",
            network_scope=NetworkScope.LOCAL,
            latency_ms=transcript.latency_ms,
        )
        self._run_step3(
            session,
            transcript=transcript.text,
            interaction_source=InteractionSource.STEPAUDIO_ASR,
            jpeg=jpeg,
        )

    def _run_step3(
        self,
        session: SessionState,
        *,
        transcript: str,
        interaction_source: InteractionSource,
        jpeg: bytes | None,
    ) -> SessionState:
        started = time.monotonic()
        degraded_reason: str | None = None
        try:
            output, latency = self.step3.analyze(transcript, jpeg)
            model_source = ModelSource.STEP3
            status = "SUCCEEDED"
        except AdapterError as error:
            latency = max(0, round((time.monotonic() - started) * 1000))
            output = fixed_step3_fallback()
            model_source = ModelSource.RULE_FALLBACK
            status = "DEGRADED"
            degraded_reason = error.code
        self.orchestrator.audit_log.record(
            session_id=session.session_id,
            event_type="STEP3_MODEL_CALL",
            payload={
                "model_source": model_source.value,
                "degraded_reason": degraded_reason,
                "raw_request_persisted": False,
                "raw_response_persisted": False,
                "authorization_from_model": False,
            },
            status=status,
            source_agent="step3-adapter",
            network_scope=NetworkScope.LOCAL,
            latency_ms=latency,
        )
        session.component_health["STEP3"] = {
            "available": model_source is ModelSource.STEP3,
            "status": status,
            "latency_ms": latency,
        }
        selected_session = self.orchestrator.continue_live_pipeline(
            session.session_id,
            transcript=transcript,
            interaction_source=interaction_source.value,
            step3_output=output,
            model_source=model_source.value,
            degraded_reason=degraded_reason,
        )
        return self._respond_and_prepare(selected_session)

    def _record_vision_event(
        self, session: SessionState, observation: VisionObservation, status: str
    ) -> None:
        self.orchestrator.audit_log.record(
            session_id=session.session_id,
            event_type="VISION_OBSERVATION",
            payload={
                "edge": status,
                "source": observation.source.value,
                "degraded": observation.degraded,
                "raw_frame_persisted": False,
            },
            status=status,
            source_agent="vision-adapter",
            network_scope=NetworkScope.LOCAL,
            latency_ms=observation.latency_ms,
        )

    def _record_synthetic_vision_call(
        self,
        session: SessionState,
        observation: dict[str, object],
        edge: str,
    ) -> None:
        self.orchestrator.audit_log.record(
            session_id=session.session_id,
            event_type="STEP3_VISION_CALL",
            payload={
                "attempt_id": str(observation["attempt_id"]),
                "scene_id": str(observation["scene_id"]),
                "synthetic": bool(observation["synthetic"]),
                "edge": edge,
                "person_present": bool(observation["person_present"]),
                "scene_type": str(observation["scene_type"]),
                "model_source": ModelSource.STEP3.value,
                "raw_request_persisted": False,
                "raw_response_persisted": False,
                "authorization_from_model": False,
            },
            status="SUCCEEDED",
            source_agent="step3-vision-adapter",
            network_scope=NetworkScope.LOCAL,
            confidence=float(observation["confidence"]),
            latency_ms=int(observation["latency_ms"]),
        )
