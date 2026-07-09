"""Multi-line debounced live textarea Streamlit component."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import streamlit.components.v1 as components

_component = components.declare_component(
    "live_textarea",
    path=str(Path(__file__).parent.absolute()),
)


def live_textarea(
    label: str = "Input",
    value: str = "",
    key: Optional[str] = None,
    debounce: int = 450,
    height: int = 280,
    placeholder: str = "",
    disabled: bool = False,
) -> str:
    """Return current text; updates parent app after debounce ms of typing."""
    result = _component(
        label=label,
        value=value,
        debounce=int(debounce),
        height=int(height),
        placeholder=placeholder,
        disabled=disabled,
        key=key,
        default=value,
    )
    if result is None:
        return value
    return str(result)
