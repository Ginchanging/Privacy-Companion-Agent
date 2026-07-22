from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.app.api import DemoASGIApp
from backend.app.local_music import BrowserMusicDelivery
from backend.app.mocks import MockStep3
from backend.app.orchestrator import Orchestrator
from backend.app.persistence import SQLitePersistence
from backend.app.schemas.actions import AuthorizationStatus, ExecutionStatus
from backend.app.schemas.analysis import TextStateLabel, TextStateModelOutput
from backend.app.schemas.phase4 import WeatherSnapshot, WeatherSource
from backend.app.schemas.reaction import LLMReaction
from backend.app.schemas.step3 import StateLabel
from external_connector.weather import RealExternalConnector
from tests.helpers import NOW
from tests.phase1c.helpers import FixedClock
from tests.phase2.helpers import json_request, request
from tests.phase4.helpers import FakeWeatherTransport


def _reaction() -> LLMReaction:
    return LLMReaction.model_validate(
        {
            "reply_text": "Synthetic supportive reply.",
            "tone": "SUPPORTIVE",
            "follow_up_question": None,
            "reasons": ["Synthetic structured context."],
            "suggestions": [{"type": "EMOTION_MATCHED_MUSIC"}],
        }
    )


def _text_output() -> TextStateModelOutput:
    return TextStateModelOutput.model_validate(
        {
            "state_hypotheses": [
                {
                    "label": "PHYSICAL_FATIGUE",
                    "confidence": 0.65,
                    "evidence": ["synthetic"],
                },
                {"label": "CALM", "confidence": 0.35, "evidence": []},
            ]
        }
    )


class BrowserPlaybackTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_browser_playback_completes_five_out_of_five(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "live-browser.sqlite3"
            session_ids: set[str] = set()
            for sample in range(5):
                with self.subTest(sample=sample):
                    persistence = SQLitePersistence(database)
                    orchestrator = Orchestrator(
                        clock=FixedClock(),
                        persistence=persistence,
                        live_connector=RealExternalConnector(
                            transport=FakeWeatherTransport(), clock=FixedClock()
                        ),
                        browser_music=BrowserMusicDelivery(),
                    )
                    session = orchestrator.begin_live_session(
                        perception_source="STATIC_SYNTHETIC", degraded_reasons=[]
                    )
                    session = orchestrator.continue_live_pipeline(
                        session.session_id,
                        transcript="Synthetic user feels tired.",
                        interaction_source="TEXT_FALLBACK",
                        step3_output=MockStep3().analyze(),
                        model_source="RULE_FALLBACK",
                    )
                    session = orchestrator.clarify(
                        session.session_id, StateLabel.PHYSICAL_FATIGUE
                    )
                    app = DemoASGIApp(orchestrator)
                    music_id = session.music_action.action_id
                    ac_id = session.ac_action.action_id

                    status, approved = await json_request(
                        app,
                        "POST",
                        f"/v1/live/sessions/{session.session_id}/actions/{music_id}/authorization",
                        {"approved": True},
                    )
                    self.assertEqual(status, 200)
                    self.assertEqual(approved["state"], "MUSIC_AUTHORIZED")
                    self.assertEqual(approved["music_playback"]["status"], "READY")
                    self.assertNotIn(music_id, approved["results"])
                    self.assertEqual(
                        persistence.get_action(music_id).execution_status,
                        ExecutionStatus.NOT_STARTED,
                    )
                    self.assertEqual(
                        approved["authorizations"][ac_id]["authorization_status"],
                        AuthorizationStatus.PENDING.value,
                    )

                    status, headers, audio = await request(
                        app,
                        "GET",
                        f"/v1/live/sessions/{session.session_id}/actions/{music_id}/audio",
                    )
                    self.assertEqual(status, 200)
                    self.assertEqual(headers[b"content-type"], b"audio/wav")
                    self.assertEqual(headers[b"cache-control"], b"no-store")
                    self.assertGreater(len(audio), 0)
                    self.assertNotIn(audio[:64], database.read_bytes())

                    status, completed = await json_request(
                        app,
                        "POST",
                        f"/v1/live/sessions/{session.session_id}/actions/{music_id}/playback-result",
                        {"status": "STARTED", "reason": None},
                    )
                    self.assertEqual(status, 200)
                    self.assertEqual(completed["state"], "WAITING_AC_AUTHORIZATION")
                    result = completed["results"][music_id]["result"]
                    self.assertTrue(result["playback_started"])
                    self.assertEqual(result["playback_scope"], "BROWSER")
                    self.assertFalse(result["audible_confirmed"])
                    self.assertEqual(
                        completed["authorizations"][ac_id]["authorization_status"],
                        AuthorizationStatus.PENDING.value,
                    )
                    session_ids.add(session.session_id)
                    orchestrator.close()

            self.assertEqual(len(session_ids), 5)

    async def test_text_analysis_browser_playback_completes_five_out_of_five(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            persistence = SQLitePersistence(Path(temporary) / "text-browser.sqlite3")
            orchestrator = Orchestrator(
                clock=FixedClock(),
                persistence=persistence,
                browser_music=BrowserMusicDelivery(),
            )
            app = DemoASGIApp(orchestrator)
            session_ids: set[str] = set()
            weather = WeatherSnapshot(
                city_code="310000",
                temperature_c=22.0,
                condition="clear",
                source=WeatherSource.REAL_API,
                fetched_at=NOW,
                provider="OPEN_METEO",
            )
            for sample in range(5):
                with self.subTest(sample=sample):
                    session = orchestrator.start_text_analysis_session(
                        _text_output(), _reaction(), weather
                    )
                    session = orchestrator.confirm_text_state(
                        session.session_id,
                        TextStateLabel.PHYSICAL_FATIGUE,
                        _reaction(),
                    )
                    music_id = session.music_action.action_id
                    _, approved = await json_request(
                        app,
                        "POST",
                        f"/v1/analysis/sessions/{session.session_id}/actions/{music_id}/authorization",
                        {"approved": True},
                    )
                    self.assertEqual(approved["state"], "MUSIC_AUTHORIZED")
                    status, _, _ = await request(
                        app,
                        "GET",
                        f"/v1/analysis/sessions/{session.session_id}/actions/{music_id}/audio",
                    )
                    self.assertEqual(status, 200)
                    _, completed = await json_request(
                        app,
                        "POST",
                        f"/v1/analysis/sessions/{session.session_id}/actions/{music_id}/playback-result",
                        {"status": "STARTED", "reason": None},
                    )
                    self.assertEqual(completed["state"], "COMPLETED")
                    self.assertTrue(completed["summary_saved"])
                    session_ids.add(session.session_id)

            self.assertEqual(len(session_ids), 5)
            orchestrator.close()

    async def test_audio_requires_delivery_and_matching_session(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            persistence = SQLitePersistence(Path(temporary) / "guard.sqlite3")
            orchestrator = Orchestrator(
                clock=FixedClock(),
                persistence=persistence,
                browser_music=BrowserMusicDelivery(),
            )
            session = orchestrator.start_text_analysis_session(
                _text_output(),
                _reaction(),
                WeatherSnapshot(
                    city_code="310000",
                    temperature_c=22.0,
                    condition="clear",
                    source=WeatherSource.REAL_API,
                    fetched_at=NOW,
                    provider="OPEN_METEO",
                ),
            )
            session = orchestrator.confirm_text_state(
                session.session_id, TextStateLabel.PHYSICAL_FATIGUE, _reaction()
            )
            app = DemoASGIApp(orchestrator)
            music_id = session.music_action.action_id

            status, _ = await json_request(
                app,
                "POST",
                f"/v1/analysis/sessions/{session.session_id}/actions/{music_id}/authorization",
                {"approved": True},
            )
            self.assertEqual(status, 200)
            status, rejected = await json_request(
                app,
                "POST",
                f"/v1/analysis/sessions/{session.session_id}/actions/{music_id}/playback-result",
                {"status": "STARTED", "reason": None},
            )
            self.assertEqual(status, 409)
            self.assertEqual(rejected["error"], "INVALID_OPERATION")
            status, _, _ = await request(
                app,
                "GET",
                f"/v1/live/sessions/{session.session_id}/actions/{music_id}/audio",
            )
            self.assertEqual(status, 409)
            self.assertEqual(
                persistence.get_action(music_id).execution_status,
                ExecutionStatus.NOT_STARTED,
            )

    async def test_failed_browser_report_never_claims_playback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            persistence = SQLitePersistence(Path(temporary) / "failed-browser.sqlite3")
            orchestrator = Orchestrator(
                clock=FixedClock(),
                persistence=persistence,
                browser_music=BrowserMusicDelivery(),
            )
            session = orchestrator.start_text_analysis_session(
                _text_output(),
                _reaction(),
                WeatherSnapshot(
                    city_code="310000",
                    temperature_c=22.0,
                    condition="clear",
                    source=WeatherSource.REAL_API,
                    fetched_at=NOW,
                    provider="OPEN_METEO",
                ),
            )
            session = orchestrator.confirm_text_state(
                session.session_id, TextStateLabel.PHYSICAL_FATIGUE, _reaction()
            )
            app = DemoASGIApp(orchestrator)
            music_id = session.music_action.action_id

            await json_request(
                app,
                "POST",
                f"/v1/analysis/sessions/{session.session_id}/actions/{music_id}/authorization",
                {"approved": True},
            )
            await request(
                app,
                "GET",
                f"/v1/analysis/sessions/{session.session_id}/actions/{music_id}/audio",
            )
            status, failed = await json_request(
                app,
                "POST",
                f"/v1/analysis/sessions/{session.session_id}/actions/{music_id}/playback-result",
                {"status": "FAILED", "reason": "MEDIA_ERROR"},
            )

            self.assertEqual(status, 200)
            result = failed["results"][music_id]["result"]
            self.assertFalse(result["playback_started"])
            self.assertFalse(result["physical_action_performed"])
            self.assertFalse(result["audible_confirmed"])
            self.assertEqual(result["code"], "MEDIA_ERROR")
            self.assertEqual(
                persistence.get_action(music_id).execution_status,
                ExecutionStatus.FAILED,
            )
            orchestrator.close()

    async def test_reset_discards_staged_audio_without_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            orchestrator = Orchestrator(
                clock=FixedClock(),
                persistence=SQLitePersistence(Path(temporary) / "reset-browser.sqlite3"),
                browser_music=BrowserMusicDelivery(),
            )
            session = orchestrator.start_text_analysis_session(
                _text_output(),
                _reaction(),
                WeatherSnapshot(
                    city_code="310000",
                    temperature_c=22.0,
                    condition="clear",
                    source=WeatherSource.REAL_API,
                    fetched_at=NOW,
                    provider="OPEN_METEO",
                ),
            )
            session = orchestrator.confirm_text_state(
                session.session_id, TextStateLabel.PHYSICAL_FATIGUE, _reaction()
            )
            app = DemoASGIApp(orchestrator)
            music_id = session.music_action.action_id
            await json_request(
                app,
                "POST",
                f"/v1/analysis/sessions/{session.session_id}/actions/{music_id}/authorization",
                {"approved": True},
            )

            status, reset = await json_request(
                app,
                "POST",
                f"/v1/analysis/sessions/{session.session_id}/reset",
                {},
            )
            self.assertEqual(status, 200)
            self.assertFalse(reset["active"])
            status, _, _ = await request(
                app,
                "GET",
                f"/v1/analysis/sessions/{session.session_id}/actions/{music_id}/audio",
            )
            self.assertEqual(status, 409)
            self.assertEqual(
                orchestrator.persistence.get_action(music_id).execution_status,
                ExecutionStatus.NOT_STARTED,
            )
            orchestrator.close()


if __name__ == "__main__":
    unittest.main()
