from __future__ import annotations

import json
import io
import socket
import tempfile
import time
import unittest
import wave
from datetime import timedelta
from pathlib import Path
from typing import Any

from backend.app.local_music import LocalMusicPlayer
from backend.app.mocks import MockStep3
from backend.app.orchestrator import InvalidOperation, Orchestrator
from backend.app.persistence import SQLitePersistence
from backend.app.schemas.actions import AuthorizationStatus, ExecutionStatus
from backend.app.schemas.music import PlaylistKey
from backend.app.schemas.step3 import StateLabel
from external_connector.audius import (
    AUDIUS_TIMEOUT_SECONDS,
    MAX_AUDIO_BYTES,
    AudiusConnectorError,
    AudiusMusicConnector,
    AudiusPlaylistSnapshot,
    AudiusSettings,
    HTTPResponse,
    PinnedHTTPSAudiusTransport,
    ValidatedContentTarget,
    validate_content_url,
)
from track_catalog.contracts import (
    CatalogLeaseRequest,
    CatalogResultRequest,
    CatalogSnapshotRequest,
)
from track_catalog.store import CatalogStore
from external_connector.weather import RealExternalConnector
from tests.helpers import NOW
from tests.phase1c.helpers import FixedClock
from tests.phase4.helpers import FakeWeatherTransport, RecordingPlaybackBackend


PUBLIC_ADDRESS = "93.184.216.34"
CONTENT_URL = "https://content.example/audio.mp3?sig=synthetic-signature"


def public_resolver(hostname: str, port: int) -> list[tuple[Any, ...]]:
    return [
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            (PUBLIC_ADDRESS, port),
        )
    ]


def private_resolver(hostname: str, port: int) -> list[tuple[Any, ...]]:
    return [
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            ("127.0.0.1", port),
        )
    ]


def configured_settings() -> AudiusSettings:
    return AudiusSettings(
        enabled=True,
        api_key="synthetic-api-key",
        bearer_token="synthetic-bearer-token",
        playlist_urls={
            PlaylistKey.RELAX: "https://audius.co/demo/relax-playlist"
        },
        configured=True,
    )


def connector_request() -> dict[str, object]:
    return {
        "request_id": "request-audius-001",
        "source_agent": "music-agent",
        "destination": "PUBLIC_MUSIC_API",
        "network_scope": "INTERNET",
        "payload": {"action": "play", "track_id": "emotion_relax_01"},
        "created_at": NOW,
    }


def sync_request() -> dict[str, object]:
    return {
        "request_id": "request-audius-sync-001",
        "source_agent": "music-agent",
        "destination": "PUBLIC_MUSIC_API",
        "network_scope": "INTERNET",
        "payload": {"action": "sync_playlist", "playlist_ref": "RELAX"},
        "created_at": NOW,
    }


class FakeAudiusTransport:
    def __init__(self) -> None:
        self.api_calls: list[tuple[str, dict[str, str], float, int]] = []
        self.content_calls: list[
            tuple[ValidatedContentTarget, dict[str, str], float, int]
        ] = []
        self.metadata_status = 200
        self.stream_status = 200
        self.playlist_status = 200
        self.playlist: dict[str, object] = {
            "data": {
                "id": "playlist001",
                "is_private": False,
                "is_album": False,
                "is_stream_gated": False,
                "stream_conditions": None,
                "playlist_contents": [{"track_id": "D7KyD"}],
            }
        }
        self.metadata: dict[str, object] = {
            "data": {
                "id": "D7KyD",
                "is_streamable": True,
                "is_unlisted": False,
                "is_stream_gated": False,
                "stream_conditions": None,
                "allowed_api_keys": [],
                "is_available": True,
            }
        }
        self.stream: dict[str, object] = {"data": CONTENT_URL}
        self.content = HTTPResponse(
            200,
            {"content-type": "audio/mpeg", "content-length": "15"},
            b"synthetic-audio",
        )
        self.api_error: AudiusConnectorError | None = None
        self.api_responses: list[HTTPResponse] = []
        self.content_responses: list[HTTPResponse] = []

    def fetch_api(
        self,
        request_target: str,
        headers: dict[str, str],
        timeout_seconds: float,
        max_bytes: int,
    ) -> HTTPResponse:
        self.api_calls.append(
            (request_target, dict(headers), timeout_seconds, max_bytes)
        )
        if self.api_error is not None:
            raise self.api_error
        if self.api_responses:
            return self.api_responses.pop(0)
        is_playlist = request_target.startswith(
            ("/v1/playlists/by_permalink/", "/v1/playlists/by-permalink/")
        )
        is_stream = "/stream?" in request_target
        if is_playlist:
            status = self.playlist_status
            body = self.playlist
        else:
            status = self.stream_status if is_stream else self.metadata_status
            body = self.stream if is_stream else self.metadata
        return HTTPResponse(
            status,
            {"content-type": "application/json"},
            json.dumps(body).encode("utf-8"),
        )

    def fetch_content(
        self,
        target: ValidatedContentTarget,
        headers: dict[str, str],
        timeout_seconds: float,
        max_bytes: int,
    ) -> HTTPResponse:
        self.content_calls.append((target, dict(headers), timeout_seconds, max_bytes))
        if self.content_responses:
            return self.content_responses.pop(0)
        return self.content


class FailMemoryOnceBackend(RecordingPlaybackBackend):
    def __init__(self) -> None:
        super().__init__()
        self.memory_attempts = 0

    def play_memory(self, audio: bytes) -> None:
        self.memory_attempts += 1
        raise RuntimeError("synthetic preview device failure")


class InProcessCatalog:
    def __init__(self, path: Path) -> None:
        self.store = CatalogStore(path, clock=FixedClock())

    def health(self) -> dict[str, object]:
        return self.store.health()

    def category_status(self, playlist_key: PlaylistKey) -> str:
        categories = self.store.health()["categories"]
        return str(categories[playlist_key.value]["status"])

    def replace_snapshot(self, request: CatalogSnapshotRequest):
        return self.store.replace_snapshot(request)

    def lease(self, request: CatalogLeaseRequest):
        return self.store.lease(request)

    def record_result(self, request: CatalogResultRequest) -> None:
        self.store.record_result(request)


class AudiusConnectorTests(unittest.TestCase):
    def make_connector(
        self,
        transport: FakeAudiusTransport,
        *,
        decoder=lambda audio: object(),
    ) -> AudiusMusicConnector:
        return AudiusMusicConnector(
            configured_settings(),
            transport=transport,
            resolver=public_resolver,
            decoder=decoder,
        )

    def test_missing_partial_disabled_and_invalid_playlist_are_not_configured(self) -> None:
        cases = (
            {},
            {"SPARK_AUDIUS_ENABLED": "false"},
            {
                "SPARK_AUDIUS_ENABLED": "true",
                "SPARK_AUDIUS_API_KEY": "present",
            },
            {
                "SPARK_AUDIUS_ENABLED": "true",
                "SPARK_AUDIUS_API_KEY": "present",
                "SPARK_AUDIUS_BEARER_TOKEN": "present",
            },
        )
        for environment in cases:
            with self.subTest(environment=sorted(environment)):
                transport = FakeAudiusTransport()
                connector = AudiusMusicConnector(
                    AudiusSettings.from_environment(
                        environment,
                        config_path=Path(self.id() + "-missing.json"),
                    ),
                    transport=transport,
                    resolver=public_resolver,
                )
                self.assertEqual(connector.health()["status"], "NOT_CONFIGURED")
                with self.assertRaisesRegex(AudiusConnectorError, "NOT_CONFIGURED"):
                    connector.fetch_preview(connector_request(), "D7KyD")
                self.assertEqual(transport.api_calls, [])
                self.assertEqual(transport.content_calls, [])
                self.assertEqual(connector.sent_requests, [])
        with tempfile.TemporaryDirectory() as temporary:
            invalid_config = Path(temporary) / "audius_playlists.local.json"
            invalid_config.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "playlists": {
                            "RELAX": "https://audius.co:443/demo/playlist"
                        },
                    }
                ),
                encoding="utf-8",
            )
            settings = AudiusSettings.from_environment(
                {
                    "SPARK_AUDIUS_ENABLED": "true",
                    "SPARK_AUDIUS_API_KEY": "present",
                    "SPARK_AUDIUS_BEARER_TOKEN": "present",
                },
                config_path=invalid_config,
            )
        self.assertFalse(settings.configured)
        self.assertEqual(settings.playlist_urls, {})

    def test_health_never_probes_and_transitions_after_fetch(self) -> None:
        transport = FakeAudiusTransport()
        connector = self.make_connector(transport)
        self.assertEqual(connector.health()["status"], "CONFIGURED_NOT_PROBED")
        self.assertEqual(transport.api_calls, [])
        connector.fetch_preview(connector_request(), "D7KyD")
        self.assertEqual(connector.health()["status"], "READY")

    def test_current_three_segment_playlist_permalink_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "audius_playlists.local.json"
            config.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "playlists": {
                            "RELAX": "https://audius.co/byte/playlist/lofi-chillhop-beats-906"
                        },
                    }
                ),
                encoding="utf-8",
            )
            settings = AudiusSettings.from_environment(
                {
                    "SPARK_AUDIUS_ENABLED": "true",
                    "SPARK_AUDIUS_API_KEY": "synthetic-api-key",
                    "SPARK_AUDIUS_BEARER_TOKEN": "synthetic-bearer-token",
                },
                config_path=config,
            )
        self.assertTrue(settings.configured_for(PlaylistKey.RELAX))
        self.assertEqual(
            settings.playlist_urls[PlaylistKey.RELAX],
            "https://audius.co/byte/playlist/lofi-chillhop-beats-906",
        )

    def test_runtime_playlist_config_and_sync_are_bounded_and_ordered(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "audius_playlists.local.json"
            config.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "playlists": {
                            "RELAX": "https://audius.co/demo/playlist/relax-playlist"
                        },
                    }
                ),
                encoding="utf-8",
            )
            settings = AudiusSettings.from_environment(
                {
                    "SPARK_AUDIUS_ENABLED": "true",
                    "SPARK_AUDIUS_API_KEY": "synthetic-api-key",
                    "SPARK_AUDIUS_BEARER_TOKEN": "synthetic-bearer-token",
                },
                config_path=config,
            )
        self.assertTrue(settings.configured_for(PlaylistKey.RELAX))
        transport = FakeAudiusTransport()
        transport.playlist["data"]["playlist_contents"] = [
            {"track_id": f"track{index:03d}"} for index in range(501)
        ] + [{"track_id": "track000"}]
        connector = AudiusMusicConnector(
            settings,
            transport=transport,
            resolver=public_resolver,
            decoder=lambda audio: object(),
        )
        snapshot = connector.sync_playlist(sync_request(), PlaylistKey.RELAX)
        self.assertEqual(snapshot.provider_playlist_id, "playlist001")
        self.assertEqual(len(snapshot.track_ids), 500)
        self.assertEqual(snapshot.track_ids[:2], ("track000", "track001"))
        self.assertEqual(snapshot.source_count, 502)
        self.assertTrue(snapshot.truncated)
        self.assertEqual(len(transport.api_calls), 1)
        target, headers, _, _ = transport.api_calls[0]
        self.assertEqual(
            target,
            "/v1/playlists/by_permalink/demo/relax-playlist"
            "?api_key=synthetic-api-key",
        )
        self.assertIn("api_key=synthetic-api-key", target)
        self.assertEqual(headers["Authorization"], "Bearer synthetic-bearer-token")
        self.assertEqual(transport.content_calls, [])

    def test_official_playlist_array_and_legacy_object_are_both_strictly_supported(self) -> None:
        transport = FakeAudiusTransport()
        playlist = transport.playlist["data"]
        transport.playlist["data"] = [playlist]
        snapshot = self.make_connector(transport).sync_playlist(
            sync_request(), PlaylistKey.RELAX
        )
        self.assertEqual(snapshot.provider_playlist_id, "playlist001")
        self.assertEqual(snapshot.track_ids, ("D7KyD",))

        invalid_values = ([], [playlist, playlist], ["not-an-object"])
        for value in invalid_values:
            with self.subTest(value=value):
                transport = FakeAudiusTransport()
                transport.playlist["data"] = value
                with self.assertRaisesRegex(
                    AudiusConnectorError, "AUDIUS_PLAYLIST_SCHEMA_REJECTED"
                ):
                    self.make_connector(transport).sync_playlist(
                        sync_request(), PlaylistKey.RELAX
                    )

    def test_api_redirect_is_same_origin_bounded_and_keeps_credentials_on_api_only(self) -> None:
        transport = FakeAudiusTransport()
        body = dict(transport.playlist)
        body["data"] = [body["data"]]
        transport.api_responses = [
            HTTPResponse(
                302,
                {
                    "location": (
                        "https://api.audius.co/v1/playlists/by-permalink/"
                        "demo/relax-playlist"
                    )
                },
                b"",
            ),
            HTTPResponse(
                200,
                {"content-type": "application/json"},
                json.dumps(body).encode("utf-8"),
            ),
        ]
        snapshot = self.make_connector(transport).sync_playlist(
            sync_request(), PlaylistKey.RELAX
        )
        self.assertEqual(snapshot.track_ids, ("D7KyD",))
        self.assertEqual(len(transport.api_calls), 2)
        self.assertTrue(transport.api_calls[1][0].startswith(
            "/v1/playlists/by-permalink/"
        ))
        self.assertEqual(
            transport.api_calls[1][1]["Authorization"],
            "Bearer synthetic-bearer-token",
        )

        transport = FakeAudiusTransport()
        transport.api_responses = [
            HTTPResponse(
                302,
                {
                    "location": (
                        "https://content.example/v1/playlists/by_permalink/"
                        "demo/relax-playlist?api_key=synthetic-api-key"
                    )
                },
                b"",
            )
        ]
        with self.assertRaisesRegex(
            AudiusConnectorError, "AUDIUS_API_REDIRECT_REJECTED"
        ):
            self.make_connector(transport).sync_playlist(
                sync_request(), PlaylistKey.RELAX
            )
        self.assertEqual(len(transport.api_calls), 1)

    def test_success_uses_credentials_only_for_fixed_api_requests(self) -> None:
        transport = FakeAudiusTransport()
        connector = self.make_connector(transport)
        preview = connector.fetch_preview(connector_request(), "D7KyD")
        self.assertEqual(preview.audio, b"synthetic-audio")
        self.assertEqual(preview.provider_track_id, "D7KyD")
        self.assertEqual(len(transport.api_calls), 2)
        for target, headers, timeout, _ in transport.api_calls:
            self.assertIn("api_key=synthetic-api-key", target)
            self.assertEqual(headers["Authorization"], "Bearer synthetic-bearer-token")
            self.assertEqual(timeout, AUDIUS_TIMEOUT_SECONDS)
        self.assertIn("preview=true", transport.api_calls[1][0])
        self.assertIn("no_redirect=true", transport.api_calls[1][0])
        self.assertEqual(len(transport.content_calls), 1)
        target, headers, timeout, limit = transport.content_calls[0]
        self.assertEqual(target.hostname, "content.example")
        self.assertEqual(target.addresses, (PUBLIC_ADDRESS,))
        self.assertNotIn("Authorization", headers)
        self.assertNotIn("api_key", str(headers))
        self.assertEqual(timeout, AUDIUS_TIMEOUT_SECONDS)
        self.assertEqual(limit, MAX_AUDIO_BYTES)
        self.assertEqual(
            connector.sent_requests[0].payload,
            {"action": "play", "track_id": "emotion_relax_01"},
        )

    def test_transport_rejects_legacy_resolve_redirect_entrypoint(self) -> None:
        transport = PinnedHTTPSAudiusTransport(resolver=public_resolver)
        with self.assertRaisesRegex(
            AudiusConnectorError, "AUDIUS_API_TARGET_REJECTED"
        ):
            transport.fetch_api(
                "/v1/resolve?url=https%3A%2F%2Faudius.co%2Fdemo%2Fplaylist",
                {},
                AUDIUS_TIMEOUT_SECONDS,
                1024,
            )

    def test_http_failures_timeout_and_metadata_policy_reject(self) -> None:
        with self.assertRaisesRegex(AudiusConnectorError, "AUDIUS_TIMEOUT"):
            AudiusMusicConnector._remaining_timeout(time.monotonic() - 1)

        for status in (401, 403, 429, 500, 503):
            with self.subTest(status=status):
                transport = FakeAudiusTransport()
                transport.metadata_status = status
                connector = self.make_connector(transport)
                with self.assertRaisesRegex(
                    AudiusConnectorError, f"AUDIUS_METADATA_HTTP_{status}"
                ):
                    connector.fetch_preview(connector_request(), "D7KyD")
                self.assertEqual(transport.content_calls, [])
                self.assertEqual(connector.health()["status"], "DEGRADED")

        transport = FakeAudiusTransport()
        transport.api_error = AudiusConnectorError(
            "AUDIUS_TRANSPORT_FAILED", request_sent=True
        )
        with self.assertRaisesRegex(AudiusConnectorError, "AUDIUS_TRANSPORT_FAILED"):
            self.make_connector(transport).fetch_preview(connector_request(), "D7KyD")

        invalid_metadata = (
            {"data": {"id": "other"}},
            {"data": {"id": "D7KyD", "is_streamable": False}},
            {
                "data": {
                    "id": "D7KyD",
                    "is_streamable": True,
                    "is_unlisted": True,
                    "is_stream_gated": False,
                }
            },
            {
                "data": {
                    "id": "D7KyD",
                    "is_streamable": True,
                    "is_unlisted": False,
                    "is_stream_gated": True,
                }
            },
        )
        for metadata in invalid_metadata:
            with self.subTest(metadata=metadata):
                transport = FakeAudiusTransport()
                transport.metadata = metadata
                with self.assertRaises(AudiusConnectorError):
                    self.make_connector(transport).fetch_preview(
                        connector_request(), "D7KyD"
                    )
                self.assertEqual(transport.content_calls, [])

    def test_content_type_size_redirect_and_decode_fail_closed(self) -> None:
        transport = FakeAudiusTransport()
        transport.stream_status = 302
        with self.assertRaisesRegex(
            AudiusConnectorError, "AUDIUS_API_REDIRECT_REJECTED"
        ):
            self.make_connector(transport).fetch_preview(connector_request(), "D7KyD")
        self.assertEqual(transport.content_calls, [])

        cases = (
            HTTPResponse(302, {"content-type": "audio/mpeg"}, b"redirect"),
            HTTPResponse(200, {"content-type": "text/html"}, b"not audio"),
            HTTPResponse(
                200,
                {
                    "content-type": "audio/mpeg",
                    "content-length": str(MAX_AUDIO_BYTES + 1),
                },
                b"x",
            ),
            HTTPResponse(
                200,
                {"content-type": "audio/mpeg"},
                b"x" * (MAX_AUDIO_BYTES + 1),
            ),
        )
        for response in cases:
            with self.subTest(status=response.status, headers=response.headers):
                transport = FakeAudiusTransport()
                transport.content = response
                with self.assertRaises(AudiusConnectorError):
                    self.make_connector(transport).fetch_preview(
                        connector_request(), "D7KyD"
                    )

        transport = FakeAudiusTransport()

        def reject_decode(audio: bytes) -> object:
            raise AudiusConnectorError("AUDIUS_AUDIO_DECODE_FAILED", request_sent=True)

        with self.assertRaisesRegex(AudiusConnectorError, "AUDIUS_AUDIO_DECODE_FAILED"):
            self.make_connector(transport, decoder=reject_decode).fetch_preview(
                connector_request(), "D7KyD"
            )

    def test_content_redirect_is_revalidated_bounded_and_never_receives_credentials(self) -> None:
        transport = FakeAudiusTransport()
        transport.content_responses = [
            HTTPResponse(
                307,
                {"location": "https://cdn.example/preview.mp3?sig=synthetic"},
                b"",
            ),
            transport.content,
        ]
        preview = self.make_connector(transport).fetch_preview(
            connector_request(), "D7KyD"
        )
        self.assertEqual(preview.audio, b"synthetic-audio")
        self.assertEqual(len(transport.content_calls), 2)
        self.assertEqual(transport.content_calls[1][0].hostname, "cdn.example")
        for _, headers, _, _ in transport.content_calls:
            self.assertNotIn("Authorization", headers)
            self.assertNotIn("api_key", str(headers))

        cases = (
            (
                [HTTPResponse(307, {}, b"")],
                "AUDIUS_CONTENT_REDIRECT_REJECTED",
            ),
            (
                [HTTPResponse(307, {"location": CONTENT_URL}, b"")],
                "AUDIUS_CONTENT_REDIRECT_LOOP",
            ),
            (
                [
                    HTTPResponse(307, {"location": "https://a.example/a"}, b""),
                    HTTPResponse(307, {"location": "https://b.example/b"}, b""),
                    HTTPResponse(307, {"location": "https://c.example/c"}, b""),
                ],
                "AUDIUS_CONTENT_REDIRECT_LIMIT",
            ),
        )
        for responses, code in cases:
            with self.subTest(code=code):
                transport = FakeAudiusTransport()
                transport.content_responses = responses
                with self.assertRaisesRegex(AudiusConnectorError, code):
                    self.make_connector(transport).fetch_preview(
                        connector_request(), "D7KyD"
                    )

    def test_default_miniaudio_decoder_accepts_demo_audio_and_rejects_invalid_mp3(self) -> None:
        transport = FakeAudiusTransport()
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(8_000)
            writer.writeframes(b"\x00\x00" * 800)
        audio = buffer.getvalue()
        transport.content = HTTPResponse(
            200,
            {"content-type": "audio/wav", "content-length": str(len(audio))},
            audio,
        )
        connector = AudiusMusicConnector(
            configured_settings(),
            transport=transport,
            resolver=public_resolver,
        )
        self.assertEqual(
            connector.fetch_preview(connector_request(), "D7KyD").size_bytes,
            len(audio),
        )

        transport = FakeAudiusTransport()
        transport.content = HTTPResponse(
            200,
            {"content-type": "audio/mpeg"},
            b"not-a-valid-mp3",
        )
        connector = AudiusMusicConnector(
            configured_settings(),
            transport=transport,
            resolver=public_resolver,
        )
        with self.assertRaisesRegex(AudiusConnectorError, "AUDIUS_AUDIO_DECODE_FAILED"):
            connector.fetch_preview(connector_request(), "D7KyD")

    def test_malicious_content_urls_and_private_dns_are_rejected(self) -> None:
        urls = (
            "http://content.example/audio.mp3",
            "https://user@content.example/audio.mp3",
            "https://content.example:444/audio.mp3",
            "https://127.0.0.1/audio.mp3",
            "https://content.example/audio.mp3#fragment",
        )
        for url in urls:
            with self.subTest(url=url):
                with self.assertRaises(AudiusConnectorError):
                    validate_content_url(url, resolver=public_resolver)
        with self.assertRaisesRegex(AudiusConnectorError, "DNS_REJECTED"):
            validate_content_url(
                "https://content.example/audio.mp3", resolver=private_resolver
            )


class AudiusOrchestrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def ready_session(
        self,
        transport: FakeAudiusTransport,
        backend: RecordingPlaybackBackend,
        *,
        settings: AudiusSettings | None = None,
    ) -> tuple[Orchestrator, object]:
        persistence = SQLitePersistence(Path(self.temporary.name) / "demo.sqlite3")
        audius = AudiusMusicConnector(
            settings or configured_settings(),
            transport=transport,
            resolver=public_resolver,
            decoder=lambda audio: object(),
        )
        orchestrator = Orchestrator(
            clock=FixedClock(),
            persistence=persistence,
            live_connector=RealExternalConnector(
                transport=FakeWeatherTransport(), clock=FixedClock()
            ),
            live_music=LocalMusicPlayer(backend=backend),
            live_audius=audius,
            track_catalog=InProcessCatalog(
                Path(self.temporary.name) / "audius_catalog.sqlite3"
            ),
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
        return orchestrator, session

    def test_approved_preview_plays_memory_and_keeps_ac_pending(self) -> None:
        transport = FakeAudiusTransport()
        backend = RecordingPlaybackBackend()
        orchestrator, session = self.ready_session(transport, backend)
        music_id = session.music_action.action_id
        ac_id = session.ac_action.action_id
        session = orchestrator.authorize(session.session_id, music_id, True)
        result = session.results[music_id].result
        self.assertEqual(backend.memory_payloads, [b"synthetic-audio"])
        self.assertEqual(backend.paths, [])
        self.assertEqual(result["source"], "AUDIUS_PREVIEW")
        self.assertEqual(result["provider"], "AUDIUS")
        self.assertEqual(result["fetch_scope"], "INTERNET")
        self.assertEqual(result["playback_scope"], "LOCAL")
        self.assertFalse(result["fallback_used"])
        self.assertTrue(result["playback_started"])
        self.assertEqual(
            session.authorizations[ac_id].authorization_status,
            AuthorizationStatus.PENDING,
        )

        serialized = json.dumps(
            {
                "snapshot": orchestrator.snapshot(session.session_id),
                "events": [
                    item.model_dump(mode="json")
                    for item in orchestrator.audit_log.list_events(session.session_id)
                ],
                "action": orchestrator.get_persisted_action(music_id).model_dump(
                    mode="json"
                ),
            },
            default=str,
        )
        self.assertNotIn("synthetic-api-key", serialized)
        self.assertNotIn("synthetic-bearer-token", serialized)
        self.assertNotIn(CONTENT_URL, serialized)
        self.assertNotIn("synthetic-audio", serialized)
        self.assertIn('"source": "AUDIUS_PREVIEW"', serialized)

    def test_approved_preview_resyncs_category_when_no_ready_tracks_remain(self) -> None:
        transport = FakeAudiusTransport()
        backend = RecordingPlaybackBackend()
        orchestrator, session = self.ready_session(transport, backend)
        catalog = orchestrator.track_catalog
        self.assertIsNotNone(catalog)
        catalog.replace_snapshot(  # type: ignore[union-attr]
            CatalogSnapshotRequest(
                playlist_key=PlaylistKey.RELAX,
                playlist_id="previousPlaylist",
                track_ids=["D7KyD"],
                source_count=1,
                truncated=False,
            )
        )
        catalog.lease(  # type: ignore[union-attr]
            CatalogLeaseRequest(
                action_id="previous-action",
                playlist_key=PlaylistKey.RELAX,
                logical_track_id="emotion_relax_01",
            )
        )
        catalog.record_result(  # type: ignore[union-attr]
            CatalogResultRequest(
                action_id="previous-action",
                playlist_key=PlaylistKey.RELAX,
                provider_track_id="D7KyD",
                outcome="FETCH_FAILED",
                reason_code="AUDIUS_TRACK_GATED",
            )
        )
        self.assertEqual(catalog.category_status(PlaylistKey.RELAX), "DEGRADED")  # type: ignore[union-attr]

        music_id = session.music_action.action_id
        session = orchestrator.authorize(session.session_id, music_id, True)

        self.assertEqual(session.results[music_id].result["source"], "AUDIUS_PREVIEW")
        self.assertEqual(backend.memory_payloads, [b"synthetic-audio"])
        self.assertTrue(
            transport.api_calls[0][0].startswith(
                "/v1/playlists/by_permalink/demo/relax-playlist?"
            )
        )
        self.assertEqual(catalog.category_status(PlaylistKey.RELAX), "READY")  # type: ignore[union-attr]
        event_types = {
            item.event_type
            for item in orchestrator.audit_log.list_events(session.session_id)
        }
        self.assertIn("AUDIUS_PLAYLIST_SYNC", event_types)

    def test_fetch_failure_falls_back_once_in_same_action(self) -> None:
        transport = FakeAudiusTransport()
        transport.metadata_status = 503
        backend = RecordingPlaybackBackend()
        orchestrator, session = self.ready_session(transport, backend)
        music_id = session.music_action.action_id
        session = orchestrator.authorize(session.session_id, music_id, True)
        result = session.results[music_id].result
        self.assertEqual(backend.memory_payloads, [])
        self.assertEqual(len(backend.paths), 1)
        self.assertEqual(result["source"], "LOCAL_FALLBACK")
        self.assertTrue(result["fallback_used"])
        self.assertEqual(result["fallback_reason"], "AUDIUS_METADATA_HTTP_503")
        self.assertEqual(result["fetch_scope"], "INTERNET")
        self.assertEqual(result["track_id"], "emotion_relax_01")
        self.assertEqual(result["fallback_asset_id"], "calm_piano_01")
        self.assertEqual(session.music_action.action_id, music_id)

    def test_preview_device_failure_stops_then_uses_local_once(self) -> None:
        transport = FakeAudiusTransport()
        backend = FailMemoryOnceBackend()
        orchestrator, session = self.ready_session(transport, backend)
        music_id = session.music_action.action_id
        session = orchestrator.authorize(session.session_id, music_id, True)
        self.assertEqual(backend.memory_attempts, 1)
        self.assertEqual(len(backend.paths), 1)
        self.assertEqual(
            session.results[music_id].result["fallback_reason"],
            "AUDIUS_PLAYBACK_FAILED",
        )

    def test_unconfigured_rejection_wrong_id_duplicate_and_expiry_make_no_fetch(self) -> None:
        transport = FakeAudiusTransport()
        backend = RecordingPlaybackBackend()
        unconfigured = AudiusSettings(True, "only-key", "", {}, False)
        orchestrator, session = self.ready_session(
            transport, backend, settings=unconfigured
        )
        music_id = session.music_action.action_id
        session = orchestrator.authorize(session.session_id, music_id, True)
        self.assertEqual(transport.api_calls, [])
        self.assertEqual(len(backend.paths), 1)
        self.assertEqual(
            session.results[music_id].result["fallback_reason"], "NOT_CONFIGURED"
        )
        self.assertEqual(session.results[music_id].result["fetch_scope"], "NOT_INVOKED")

        transport = FakeAudiusTransport()
        backend = RecordingPlaybackBackend()
        orchestrator, session = self.ready_session(transport, backend)
        orchestrator.authorize(session.session_id, session.music_action.action_id, False)
        self.assertEqual(transport.api_calls, [])
        self.assertEqual(backend.paths, [])
        self.assertEqual(backend.memory_payloads, [])

        transport = FakeAudiusTransport()
        backend = RecordingPlaybackBackend()
        orchestrator, session = self.ready_session(transport, backend)
        with self.assertRaises(InvalidOperation):
            orchestrator.authorize(session.session_id, "music-wrong", True)
        self.assertEqual(transport.api_calls, [])
        session = orchestrator.authorize(session.session_id, session.music_action.action_id, True)
        call_count = len(transport.api_calls)
        with self.assertRaises(InvalidOperation):
            orchestrator.authorize(session.session_id, session.music_action.action_id, True)
        self.assertEqual(len(transport.api_calls), call_count)

        transport = FakeAudiusTransport()
        backend = RecordingPlaybackBackend()
        orchestrator, session = self.ready_session(transport, backend)
        orchestrator.clock.value = NOW + timedelta(minutes=10)  # type: ignore[attr-defined]
        orchestrator.authorize(session.session_id, session.music_action.action_id, True)
        self.assertEqual(transport.api_calls, [])
        self.assertEqual(backend.paths, [])

    def test_external_and_local_failure_marks_action_failed(self) -> None:
        transport = FakeAudiusTransport()
        transport.metadata_status = 500
        backend = RecordingPlaybackBackend(fail=True)
        orchestrator, session = self.ready_session(transport, backend)
        music_id = session.music_action.action_id
        session = orchestrator.authorize(session.session_id, music_id, True)
        result = session.results[music_id]
        self.assertEqual(result.execution_status, ExecutionStatus.FAILED)
        self.assertFalse(result.result["playback_started"])
        self.assertEqual(result.result["fallback_reason"], "AUDIUS_METADATA_HTTP_500")
        self.assertEqual(len(backend.paths), 0)


if __name__ == "__main__":
    unittest.main()
