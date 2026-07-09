"""Pydantic request/response models for the envit5 translation API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Direction = Literal["vi-en", "en-vi", "auto"]

MAX_TEXT_LENGTH = 2000
DEFAULT_MAX_NEW_TOKENS = 1000
MAX_NEW_TOKENS_CAP = 1000


class TranslateRequest(BaseModel):
    text: str = Field(..., description="Source text to translate")
    direction: Direction = Field(
        ..., description='Translation direction: "vi-en", "en-vi", or "auto"'
    )
    max_new_tokens: int = Field(
        default=DEFAULT_MAX_NEW_TOKENS,
        description="Maximum new tokens to generate (clamped to 1..1000)",
    )

    @field_validator("text")
    @classmethod
    def text_must_be_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("text must be non-empty after stripping whitespace")
        if len(stripped) > MAX_TEXT_LENGTH:
            raise ValueError(
                f"text exceeds maximum length of {MAX_TEXT_LENGTH} characters"
            )
        return stripped

    @field_validator("max_new_tokens")
    @classmethod
    def clamp_max_new_tokens(cls, value: int) -> int:
        return max(1, min(int(value), MAX_NEW_TOKENS_CAP))


class HealthResponse(BaseModel):
    status: str
    model_id: str
    device: str
    ready: bool
