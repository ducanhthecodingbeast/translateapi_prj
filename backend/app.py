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
    version="0.2.0",
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
async def cancel_generation(request: Request) -> dict:
    """Cancel only the given job_id. Never steals other users."""
    job_id = None
    try:
        body = await request.json()
        if isinstance(body, dict):
            job_id = body.get("job_id")
    except Exception:
        job_id = None
    return service.request_cancel(job_id)


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

    job_id = (getattr(body, "job_id", None) or "").strip() or str(uuid.uuid4())
    queue_timeout_s = 60.0
    queue_poll_s = 0.4

    def event_stream() -> Iterator[dict]:
        acquired = False
        full_text = ""
        try:
            yield _sse_event(
                "queued",
                {"job_id": job_id, "message": "waiting for model", "wait_s": 0},
            )
            deadline = time.monotonic() + queue_timeout_s
            while True:
                if service.is_job_cancelled(job_id):
                    yield _sse_event(
                        "cancelled",
                        {"job_id": job_id, "message": "cancelled while queued"},
                    )
                    return
                status = service.try_begin_job(job_id)
                if status is None:
                    acquired = True
                    break
                if status == "cancelled":
                    yield _sse_event(
                        "cancelled",
                        {"job_id": job_id, "message": "cancelled while queued"},
                    )
                    return
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    yield _sse_event(
                        "error",
                        {
                            "job_id": job_id,
                            "code": "queue_timeout",
                            "message": (
                                f"Translation queue busy for >{int(queue_timeout_s)}s. "
                                "Retry shortly."
                            ),
                        },
                    )
                    return
                yield _sse_event(
                    "queued",
                    {
                        "job_id": job_id,
                        "message": "waiting for model",
                        "wait_s": int(remaining),
                    },
                )
                time.sleep(queue_poll_s)

            chunks = service.prepare_chunks(body.text)
            n_chunks = len(chunks)
            yield _sse_event(
                "meta",
                {
                    "job_id": job_id,
                    "direction": direction,
                    "chunks": n_chunks,
                    "status": "running",
                },
            )

            stream = service.stream_translate(
                body.text,
                direction=direction,
                max_new_tokens=body.max_new_tokens,
            )
            while True:
                try:
                    event = next(stream)
                    etype = event.get("type")
                    if etype == "chunk":
                        yield _sse_event("chunk", {"i": event["i"], "n": event["n"]})
                    elif etype == "token":
                        piece = event["t"]
                        full_text += piece
                        yield _sse_event("token", {"t": piece, "i": event.get("i", 0)})
                except StopIteration as stop:
                    if stop.value:
                        full_text = stop.value
                    break

            yield _sse_event(
                "done",
                {
                    "text": full_text,
                    "job_id": job_id,
                    "direction": direction,
                    "chunks": n_chunks,
                },
            )
        except GenerationCancelled as exc:
            yield _sse_event("cancelled", {"job_id": job_id, "message": str(exc)})
        except Exception as exc:  # noqa: BLE001
            logger.exception("translate stream failed")
            yield _sse_event("error", {"job_id": job_id, "message": str(exc)})
        finally:
            if acquired:
                service.end_job(job_id)

    return EventSourceResponse(event_stream())



if __name__ == "__main__":
    import uvicorn

    # Default to 18800 — host 8000 is often occupied on shared machines.
    uvicorn.run("app:app", host="127.0.0.1", port=18800, reload=False)
