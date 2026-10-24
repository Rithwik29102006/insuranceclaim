"""Configuration validation and model inspection for ClaimCheck 2.0.

Inspects environment configuration without performing any network calls.
Verifies NVIDIA Nemotron model selection and reports readiness.
Never returns, prints, or logs secret API keys.
"""

from __future__ import annotations

from typing import Dict, List, Optional
from urllib.parse import urlparse
from pydantic import BaseModel, Field

from src import settings


class ConfigStatus(BaseModel):
    """Structured report on environment and model configuration."""
    variables: Dict[str, bool] = Field(default_factory=dict)
    endpoint_host: str = ""
    model_reasoning: Optional[str] = None
    model_fast: Optional[str] = None
    is_nemotron_reasoning: bool = False
    is_nemotron_fast: bool = False
    is_live_ready: bool = False
    warnings: List[str] = Field(default_factory=list)
    missing_variables: List[str] = Field(default_factory=list)


def inspect_configuration() -> ConfigStatus:
    """Inspect current configuration and check for required NVIDIA Nemotron models.

    Returns:
        ConfigStatus report without exposing any secret values.
    """
    var_status = {k: settings.is_set(k) for k in settings.SETTING_KEYS}

    missing_live = []
    for req in ("NEBIUS_API_KEY", "NEBIUS_MODEL_REASONING", "NEBIUS_MODEL_FAST"):
        if not var_status.get(req, False):
            missing_live.append(req)

    # Parse endpoint host
    raw_base_url = settings.get_nebius_base_url()
    parsed = urlparse(raw_base_url)
    endpoint_host = parsed.netloc or parsed.path

    model_reasoning = settings.get_nebius_model_reasoning()
    model_fast = settings.get_nebius_model_fast()

    is_nemotron_reasoning = bool(model_reasoning and "nemotron" in model_reasoning.lower())
    is_nemotron_fast = bool(model_fast and "nemotron" in model_fast.lower())

    warnings = []
    if model_reasoning and not is_nemotron_reasoning:
        warnings.append(
            f"Configured reasoning model '{model_reasoning}' does not identify as NVIDIA Nemotron. "
            "The hackathon rules require an NVIDIA open model."
        )

    if model_fast and not is_nemotron_fast:
        warnings.append(
            f"Configured fast model '{model_fast}' does not identify as NVIDIA Nemotron. "
            "The hackathon rules require an NVIDIA open model."
        )

    is_ready = (len(missing_live) == 0 and is_nemotron_reasoning and is_nemotron_fast)

    return ConfigStatus(
        variables=var_status,
        endpoint_host=endpoint_host,
        model_reasoning=model_reasoning,
        model_fast=model_fast,
        is_nemotron_reasoning=is_nemotron_reasoning,
        is_nemotron_fast=is_nemotron_fast,
        is_live_ready=is_ready,
        warnings=warnings,
        missing_variables=missing_live,
    )
