"""Automated verification suite for synthetic policy, gold rulebook, and scenarios.

Ensures compliance with shared Pydantic schemas, verbatim quotation extraction,
1-based page indexing conventions, and deterministic claim scenario validation.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
import pytest

from src.documents.pdf_extractor import extract_text_from_pdf, DocumentExtraction
from src.schemas import (
    Rulebook,
    RuleType,
    FindingStatus,
    ClaimScenario,
)

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
POLICY_PDF_PATH = DATA_DIR / "synthetic_policy.pdf"
RULEBOOK_JSON_PATH = DATA_DIR / "gold_rulebook.json"
TEST_CASES_DIR = DATA_DIR / "test_cases"


def normalize_whitespace(text: str) -> str:
    """Normalize multiline and consecutive whitespace into single spaces for robust quote checking."""
    return re.sub(r"\s+", " ", text).strip()


@pytest.fixture(scope="module")
def extracted_policy() -> DocumentExtraction:
    """Parse the synthetic policy PDF using the existing PDF extraction utility."""
    assert POLICY_PDF_PATH.exists(), f"Synthetic policy PDF missing at {POLICY_PDF_PATH}"
    with open(POLICY_PDF_PATH, "rb") as f:
        pdf_bytes = f.read()
    return extract_text_from_pdf(pdf_bytes, document_id="test_synthetic_policy")


@pytest.fixture(scope="module")
def loaded_rulebook() -> Rulebook:
    """Load and validate the gold rulebook against Pydantic schema."""
    assert RULEBOOK_JSON_PATH.exists(), f"Gold rulebook JSON missing at {RULEBOOK_JSON_PATH}"
    with open(RULEBOOK_JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return Rulebook.model_validate(data)


@pytest.fixture(scope="module")
def loaded_scenarios() -> list[ClaimScenario]:
    """Load and validate all test scenario JSON files."""
    scenario_files = sorted(TEST_CASES_DIR.glob("scenario_*.json"))
    assert len(scenario_files) >= 8, f"Expected at least 8 scenarios, found {len(scenario_files)}"

    scenarios = []
    for sc_file in scenario_files:
        with open(sc_file, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        scenario = ClaimScenario.model_validate(data)
        scenarios.append(scenario)
    return scenarios


# -----------------------------------------------------------------------------
# Test 1: Synthetic PDF exists and can be parsed by existing extractor
# -----------------------------------------------------------------------------
def test_synthetic_pdf_exists_and_parseable(extracted_policy: DocumentExtraction):
    assert extracted_policy.total_pages in (3, 4), f"Expected 3-4 pages, got {extracted_policy.total_pages}"
    assert len(extracted_policy.pages) == extracted_policy.total_pages
    for page in extracted_policy.pages:
        assert len(page.text.strip()) > 50, f"Page {page.page_number} has unexpectedly low text"
        assert page.needs_ocr is False, f"Page {page.page_number} flagged for OCR unexpectedly"
        assert page.source_type == "pdf_text"


# -----------------------------------------------------------------------------
# Test 2: Gold rulebook JSON loads and validates against Pydantic schema
# -----------------------------------------------------------------------------
def test_gold_rulebook_schema_validation(loaded_rulebook: Rulebook):
    assert loaded_rulebook.policy_id == "POL-AURA-2026-001"
    assert len(loaded_rulebook.rules) == 5
    assert len(loaded_rulebook.ambiguities) == 1
    amb = loaded_rulebook.ambiguities[0]
    assert amb.ambiguity_id == "AMB_PRE_EXISTING_CONDITIONS"
    assert amb.section == "Section 4.1"
    assert amb.source.page == 4


# -----------------------------------------------------------------------------
# Test 3: All five required rule types are represented
# -----------------------------------------------------------------------------
def test_all_five_rule_types_represented(loaded_rulebook: Rulebook):
    rule_types = {r.rule_type for r in loaded_rulebook.rules}
    expected_types = {
        RuleType.REQUIRED_DOCUMENTS.value,
        RuleType.WAITING_PERIOD.value,
        RuleType.ROOM_RENT_CAP.value,
        RuleType.SUB_LIMIT.value,
        RuleType.NON_PAYABLE_ITEMS.value,
    }
    assert rule_types == expected_types, f"Rule types mismatch. Found: {rule_types}, Expected: {expected_types}"


# -----------------------------------------------------------------------------
# Test 4: Every rule ID is unique
# -----------------------------------------------------------------------------
def test_rule_ids_unique(loaded_rulebook: Rulebook):
    rule_ids = [r.rule_id for r in loaded_rulebook.rules]
    assert len(rule_ids) == len(set(rule_ids)), f"Duplicate rule IDs detected: {rule_ids}"


# -----------------------------------------------------------------------------
# Test 5 & 6: Quotations appear verbatim on referenced 1-based PDF pages
# -----------------------------------------------------------------------------
def test_quotations_appear_verbatim_on_referenced_pages(
    extracted_policy: DocumentExtraction, loaded_rulebook: Rulebook
):
    page_text_map = {p.page_number: p.text for p in extracted_policy.pages}

    # Verify 1-based page indexing
    assert min(page_text_map.keys()) == 1
    assert max(page_text_map.keys()) == extracted_policy.total_pages

    # Check executable rules
    for rule in loaded_rulebook.rules:
        target_page = rule.source.page
        assert target_page in page_text_map, (
            f"Rule {rule.rule_id} references page {target_page}, "
            f"which does not exist in extracted PDF (pages 1..{extracted_policy.total_pages})"
        )

        page_text = page_text_map[target_page]
        norm_page = normalize_whitespace(page_text)
        norm_quote = normalize_whitespace(rule.source.quote)

        assert norm_quote in norm_page, (
            f"Quotation for rule {rule.rule_id} does not appear verbatim on Page {target_page}.\n"
            f"Quote: {norm_quote}\n"
            f"Extracted Page Text: {norm_page}"
        )

    # Check policy ambiguities (e.g. Section 4.1 on Page 4)
    for amb in loaded_rulebook.ambiguities:
        target_page = amb.source.page
        assert target_page in page_text_map, (
            f"Ambiguity {amb.ambiguity_id} references page {target_page}, "
            f"which does not exist in extracted PDF"
        )
        page_text = page_text_map[target_page]
        norm_page = normalize_whitespace(page_text)
        norm_quote = normalize_whitespace(amb.source.quote)
        assert norm_quote in norm_page, (
            f"Quotation for ambiguity {amb.ambiguity_id} does not appear verbatim on Page {target_page}."
        )


# -----------------------------------------------------------------------------
# Test 7: Every test scenario loads and has the required structure
# -----------------------------------------------------------------------------
def test_claim_scenarios_load_and_validate(loaded_scenarios: list[ClaimScenario]):
    assert len(loaded_scenarios) >= 8
    scenario_ids = [s.scenario_id for s in loaded_scenarios]
    assert len(scenario_ids) == len(set(scenario_ids)), f"Duplicate scenario IDs: {scenario_ids}"

    for sc in loaded_scenarios:
        assert len(sc.description) > 10
        assert len(sc.claim_facts) >= 1
        assert len(sc.applicable_rule_ids) >= 1
        assert len(sc.expected_findings) >= 1


# -----------------------------------------------------------------------------
# Test 8: Every scenario references valid rule IDs
# -----------------------------------------------------------------------------
def test_scenarios_reference_valid_rule_ids(
    loaded_scenarios: list[ClaimScenario], loaded_rulebook: Rulebook
):
    valid_rule_ids = {r.rule_id for r in loaded_rulebook.rules} | {
        a.ambiguity_id for a in loaded_rulebook.ambiguities
    }

    for sc in loaded_scenarios:
        for rid in sc.applicable_rule_ids:
            assert rid in valid_rule_ids, f"Scenario {sc.scenario_id} references invalid rule_id '{rid}'"

        for finding in sc.expected_findings:
            assert finding.rule_id in valid_rule_ids, (
                f"Scenario {sc.scenario_id} finding references invalid rule_id '{finding.rule_id}'"
            )


# -----------------------------------------------------------------------------
# Test 9: All required scenario categories are covered
# -----------------------------------------------------------------------------
def test_all_required_scenario_categories_covered(loaded_scenarios: list[ClaimScenario]):
    """Verify scenarios cover all 8 mandatory requirement scenarios."""
    findings_by_rule_and_status = {
        (f.rule_id, f.status)
        for sc in loaded_scenarios
        for f in sc.expected_findings
    }

    # 1. All required documents present
    assert ("RULE_REQ_DOCS", FindingStatus.SATISFIED.value) in findings_by_rule_and_status
    # 2. A required document missing
    assert ("RULE_REQ_DOCS", FindingStatus.VIOLATED.value) in findings_by_rule_and_status
    # 3. Initial waiting period clearly satisfied
    assert ("RULE_WAITING_PERIOD", FindingStatus.SATISFIED.value) in findings_by_rule_and_status
    # 4. Initial waiting period not yet satisfied
    assert ("RULE_WAITING_PERIOD", FindingStatus.VIOLATED.value) in findings_by_rule_and_status
    # 5. Room rent within the stated limit
    assert ("RULE_ROOM_RENT_CAP", FindingStatus.SATISFIED.value) in findings_by_rule_and_status
    # 6. Room rent above the stated limit
    assert ("RULE_ROOM_RENT_CAP", FindingStatus.VIOLATED.value) in findings_by_rule_and_status
    # 7. A sub-limit exceeded
    assert ("RULE_CATARACT_SUBLIMIT", FindingStatus.VIOLATED.value) in findings_by_rule_and_status
    # 8. A non-payable item present
    assert ("RULE_NON_PAYABLE_ITEMS", FindingStatus.VIOLATED.value) in findings_by_rule_and_status


# -----------------------------------------------------------------------------
# Test 10: Every expected finding uses a permitted status
# -----------------------------------------------------------------------------
def test_expected_findings_use_permitted_statuses(loaded_scenarios: list[ClaimScenario]):
    permitted_statuses = {s.value for s in FindingStatus}
    for sc in loaded_scenarios:
        for finding in sc.expected_findings:
            assert finding.status in permitted_statuses, (
                f"Scenario {sc.scenario_id} finding has unpermitted status '{finding.status}'"
            )


# -----------------------------------------------------------------------------
# Test 11: Financial impacts are not asserted without sufficient facts and policy support
# -----------------------------------------------------------------------------
def test_financial_impacts_justified_and_grounded(loaded_scenarios: list[ClaimScenario]):
    for sc in loaded_scenarios:
        # If missing information is required, financial impact must not be asserted
        if sc.missing_information_required:
            assert sc.expected_financial_impact is None, (
                f"Scenario {sc.scenario_id} asserts financial impact {sc.expected_financial_impact} "
                "despite missing_information_required being True."
            )

        # For satisfied rules, financial impact must be 0.0
        all_satisfied = all(f.status == FindingStatus.SATISFIED.value for f in sc.expected_findings)
        if all_satisfied and sc.expected_financial_impact is not None:
            assert sc.expected_financial_impact == 0.0, (
                f"Scenario {sc.scenario_id} has all satisfied findings but non-zero impact."
            )

        # When financial impact is asserted, it must be non-negative
        if sc.expected_financial_impact is not None:
            assert sc.expected_financial_impact >= 0.0


# -----------------------------------------------------------------------------
# Test 12: Room-rent rule parameters include cap, formula basis, affected categories
# -----------------------------------------------------------------------------
def test_room_rent_rule_parameters(loaded_rulebook: Rulebook):
    room_rules = [r for r in loaded_rulebook.rules if r.rule_type == RuleType.ROOM_RENT_CAP.value]
    assert len(room_rules) == 1
    rule = room_rules[0]
    assert rule.parameters.get("cap") == 5000.0
    assert rule.parameters.get("formula_basis") == "5000 / actual_daily_rate"
    affected = rule.parameters.get("affected_categories", [])
    assert "professional_fees" in affected
    assert "operation_theatre_charges" in affected


# -----------------------------------------------------------------------------
# Test 13: Scenario 11 verifies proportional room-rent deduction step by step
# -----------------------------------------------------------------------------
def test_scenario_11_proportional_deduction(loaded_scenarios: list[ClaimScenario]):
    sc11 = next((s for s in loaded_scenarios if s.scenario_id == "SCENARIO_11_ROOM_RENT_PROPORTIONAL_DEDUCTION"), None)
    assert sc11 is not None, "Scenario 11 not found in test cases"
    assert sc11.expected_financial_impact == 27500.0
    finding = sc11.expected_findings[0]
    assert finding.status == FindingStatus.VIOLATED.value
    assert finding.estimated_impact == 27500.0
    assert len(finding.calculation_steps) >= 4
    # Check that ratio and calculation steps are explicitly detailed
    steps_joined = " ".join(finding.calculation_steps)
    assert "5000 / 10000 = 0.50" in steps_joined
    assert "27500.00" in steps_joined


# -----------------------------------------------------------------------------
# Test 14: Scenario 12 verifies Section 4.1 ambiguity requires review
# -----------------------------------------------------------------------------
def test_scenario_12_ambiguity_needs_review(loaded_scenarios: list[ClaimScenario]):
    sc12 = next((s for s in loaded_scenarios if s.scenario_id == "SCENARIO_12_PRE_EXISTING_CONDITION_AMBIGUITY"), None)
    assert sc12 is not None, "Scenario 12 not found in test cases"
    assert sc12.human_review_required is True
    assert sc12.missing_information_required is True
    assert sc12.expected_financial_impact is None
    finding = sc12.expected_findings[0]
    assert finding.status == FindingStatus.NEEDS_REVIEW.value
    assert finding.rule_id == "AMB_PRE_EXISTING_CONDITIONS"
