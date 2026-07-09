#!/usr/bin/env python3
"""Prefetch VietAI/envit5-translation into the local Hugging Face cache."""

from __future__ import annotations

import argparse
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Download envit5 translation model")
    parser.add_argument(
        "--model-id",
        default=os.environ.get("ENVIT5_MODEL_ID", "VietAI/envit5-translation"),
        help="Hugging Face model id (default: VietAI/envit5-translation)",
    )
    parser.add_argument(
        "--cache-dir",
        default=os.environ.get("HF_HOME")
        or os.environ.get("TRANSFORMERS_CACHE")
        or None,
        help="Optional HF cache directory",
    )
    args = parser.parse_args()

    print(f"Downloading tokenizer + model: {args.model_id}")
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

    kwargs = {}
    if args.cache_dir:
        kwargs["cache_dir"] = args.cache_dir
        os.makedirs(args.cache_dir, exist_ok=True)

    tok = AutoTokenizer.from_pretrained(args.model_id, **kwargs)
    model = AutoModelForSeq2SeqLM.from_pretrained(args.model_id, **kwargs)
    print(f"OK — vocab size={getattr(tok, 'vocab_size', '?')}, "
          f"params≈{sum(p.numel() for p in model.parameters()) / 1e6:.1f}M")
    return 0


if __name__ == "__main__":
    sys.exit(main())
