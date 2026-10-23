"""Automated test suite for the ClaimCheck 2.0 benchmark evaluation harness.

Runs exclusively in mock mode (offline, no network or API keys required).
Verifies:
1. CLI execution with custom output and packet subsets.
2. Metadata capture (git commit hash, seed, prompt version, model IDs).
3. Comprehensive metric computation (fact accuracy, status accuracy, false-warning rate,
   detection rate, payout accuracy, citation accuracy, latency, tokens).
4. Image-only rasterised pages trigger "ocr_unavailable" and are scored as extraction failures.
5. Markdown table and JSON persistence in evaluation/.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import pytest

from benchmark.evaluate import (
    DEFAULT_SEED,
    PROMPT_VERSION,
    evaluate_packet,
    get_git_commit_hash,
    load_gold_rulebook,
    resolve_packet_ids,
    run_evaluation,
)
from src.documents.ocr import is_tesseract_available
from src.schemas import Rulebook

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
PACKETS_DIR = DATA_DIR / "packets"
EVALUATION_DIR = ROOT_DIR / "evaluation"


@pytest.fixture(scope="module")
def gold_rulebook() -> Rulebook:
    """Load the gold standard rulebook."""
    return load_gold_rulebook()


# -----------------------------------------------------------------------------
# Test 1: CLI execution in mock mode with subset of packets
# -----------------------------------------------------------------------------
def test_evaluate_cli_mock_mode_subset(tmp_path: Path):
    """Test invoking benchmark/evaluate.py from CLI in mock mode."""
    out_json = tmp_path / "custom_results.json"
    out_md = tmp_path / "custom_results.md"

    cmd = [
        sys.executable,
        str(ROOT_DIR / "benchmark" / "evaluate.py"),
        "--strategy", "mock",
        "--packets", "packet_01,packet_02",
        "--out", str(out_json),
        "--seed", str(DEFAULT_SEED),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, f"CLI exited with error: {result.stderr}"

    assert out_json.exists(), "JSON output file was not created"
    assert out_md.exists(), "Markdown output file was not created"

    data = json.loads(out_json.read_text(encoding="utf-8"))
    assert data["metadata"]["strategy"] == "mock"
    assert data["metadata"]["total_packets_evaluated"] == 2
    assert "metrics" in data
    assert "packet_results" in data
    assert len(data["packet_results"]) == 2

    md_text = out_md.read_text(encoding="utf-8")
    assert "# ClaimCheck 2.0 — Benchmark Evaluation Report" in md_text
    assert "packet_01" in md_text
    assert "packet_02" in md_text


# -----------------------------------------------------------------------------
# Test 2: Metadata completeness
# -----------------------------------------------------------------------------
def test_evaluate_metadata_completeness(tmp_path: Path):
    """Verify evaluation metadata includes git hash, seed, prompt version, and model IDs."""
    out_json = tmp_path / "metadata_test.json"
    json_path, md_path, report = run_evaluation(
        strategy="mock",
        packets_arg="packet_01",
        out_path=out_json,
        seed=12345,
    )

    meta = report.metadata
    assert meta["strategy"] == "mock"
    assert meta["seed"] == 12345
    assert meta["prompt_version"] == PROMPT_VERSION
    assert "git_commit_hash" in meta and len(meta["git_commit_hash"]) > 0
    assert "model_ids" in meta
    assert meta["model_ids"]["primary_model"] == "mock-nemotron-offline"
    assert "timestamp" in meta


# -----------------------------------------------------------------------------
# Test 3: Metric computation & seeded corruption verification
# -----------------------------------------------------------------------------
def test_evaluate_metrics_and_seeded_corruptions(tmp_path: Path):
    """Verify metrics properly calculate false warnings, payout mismatches, and citation failures."""
    out_json = tmp_path / "metrics_test.json"
    # Select clean packets + corrupted packets (03 citation, 05 false warning, 07 payout)
    json_path, md_path, report = run_evaluation(
        strategy="mock",
        packets_arg="packet_01,packet_02,packet_03,packet_04,packet_05,packet_07",
        out_path=out_json,
        seed=DEFAULT_SEED,
    )

    m = report.metrics

    # Fact accuracy
    assert 0.0 < m["overall_fact_extraction_accuracy"] <= 1.0
    assert "submitted_documents" in report.fact_breakdown

    # Status accuracy
    assert 0.0 < m["finding_status_accuracy"] <= 1.0

    # Seeded false-warning in packet_05 (room rent daily rate perturbed)
    assert m["false_warning_rate"] > 0.0, "Expected non-zero false-warning rate from packet_05"

    # Seeded payout calculation mismatch in packet_07
    assert m["payout_calculation_accuracy"] < 1.0, "Expected payout mismatch from packet_07"

    # Seeded citation mismatch in packet_03
    assert m["citation_accuracy"] < 1.0, "Expected citation verification mismatch from packet_03"

    # Latency and token usage
    assert m["average_latency_ms"] > 0.0
    assert m["token_usage"]["total_tokens"] > 0


# -----------------------------------------------------------------------------
# Test 4: OCR Unavailable is recorded and scored as extraction failure
# -----------------------------------------------------------------------------
def test_ocr_unavailable_scored_as_extraction_failure(gold_rulebook: Rulebook):
    """Verify image-only rasterised pages without Tesseract record 'ocr_unavailable' and fail extraction."""
    # packet_11 is guaranteed to have a rasterised hospital bill
    packet_dir = PACKETS_DIR / "packet_11"
    assert packet_dir.exists()

    res = evaluate_packet(
        packet_id="packet_11",
        packet_dir=packet_dir,
        rulebook=gold_rulebook,
        strategy="mock",
        seed=DEFAULT_SEED,
        mock_ocr=False,  # Strict mode: check live Tesseract
    )

    tesseract_available = is_tesseract_available("eng")
    if not tesseract_available:
        # Tesseract is not installed on this test host
        assert res.ocr_status == "ocr_unavailable"
        # Must record ocr_unavailable in failures, never skip silently
        assert any("ocr_unavailable" in f for f in res.failures), (
            f"Expected 'ocr_unavailable' failure message in packet_11 failures: {res.failures}"
        )
        # Facts that cite hospital_bill.pdf must not be extracted
        assert res.facts_extracted_count < res.facts_ground_truth_count
        assert res.fact_accuracy < 1.0
    else:
        # Tesseract is available
        assert res.ocr_status in ("ocr_applied", "ok")


# -----------------------------------------------------------------------------
# Test 5: Full 20-packet benchmark evaluation in mock mode
# -----------------------------------------------------------------------------
def test_evaluate_all_20_packets_offline(tmp_path: Path):
    """Run complete 20-packet benchmark in mock mode and assert valid report structure."""
    out_json = tmp_path / "all_packets_report.json"
    json_path, md_path, report = run_evaluation(
        strategy="mock",
        packets_arg="all",
        out_path=out_json,
        seed=DEFAULT_SEED,
    )

    assert report.metadata["total_packets_evaluated"] == 20
    assert len(report.packet_results) == 20

    # Confirm all 6 required rasterised packets are present
    rasterised_ids = {"packet_06", "packet_10", "packet_11", "packet_15", "packet_17", "packet_20"}
    packet_results_by_id = {p["packet_id"]: p for p in report.packet_results}

    for rid in rasterised_ids:
        assert rid in packet_results_by_id
        if not is_tesseract_available("eng"):
            assert packet_results_by_id[rid]["ocr_status"] == "ocr_unavailable"

    # Confirm report JSON contains valid keys
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert set(data.keys()) == {
        "metadata",
        "metrics",
        "fact_breakdown",
        "failures_by_packet",
        "packet_results",
    }

    # Confirm Markdown report exists and is populated
    md_text = md_path.read_text(encoding="utf-8")
    assert len(md_text) > 1000
    assert "Overall Fact Extraction Accuracy" in md_text
    assert "Finding Status Accuracy" in md_text
