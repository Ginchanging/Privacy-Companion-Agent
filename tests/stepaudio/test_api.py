from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.app.adapters import AdapterError, ReplyResult, TranscriptResult
from backend.app.api import DemoASGIApp
from backend.app.live import DEMO_AUDIO_FILENAME, LiveCoordinator
from backend.app.orchestrator import Orchestrator
from backend.app.persistence import SQLitePersistence
from backend.app.schemas.step3 import Step3Output
from tests.helpers import step3_data
from tests.phase2.helpers import json_request, request
from tests.stepaudio.test_speech_loop import VALID_WAV


class APIAudio:
    filename = DEMO_AUDIO_FILENAME

    def __init__(self) -> None:
        self.fail_tts = False

    def transcribe(self):
        return TranscriptResult("今天有点累", 10)

    def respond(self, confirmed_state: str, reply_style: str):
        return ReplyResult("先休息一会儿吧。", 11)

    def synthesize_wav(self, text: str):
        if self.fail_tts:
            raise AdapterError("TTS_UNAVAILABLE", "synthetic timeout")
        return VALID_WAV, 12

    def health(self):
        raise AssertionError("health not used")


class APIStep3:
    def analyze(self, transcript: str, jpeg: bytes | None = None):
        return Step3Output.model_validate(step3_data()), 9

    def health(self):
        raise AssertionError("health not used")


class StepAudioSpeechAPITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "speech-api.sqlite3"
        self.orchestrator = Orchestrator(
            persistence=SQLitePersistence(self.database)
        )
        self.audio = APIAudio()
        self.live = LiveCoordinator(
            self.orchestrator,
            audio=self.audio,  # type: ignore[arg-type]
            step3=APIStep3(),  # type: ignore[arg-type]
        )
        self.app = DemoASGIApp(self.orchestrator, live=self.live)
        session = self.orchestrator.begin_live_session(
            perception_source="SYNTHETIC_IMAGE",
            degraded_reasons=[],
            wait_for_fixed_text=True,
        )
        self.session_id = session.session_id

    async def asyncTearDown(self) -> None:
        self.temporary.cleanup()

    async def _run_speech(self) -> None:
        status, snapshot = await json_request(
            self.app,
            "POST",
            f"/v1/live/sessions/{self.session_id}/speech-demo",
            {},
        )
        self.assertEqual(status, 200)
        self.assertEqual(snapshot["state"], "WAITING_MUSIC_AUTHORIZATION")
        self.assertFalse(snapshot["selected_state"]["user_confirmed"])
        self.assertEqual(snapshot["assistant_reply"]["source"], "STEPAUDIO")

    async def test_server_selects_fixed_speech_and_rejects_any_request_fields(self) -> None:
        status, body = await json_request(
            self.app,
            "POST",
            f"/v1/live/sessions/{self.session_id}/speech-demo",
            {"filename": "arbitrary.wav"},
        )
        self.assertEqual(status, 422)
        self.assertEqual(body["error"], "VALIDATION_ERROR")
        self.assertIsNone(self.orchestrator.get_session(self.session_id).transcript)

    async def test_live_tts_is_no_store_wav_and_playback_is_reported(self) -> None:
        await self._run_speech()
        status, headers, body = await request(
            self.app,
            "POST",
            f"/v1/live/sessions/{self.session_id}/tts",
            {},
        )
        self.assertEqual(status, 200)
        self.assertEqual(headers[b"content-type"], b"audio/wav")
        self.assertEqual(headers[b"cache-control"], b"no-store")
        self.assertEqual(body, VALID_WAV)
        self.assertEqual(
            self.orchestrator.get_session(self.session_id).tts_playback.value,
            "READY",
        )
        status, snapshot = await json_request(
            self.app,
            "POST",
            f"/v1/live/sessions/{self.session_id}/tts/playback-result",
            {"status": "STARTED", "reason": None},
        )
        self.assertEqual(status, 200)
        self.assertEqual(snapshot["tts_playback"], "STARTED")

    async def test_tts_failure_keeps_reply_as_text_and_marks_failed(self) -> None:
        await self._run_speech()
        self.audio.fail_tts = True
        status, body = await json_request(
            self.app,
            "POST",
            f"/v1/live/sessions/{self.session_id}/tts",
            {},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body, {"status": "TEXT_ONLY", "error": "TTS_UNAVAILABLE"})
        snapshot = self.orchestrator.snapshot(self.session_id)
        self.assertEqual(snapshot["tts_playback"], "FAILED")
        self.assertEqual(snapshot["assistant_reply"]["text"], "先休息一会儿吧。")

    async def test_playback_failure_reason_is_bounded(self) -> None:
        await self._run_speech()
        await request(
            self.app,
            "POST",
            f"/v1/live/sessions/{self.session_id}/tts",
            {},
        )
        status, body = await json_request(
            self.app,
            "POST",
            f"/v1/live/sessions/{self.session_id}/tts/playback-result",
            {"status": "FAILED", "reason": "NETWORK_ERROR"},
        )
        self.assertEqual(status, 422)
        self.assertEqual(body["error"], "VALIDATION_ERROR")


if __name__ == "__main__":
    unittest.main()
