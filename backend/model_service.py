"""envit5 model lifecycle, direction helpers, and streaming generation."""

from __future__ import annotations

import logging
import re
import threading
from typing import Callable, Generator, Iterable, List, Literal, Optional

try:  # Optional for unit-only imports in offline environments.
    import torch
except ModuleNotFoundError:  # pragma: no cover - exercised indirectly in tests
    torch = None  # type: ignore[assignment]

try:  # Optional for unit-only imports in offline environments.
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer, TextIteratorStreamer
except ModuleNotFoundError:  # pragma: no cover - exercised indirectly in tests
    AutoModelForSeq2SeqLM = AutoTokenizer = TextIteratorStreamer = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

MODEL_ID = "VietAI/envit5-translation"
ResolvedDirection = Literal["vi-en", "en-vi"]

# Leave headroom under the 512 encode limit for the "vi: "/"en: " prefix.
MAX_SRC_TOKENS = 480

# Vietnamese-specific letters / diacritics (common in modern Vietnamese text).
_VI_CHARS = re.compile(
    r"[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợ"
    r"ùúủũụưừứửữựỳýỷỹỵđ"
    r"ÀÁẢÃẠĂẰẮẲẴẶÂẦẤẨẪẬÈÉẺẼẸÊỀẾỂỄỆÌÍỈĨỊÒÓỎÕỌÔỒỐỔỖỘƠỜỚỞỠỢ"
    r"ÙÚỦŨỤƯỪỨỬỮỰỲÝỶỸỴĐ]"
)
_LETTER = re.compile(r"[A-Za-zÀ-ỹĐđ]")

# Real sentence terminators (ellipsis handled separately so "..." is one unit).
_SENT_END_CHARS = set(".!?。！？")
_QUOTE_CHARS = set("\"'“”‘’«»")


class ModelNotReadyError(RuntimeError):
    """Raised when translate is called before the model finished loading."""


class AutoDetectError(ValueError):
    """Raised when direction=auto cannot be resolved confidently."""


class GenerationCancelled(RuntimeError):
    """Raised when generation is cancelled mid-stream (client disconnect / supersede)."""


def detect_direction(text: str) -> ResolvedDirection:
    """Heuristic VI/EN detector for v1.

    Prefer Vietnamese when characteristic diacritics/letters are present;
    otherwise English. If there are no letters at all, require explicit direction.
    """
    stripped = text.strip()
    if not stripped or not _LETTER.search(stripped):
        raise AutoDetectError(
            "Could not auto-detect language (no letters found). "
            "Please set direction to 'vi-en' or 'en-vi'."
        )
    if _VI_CHARS.search(stripped):
        return "vi-en"
    return "en-vi"


def resolve_direction(text: str, direction: str) -> ResolvedDirection:
    if direction == "auto":
        return detect_direction(text)
    if direction in ("vi-en", "en-vi"):
        return direction  # type: ignore[return-value]
    raise ValueError(f"Invalid direction: {direction!r}")


def apply_prefix(text: str, direction: ResolvedDirection) -> str:
    """Apply envit5 source-language prefixes required by the model card."""
    if direction == "vi-en":
        return f"vi: {text}"
    return f"en: {text}"


def strip_target_prefix(text: str, direction: ResolvedDirection) -> str:
    """Remove the target-language tag envit5 often emits (e.g. 'en: ', 'vi: ')."""
    for tag in ("en: ", "vi: ", "en:", "vi:"):
        if text.startswith(tag):
            return text[len(tag) :].lstrip()
    stripped = text.lstrip()
    for tag in ("en: ", "vi: ", "en:", "vi:"):
        if stripped.startswith(tag):
            return stripped[len(tag) :].lstrip()
    return text


def split_sentences(text: str) -> List[str]:
    """Split on real sentence ends; keep ellipsis, commas, and quoted interiors intact.

    Rules:
    - ``...`` / ``…`` is one terminator (not three periods).
    - ``,`` / ``,,`` / ``,,,`` never end a sentence.
    - ``.!?…。！？`` only end a sentence when not inside quotes and followed by
      whitespace, a closing quote + whitespace, or end-of-text.
    """
    s = text.strip()
    if not s:
        return []

    sentences: List[str] = []
    buf: List[str] = []
    i = 0
    n = len(s)
    # ponytail: toggle map covers paired + ambiguous ASCII quotes
    in_quote = False

    def _flush() -> None:
        piece = "".join(buf).strip()
        buf.clear()
        if piece:
            sentences.append(piece)

    def _should_end_sentence(pos: int) -> bool:
        """True if terminator at end-of-text or before whitespace then non-lowercase.

        Lowercase after `."` / `...` keeps one sentence: She whispered "Wait..." then left.
        Uppercase starts a new one: He said "Hi." Bye.
        """
        if in_quote:
            return False
        if pos >= n:
            return True
        if not s[pos].isspace():
            return False
        j = pos
        while j < n and s[j].isspace():
            j += 1
        if j >= n:
            return True
        # New sentence usually starts with uppercase / digit / quote; lowercase continues.
        return not s[j].islower()

    while i < n:
        # Ellipsis as a single unit: "..." or "…"
        if s.startswith("...", i) or s[i] == "…":
            if s.startswith("...", i):
                buf.append("...")
                i += 3
            else:
                buf.append("…")
                i += 1
            while i < n and s[i] in _QUOTE_CHARS:
                buf.append(s[i])
                in_quote = not in_quote
                i += 1
            if _should_end_sentence(i):
                _flush()
                while i < n and s[i].isspace():
                    i += 1
            continue

        ch = s[i]

        if ch in _QUOTE_CHARS:
            in_quote = not in_quote
            buf.append(ch)
            i += 1
            continue

        # Bare commas (including ,, / ,,,) never end a sentence.
        if ch in _SENT_END_CHARS:
            buf.append(ch)
            i += 1
            while i < n and s[i] in _QUOTE_CHARS:
                buf.append(s[i])
                in_quote = not in_quote
                i += 1
            if _should_end_sentence(i):
                _flush()
                while i < n and s[i].isspace():
                    i += 1
            continue

        buf.append(ch)
        i += 1

    _flush()
    return sentences


def pack_chunks(
    sentences: List[str],
    count_tokens: Callable[[str], int],
    max_tokens: int = MAX_SRC_TOKENS,
) -> List[str]:
    """Greedily pack sentences under max_tokens; hard-split oversized ones by words."""
    if not sentences:
        return []

    chunks: List[str] = []
    cur: List[str] = []

    def _cur_text(extra: str = "") -> str:
        parts = cur + ([extra] if extra else [])
        return " ".join(parts)

    def _flush_cur() -> None:
        if cur:
            chunks.append(" ".join(cur))
            cur.clear()

    def _hard_split(sentence: str) -> None:
        words = sentence.split()
        if not words:
            return
        piece: List[str] = []
        for w in words:
            trial = " ".join(piece + [w]) if piece else w
            if piece and count_tokens(trial) > max_tokens:
                chunks.append(" ".join(piece))
                piece = [w]
            else:
                piece.append(w)
        if piece:
            # emit even if a single word still exceeds (encode will truncate)
            chunks.append(" ".join(piece))

    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        n = count_tokens(sent)
        if n > max_tokens:
            _flush_cur()
            _hard_split(sent)
            continue
        if cur and count_tokens(_cur_text(sent)) > max_tokens:
            _flush_cur()
        cur.append(sent)

    _flush_cur()
    return chunks


class TranslationService:
    """Holds a single envit5 model instance and a generate lock."""

    def __init__(self, model_id: str = MODEL_ID) -> None:
        self.model_id = model_id
        self.device = "cuda" if torch is not None and torch.cuda.is_available() else "cpu"
        self.tokenizer: Optional[AutoTokenizer] = None
        self.model: Optional[AutoModelForSeq2SeqLM] = None
        self.ready = False
        self._lock = threading.Lock()
        self._load_error: Optional[str] = None
        self._cancel = threading.Event()
        self._gen_thread: Optional[threading.Thread] = None

    def load(self) -> None:
        logger.info("Loading model %s on %s ...", self.model_id, self.device)
        if torch is None or AutoModelForSeq2SeqLM is None or AutoTokenizer is None:
            raise ModuleNotFoundError(
                "torch and transformers are required to load the translation model"
            )
        try:
            # transformers 5.x breaks envit5 AutoTokenizer (Unigram vs BPE tokenizer.json).
            try:
                self.tokenizer = AutoTokenizer.from_pretrained(self.model_id)
            except TypeError as tok_exc:
                from huggingface_hub import hf_hub_download
                from transformers import PreTrainedTokenizerFast

                logger.warning(
                    "AutoTokenizer failed for %s (%s); using PreTrainedTokenizerFast",
                    self.model_id,
                    tok_exc,
                )
                tok_file = hf_hub_download(self.model_id, "tokenizer.json")
                # Pass specials in constructor so TextIteratorStreamer skip_special_tokens works.
                self.tokenizer = PreTrainedTokenizerFast(
                    tokenizer_file=tok_file,
                    eos_token="</s>",
                    unk_token="<unk>",
                    pad_token="<pad>",
                )
            self.model = AutoModelForSeq2SeqLM.from_pretrained(self.model_id)
            self.model.to(self.device)
            self.model.eval()
            self.ready = True
            self._load_error = None
            logger.info("Model ready on %s", self.device)
        except Exception as exc:  # noqa: BLE001 — surface load failures via /health
            self.ready = False
            self._load_error = str(exc)
            logger.exception("Failed to load model: %s", exc)
            raise

    def health(self) -> dict:
        return {
            "status": "ok" if self.ready else "loading" if self._load_error is None else "error",
            "model_id": self.model_id,
            "device": self.device,
            "ready": self.ready,
            "busy": self._lock.locked(),
        }

    def try_acquire(self) -> bool:
        return self._lock.acquire(blocking=False)

    def release(self) -> None:
        if self._lock.locked():
            self._lock.release()

    def request_cancel(self) -> bool:
        """Signal the active generation to stop. Returns whether a job was busy."""
        busy = self._lock.locked()
        if busy:
            self._cancel.set()
            logger.info("Cancel requested for active generation")
        return busy

    def count_tokens(self, text: str) -> int:
        """Token length of raw source text (no language prefix)."""
        if self.tokenizer is None:
            # Approximate for unit tests / pre-load packing.
            return max(1, len(text.split()))
        return len(self.tokenizer.encode(text, add_special_tokens=False))

    def prepare_chunks(self, text: str) -> List[str]:
        """Split + pack source text into encode-safe chunks."""
        sentences = split_sentences(text)
        if not sentences:
            return [text.strip()] if text.strip() else []
        return pack_chunks(sentences, self.count_tokens, MAX_SRC_TOKENS)

    def _stream_one_chunk(
        self,
        text: str,
        direction: ResolvedDirection,
        max_new_tokens: int,
    ) -> Generator[str, None, str]:
        """Yield decoded token pieces for a single chunk; return full chunk text."""
        assert self.model is not None and self.tokenizer is not None
        if torch is None or TextIteratorStreamer is None:
            raise ModelNotReadyError("Model dependencies are not installed yet")

        if self._cancel.is_set():
            raise GenerationCancelled("Generation cancelled")

        prefixed = apply_prefix(text, direction)
        inputs = self.tokenizer(
            prefixed,
            return_tensors="pt",
            truncation=True,
            max_length=512,
        )
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        streamer = TextIteratorStreamer(
            self.tokenizer,
            skip_prompt=True,
            skip_special_tokens=True,
        )

        from transformers import StoppingCriteria, StoppingCriteriaList

        cancel_flag = self._cancel

        class _CancelCriteria(StoppingCriteria):
            def __call__(self, input_ids, scores, **kwargs) -> bool:  # noqa: ANN001
                return cancel_flag.is_set()

        generation_kwargs = {
            **inputs,
            "streamer": streamer,
            "max_new_tokens": max_new_tokens,
            "num_beams": 1,  # greedy/stream-friendly; beam search does not stream well
            "do_sample": False,
            "stopping_criteria": StoppingCriteriaList([_CancelCriteria()]),
        }

        error_box: list[BaseException] = []

        def _generate() -> None:
            try:
                assert self.model is not None
                with torch.inference_mode():
                    self.model.generate(**generation_kwargs)
            except BaseException as exc:  # noqa: BLE001 — relay to consumer
                error_box.append(exc)

        thread = threading.Thread(target=_generate, daemon=True)
        self._gen_thread = thread
        thread.start()

        pieces: list[str] = []
        buffer = ""
        tag_stripped = False
        cancelled = False
        try:
            for piece in streamer:
                if cancel_flag.is_set():
                    cancelled = True
                    break
                if not piece:
                    continue
                if not tag_stripped:
                    buffer += piece
                    cleaned = strip_target_prefix(buffer, direction)
                    if cleaned != buffer or len(buffer) > 8:
                        tag_stripped = True
                        if cleaned:
                            pieces.append(cleaned)
                            yield cleaned
                        buffer = ""
                    continue
                pieces.append(piece)
                yield piece
        finally:
            thread.join(timeout=5 if cancel_flag.is_set() else 120)
            self._gen_thread = None

        if cancelled or cancel_flag.is_set():
            raise GenerationCancelled("Generation cancelled")

        if error_box:
            raise RuntimeError(f"Generation failed: {error_box[0]}") from error_box[0]

        if buffer and not tag_stripped:
            cleaned = strip_target_prefix(buffer, direction)
            if cleaned:
                pieces.append(cleaned)

        return "".join(pieces).strip()

    def stream_translate(
        self,
        text: str,
        direction: ResolvedDirection,
        max_new_tokens: int = 256,
    ) -> Generator[dict, None, str]:
        """Yield SSE-shaped events for multi-chunk translation; return full text.

        Yields dicts:
          {"type": "chunk", "i": int, "n": int}
          {"type": "token", "t": str, "i": int}

        Caller MUST hold the generate lock (via try_acquire) and release it
        in a finally block. Cooperative cancel via request_cancel().
        """
        if not self.ready or self.model is None or self.tokenizer is None:
            raise ModelNotReadyError("Model is not loaded yet")

        self._cancel.clear()

        chunks = self.prepare_chunks(text)
        if not chunks:
            return ""

        n = len(chunks)
        assembled: list[str] = []

        for i, chunk in enumerate(chunks):
            if self._cancel.is_set():
                raise GenerationCancelled("Generation cancelled")

            yield {"type": "chunk", "i": i, "n": n}

            gen = self._stream_one_chunk(chunk, direction, max_new_tokens)
            chunk_text = ""
            try:
                while True:
                    piece = next(gen)
                    chunk_text += piece
                    yield {"type": "token", "t": piece, "i": i}
            except StopIteration as stop:
                if stop.value:
                    chunk_text = stop.value

            if chunk_text:
                assembled.append(chunk_text)

        return " ".join(assembled).strip()


# Process-wide singleton used by FastAPI
service = TranslationService()


def iter_full_text(token_iter: Iterable[str]) -> str:
    """Helper for tests: consume a stream generator and return joined text."""
    return "".join(token_iter)
