"""envit5 model lifecycle, direction helpers, and streaming generation."""

from __future__ import annotations

import logging
import re
import threading
from typing import Generator, Iterable, Literal, Optional

import torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer, TextIteratorStreamer

logger = logging.getLogger(__name__)

MODEL_ID = "VietAI/envit5-translation"
ResolvedDirection = Literal["vi-en", "en-vi"]

# Vietnamese-specific letters / diacritics (common in modern Vietnamese text).
_VI_CHARS = re.compile(
    r"[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợ"
    r"ùúủũụưừứửữựỳýỷỹỵđ"
    r"ÀÁẢÃẠĂẰẮẲẴẶÂẦẤẨẪẬÈÉẺẼẸÊỀẾỂỄỆÌÍỈĨỊÒÓỎÕỌÔỒỐỔỖỘƠỜỚỞỠỢ"
    r"ÙÚỦŨỤƯỪỨỬỮỰỲÝỶỸỴĐ]"
)
_LETTER = re.compile(r"[A-Za-zÀ-ỹĐđ]")


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


class TranslationService:
    """Holds a single envit5 model instance and a generate lock."""

    def __init__(self, model_id: str = MODEL_ID) -> None:
        self.model_id = model_id
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.tokenizer: Optional[AutoTokenizer] = None
        self.model: Optional[AutoModelForSeq2SeqLM] = None
        self.ready = False
        self._lock = threading.Lock()
        self._load_error: Optional[str] = None
        self._cancel = threading.Event()
        self._gen_thread: Optional[threading.Thread] = None

    def load(self) -> None:
        logger.info("Loading model %s on %s ...", self.model_id, self.device)
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_id)
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

    def stream_translate(
        self,
        text: str,
        direction: ResolvedDirection,
        max_new_tokens: int = 1000,
    ) -> Generator[str, None, str]:
        """Yield decoded token pieces; return the full translated string.

        Caller MUST hold the generate lock (via try_acquire) and release it
        in a finally block. Cooperative cancel via request_cancel().
        """
        if not self.ready or self.model is None or self.tokenizer is None:
            raise ModelNotReadyError("Model is not loaded yet")

        self._cancel.clear()

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

        # StoppingCriteria checks the cancel flag between decode steps so a
        # superseded live-type request can free the lock quickly.
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
            # If cancelled, wait briefly for the generate thread to notice StoppingCriteria.
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


# Process-wide singleton used by FastAPI
service = TranslationService()


def iter_full_text(token_iter: Iterable[str]) -> str:
    """Helper for tests: consume a stream generator and return joined text."""
    return "".join(token_iter)
