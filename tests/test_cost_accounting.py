"""Automated tests for cost accounting and pricing table enforcement in ClaimCheck 2.0."""

from __future__ import annotations

from pathlib import Path
import pytest

from benchmark.evaluate import (
    DEFAULT_PRICING_PATH,
    calculate_token_cost,
    load_pricing_table,
)

ROOT_DIR = Path(__file__).resolve().parent.parent


def test_pricing_table_loads_and_contains_standard_models():
    """Verify that config/model_pricing.json loads and contains all required models."""
    pricing = load_pricing_table(DEFAULT_PRICING_PATH)
    assert isinstance(pricing, dict)
    assert len(pricing) >= 4

    expected_models = [
        "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
        "nvidia/nemotron-3-super-120b-a12b",
        "mock-nemotron-offline",
    ]
    for model_id in expected_models:
        assert model_id in pricing, f"Expected model '{model_id}' in pricing table"
        entry = pricing[model_id]
        assert "price_per_million_input_usd" in entry
        assert "price_per_million_output_usd" in entry
        assert entry["price_per_million_input_usd"] >= 0.0
        assert entry["price_per_million_output_usd"] >= 0.0


def test_calculate_token_cost_accurate():
    """Verify exact token cost computation according to catalog rates."""
    pricing_table = {
        "test-model": {
            "price_per_million_input_usd": 0.20,
            "price_per_million_output_usd": 0.60,
        }
    }
    # 500k prompt tokens @ $0.20/1M = $0.10
    # 250k completion tokens @ $0.60/1M = $0.15
    # Total = $0.25
    cost = calculate_token_cost("test-model", 500_000, 250_000, pricing_table)
    assert cost == 0.25


def test_missing_model_fails_loudly():
    """Verify that evaluate cost accounting fails loudly with KeyError when a model is not priced."""
    pricing_table = {
        "known-model": {
            "price_per_million_input_usd": 0.10,
            "price_per_million_output_usd": 0.30,
        }
    }
    with pytest.raises(KeyError) as exc_info:
        calculate_token_cost("unknown-nemotron-xyz", 1000, 1000, pricing_table)

    assert "Missing pricing configuration for model: 'unknown-nemotron-xyz'" in str(exc_info.value)
