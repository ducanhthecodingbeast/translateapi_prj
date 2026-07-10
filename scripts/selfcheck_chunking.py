#!/usr/bin/env python3
"""No-GPU self-check for split/pack + schema limits (acceptance A*)."""
from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

# Stub heavy deps so helpers import without torch/transformers installed.
torch = types.ModuleType("torch")
torch.cuda = types.SimpleNamespace(is_available=lambda: False)
sys.modules["torch"] = torch
transformers = types.ModuleType("transformers")


class _Dummy:
    pass


transformers.AutoModelForSeq2SeqLM = _Dummy
transformers.AutoTokenizer = _Dummy
transformers.TextIteratorStreamer = _Dummy
sys.modules["transformers"] = transformers

from model_service import pack_chunks, split_sentences  # noqa: E402
from schemas import MAX_TEXT_LENGTH, TranslateRequest  # noqa: E402


def check(name: str, got, exp) -> int:
    if got != exp:
        print(f"FAIL {name}: got={got!r} exp={exp!r}")
        return 1
    print(f"OK {name}")
    return 0


def main() -> int:
    failed = 0
    failed += check(
        "basic",
        split_sentences("Hello world. How are you? Fine!"),
        ["Hello world.", "How are you?", "Fine!"],
    )
    failed += check(
        "ellipsis",
        split_sentences("Wait... Really? Done… Yes."),
        ["Wait...", "Really?", "Done…", "Yes."],
    )
    failed += check(
        "commas",
        split_sentences("a,, b,,, c. Next."),
        ["a,, b,,, c.", "Next."],
    )
    failed += check(
        "quote_hi",
        split_sentences('He said "Hi." Bye.'),
        ['He said "Hi."', "Bye."],
    )
    failed += check(
        "quote_wait",
        split_sentences('She whispered "Wait..." then left.'),
        ['She whispered "Wait..." then left.'],
    )
    failed += check(
        "quote_stop",
        split_sentences('He said "Stop." Next came silence.'),
        ['He said "Stop."', "Next came silence."],
    )
    failed += check(
        "quote_then",
        split_sentences('He said "Hi." then left quietly.'),
        ['He said "Hi." then left quietly.'],
    )
    failed += check(
        "commas_only",
        split_sentences("apples, oranges, bananas"),
        ["apples, oranges, bananas"],
    )

    sents = split_sentences("Xin chào. Tôi là sinh viên. Bạn khỏe không?")
    if not (len(sents) == 3 and sents[0] == "Xin chào."):
        print("FAIL vietnamese", sents)
        failed += 1
    else:
        print("OK vietnamese", sents)

    chunks = pack_chunks(
        ["One.", "Two.", "Three."],
        count_tokens=lambda t: len(t.split()),
        max_tokens=3,
    )
    if " ".join(chunks) != "One. Two. Three.":
        print("FAIL pack", chunks)
        failed += 1
    else:
        print("OK pack", chunks)

    hard = pack_chunks(
        ["alpha beta gamma delta epsilon"],
        count_tokens=lambda t: len(t.split()),
        max_tokens=2,
    )
    if not all(len(c.split()) <= 2 for c in hard) or " ".join(hard) != "alpha beta gamma delta epsilon":
        print("FAIL hard", hard)
        failed += 1
    else:
        print("OK hard", hard)

    req = TranslateRequest(text="a" * 5000, direction="en-vi")
    if len(req.text) != 5000:
        print("FAIL long text")
        failed += 1
    else:
        print("OK long text")

    try:
        TranslateRequest(text="a" * (MAX_TEXT_LENGTH + 1), direction="vi-en")
        print("FAIL reject overlong")
        failed += 1
    except Exception:
        print("OK reject overlong")

    req2 = TranslateRequest(text="hello", direction="en-vi", max_new_tokens=9999)
    if req2.max_new_tokens != 512:
        print("FAIL clamp", req2.max_new_tokens)
        failed += 1
    else:
        print("OK clamp", req2.max_new_tokens)

    demo = 'Wait... Really? He said "Hi." Bye. a,, b,,, c. Next sentence here.'
    print("demo:", split_sentences(demo))

    if failed:
        print(f"{failed} failures")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
