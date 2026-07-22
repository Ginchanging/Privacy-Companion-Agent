"""Authorization-aware LOCAL playback for the single Phase 4 Demo track."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any, Protocol

from backend.app.mocks import ActionMockError
from backend.app.schemas.actions import (
    ActionAuthorization,
    ActionProposal,
    ActionResult,
    ActionType,
    AuthorizationStatus,
    ExecutionStatus,
    MusicActionPayload,
)
from backend.app.schemas.network import MusicPayload
from backend.app.schemas.music import playlist_for_logical_track
from backend.app.schemas.music import (
    BrowserPlaybackSource,
    BrowserPlaybackStatus,
    MusicPlaybackView,
)


DEFAULT_MUSIC_ROOT = Path("data/music")
ALLOWED_TRACK_ID = "calm_piano_01"
MAX_BROWSER_AUDIO_BYTES = 8 * 1024 * 1024
MAX_BROWSER_AUDIO_ARTIFACTS = 8
_BROWSER_AUDIO_CONTENT_TYPES = frozenset(
    {
        "audio/aac",
        "audio/flac",
        "audio/mp3",
        "audio/mp4",
        "audio/mpeg",
        "audio/ogg",
        "audio/wav",
        "audio/x-wav",
    }
)
_LOCAL_AUDIO_CONTENT_TYPES = {
    ".flac": "audio/flac",
    ".wav": "audio/wav",
}


class LocalMusicError(ActionMockError):
    pass


class BrowserPlaybackError(LocalMusicError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class BrowserAudioDelivery:
    audio: bytes = field(repr=False)
    content_type: str
    view: MusicPlaybackView


@dataclass(slots=True)
class _BrowserAudioArtifact:
    session_id: str
    action_id: str
    audio: bytes = field(repr=False)
    content_type: str
    source: BrowserPlaybackSource
    expires_at: datetime
    metadata: dict[str, Any]
    status: BrowserPlaybackStatus = BrowserPlaybackStatus.READY


class PlaybackBackend(Protocol):
    def play(self, path: Path) -> None:
        """Open the audio device and begin background playback."""

    def play_memory(self, audio: bytes) -> None:
        """Open the audio device and begin playback from in-memory bytes."""

    def close(self) -> None:
        """Stop playback and release the device."""


class MiniaudioPlaybackBackend:
    """Lazy miniaudio wrapper so importing the ASGI app never opens a device."""

    def __init__(self) -> None:
        self._device = None
        self._stream = None
        self._audio: bytes | None = None

    def play(self, path: Path) -> None:
        try:
            import miniaudio
        except ImportError as error:
            raise LocalMusicError("miniaudio is not installed") from error
        self.close()
        try:
            stream = miniaudio.stream_file(str(path))
            device = miniaudio.PlaybackDevice()
            device.start(stream)
        except Exception as error:
            try:
                if "device" in locals():
                    device.close()
            except Exception:
                pass
            raise LocalMusicError("local audio playback could not start") from error
        self._stream = stream
        self._device = device

    def play_memory(self, audio: bytes) -> None:
        try:
            import miniaudio
        except ImportError as error:
            raise LocalMusicError("miniaudio is not installed") from error
        self.close()
        try:
            stream = miniaudio.stream_memory(audio)
            device = miniaudio.PlaybackDevice()
            device.start(stream)
        except Exception as error:
            try:
                if "device" in locals():
                    device.close()
            except Exception:
                pass
            raise LocalMusicError("memory audio playback could not start") from error
        self._audio = audio
        self._stream = stream
        self._device = device

    def close(self) -> None:
        device = self._device
        self._device = None
        self._stream = None
        self._audio = None
        if device is None:
            return
        try:
            device.stop()
        finally:
            device.close()


class LocalMusicPlayer:
    def __init__(
        self,
        root: str | Path = DEFAULT_MUSIC_ROOT,
        *,
        backend: PlaybackBackend | None = None,
    ) -> None:
        self.root = Path(root)
        self.backend = backend or MiniaudioPlaybackBackend()
        self.executed_action_ids: list[str] = []
        self._lock = RLock()

    def health(self) -> dict[str, object]:
        try:
            path = self._validated_track(ALLOWED_TRACK_ID)
        except LocalMusicError:
            return {"component": "LOCAL_MUSIC", "available": False, "status": "ASSET_INVALID", "latency_ms": 0}
        return {
            "component": "LOCAL_MUSIC",
            "available": True,
            "status": "PLAYING" if self.executed_action_ids else "READY_NOT_PLAYED",
            "latency_ms": 0,
            "track": path.name,
        }

    def execute(
        self,
        proposal: ActionProposal,
        authorization: ActionAuthorization,
        now: datetime,
        *,
        fallback_reason: str = "NOT_CONFIGURED",
        fetch_invoked: bool = False,
    ) -> ActionResult:
        with self._lock:
            self._validate_action(proposal, authorization, now)

            command = MusicPayload(action="play", track_id=proposal.payload.track_id)
            playlist_key = playlist_for_logical_track(command.track_id)
            path = self._validated_track(ALLOWED_TRACK_ID)
            try:
                self.backend.play(path)
            except LocalMusicError:
                raise
            except Exception as error:
                raise LocalMusicError("local audio playback could not start") from error
            self.executed_action_ids.append(proposal.action_id)
            return ActionResult(
                action_id=proposal.action_id,
                action_type=proposal.action_type,
                execution_status=ExecutionStatus.SUCCEEDED,
                result={
                    "mock": False,
                    "playback_started": True,
                    "physical_action_performed": True,
                    "track_id": command.track_id,
                    "playlist_key": playlist_key.value,
                    "fallback_asset_id": ALLOWED_TRACK_ID,
                    "network_scope": "LOCAL",
                    "source": "LOCAL_FALLBACK",
                    "provider": "LOCAL",
                    "fetch_scope": "INTERNET" if fetch_invoked else "NOT_INVOKED",
                    "playback_scope": "LOCAL",
                    "fallback_used": True,
                    "fallback_reason": fallback_reason,
                    "fallback_notice": (
                        "EMOTION_PLAYLIST_UNAVAILABLE_USING_LOCAL_CALM_PIANO"
                    ),
                    "preview": False,
                },
                completed_at=now,
            )

    def execute_preview(
        self,
        proposal: ActionProposal,
        authorization: ActionAuthorization,
        now: datetime,
        *,
        audio: bytes,
        provider_track_id: str,
        size_bytes: int,
        fetch_latency_ms: int,
    ) -> ActionResult:
        with self._lock:
            self._validate_action(proposal, authorization, now)
            playlist_key = playlist_for_logical_track(proposal.payload.track_id)
            try:
                self.backend.play_memory(audio)
            except LocalMusicError:
                raise
            except Exception as error:
                raise LocalMusicError("memory audio playback could not start") from error
            self.executed_action_ids.append(proposal.action_id)
            return ActionResult(
                action_id=proposal.action_id,
                action_type=proposal.action_type,
                execution_status=ExecutionStatus.SUCCEEDED,
                result={
                    "mock": False,
                    "playback_started": True,
                    "physical_action_performed": True,
                    "track_id": proposal.payload.track_id,
                    "playlist_key": playlist_key.value,
                    "provider_track_id": provider_track_id,
                    "network_scope": "LOCAL",
                    "source": "AUDIUS_PREVIEW",
                    "provider": "AUDIUS",
                    "fetch_scope": "INTERNET",
                    "playback_scope": "LOCAL",
                    "fallback_used": False,
                    "fallback_reason": None,
                    "preview": True,
                    "size_bytes": size_bytes,
                    "fetch_latency_ms": fetch_latency_ms,
                },
                completed_at=now,
            )

    def close(self) -> None:
        with self._lock:
            self.backend.close()

    def _validate_action(
        self,
        proposal: ActionProposal,
        authorization: ActionAuthorization,
        now: datetime,
    ) -> None:
        if proposal.action_type is not ActionType.PLAY_MUSIC or not isinstance(
            proposal.payload, MusicActionPayload
        ):
            raise LocalMusicError("local player received a non-music action")
        if proposal.action_id != authorization.action_id:
            raise LocalMusicError("music action_id does not match authorization")
        if proposal.action_type is not authorization.action_type:
            raise LocalMusicError("music action type does not match authorization")
        if authorization.authorization_status is not AuthorizationStatus.APPROVED:
            raise LocalMusicError("music action is not approved")
        if now >= proposal.expires_at or now >= authorization.expires_at:
            raise LocalMusicError("music authorization has expired")
        if proposal.action_id in self.executed_action_ids:
            raise LocalMusicError("music action has already executed")

    def _validated_track(self, track_id: str) -> Path:
        if track_id != ALLOWED_TRACK_ID:
            raise LocalMusicError("track_id is not allowlisted")
        catalog_path = self.root / "catalog.json"
        try:
            catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
            tracks = catalog["tracks"]
            track = next(item for item in tracks if item.get("track_id") == track_id)
            relative = Path(track["path"])
            expected_digest = str(track["sha256"]).lower()
        except (OSError, json.JSONDecodeError, KeyError, StopIteration, TypeError) as error:
            raise LocalMusicError("music catalog is invalid") from error
        root = self.root.resolve()
        path = (root / relative).resolve()
        if (
            not path.is_relative_to(root)
            or path.suffix.casefold() not in _LOCAL_AUDIO_CONTENT_TYPES
        ):
            raise LocalMusicError("music catalog path is unsafe")
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as error:
            raise LocalMusicError("music asset is unavailable") from error
        if digest != expected_digest:
            raise LocalMusicError("music asset digest does not match catalog")
        return path


class BrowserMusicDelivery:
    """Bounded, memory-only audio handoff for the loopback browser console."""

    def __init__(
        self,
        root: str | Path = DEFAULT_MUSIC_ROOT,
        *,
        max_artifacts: int = MAX_BROWSER_AUDIO_ARTIFACTS,
    ) -> None:
        if max_artifacts < 1:
            raise ValueError("max_artifacts must be positive")
        self.player = LocalMusicPlayer(root)
        self.max_artifacts = max_artifacts
        self._artifacts: dict[str, _BrowserAudioArtifact] = {}
        self._lock = RLock()

    def stage_preview(
        self,
        proposal: ActionProposal,
        authorization: ActionAuthorization,
        now: datetime,
        *,
        audio: bytes,
        content_type: str,
        metadata: dict[str, Any],
    ) -> MusicPlaybackView:
        return self._stage(
            proposal,
            authorization,
            now,
            audio=audio,
            content_type=content_type,
            source=BrowserPlaybackSource.AUDIUS_PREVIEW,
            metadata=metadata,
        )

    def stage_local(
        self,
        proposal: ActionProposal,
        authorization: ActionAuthorization,
        now: datetime,
        *,
        metadata: dict[str, Any],
    ) -> MusicPlaybackView:
        self.player._validate_action(proposal, authorization, now)
        path = self._validated_browser_track(ALLOWED_TRACK_ID)
        try:
            audio = path.read_bytes()
        except OSError as error:
            raise BrowserPlaybackError("LOCAL_ASSET_UNAVAILABLE") from error
        return self._stage(
            proposal,
            authorization,
            now,
            audio=audio,
            content_type=_LOCAL_AUDIO_CONTENT_TYPES[path.suffix.casefold()],
            source=BrowserPlaybackSource.LOCAL_FALLBACK,
            metadata=metadata,
        )

    def deliver(
        self, session_id: str, action_id: str, now: datetime
    ) -> BrowserAudioDelivery:
        with self._lock:
            artifact = self._require(session_id, action_id, now)
            if artifact.status not in {
                BrowserPlaybackStatus.READY,
                BrowserPlaybackStatus.DELIVERED,
            }:
                raise BrowserPlaybackError("BROWSER_AUDIO_NOT_DELIVERABLE")
            artifact.status = BrowserPlaybackStatus.DELIVERED
            return BrowserAudioDelivery(
                audio=artifact.audio,
                content_type=artifact.content_type,
                view=self._view(artifact),
            )

    def complete(
        self,
        session_id: str,
        proposal: ActionProposal,
        authorization: ActionAuthorization,
        now: datetime,
        *,
        started: bool,
        reason: str | None,
    ) -> tuple[MusicPlaybackView, ActionResult]:
        with self._lock:
            artifact = self._require(session_id, proposal.action_id, now)
            if artifact.status is not BrowserPlaybackStatus.DELIVERED:
                raise BrowserPlaybackError("BROWSER_AUDIO_NOT_DELIVERED")
            self.player._validate_action(proposal, authorization, now)
            metadata = dict(artifact.metadata)
            metadata.update(
                {
                    "mock": False,
                    "network_scope": "LOCAL",
                    "playback_scope": "BROWSER",
                    "browser_reported": True,
                    "audible_confirmed": False,
                }
            )
            if started:
                artifact.status = BrowserPlaybackStatus.STARTED
                self.player.executed_action_ids.append(proposal.action_id)
                metadata.update(
                    {
                        "playback_started": True,
                        "physical_action_performed": True,
                    }
                )
                execution_status = ExecutionStatus.SUCCEEDED
            else:
                artifact.status = BrowserPlaybackStatus.FAILED
                metadata.update(
                    {
                        "playback_started": False,
                        "physical_action_performed": False,
                        "code": reason or "BROWSER_PLAYBACK_FAILED",
                    }
                )
                execution_status = ExecutionStatus.FAILED
            view = self._view(artifact)
            del self._artifacts[proposal.action_id]
            return view, ActionResult(
                action_id=proposal.action_id,
                action_type=proposal.action_type,
                execution_status=execution_status,
                result=metadata,
                completed_at=now,
            )

    def discard(self, action_id: str) -> None:
        with self._lock:
            self._artifacts.pop(action_id, None)

    def clear(self) -> None:
        with self._lock:
            self._artifacts.clear()
        self.player.close()

    def _stage(
        self,
        proposal: ActionProposal,
        authorization: ActionAuthorization,
        now: datetime,
        *,
        audio: bytes,
        content_type: str,
        source: BrowserPlaybackSource,
        metadata: dict[str, Any],
    ) -> MusicPlaybackView:
        with self._lock:
            self.player._validate_action(proposal, authorization, now)
            normalized_type = content_type.split(";", 1)[0].strip().casefold()
            if normalized_type not in _BROWSER_AUDIO_CONTENT_TYPES:
                raise BrowserPlaybackError("BROWSER_AUDIO_CONTENT_TYPE_REJECTED")
            if not audio or len(audio) > MAX_BROWSER_AUDIO_BYTES:
                raise BrowserPlaybackError("BROWSER_AUDIO_SIZE_REJECTED")
            self._purge_expired(now)
            if proposal.action_id in self._artifacts:
                raise BrowserPlaybackError("BROWSER_AUDIO_ALREADY_STAGED")
            if len(self._artifacts) >= self.max_artifacts:
                raise BrowserPlaybackError("BROWSER_AUDIO_CAPACITY_EXCEEDED")
            artifact = _BrowserAudioArtifact(
                session_id=proposal.session_id,
                action_id=proposal.action_id,
                audio=bytes(audio),
                content_type=normalized_type,
                source=source,
                expires_at=proposal.expires_at,
                metadata=dict(metadata),
            )
            self._artifacts[proposal.action_id] = artifact
            return self._view(artifact)

    def _require(
        self, session_id: str, action_id: str, now: datetime
    ) -> _BrowserAudioArtifact:
        artifact = self._artifacts.get(action_id)
        if artifact is None or artifact.session_id != session_id:
            raise BrowserPlaybackError("BROWSER_AUDIO_NOT_FOUND")
        if now >= artifact.expires_at:
            del self._artifacts[action_id]
            raise BrowserPlaybackError("BROWSER_AUDIO_EXPIRED")
        return artifact

    def _purge_expired(self, now: datetime) -> None:
        expired = [
            action_id
            for action_id, artifact in self._artifacts.items()
            if now >= artifact.expires_at
        ]
        for action_id in expired:
            del self._artifacts[action_id]

    def _validated_browser_track(self, track_id: str) -> Path:
        if track_id != ALLOWED_TRACK_ID:
            raise BrowserPlaybackError("LOCAL_ASSET_NOT_ALLOWLISTED")
        catalog_path = self.player.root / "catalog.json"
        try:
            catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
            track = next(
                item
                for item in catalog["tracks"]
                if item.get("track_id") == track_id
            )
            relative = Path(track["browser_path"])
            expected_digest = str(track["browser_sha256"]).lower()
        except (
            OSError,
            json.JSONDecodeError,
            KeyError,
            StopIteration,
            TypeError,
        ) as error:
            raise BrowserPlaybackError("BROWSER_ASSET_CATALOG_INVALID") from error
        root = self.player.root.resolve()
        path = (root / relative).resolve()
        if (
            not path.is_relative_to(root)
            or path.suffix.casefold() not in _LOCAL_AUDIO_CONTENT_TYPES
        ):
            raise BrowserPlaybackError("BROWSER_ASSET_PATH_REJECTED")
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as error:
            raise BrowserPlaybackError("BROWSER_ASSET_UNAVAILABLE") from error
        if digest != expected_digest:
            raise BrowserPlaybackError("BROWSER_ASSET_DIGEST_MISMATCH")
        return path

    @staticmethod
    def _view(artifact: _BrowserAudioArtifact) -> MusicPlaybackView:
        return MusicPlaybackView(
            action_id=artifact.action_id,
            status=artifact.status,
            source=artifact.source,
            content_type=artifact.content_type,
            size_bytes=len(artifact.audio),
            expires_at=artifact.expires_at,
        )
