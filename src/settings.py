"""Central configuration settings loader for ClaimCheck 2.0.

Loads configuration from environment variables and falls back to Streamlit secrets.
Distinguishes real configured values from empty strings and catalog placeholders.
Never logs, prints, or exposes secret values.
"""

from __future__ import annotations

import os
from typing import Optional
from dotenv import load_dotenv

# Load environment variables from .env file if present
load_dotenv()

# Recognized setting keys
SETTING_KEYS = (
    "NEBIUS_API_KEY",
    "NEBIUS_BASE_URL",
    "NEBIUS_MODEL_REASONING",
    "NEBIUS_MODEL_FAST",
    "TAVILY_API_KEY",
    "TESSERACT_CMD",
    "TESSDATA_PREFIX",
)

DEFAULT_NEBIUS_BASE_URL = "https://api.tokenfactory.nebius.com/v1/"


def _get_raw_value(name: str) -> Optional[str]:
    """Retrieve raw setting value from environment or Streamlit secrets."""
    # 1. Environment variable
    val = os.getenv(name)
    if val is not None and val != "":
        return val

    # 2. Fall back to streamlit secrets if running within Streamlit
    try:
        import streamlit as st
        if hasattr(st, "secrets") and name in st.secrets:
            s_val = st.secrets[name]
            if s_val is not None and str(s_val) != "":
                return str(s_val)
    except Exception:
        pass

    return None


def is_set(name: str) -> bool:
    """Return True if setting is present, non-empty, and not a template placeholder.

    Returns False for:
    - None or empty string
    - Values starting with 'your_' (case-insensitive)
    - Values wrapped in angle brackets like '<model id ...>'
    - Common placeholder tokens like 'placeholder' or 'none'
    """
    raw = _get_raw_value(name)
    if raw is None:
        return False

    cleaned = raw.strip()
    if not cleaned:
        return False

    lower = cleaned.lower()
    if lower.startswith("your_"):
        return False
    if cleaned.startswith("<") and cleaned.endswith(">"):
        return False
    if lower in ("placeholder", "none", "null", "unset"):
        return False

    return True


def get_setting(name: str, default: Optional[str] = None) -> Optional[str]:
    """Return the setting value if valid and set, else return default."""
    if is_set(name):
        return _get_raw_value(name)
    if name == "NEBIUS_BASE_URL" and default is None:
        return DEFAULT_NEBIUS_BASE_URL
    return default


def get_nebius_api_key() -> Optional[str]:
    return get_setting("NEBIUS_API_KEY")


def get_nebius_base_url() -> str:
    return get_setting("NEBIUS_BASE_URL", DEFAULT_NEBIUS_BASE_URL) or DEFAULT_NEBIUS_BASE_URL


def get_nebius_model_reasoning() -> Optional[str]:
    return get_setting("NEBIUS_MODEL_REASONING")


def get_nebius_model_fast() -> Optional[str]:
    return get_setting("NEBIUS_MODEL_FAST")


def get_tavily_api_key() -> Optional[str]:
    return get_setting("TAVILY_API_KEY")


def get_tesseract_cmd() -> Optional[str]:
    return get_setting("TESSERACT_CMD")


def get_tessdata_prefix() -> Optional[str]:
    return get_setting("TESSDATA_PREFIX")
