from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.app.adapters import ReplyResult, TranscriptResult
from backend.app.live import DEMO_AUDIO_FILENAME, LiveCoordinator
from backend.app.orchestrator import Orchestrator
from backend.app.persistence import SQLitePersistence
from backend.app.schemas.music import BrowserPlaybackReport
from backend.app.schemas.step3 import StateLabel, Step3Output
from backend.app.state_machine import DemoState
from tests.helpers import step3_data


VALID_WAV = b"RIFF" + (4).to_bytes(4, "little") + b"WAVE"


class SuccessfulSyntheticAudio:
    filename = DEMO_AUDIO_FILENAME

    def __init__(self) -> None:
        self.respond_calls: list[tuple[str, str]] = []
        self.tts_texts: list[str] = []

    def transcribe(self) -> TranscriptResult:
        return TranscriptResult("今天有点累", 31)

    def respond(self, confirmed_state: str, reply_style: str) -> ReplyResult:
        self.respond_calls.append((confirmed_state, reply_style))
        return ReplyResult("辛苦了，先让自己慢下来休息一会儿吧。", 42)

    def synthesize_wav(self, text: str) -> tuple[bytes, int]:
        self.tts_texts.append(text)
        return VALID_WAV, 53


class SuccessfulStep3:
    def __init__(self) -> None:
        self.calls = 0

    def analyze(self, transcript: str, jpeg: bytes | None = None):
        self.calls += 1
        if transcript != "今天有点累" or jpeg is not None:
            raise AssertionError("speech Demo sent unexpected Step3 input")
        return Step3Output.model_validate(step3_data()), 37


class StepAudioSpeechLoopTests(unittest.TestCase):
    def test_fixed_synthetic_loop_is_repeatable_five_of_five(self) -> None:
        successes = 0
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for sample in range(5):
                with self.subTest(sample=sample + 1):
                    database = root / f"speech-{sample}.sqlite3"
                    orchestrator = Orchestrator(
                        persistence=SQLitePersistence(database)
                    )
                    audio = SuccessfulSyntheticAudio()
                    step3 = SuccessfulStep3()
                    live = LiveCoordinator(
                        orchestrator,
                        audio=audio,  # type: ignore[arg-type]
                        step3=step3,  # type: ignore[arg-type]
                    )
                    session = orchestrator.begin_live_session(
                        perception_source="SYNTHETIC_IMAGE",
                        degraded_reasons=[],
                        wait_for_fixed_text=True,
                    )

                    live.run_speech_demo(session.session_id)
                    self.assertEqual(session.transcript, "今天有点累")
                    self.assertEqual(session.state, DemoState.WAITING_MUSIC_AUTHORIZATION)
                    self.assertIsNotNone(session.step3_output)
                    self.assertEqual(session.selected_state.label.value, "PHYSICAL_FATIGUE")
                    self.assertFalse(session.selected_state.user_confirmed)
                    self.assertIsNotNone(session.assistant_reply)
                    self.assertIsNotNone(session.music_action)
                    self.assertIsNotNone(session.ac_action)
                    self.assertEqual(session.tts_playback.value, "NOT_REQUESTED")

                    self.assertEqual(
                        audio.respond_calls, [("PHYSICAL_FATIGUE", "GENTLE")]
                    )
                    self.assertEqual(session.assistant_reply.source.value, "STEPAUDIO")
                    self.assertEqual(
                        session.state, DemoState.WAITING_MUSIC_AUTHORIZATION
                    )
                    self.assertNotEqual(
                        session.music_action.action_id, session.ac_action.action_id
                    )

                    wav, latency_ms = live.synthesize_reply_wav(session.session_id)
                    self.assertEqual((wav, latency_ms), (VALID_WAV, 53))
                    self.assertEqual(session.tts_playback.value, "READY")
                    live.report_tts_playback(
                        session.session_id,
                        BrowserPlaybackReport(status="STARTED", reason=None),
                    )
                    self.assertEqual(session.tts_playback.value, "STARTED")

                    events = orchestrator.audit_log.list_events(session.session_id)
                    serialized_events = str(
                        [event.model_dump(mode="json") for event in events]
                    )
                    self.assertNotIn("辛苦了，先让自己慢下来", serialized_events)
                    raw_database = database.read_bytes()
                    self.assertNotIn(VALID_WAV, raw_database)
                    self.assertNotIn("今天有点累".encode(), raw_database)
                    self.assertNotIn("辛苦了".encode(), raw_database)
                    self.assertEqual(step3.calls, 1)
                    successes += 1

        self.assertEqual(successes, 5)


if __name__ == "__main__":
    unittest.main()
