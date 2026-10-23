"""Automated test suite verifying the 20-packet benchmark dataset and PDF extractor integration.

Verifies:
1. All 20 packet directories and all 5 files per packet exist.
2. Ground-truth and expected findings conform strictly to Pydantic schemas.
3. Digital PDFs are text-extractable with needs_ocr=False and quotes present.
4. Six rasterised bills (including Packet 11) have needs_ocr=True and no digital text layer.
5. Deterministic regeneration is byte-for-byte repeatable.
6. Rule engine evaluate() completely agrees with independent ground-truth expected findings.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import pytest

from benchmark.generate_packets import (
    BENCHMARK_SEED,
    generate_single_packet,
)
from benchmark.ground_truth import get_all_packet_specs
from src.documents.pdf_extractor import extract_text_from_pdf
from src.engine import evaluate
from src.schemas import (
    ClaimFact,
    Finding,
    Rulebook,
)

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
PACKETS_DIR = DATA_DIR / "packets"
RULEBOOK_PATH = DATA_DIR / "gold_rulebook.json"

EXPECTED_FILES = {
    "claim_form.pdf",
    "hospital_bill.pdf",
    "discharge_summary.pdf",
    "ground_truth_facts.json",
    "expected_findings.json",
}

RASTERISED_PACKET_IDS = {
    "packet_06",
    "packet_10",
    "packet_11",  # Proportional room rent explicitly required
    "packet_15",
    "packet_17",
    "packet_20",
}


@pytest.fixture(scope="module")
def gold_rulebook() -> Rulebook:
    """Load the gold standard rulebook."""
    with open(RULEBOOK_PATH, "r", encoding="utf-8") as f:
        return Rulebook.model_validate(json.load(f))


@pytest.fixture(scope="module")
def all_packet_dirs() -> list[Path]:
    """Retrieve all 20 sorted packet directories."""
    packet_dirs = sorted([p for p in PACKETS_DIR.iterdir() if p.is_dir()])
    return packet_dirs


# -----------------------------------------------------------------------------
# Test 1: Directory Structure and 5 Files Per Packet
# -----------------------------------------------------------------------------
def test_all_20_packet_directories_and_files_exist(all_packet_dirs: list[Path]):
    """Verify exactly 20 packet directories exist and each contains all 5 required files."""
    assert len(all_packet_dirs) == 20, f"Expected 20 packets, found {len(all_packet_dirs)}"

    for idx, pdir in enumerate(all_packet_dirs, start=1):
        expected_name = f"packet_{idx:02d}"
        assert pdir.name == expected_name, f"Expected folder '{expected_name}', got '{pdir.name}'"

        actual_files = {f.name for f in pdir.iterdir() if f.is_file()}
        missing_files = EXPECTED_FILES - actual_files
        assert not missing_files, f"Packet '{pdir.name}' is missing files: {missing_files}"

        for fname in EXPECTED_FILES:
            file_path = pdir / fname
            assert file_path.stat().st_size > 0, f"File '{fname}' in '{pdir.name}' is empty (0 bytes)"


# -----------------------------------------------------------------------------
# Test 2: Pydantic Schema Validation for Facts and Findings
# -----------------------------------------------------------------------------
def test_ground_truth_facts_and_findings_schemas(all_packet_dirs: list[Path]):
    """Validate JSON contents against ClaimFact and Finding schemas, and check source refs."""
    allowed_docs = {"claim_form.pdf", "hospital_bill.pdf", "discharge_summary.pdf"}

    for pdir in all_packet_dirs:
        # Validate facts
        facts_file = pdir / "ground_truth_facts.json"
        with open(facts_file, "r", encoding="utf-8") as f:
            facts_raw = json.load(f)
        assert isinstance(facts_raw, list) and len(facts_raw) > 0, f"No facts in {pdir.name}"
        facts = [ClaimFact.model_validate(item) for item in facts_raw]

        for fact in facts:
            assert fact.source.document in allowed_docs, (
                f"[{pdir.name}] Invalid document name '{fact.source.document}' in fact '{fact.name}'"
            )
            assert fact.source.page >= 1, f"[{pdir.name}] Invalid page {fact.source.page} in fact '{fact.name}'"
            assert len(fact.source.quote.strip()) > 0, f"[{pdir.name}] Empty quote in fact '{fact.name}'"

        # Validate findings
        findings_file = pdir / "expected_findings.json"
        with open(findings_file, "r", encoding="utf-8") as f:
            findings_raw = json.load(f)
        assert isinstance(findings_raw, list) and len(findings_raw) > 0, f"No findings in {pdir.name}"
        findings = [Finding.model_validate(item) for item in findings_raw]

        for finding in findings:
            assert len(finding.calculation_steps) > 0, f"[{pdir.name}] Empty calculation steps for {finding.rule_id}"
            assert finding.status in {"satisfied", "violated", "unable_to_verify", "needs_review"}


# -----------------------------------------------------------------------------
# Test 3: Digital PDFs are Text-Extractable via extract_text_from_pdf()
# -----------------------------------------------------------------------------
def test_digital_pdfs_are_text_extractable(all_packet_dirs: list[Path]):
    """Verify all digital PDFs have readable text with needs_ocr=False and contain quotes."""
    for pdir in all_packet_dirs:
        # Load facts to verify quotes for digital docs
        facts_file = pdir / "ground_truth_facts.json"
        with open(facts_file, "r", encoding="utf-8") as f:
            facts = [ClaimFact.model_validate(item) for item in json.load(f)]

        is_raster_packet = pdir.name in RASTERISED_PACKET_IDS

        for doc_name in ["claim_form.pdf", "hospital_bill.pdf", "discharge_summary.pdf"]:
            # Skip rasterised bills for digital text extraction check
            if is_raster_packet and doc_name == "hospital_bill.pdf":
                continue

            pdf_path = pdir / doc_name
            pdf_bytes = pdf_path.read_bytes()
            extraction = extract_text_from_pdf(pdf_bytes, document_id=f"{pdir.name}_{doc_name}")

            assert extraction.total_pages >= 1
            for page in extraction.pages:
                assert not page.needs_ocr, (
                    f"[{pdir.name}/{doc_name}] Page {page.page_number} flagged needs_ocr=True unexpectedly"
                )
                assert len(page.text.strip()) >= 50, (
                    f"[{pdir.name}/{doc_name}] Insufficient text on page {page.page_number}"
                )

            # If a fact points to this digital document, assert its quote is found in extracted text
            for fact in facts:
                if fact.source.document == doc_name:
                    page_idx = fact.source.page - 1
                    assert 0 <= page_idx < len(extraction.pages)
                    extracted_text = extraction.pages[page_idx].text
                    # Check quote substring
                    clean_quote = " ".join(fact.source.quote.split())
                    clean_text = " ".join(extracted_text.split())
                    assert clean_quote in clean_text, (
                        f"[{pdir.name}/{doc_name}] Quote not found on page {fact.source.page}:\n"
                        f"Expected quote: '{clean_quote}'\nIn extracted text: '{clean_text}'"
                    )


# -----------------------------------------------------------------------------
# Test 4: Six Rasterised Bills Require OCR and Contain No Digital Text
# -----------------------------------------------------------------------------
def test_six_rasterised_bills_require_ocr():
    """Verify exactly six packets have rasterised hospital bills with needs_ocr=True."""
    assert "packet_11" in RASTERISED_PACKET_IDS, "Packet 11 (proportional deduction) must be rasterised"
    assert len(RASTERISED_PACKET_IDS) == 6, f"Expected 6 rasterised packets, got {len(RASTERISED_PACKET_IDS)}"

    for pid in sorted(RASTERISED_PACKET_IDS):
        bill_path = PACKETS_DIR / pid / "hospital_bill.pdf"
        assert bill_path.exists(), f"Hospital bill missing in {pid}"

        pdf_bytes = bill_path.read_bytes()
        extraction = extract_text_from_pdf(pdf_bytes, document_id=f"{pid}_raster_bill")

        assert extraction.total_pages >= 1
        for page in extraction.pages:
            assert page.needs_ocr is True, (
                f"[{pid}/hospital_bill.pdf] Page {page.page_number} expected needs_ocr=True, got False"
            )
            # Digital text layer must be empty or contain fewer than 50 characters
            assert len(page.text.strip()) < 50, (
                f"[{pid}/hospital_bill.pdf] Page {page.page_number} unexpectedly contains text: '{page.text}'"
            )


# -----------------------------------------------------------------------------
# Test 5: Packet Generation Repeatability
# -----------------------------------------------------------------------------
def test_benchmark_generation_repeatability(gold_rulebook: Rulebook):
    """Verify re-generating packets with fixed seed produces byte-for-byte identical output."""
    specs = {s.packet_id: s for s in get_all_packet_specs()}

    # Test both a digital packet (packet_01) and a rasterised packet (packet_11)
    test_packets = ["packet_01", "packet_11"]

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        for pid in test_packets:
            spec = specs[pid]
            orig_dir = PACKETS_DIR / pid
            regen_dir = tmp_path / pid

            generate_single_packet(spec, gold_rulebook, regen_dir, base_seed=BENCHMARK_SEED)

            for fname in EXPECTED_FILES:
                orig_bytes = (orig_dir / fname).read_bytes()
                regen_bytes = (regen_dir / fname).read_bytes()
                assert orig_bytes == regen_bytes, (
                    f"[{pid}/{fname}] Binary mismatch between original and regenerated file! "
                    f"Original size={len(orig_bytes)}, regenerated size={len(regen_bytes)}"
                )


# -----------------------------------------------------------------------------
# Test 6: Rule Engine Evaluation Agreement with Expected Findings
# -----------------------------------------------------------------------------
def test_rule_engine_agrees_with_benchmark_expected_findings(
    gold_rulebook: Rulebook,
    all_packet_dirs: list[Path],
):
    """Verify rule engine evaluate() agrees with expected findings for all 20 packets."""
    specs = {s.packet_id: s for s in get_all_packet_specs()}

    for pdir in all_packet_dirs:
        pid = pdir.name
        spec = specs[pid]

        with open(pdir / "ground_truth_facts.json", "r", encoding="utf-8") as f:
            facts = [ClaimFact.model_validate(item) for item in json.load(f)]

        with open(pdir / "expected_findings.json", "r", encoding="utf-8") as f:
            expected_findings = [Finding.model_validate(item) for item in json.load(f)]

        engine_findings = evaluate(gold_rulebook, facts, spec.applicable_rule_ids)

        assert len(engine_findings) == len(expected_findings), (
            f"[{pid}] Count mismatch: engine returned {len(engine_findings)}, expected {len(expected_findings)}"
        )

        engine_by_id = {f.rule_id: f for f in engine_findings}
        for expected in expected_findings:
            actual = engine_by_id.get(expected.rule_id)
            assert actual is not None, f"[{pid}] Missing finding for rule '{expected.rule_id}'"

            assert actual.status == expected.status, (
                f"[{pid}] Status mismatch for '{expected.rule_id}': got '{actual.status}', expected '{expected.status}'"
            )
            assert actual.estimated_impact == expected.estimated_impact, (
                f"[{pid}] Impact mismatch for '{expected.rule_id}': got '{actual.estimated_impact}', expected '{expected.estimated_impact}'"
            )
            assert len(actual.calculation_steps) > 0, f"[{pid}] Empty calculation steps for '{expected.rule_id}'"
