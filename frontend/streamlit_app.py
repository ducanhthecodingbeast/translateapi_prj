"""Streamlit UI for envit5 live token-streaming translation (SSE client).

Live-as-you-type: after a short debounce, each source edit streams tokens
into the output panel below. Visual system follows /home/aiface/nvidia/DESIGN.md.
"""

from __future__ import annotations

import html
import json
import os
import time
from typing import Generator, Optional

import httpx
import streamlit as st

from live_textarea_component import live_textarea

DEFAULT_API_BASE = os.environ.get("ENVIT5_API_BASE", "http://127.0.0.1:18800")
# Pause after last keystroke before starting a new SSE translate.
DEBOUNCE_MS = int(os.environ.get("ENVIT5_DEBOUNCE_MS", "450"))
# Minimum characters before auto-translate fires (avoids noise on 1–2 letters).
MIN_CHARS = int(os.environ.get("ENVIT5_MIN_CHARS", "2"))

# NVIDIA design tokens (from DESIGN.md)
C_PRIMARY = "#76b900"
C_PRIMARY_DARK = "#5a8d00"
C_INK = "#000000"
C_CANVAS = "#ffffff"
C_SURFACE_DARK = "#000000"
C_SURFACE_SOFT = "#f7f7f7"
C_HAIRLINE = "#cccccc"
C_BODY = "#1a1a1a"
C_MUTE = "#757575"
C_ON_DARK = "#ffffff"
C_ON_DARK_MUTE = "rgba(255,255,255,0.7)"
C_ERROR = "#e52020"
C_SUCCESS_DEEP = "#3f8500"

DIRECTION_LABELS = {
    "Auto": "auto",
    "VI → EN": "vi-en",
    "EN → VI": "en-vi",
}

NVIDIA_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;700&display=swap');

:root {{
  --nv-primary: {C_PRIMARY};
  --nv-primary-dark: {C_PRIMARY_DARK};
  --nv-ink: {C_INK};
  --nv-canvas: {C_CANVAS};
  --nv-surface-dark: {C_SURFACE_DARK};
  --nv-surface-soft: {C_SURFACE_SOFT};
  --nv-hairline: {C_HAIRLINE};
  --nv-body: {C_BODY};
  --nv-mute: {C_MUTE};
  --nv-on-dark: {C_ON_DARK};
  --nv-error: {C_ERROR};
  --nv-success: {C_SUCCESS_DEEP};
  --nv-radius: 2px;
}}

html, body, [class*="css"], .stApp, .stMarkdown, .stText, p, span, label, div {{
  font-family: Inter, Arial, Helvetica, sans-serif !important;
}}

#MainMenu {{ visibility: hidden; }}
footer {{ visibility: hidden; }}
header[data-testid="stHeader"] {{ background: transparent; }}
div[data-testid="stToolbar"] {{ display: none; }}
.stDeployButton {{ display: none; }}

.stApp {{
  background: var(--nv-canvas);
  color: var(--nv-body);
}}

.block-container {{
  padding-top: 0 !important;
  padding-bottom: 0 !important;
  max-width: 1180px !important;
}}

/* Side-by-side input / output panels — matched heights */
.nv-io-panel {{
  background: var(--nv-canvas);
  border: 1px solid var(--nv-hairline);
  border-radius: var(--nv-radius);
  padding: 20px 20px 12px 20px;
  position: relative;
  min-height: 120px;
  height: 100%;
  display: flex;
  flex-direction: column;
  margin-bottom: 0;
}}
.nv-io-panel::before {{
  content: "";
  position: absolute;
  top: 0;
  left: 0;
  width: 12px;
  height: 12px;
  background: var(--nv-primary);
}}
.nv-io-panel .nv-card-title {{
  margin-top: 4px;
}}
.nv-direction-bar {{
  background: var(--nv-canvas);
  border: 1px solid var(--nv-hairline);
  border-radius: var(--nv-radius);
  padding: 16px 20px;
  position: relative;
  margin-top: 8px;
  margin-bottom: 8px;
}}
.nv-direction-bar::before {{
  content: "";
  position: absolute;
  top: 0;
  left: 0;
  width: 12px;
  height: 12px;
  background: var(--nv-primary);
}}
div[data-testid="column"] {{
  padding-left: 0.4rem !important;
  padding-right: 0.4rem !important;
}}
div[data-testid="column"] > div {{
  height: 100%;
}}

.nv-utility {{
  background: var(--nv-surface-dark);
  color: var(--nv-on-dark);
  font-size: 12px;
  font-weight: 400;
  line-height: 1.25;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  margin: 0 -1rem;
}}
.nv-utility span {{ opacity: 0.85; }}
.nv-utility strong {{ color: var(--nv-primary); font-weight: 700; }}

.nv-nav {{
  background: var(--nv-surface-dark);
  color: var(--nv-on-dark);
  height: 64px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  margin: 0 -1rem;
  border-top: 1px solid #1a1a1a;
}}
.nv-brand {{
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 16px;
  font-weight: 700;
}}
.nv-brand-mark {{
  width: 18px;
  height: 18px;
  background: var(--nv-primary);
  display: inline-block;
}}
.nv-nav-meta {{
  font-size: 14px;
  font-weight: 700;
  color: var(--nv-on-dark);
  opacity: 0.9;
}}
.nv-nav-meta em {{
  font-style: normal;
  color: var(--nv-primary);
  font-weight: 700;
}}

.nv-breadcrumb {{
  background: var(--nv-surface-soft);
  color: var(--nv-body);
  height: 48px;
  display: flex;
  align-items: center;
  padding: 0 24px;
  margin: 0 -1rem 32px -1rem;
  font-size: 14px;
  font-weight: 700;
  text-transform: uppercase;
  border-bottom: 1px solid var(--nv-hairline);
}}
.nv-breadcrumb .sep {{ color: var(--nv-mute); margin: 0 10px; font-weight: 400; }}
.nv-breadcrumb .current {{ color: var(--nv-ink); }}
.nv-breadcrumb .muted {{ color: var(--nv-mute); }}

.nv-hero {{
  background: var(--nv-surface-dark);
  color: var(--nv-on-dark);
  padding: 48px 32px;
  margin: 0 -1rem 32px -1rem;
  position: relative;
}}
.nv-hero::before {{
  content: "";
  position: absolute;
  top: 16px;
  left: 16px;
  width: 12px;
  height: 12px;
  background: var(--nv-primary);
}}
.nv-eyebrow {{
  font-size: 14px;
  font-weight: 700;
  text-transform: uppercase;
  color: var(--nv-primary);
  margin: 0 0 12px 0;
}}
.nv-hero h1 {{
  font-size: 36px;
  font-weight: 700;
  line-height: 1.25;
  margin: 0 0 12px 0;
  color: var(--nv-on-dark) !important;
}}
.nv-hero p {{
  font-size: 16px;
  font-weight: 400;
  line-height: 1.5;
  color: {C_ON_DARK_MUTE};
  margin: 0;
  max-width: 680px;
}}

.nv-card {{
  background: var(--nv-canvas);
  border: 1px solid var(--nv-hairline);
  border-radius: var(--nv-radius);
  padding: 24px;
  position: relative;
  margin-bottom: 16px;
}}
.nv-card::before {{
  content: "";
  position: absolute;
  top: 0;
  left: 0;
  width: 12px;
  height: 12px;
  background: var(--nv-primary);
}}
.nv-card-title {{
  font-size: 17px;
  font-weight: 700;
  line-height: 1.47;
  color: var(--nv-ink);
  margin: 4px 0 8px 0;
}}
.nv-card-desc {{
  font-size: 15px;
  font-weight: 400;
  line-height: 1.67;
  color: var(--nv-mute);
  margin: 0;
}}
.nv-badge {{
  display: inline-block;
  background: var(--nv-surface-soft);
  color: var(--nv-body);
  font-size: 14px;
  font-weight: 700;
  text-transform: uppercase;
  padding: 4px 10px;
  border-radius: var(--nv-radius);
  margin-bottom: 12px;
}}
.nv-live-dot {{
  display: inline-block;
  width: 8px;
  height: 8px;
  background: var(--nv-primary);
  margin-right: 8px;
  vertical-align: middle;
  animation: nv-pulse 1.2s ease-in-out infinite;
}}
@keyframes nv-pulse {{
  0%, 100% {{ opacity: 1; }}
  50% {{ opacity: 0.35; }}
}}

.nv-output {{
  background: var(--nv-surface-soft);
  border: 1px solid var(--nv-hairline);
  border-radius: var(--nv-radius);
  padding: 16px 18px;
  min-height: 280px;
  height: 280px;
  overflow-y: auto;
  flex: 1;
  font-size: 16px;
  font-weight: 400;
  line-height: 1.55;
  color: var(--nv-body);
  white-space: pre-wrap;
  word-break: break-word;
  box-sizing: border-box;
}}
.nv-output-empty {{ color: var(--nv-mute); }}
.nv-cursor {{
  display: inline-block;
  width: 8px;
  height: 1.1em;
  background: var(--nv-primary);
  margin-left: 2px;
  vertical-align: text-bottom;
  animation: nv-blink 1s step-end infinite;
}}
@keyframes nv-blink {{
  0%, 100% {{ opacity: 1; }}
  50% {{ opacity: 0; }}
}}

.nv-meta-row {{
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}}
.nv-chip {{
  background: var(--nv-surface-soft);
  border: 1px solid var(--nv-hairline);
  color: var(--nv-body);
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  padding: 4px 10px;
  border-radius: var(--nv-radius);
}}
.nv-chip strong {{ color: var(--nv-primary); font-weight: 700; }}

.nv-status {{
  border: 1px solid var(--nv-hairline);
  border-radius: var(--nv-radius);
  padding: 12px 16px;
  font-size: 14px;
  font-weight: 700;
  margin: 8px 0 12px 0;
}}
.nv-status-info {{
  background: var(--nv-surface-soft);
  color: var(--nv-body);
  border-left: 3px solid var(--nv-primary);
}}
.nv-status-ok {{
  background: #f3f9eb;
  color: var(--nv-success);
  border-left: 3px solid var(--nv-primary);
}}
.nv-status-err {{
  background: #fdecec;
  color: var(--nv-error);
  border-left: 3px solid var(--nv-error);
}}
.nv-status-wait {{
  background: var(--nv-surface-soft);
  color: var(--nv-mute);
  border-left: 3px solid var(--nv-hairline);
}}

.nv-footer {{
  background: var(--nv-surface-dark);
  color: {C_ON_DARK_MUTE};
  margin: 48px -1rem 0 -1rem;
  padding: 32px 24px 24px 24px;
}}
.nv-footer-grid {{
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 24px;
  margin-bottom: 24px;
}}
.nv-footer h4 {{
  color: var(--nv-on-dark);
  font-size: 16px;
  font-weight: 700;
  margin: 0 0 12px 0;
}}
.nv-footer p, .nv-footer li {{
  font-size: 15px;
  line-height: 1.67;
  margin: 0 0 6px 0;
  color: {C_ON_DARK_MUTE};
}}
.nv-footer ul {{ list-style: none; padding: 0; margin: 0; }}
.nv-footer-legal {{
  border-top: 1px solid #5e5e5e;
  padding-top: 16px;
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  color: var(--nv-mute);
}}

div[data-testid="stSidebar"] {{
  background: var(--nv-surface-soft);
  border-right: 1px solid var(--nv-hairline);
}}

div.stButton > button[kind="primary"],
button[kind="primary"] {{
  background-color: var(--nv-primary) !important;
  color: #000000 !important;
  border: none !important;
  border-radius: var(--nv-radius) !important;
  font-weight: 700 !important;
  font-size: 16px !important;
  height: 44px !important;
  box-shadow: none !important;
}}
div.stButton > button[kind="primary"]:active,
button[kind="primary"]:active {{
  background-color: var(--nv-primary-dark) !important;
}}
div.stButton > button:not([kind="primary"]) {{
  background: transparent !important;
  color: var(--nv-ink) !important;
  border: 2px solid var(--nv-primary) !important;
  border-radius: var(--nv-radius) !important;
  font-weight: 700 !important;
  height: 44px !important;
  box-shadow: none !important;
}}

.stTextInput input, .stTextArea textarea,
.stSelectbox div[data-baseweb="select"] > div {{
  border-radius: var(--nv-radius) !important;
  border: 1px solid var(--nv-hairline) !important;
  background: var(--nv-canvas) !important;
  color: var(--nv-ink) !important;
  font-size: 16px !important;
  box-shadow: none !important;
}}
.stTextInput input:focus, .stTextArea textarea:focus {{
  border: 2px solid var(--nv-primary) !important;
  box-shadow: none !important;
}}

label, .stSelectbox label, .stTextArea label, .stTextInput label, .stSlider label {{
  color: var(--nv-ink) !important;
  font-weight: 700 !important;
  font-size: 14px !important;
  text-transform: uppercase !important;
}}

div[data-testid="stSlider"] div[role="slider"] {{
  background-color: var(--nv-primary) !important;
}}

section.main > div {{
  padding-left: 1rem;
  padding-right: 1rem;
}}

@media (max-width: 768px) {{
  .nv-hero h1 {{ font-size: 28px; }}
  .nv-footer-grid {{ grid-template-columns: 1fr; }}
}}
</style>
"""


def parse_sse_lines(response: httpx.Response) -> Generator[tuple[str, dict], None, None]:
    event_name = "message"
    data_lines: list[str] = []

    for raw_line in response.iter_lines():
        line = raw_line.rstrip("\r")
        if line == "":
            if data_lines:
                payload = "\n".join(data_lines)
                try:
                    data = json.loads(payload)
                except json.JSONDecodeError:
                    data = {"raw": payload}
                yield event_name, data
            event_name = "message"
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:") :].lstrip())

    if data_lines:
        payload = "\n".join(data_lines)
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            data = {"raw": payload}
        yield event_name, data


def request_cancel(api_base: str) -> None:
    try:
        with httpx.Client(timeout=2.0) as client:
            client.post(f"{api_base.rstrip('/')}/cancel")
    except httpx.HTTPError:
        pass


def stream_translation(
    api_base: str,
    text: str,
    direction: str,
    max_new_tokens: int = 1000,
) -> Generator[str, None, dict]:
    """Yield token pieces; return final metadata dict."""
    url = f"{api_base.rstrip('/')}/translate"
    meta: dict = {
        "direction": None,
        "full_text": "",
        "error": None,
        "model": None,
        "cancelled": False,
    }

    try:
        with httpx.Client(timeout=None) as client:
            with client.stream(
                "POST",
                url,
                json={
                    "text": text,
                    "direction": direction,
                    "max_new_tokens": max_new_tokens,
                },
                headers={"Accept": "text/event-stream"},
            ) as response:
                if response.status_code == 429:
                    # Brief retry once — previous job may still be releasing.
                    response.read()
                    time.sleep(0.25)
                    request_cancel(api_base)
                    time.sleep(0.25)
                    with client.stream(
                        "POST",
                        url,
                        json={
                            "text": text,
                            "direction": direction,
                            "max_new_tokens": max_new_tokens,
                        },
                        headers={"Accept": "text/event-stream"},
                    ) as response2:
                        yield from _consume_response(response2, meta)
                    return meta

                if response.status_code != 200:
                    body = response.read().decode("utf-8", errors="replace")
                    try:
                        detail = json.loads(body).get("detail", body)
                    except json.JSONDecodeError:
                        detail = body or f"HTTP {response.status_code}"
                    meta["error"] = f"HTTP {response.status_code}: {detail}"
                    return meta

                yield from _consume_response(response, meta)
    except httpx.ConnectError:
        meta["error"] = (
            f"Could not connect to API at {api_base}. "
            "Start the FastAPI server first (see README)."
        )
        return meta
    except httpx.HTTPError as exc:
        meta["error"] = f"HTTP error: {exc}"
        return meta

    return meta


def _consume_response(response: httpx.Response, meta: dict) -> Generator[str, None, None]:
    for event, data in parse_sse_lines(response):
        if event == "meta":
            meta["direction"] = data.get("direction")
            meta["model"] = data.get("model")
        elif event == "token":
            piece = data.get("t", "")
            if piece:
                meta["full_text"] += piece
                yield piece
        elif event == "done":
            meta["full_text"] = data.get("text", meta["full_text"])
            meta["direction"] = data.get("direction", meta["direction"])
        elif event == "error":
            msg = data.get("message", "Unknown streaming error")
            if data.get("code") == "cancelled" or msg == "cancelled":
                meta["cancelled"] = True
                meta["error"] = None
            else:
                meta["error"] = msg
            return


def check_health(api_base: str) -> Optional[dict]:
    try:
        with httpx.Client(timeout=5.0) as client:
            r = client.get(f"{api_base.rstrip('/')}/health")
            if r.status_code == 200:
                return r.json()
    except httpx.HTTPError:
        return None
    return None


def inject_styles() -> None:
    st.markdown(NVIDIA_CSS, unsafe_allow_html=True)


def render_chrome(health: Optional[dict]) -> None:
    device = (health or {}).get("device", "—")
    ready = (health or {}).get("ready")
    ready_label = "READY" if ready else "OFFLINE"
    model = (health or {}).get("model_id", "VietAI/envit5-translation")

    st.markdown(
        f"""
<div class="nv-utility">
  <span>AI TRANSLATION DEMO · LIVE AS YOU TYPE</span>
  <span>MODEL STATUS: <strong>{html.escape(ready_label)}</strong> · DEVICE: <strong>{html.escape(str(device).upper())}</strong></span>
</div>
<div class="nv-nav">
  <div class="nv-brand">
    <span class="nv-brand-mark"></span>
    <span>ENVIT5 STREAM</span>
  </div>
  <div class="nv-nav-meta">VI ↔ EN · <em>LIVE TOKEN STREAM</em></div>
</div>
<div class="nv-breadcrumb">
  <span class="muted">DEMO</span>
  <span class="sep">/</span>
  <span class="muted">TRANSLATION</span>
  <span class="sep">/</span>
  <span class="current">LIVE STREAM</span>
</div>
<div class="nv-hero">
  <div class="nv-eyebrow">VietAI / envit5-translation</div>
  <h1>Type above.<br/>Watch tokens stream below.</h1>
  <p>
    Translation starts automatically a moment after you stop typing.
    Tokens appear as the model decodes — true incremental SSE, not a fake reveal.
    Model: {html.escape(model)}.
  </p>
</div>
""",
        unsafe_allow_html=True,
    )


def render_footer() -> None:
    st.markdown(
        """
<div class="nv-footer">
  <div class="nv-footer-grid">
    <div>
      <h4>Live mode</h4>
      <ul>
        <li>Debounced as-you-type</li>
        <li>SSE token streaming</li>
        <li>Cancel + supersede</li>
      </ul>
    </div>
    <div>
      <h4>Model</h4>
      <ul>
        <li>VietAI/envit5-translation</li>
        <li>Prefixes: vi: / en:</li>
        <li>CUDA when available</li>
      </ul>
    </div>
    <div>
      <h4>API</h4>
      <ul>
        <li>GET /health</li>
        <li>POST /translate (SSE)</li>
        <li>POST /cancel</li>
      </ul>
    </div>
  </div>
  <div class="nv-footer-legal">
    DESIGN SYSTEM INSPIRED BY NVIDIA MARKETING TOKENS · DEMO ONLY · NOT AFFILIATED
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


def status_html(kind: str, message: str) -> str:
    cls = {
        "info": "nv-status nv-status-info",
        "ok": "nv-status nv-status-ok",
        "err": "nv-status nv-status-err",
        "wait": "nv-status nv-status-wait",
    }.get(kind, "nv-status nv-status-info")
    return f'<div class="{cls}">{html.escape(message)}</div>'


def output_html(
    text: str,
    direction: Optional[str] = None,
    empty: bool = False,
    streaming: bool = False,
) -> str:
    if empty:
        body = f'<span class="nv-output-empty">{html.escape(text)}</span>'
    else:
        body = html.escape(text)
        if streaming:
            body += '<span class="nv-cursor"></span>'
    chips = ""
    if direction or streaming:
        parts = []
        if streaming:
            parts.append(
                '<span class="nv-chip"><span class="nv-live-dot"></span>LIVE</span>'
            )
        if direction:
            parts.append(
                f'<span class="nv-chip">DIRECTION <strong>{html.escape(direction)}</strong></span>'
            )
        parts.append('<span class="nv-chip">STREAM <strong>SSE</strong></span>')
        chips = f'<div class="nv-meta-row">{"".join(parts)}</div>'
    return f'<div class="nv-output">{body}</div>{chips}'


def init_state() -> None:
    defaults = {
        "last_translated_key": None,
        "output_text": "",
        "output_direction": None,
        "output_error": None,
        "output_streaming": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def run_live_stream(
    api_base: str,
    text: str,
    direction: str,
    max_new_tokens: int,
    status_slot,
    output_slot,
) -> None:
    """Stream tokens into output_slot; update session_state when done."""
    request_cancel(api_base)  # supersede any prior job
    st.session_state.output_streaming = True
    st.session_state.output_error = None
    pieces: list[str] = []
    final_meta: dict = {}

    status_slot.markdown(
        status_html("info", "Streaming tokens…"),
        unsafe_allow_html=True,
    )
    output_slot.markdown(
        output_html("", streaming=True),
        unsafe_allow_html=True,
    )

    try:
        gen = stream_translation(
            api_base=api_base,
            text=text,
            direction=direction,
            max_new_tokens=max_new_tokens,
        )
        try:
            while True:
                piece = next(gen)
                pieces.append(piece)
                output_slot.markdown(
                    output_html("".join(pieces), streaming=True),
                    unsafe_allow_html=True,
                )
        except StopIteration as stop:
            final_meta = stop.value or {}
    except Exception as exc:  # noqa: BLE001
        st.session_state.output_streaming = False
        st.session_state.output_error = f"Stream failed: {exc}"
        status_slot.markdown(
            status_html("err", st.session_state.output_error),
            unsafe_allow_html=True,
        )
        return

    st.session_state.output_streaming = False

    if final_meta.get("cancelled"):
        # Superseded mid-stream; keep whatever we have until the next run finishes.
        if pieces:
            st.session_state.output_text = "".join(pieces)
        status_slot.markdown(
            status_html("wait", "Updated input — restarting stream…"),
            unsafe_allow_html=True,
        )
        return

    if final_meta.get("error"):
        st.session_state.output_error = str(final_meta["error"])
        if pieces:
            st.session_state.output_text = "".join(pieces)
            st.session_state.output_direction = final_meta.get("direction")
            output_slot.markdown(
                output_html(
                    st.session_state.output_text,
                    direction=st.session_state.output_direction,
                ),
                unsafe_allow_html=True,
            )
        status_slot.markdown(
            status_html("err", st.session_state.output_error),
            unsafe_allow_html=True,
        )
        return

    resolved = final_meta.get("direction") or direction
    full = final_meta.get("full_text") or "".join(pieces)
    st.session_state.output_text = full
    st.session_state.output_direction = resolved
    st.session_state.output_error = None
    status_slot.markdown(
        status_html("ok", f"Live · direction {resolved}"),
        unsafe_allow_html=True,
    )
    output_slot.markdown(
        output_html(full if full else "(empty translation)", direction=resolved),
        unsafe_allow_html=True,
    )


def main() -> None:
    st.set_page_config(
        page_title="envit5 Live Translation · VI↔EN",
        page_icon="🟩",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    inject_styles()
    init_state()

    with st.sidebar:
        st.markdown("### Settings")
        st.caption("API · live debounce · decode")
        api_base = st.text_input("API base URL", value=DEFAULT_API_BASE)
        max_new_tokens = st.slider("Max new tokens", 32, 1000, 1000, 32)
        debounce_ms = st.slider(
            "Debounce (ms)",
            min_value=200,
            max_value=1500,
            value=DEBOUNCE_MS,
            step=50,
            help="Wait this long after you stop typing before translating.",
        )
        live_enabled = st.toggle("Live translate while typing", value=True)
        health_click = st.button("Check API health", use_container_width=True)
        health_box = st.empty()

        health = check_health(api_base)
        if health_click:
            if health is None:
                health_box.error("API unreachable")
            else:
                health_box.json(health)

        st.markdown("---")
        st.markdown(
            f"""
<div style="font-size:12px;color:{C_MUTE};line-height:1.5;">
<strong style="color:{C_INK};">Live streaming</strong><br/>
Type left → tokens stream right<br/>
after {debounce_ms}ms debounce.<br/><br/>
Accent <span style="color:{C_PRIMARY};font-weight:700;">#76b900</span>
</div>
""",
            unsafe_allow_html=True,
        )

    if health is None:
        health = check_health(api_base)

    render_chrome(health)

    # Layout (matches wireframe):
    #   [ Source ] [ Translation ]
    #   [        Direction         ]
    left, right = st.columns(2, gap="large")
    IO_BOX_HEIGHT = 280

    with left:
        st.markdown(
            """
<div class="nv-io-panel">
  <div class="nv-badge">Input · live</div>
  <div class="nv-card-title">Source</div>
  <div class="nv-card-desc">
    Type Vietnamese or English. Translation streams into the Translation panel on the right.
  </div>
</div>
""",
            unsafe_allow_html=True,
        )
        source = live_textarea(
            label="Source text",
            key="source_text",
            placeholder="Type here… e.g. Xin chào các bạn / Hello everyone",
            debounce=debounce_ms,
            height=IO_BOX_HEIGHT,
        )

    with right:
        st.markdown(
            """
<div class="nv-io-panel">
  <div class="nv-badge">Output · token stream</div>
  <div class="nv-card-title">Translation</div>
  <div class="nv-card-desc">
    Tokens append as the model decodes. Green cursor marks an active stream.
  </div>
</div>
""",
            unsafe_allow_html=True,
        )
        status = st.empty()
        stream_area = st.empty()

        if st.session_state.output_text:
            stream_area.markdown(
                output_html(
                    st.session_state.output_text,
                    direction=st.session_state.output_direction,
                ),
                unsafe_allow_html=True,
            )
        else:
            stream_area.markdown(
                output_html("Translation appears here as you type…", empty=True),
                unsafe_allow_html=True,
            )

    # Full-width direction bar under both boxes
    st.markdown(
        """
<div class="nv-direction-bar">
  <div class="nv-badge">Direction</div>
  <div class="nv-card-title" style="margin-bottom:0;">Translation direction</div>
</div>
""",
        unsafe_allow_html=True,
    )
    col_dir, col_force = st.columns([3, 1], gap="medium")
    with col_dir:
        direction_label = st.selectbox(
            "Direction",
            options=list(DIRECTION_LABELS.keys()),
            index=0,
            key="direction_label",
            label_visibility="collapsed",
        )
    with col_force:
        force = st.button("Translate now", type="primary", use_container_width=True)

    direction = DIRECTION_LABELS[direction_label]

    text = (source or "").strip()
    translate_key = f"{direction}||{text}||{max_new_tokens}"

    should_run = False
    if not text:
        st.session_state.last_translated_key = None
        st.session_state.output_text = ""
        st.session_state.output_direction = None
        status.empty()
        stream_area.markdown(
            output_html("Translation appears here as you type…", empty=True),
            unsafe_allow_html=True,
        )
    elif len(text) < MIN_CHARS and not force:
        status.empty()
    elif force:
        should_run = True
    elif live_enabled and translate_key != st.session_state.last_translated_key:
        # live_textarea already debounced keystrokes before this rerun fired.
        should_run = True

    if should_run and text:
        if (
            not force
            and translate_key == st.session_state.last_translated_key
            and not st.session_state.output_error
        ):
            status.markdown(
                status_html(
                    "ok",
                    f"Live · direction {st.session_state.output_direction or direction}",
                ),
                unsafe_allow_html=True,
            )
        else:
            run_live_stream(
                api_base=api_base,
                text=text,
                direction=direction,
                max_new_tokens=max_new_tokens,
                status_slot=status,
                output_slot=stream_area,
            )
            if not st.session_state.output_error:
                st.session_state.last_translated_key = translate_key

    render_footer()


if __name__ == "__main__":
    main()
