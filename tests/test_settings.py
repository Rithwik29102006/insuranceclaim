"""Offline unit tests for ClaimCheck 2.0 Settings and Config Check.

Verifies:
1. Central settings loader properly classifies placeholder values as unset.
2. Environment variables take precedence over Streamlit secrets fallback.
3. Error messages and inspections never reveal secret keys.
4. Config check inspects NVIDIA Nemotron models correctly.
"""

from __future__ import annotations

import os
import pytest

from src import settings
from src.ai.config_check import inspect_configuration, ConfigStatus


def test_is_set_recognizes_placeholders(monkeypatch):
    """Placeholder patterns should be identified as not set."""
    monkeypatch.setenv("NEBIUS_API_KEY", "your_nebius_api_key_here")
    monkeypatch.setenv("TAVILY_API_KEY", "your_tavily_api_key_here")
    monkeypatch.setenv("NEBIUS_MODEL_REASONING", "<model id from your Token Factory catalog>")
    monkeypatch.setenv("NEBIUS_MODEL_FAST", "placeholder")

    assert settings.is_set("NEBIUS_API_KEY") is False
    assert settings.is_set("TAVILY_API_KEY") is False
    assert settings.is_set("NEBIUS_MODEL_REASONING") is False
    assert settings.is_set("NEBIUS_MODEL_FAST") is False


def test_is_set_recognizes_real_values(monkeypatch):
    """Genuine non-placeholder values should be identified as set."""
    monkeypatch.setenv("NEBIUS_API_KEY", "nb-token-real-dummy-12345")
    monkeypatch.setenv("NEBIUS_MODEL_FAST", "nvidia/nemotron-mini-4b-instruct")

    assert settings.is_set("NEBIUS_API_KEY") is True
    assert settings.is_set("NEBIUS_MODEL_FAST") is True


def test_env_overrides_secrets_fallback(monkeypatch):
    """os.environ takes precedence over any fallback."""
    monkeypatch.setenv("NEBIUS_MODEL_FAST", "fast-model-from-env")
    assert settings.get_nebius_model_fast() == "fast-model-from-env"


def test_config_check_flags_non_nemotron(monkeypatch):
    """Config check flags models that do not contain 'nemotron'."""
    monkeypatch.setenv("NEBIUS_API_KEY", "nb-token-test")
    monkeypatch.setenv("NEBIUS_MODEL_REASONING", "meta-llama/Llama-3-70b-instruct")
    monkeypatch.setenv("NEBIUS_MODEL_FAST", "mistralai/Mistral-7B-v0.1")

    status = inspect_configuration()
    assert isinstance(status, ConfigStatus)
    assert status.is_nemotron_reasoning is False
    assert status.is_nemotron_fast is False
    assert any("does not identify as NVIDIA Nemotron" in w for w in status.warnings)


def test_config_check_accepts_nemotron(monkeypatch):
    """Config check validates NVIDIA Nemotron model IDs."""
    monkeypatch.setenv("NEBIUS_API_KEY", "nb-token-test")
    monkeypatch.setenv("NEBIUS_MODEL_REASONING", "nvidia/nemotron-4-340b-reward")
    monkeypatch.setenv("NEBIUS_MODEL_FAST", "nvidia/nemotron-mini-4b-instruct")

    status = inspect_configuration()
    assert status.is_nemotron_reasoning is True
    assert status.is_nemotron_fast is True
    assert len(status.warnings) == 0


def test_config_check_never_exposes_api_key(monkeypatch):
    """ConfigStatus output must never leak the API key."""
    secret_value = "super-secret-key-12345678"
    monkeypatch.setenv("NEBIUS_API_KEY", secret_value)

    status = inspect_configuration()
    dumped = status.model_dump_json()

    assert secret_value not in dumped
    assert "super-secret" not in dumped
    assert status.variables.get("NEBIUS_API_KEY") is True
