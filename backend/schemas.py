"""Pydantic request/response models for the envit5 translation API."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

Direction = Literal["vi-en", "en-vi", "auto"]

# Raised for long-document chunking demos; encode still packs under 480 tokens.
MAX_TEXT_LENGTH = 20000
DEFAULT_MAX_NEW_TOKENS = 256
MAX_NEW_TOKENS_CAP = 512


class TranslateRequest(BaseModel):
    text: str = Field(..., description="Source text to translate")
    direction: Direction = Field(
        ..., description='Translation direction: "vi-en", "en-vi", or "auto"'
    )
    max_new_tokens: int = Field(
        default=DEFAULT_MAX_NEW_TOKENS,
        description="Maximum new tokens per chunk (clamped to 1..512)",
    )
    job_id: Optional[str] = Field(
        default=None,
        description="Client job id for per-request cancel",
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
