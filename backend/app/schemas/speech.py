"""Bounded session state for the synthetic StepAudio Demo loop."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field, StringConstraints

from .base import StrictModel


AssistantReplyText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]


class AssistantReplySource(StrEnum):
    STEPAUDIO = "STEPAUDIO"
    STEP3_FALLBACK = "STEP3_FALLBACK"
    RULE_FALLBACK = "RULE_FALLBACK"


class AssistantReply(StrictModel):
    text: AssistantReplyText
    source: AssistantReplySource
    latency_ms: int = Field(ge=0, le=120_000)


class TTSPlaybackStatus(StrEnum):
    NOT_REQUESTED = "NOT_REQUESTED"
    READY = "READY"
    STARTED = "STARTED"
    FAILED = "FAILED"
