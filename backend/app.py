"""FastAPI entrypoint: /health and SSE /translate for envit5."""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Iterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from model_service import (
    AutoDetectError,
    GenerationCancelled,
    resolve_direction,
    service,
)
from schemas import HealthResponse, TranslateRequest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("envit5.api")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    try:
        service.load()
    except Exception:  # noqa: BLE001 — keep server up; /health reports ready=false
        logger.exception("Model failed to load at startup; /translate will return 503")
    yield


app = FastAPI(
    title="envit5 Translation API",
    description="Vietnamese↔English token-streaming translation via VietAI/envit5-translation",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Map FastAPI/Pydantic 422 validation errors to HTTP 400 with a clear message."""
    messages: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(x) for x in err.get("loc", ()) if x != "body")
        msg = err.get("msg", "invalid value")
        messages.append(f"{loc}: {msg}" if loc else msg)
    detail = "; ".join(messages) if messages else "Invalid request"
    return JSONResponse(status_code=400, content={"detail": detail})


def _sse_event(event: str, data: dict) -> dict:
    return {"event": event, "data": json.dumps(data, ensure_ascii=False)}


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    payload = service.health()
    # HealthResponse schema is fixed; drop busy if not in model.
    return HealthResponse(
        status=payload["status"],
        model_id=payload["model_id"],
        device=payload["device"],
        ready=payload["ready"],
    )


@app.post("/cancel")
def cancel_generation() -> dict:
    """Request cancellation of the in-flight generation (live-type supersede)."""
    busy = service.request_cancel()
    return {"cancelled": busy, "message": "cancel signaled" if busy else "nothing running"}


@app.post("/translate")
def translate(body: TranslateRequest) -> EventSourceResponse:
    if not service.ready:
        raise HTTPException(status_code=503, detail="Model is not loaded / not ready")

    try:
        direction = resolve_direction(body.text, body.direction)
    except AutoDetectError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Live-as-you-type: if a previous decode is still holding the lock, ask it
    # to cancel and wait briefly so the new request can take over.
    if not service.try_acquire():
        service.request_cancel()
        acquired = False
        for _ in range(50):  # up to ~5s
            import time

            time.sleep(0.1)
            if service.try_acquire():
                acquired = True
                break
        if not acquired:
            raise HTTPException(
                status_code=429,
                detail="Translation already in progress. Retry after the current request finishes.",
            )

    def event_stream() -> Iterator[dict]:
        full_text = ""
        try:
            yield _sse_event(
                "meta",
                {"direction": direction, "model": service.model_id},
            )
            stream = service.stream_translate(
                text=body.text,
                direction=direction,
                max_new_tokens=body.max_new_tokens,
            )
            try:
                while True:
                    piece = next(stream)
                    full_text += piece
                    yield _sse_event("token", {"t": piece})
            except StopIteration as stop:
                if stop.value:
                    full_text = stop.value
                else:
                    full_text = full_text.strip()

            yield _sse_event(
                "done",
                {"text": full_text, "direction": direction},
            )
        except GenerationCancelled:
            yield _sse_event(
                "error",
                {"message": "cancelled", "code": "cancelled"},
            )
        except Exception as exc:  # noqa: BLE001 — surface as SSE error, always release lock
            logger.exception("Error during streaming translation")
            yield _sse_event("error", {"message": str(exc)})
        finally:
            service.release()

    return EventSourceResponse(event_stream())


if __name__ == "__main__":
    import uvicorn

    # Default to 18800 — host 8000 is often occupied on shared machines.
    uvicorn.run("app:app", host="127.0.0.1", port=18800, reload=False)
