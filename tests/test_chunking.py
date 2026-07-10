"""Unit tests for sentence split / pack (no GPU / model load)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from model_service import pack_chunks, split_sentences  # noqa: E402
from schemas import MAX_TEXT_LENGTH, TranslateRequest  # noqa: E402


def test_split_basic_sentences():
    sents = split_sentences("Hello world. How are you? Fine!")
    assert sents == ["Hello world.", "How are you?", "Fine!"]


def test_ellipsis_is_one_unit():
    sents = split_sentences("Wait... Really? Done… Yes.")
    assert sents == ["Wait...", "Really?", "Done…", "Yes."]


def test_repeated_commas_do_not_split():
    sents = split_sentences("a,, b,,, c. Next.")
    assert sents == ["a,, b,,, c.", "Next."]


def test_quotes_protect_internal_period():
    sents = split_sentences('He said "Hi." Bye.')
    assert sents == ['He said "Hi."', "Bye."]


def test_quotes_with_ellipsis():
    sents = split_sentences('She whispered "Wait..." then left.')
    assert sents == ['She whispered "Wait..." then left.']


def test_quoted_period_then_uppercase_splits():
    sents = split_sentences('He said "Stop." Next came silence.')
    assert sents == ['He said "Stop."', "Next came silence."]


def test_quoted_period_then_lowercase_continues():
    sents = split_sentences('He said "Hi." then left quietly.')
    assert sents == ['He said "Hi." then left quietly.']


def test_vietnamese_sentences():
    sents = split_sentences("Xin chào. Tôi là sinh viên. Bạn khỏe không?")
    assert len(sents) == 3
    assert sents[0] == "Xin chào."


def test_no_split_on_lone_comma():
    sents = split_sentences("apples, oranges, bananas")
    assert sents == ["apples, oranges, bananas"]


def test_demo_special_case_bundle():
    text = 'Wait... Really? He said "Hi." Bye. a,, b,,, c. Next sentence here.'
    sents = split_sentences(text)
    assert sents[0] == "Wait..."
    assert sents[1] == "Really?"
    assert any("a,, b,,, c." in s for s in sents)
    assert sents[-1] == "Next sentence here."


def test_pack_under_budget():
    sents = ["One.", "Two.", "Three."]
    chunks = pack_chunks(sents, count_tokens=lambda t: len(t.split()), max_tokens=3)
    # "One. Two." = 2 tokens under budget 3; "Three." alone
    assert len(chunks) >= 1
    assert " ".join(chunks).replace("  ", " ") == "One. Two. Three."


def test_pack_hard_splits_oversized():
    sents = ["alpha beta gamma delta epsilon"]
    chunks = pack_chunks(sents, count_tokens=lambda t: len(t.split()), max_tokens=2)
    assert all(len(c.split()) <= 2 for c in chunks)
    assert " ".join(chunks) == "alpha beta gamma delta epsilon"


def test_request_accepts_long_text():
    req = TranslateRequest(text="a" * 5000, direction="en-vi")
    assert len(req.text) == 5000


def test_request_rejects_over_ceiling():
    try:
        TranslateRequest(text="a" * (MAX_TEXT_LENGTH + 1), direction="vi-en")
        assert False, "should have raised"
    except Exception:
        pass


def test_max_new_tokens_clamped_to_512():
    req = TranslateRequest(text="hello", direction="en-vi", max_new_tokens=9999)
    assert req.max_new_tokens == 512
