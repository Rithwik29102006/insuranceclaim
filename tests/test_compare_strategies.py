"""Offline tests for the strategy comparison benchmark runner."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import pytest

from benchmark.compare_strategies import (
    compute_percentiles,
    format_strategy_comparison_markdown,
    run_comparison,
)

ROOT_DIR = Path(__file__).resolve().parent.parent


def test_compute_percentiles():
    """Verify exact percentile calculations."""
    data = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
    pcts = compute_percentiles(data, [50.0, 95.0])
    assert pcts[50.0] == 55.0
    assert pcts[95.0] == 95.5

    # Single value
    single_pct = compute_percentiles([42.0], [50.0, 95.0])
    assert single_pct[50.0] == 42.0
    assert single_pct[95.0] == 42.0

    # Empty
    empty_pct = compute_percentiles([], [50.0, 95.0])
    assert empty_pct[50.0] == 0.0


def test_run_comparison_offline(tmp_path: Path):
    """Verify run_comparison executes in mock mode and generates unified Markdown table."""
    out_md = tmp_path / "comparison.md"
    md_path, md_table = run_comparison(
        packets_arg="packet_01,packet_02",
        force_mock=True,
        out_path=out_md,
    )

    assert md_path.exists()
    assert "Strategy Performance & Cost Summary Table" in md_table
    assert "**ultra**" in md_table
    assert "**routed**" in md_table
    assert "p50 Latency" in md_table
    assert "Avg Cost/Packet" in md_table


def test_compare_strategies_cli(tmp_path: Path):
    """Test invoking compare_strategies.py via CLI in mock mode."""
    out_md = tmp_path / "cli_comparison.md"
    cmd = [
        sys.executable,
        str(ROOT_DIR / "benchmark" / "compare_strategies.py"),
        "--mock",
        "--packets", "packet_01,packet_02",
        "--out", str(out_md),
    ]

    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"CLI error: {res.stderr}"
    assert out_md.exists()
    content = out_md.read_text(encoding="utf-8")
    assert "**ultra**" in content
    assert "**routed**" in content
