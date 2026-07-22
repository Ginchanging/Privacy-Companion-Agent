"""Fixed emotion-to-music catalog keys for the competition Demo."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import Field, model_validator

from .analysis import TextStateLabel
from .base import Identifier, StrictModel, require_aware_datetime
from .step3 import StateLabel


class PlaylistKey(StrEnum):
    RELAX = "RELAX"
    COMFORT = "COMFORT"
    UPLIFT = "UPLIFT"
    COOLDOWN = "COOLDOWN"
    NEUTRAL = "NEUTRAL"


PlaylistKeyValue = Annotated[PlaylistKey, Field(strict=False)]


class BrowserPlaybackStatus(StrEnum):
    READY = "READY"
    DELIVERED = "DELIVERED"
    STARTED = "STARTED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class BrowserPlaybackSource(StrEnum):
    AUDIUS_PREVIEW = "AUDIUS_PREVIEW"
    LOCAL_FALLBACK = "LOCAL_FALLBACK"


class BrowserPlaybackReportStatus(StrEnum):
    STARTED = "STARTED"
    FAILED = "FAILED"


class BrowserPlaybackFailureReason(StrEnum):
    MEDIA_ERROR = "MEDIA_ERROR"
    DECODE_FAILED = "DECODE_FAILED"
    PLAY_REJECTED = "PLAY_REJECTED"


class MusicPlaybackView(StrictModel):
    action_id: Identifier
    status: BrowserPlaybackStatus
    source: BrowserPlaybackSource
    content_type: str = Field(pattern=r"^audio/[A-Za-z0-9.+-]+$")
    size_bytes: int = Field(gt=0, le=8 * 1024 * 1024)
    expires_at: datetime

    @model_validator(mode="after")
    def validate_view(self) -> "MusicPlaybackView":
        if not self.action_id.startswith("music-"):
            raise ValueError("browser playback requires a music action_id")
        require_aware_datetime(self.expires_at, "expires_at")
        return self


class BrowserPlaybackReport(StrictModel):
    status: Annotated[BrowserPlaybackReportStatus, Field(strict=False)]
    reason: Annotated[BrowserPlaybackFailureReason, Field(strict=False)] | None = None

    @model_validator(mode="after")
    def validate_report(self) -> "BrowserPlaybackReport":
        if self.status is BrowserPlaybackReportStatus.STARTED and self.reason is not None:
            raise ValueError("STARTED playback cannot include a failure reason")
        if self.status is BrowserPlaybackReportStatus.FAILED and self.reason is None:
            raise ValueError("FAILED playback requires a reason")
        return self

LOGICAL_TRACK_BY_PLAYLIST: dict[PlaylistKey, str] = {
    PlaylistKey.RELAX: "emotion_relax_01",
    PlaylistKey.COMFORT: "emotion_comfort_01",
    PlaylistKey.UPLIFT: "emotion_uplift_01",
    PlaylistKey.COOLDOWN: "emotion_cooldown_01",
    PlaylistKey.NEUTRAL: "emotion_neutral_01",
}
PLAYLIST_BY_LOGICAL_TRACK = {
    track_id: playlist_key
    for playlist_key, track_id in LOGICAL_TRACK_BY_PLAYLIST.items()
}
# Persisted actions created before the multi-playlist phase remain readable.
PLAYLIST_BY_LOGICAL_TRACK["calm_piano_01"] = PlaylistKey.RELAX

EMOTION_PLAYLIST_MAP: dict[TextStateLabel, PlaylistKey] = {
    TextStateLabel.PHYSICAL_FATIGUE: PlaylistKey.RELAX,
    TextStateLabel.STRESSED: PlaylistKey.RELAX,
    TextStateLabel.ANXIOUS: PlaylistKey.RELAX,
    TextStateLabel.EMOTIONAL_LOW: PlaylistKey.COMFORT,
    TextStateLabel.LONELY: PlaylistKey.COMFORT,
    TextStateLabel.HAPPY: PlaylistKey.UPLIFT,
    TextStateLabel.ANGRY: PlaylistKey.COOLDOWN,
    TextStateLabel.CALM: PlaylistKey.NEUTRAL,
    TextStateLabel.OTHER: PlaylistKey.NEUTRAL,
}

LEGACY_STATE_PLAYLIST_MAP: dict[StateLabel, PlaylistKey] = {
    StateLabel.PHYSICAL_FATIGUE: PlaylistKey.RELAX,
    StateLabel.EMOTIONAL_LOW: PlaylistKey.COMFORT,
    StateLabel.OTHER: PlaylistKey.NEUTRAL,
}


def playlist_for_emotion(label: TextStateLabel) -> PlaylistKey:
    return EMOTION_PLAYLIST_MAP[label]


def playlist_for_legacy_state(label: StateLabel) -> PlaylistKey:
    return LEGACY_STATE_PLAYLIST_MAP[label]


def logical_track_for_playlist(playlist_key: PlaylistKey) -> str:
    return LOGICAL_TRACK_BY_PLAYLIST[playlist_key]


def playlist_for_logical_track(track_id: str) -> PlaylistKey:
    try:
        return PLAYLIST_BY_LOGICAL_TRACK[track_id]
    except KeyError as error:
        raise ValueError("logical music track is not allowlisted") from error
