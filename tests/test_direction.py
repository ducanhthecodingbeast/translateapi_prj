"""Unit tests for prefix selection and auto-detect (no GPU / model load)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from model_service import (  # noqa: E402
    AutoDetectError,
    apply_prefix,
    detect_direction,
    resolve_direction,
    strip_target_prefix,
)
from schemas import TranslateRequest  # noqa: E402


def test_apply_prefix_vi_en():
    assert apply_prefix("Xin chào", "vi-en") == "vi: Xin chào"


def test_apply_prefix_en_vi():
    assert apply_prefix("Hello", "en-vi") == "en: Hello"


def test_strip_target_prefix():
    assert strip_target_prefix("en: Hello.", "vi-en") == "Hello."
    assert strip_target_prefix("vi: Xin chào", "en-vi") == "Xin chào"
    assert strip_target_prefix("Hello.", "vi-en") == "Hello."


def test_detect_vietnamese_diacritics():
    assert detect_direction("Xin chào các bạn") == "vi-en"


def test_detect_english():
    assert detect_direction("Hello everyone, how are you?") == "en-vi"


def test_detect_no_letters_raises():
    with pytest.raises(AutoDetectError):
        detect_direction("12345 !!!")


def test_resolve_auto():
    assert resolve_direction("Tôi là sinh viên", "auto") == "vi-en"
    assert resolve_direction("I am a student", "auto") == "en-vi"


def test_resolve_explicit():
    assert resolve_direction("anything", "vi-en") == "vi-en"
    assert resolve_direction("anything", "en-vi") == "en-vi"


def test_request_rejects_empty():
    with pytest.raises(Exception):
        TranslateRequest(text="   ", direction="auto")


def test_request_rejects_overlong():
    with pytest.raises(Exception):
        TranslateRequest(text="a" * 2001, direction="vi-en")


def test_request_accepts_trimmed():
    req = TranslateRequest(text="  hello  ", direction="en-vi")
    assert req.text == "hello"


def test_max_new_tokens_clamped():
    req = TranslateRequest(text="hello", direction="en-vi", max_new_tokens=9999)
    assert req.max_new_tokens == 1000
