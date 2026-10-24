"""Automated test suite for the deterministic rule engine.

Tests evaluate() against all scenarios in data/test_cases/, verifying statuses,
exact financial impacts, and boundary conditions (rent at cap, day 30 vs 31, missing duration).
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from src.schemas import (
    Rulebook,
    ClaimFact,
    ClaimScenario,
    FindingStatus,
    SourceRef,
)
from src.engine import evaluate

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
RULEBOOK_PATH = DATA_DIR / "gold_rulebook.json"
SCENARIOS_DIR = DATA_DIR / "test_cases"


@pytest.fixture(scope="module")
def gold_rulebook() -> Rulebook:
    """Load the gold standard rulebook."""
    with open(RULEBOOK_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return Rulebook.model_validate(data)


@pytest.fixture(scope="module")
def all_scenarios() -> list[ClaimScenario]:
    """Load all JSON scenarios from test_cases directory."""
    files = sorted(SCENARIOS_DIR.glob("scenario_*.json"))
    scenarios = []
    for f in files:
        with open(f, "r", encoding="utf-8") as fp:
            scenarios.append(ClaimScenario.model_validate(json.load(fp)))
    return scenarios


# -----------------------------------------------------------------------------
# Test 1: Evaluate against all test scenarios in data/test_cases/
# -----------------------------------------------------------------------------
def test_all_scenarios_evaluation_matches_expected(gold_rulebook: Rulebook, all_scenarios: list[ClaimScenario]):
    """Verify that every scenario's findings and impacts match expected ground truth."""
    assert len(all_scenarios) >= 12, f"Expected at least 12 scenarios, found {len(all_scenarios)}"

    for sc in all_scenarios:
        findings = evaluate(gold_rulebook, sc.claim_facts, sc.applicable_rule_ids)
        findings_by_id = {f.rule_id: f for f in findings}

        for expected in sc.expected_findings:
            actual = findings_by_id.get(expected.rule_id)
            assert actual is not None, (
                f"[{sc.scenario_id}] Missing finding for expected rule/ambiguity ID '{expected.rule_id}'"
            )
            assert actual.status == expected.status, (
                f"[{sc.scenario_id}] Status mismatch for '{expected.rule_id}': "
                f"got '{actual.status}', expected '{expected.status}'"
            )
            assert actual.estimated_impact == expected.estimated_impact, (
                f"[{sc.scenario_id}] Impact mismatch for '{expected.rule_id}': "
                f"got '{actual.estimated_impact}', expected '{expected.estimated_impact}'"
            )
            assert len(actual.calculation_steps) > 0, (
                f"[{sc.scenario_id}] Missing calculation steps for '{expected.rule_id}'"
            )


# -----------------------------------------------------------------------------
# Test 2: Boundary Test - Room rent exactly at cap (INR 5000 per day)
# -----------------------------------------------------------------------------
def test_boundary_room_rent_exactly_at_cap(gold_rulebook: Rulebook):
    """Test when actual daily room rent is exactly equal to the policy cap (INR 5000)."""
    facts = [
        ClaimFact(
            name="room_rent_billing",
            value={"daily_rate": 5000.0, "days": 5, "total_amount": 25000.0},
            source=SourceRef(document="bill.pdf", page=1, quote="Room rent: 5 days @ 5000"),
        )
    ]
    findings = evaluate(gold_rulebook, facts, ["RULE_ROOM_RENT_CAP"])
    assert len(findings) == 1
    f = findings[0]
    assert f.status == FindingStatus.SATISFIED.value
    assert f.estimated_impact == 0.0
    assert "within the permissible limit" in " ".join(f.calculation_steps)


# -----------------------------------------------------------------------------
# Test 3: Boundary Test - Waiting period Day 30 vs Day 31
# -----------------------------------------------------------------------------
def test_boundary_waiting_period_day_30_vs_31(gold_rulebook: Rulebook):
    """Day 30 is within the initial 30-day waiting period (violated).

    Day 31 is on or after the 31st day following inception (satisfied).
    """
    # Day 30 (illness) -> Violated
    facts_day_30 = [
        ClaimFact(
            name="hospitalization_details",
            value={
                "policy_inception_date": "2026-01-01",
                "admission_date": "2026-01-31",
                "days_elapsed": 30,
                "cause": "illness",
                "diagnosis": "bronchitis",
            },
            source=SourceRef(document="discharge.pdf", page=1, quote="Day 30 admission"),
        )
    ]
    findings_day_30 = evaluate(gold_rulebook, facts_day_30, ["RULE_WAITING_PERIOD"])
    assert len(findings_day_30) == 1
    assert findings_day_30[0].status == FindingStatus.VIOLATED.value
    assert findings_day_30[0].estimated_impact is None

    # Day 31 (illness) -> Satisfied
    facts_day_31 = [
        ClaimFact(
            name="hospitalization_details",
            value={
                "policy_inception_date": "2026-01-01",
                "admission_date": "2026-02-01",
                "days_elapsed": 31,
                "cause": "illness",
                "diagnosis": "bronchitis",
            },
            source=SourceRef(document="discharge.pdf", page=1, quote="Day 31 admission"),
        )
    ]
    findings_day_31 = evaluate(gold_rulebook, facts_day_31, ["RULE_WAITING_PERIOD"])
    assert len(findings_day_31) == 1
    assert findings_day_31[0].status == FindingStatus.SATISFIED.value
    assert findings_day_31[0].estimated_impact == 0.0


# -----------------------------------------------------------------------------
# Test 4: Boundary Test - Missing duration for room rent
# -----------------------------------------------------------------------------
def test_boundary_room_rent_missing_duration(gold_rulebook: Rulebook):
    """Missing stay duration when rent exceeds cap requires human review without estimated impact.

    When rent is within cap, missing duration is still satisfied (impact is 0).
    """
    # Rent exceeds cap (7500 > 5000), duration is None -> needs_review, impact is None
    facts_exceeds = [
        ClaimFact(
            name="room_rent_billing",
            value={"daily_rate": 7500.0, "days": None},
            source=SourceRef(document="interim.pdf", page=1, quote="Daily rate 7500, days unknown"),
        )
    ]
    findings_exceeds = evaluate(gold_rulebook, facts_exceeds, ["RULE_ROOM_RENT_CAP"])
    assert len(findings_exceeds) == 1
    assert findings_exceeds[0].status == FindingStatus.NEEDS_REVIEW.value
    assert findings_exceeds[0].estimated_impact is None

    # Rent within cap (4500 <= 5000), duration is None -> satisfied, impact is 0.0
    facts_within = [
        ClaimFact(
            name="room_rent_billing",
            value={"daily_rate": 4500.0, "days": None},
            source=SourceRef(document="interim.pdf", page=1, quote="Daily rate 4500, days unknown"),
        )
    ]
    findings_within = evaluate(gold_rulebook, facts_within, ["RULE_ROOM_RENT_CAP"])
    assert len(findings_within) == 1
    assert findings_within[0].status == FindingStatus.SATISFIED.value
    assert findings_within[0].estimated_impact == 0.0


# -----------------------------------------------------------------------------
# Test 5: Missing or unparseable inputs return unable_to_verify (never violated)
# -----------------------------------------------------------------------------
def test_missing_facts_return_unable_to_verify(gold_rulebook: Rulebook):
    """When no facts are provided, every rule must return unable_to_verify, never violated."""
    findings = evaluate(gold_rulebook, [])
    for f in findings:
        assert f.status == FindingStatus.UNABLE_TO_VERIFY.value
        assert f.estimated_impact is None
        assert "Missing or unparseable" in " ".join(f.calculation_steps) or "not contain" in f.explanation


# -----------------------------------------------------------------------------
# Test 6: Normalization without fuzzy guessing for non-payable items
# -----------------------------------------------------------------------------
def test_bill_item_normalization_without_fuzzy_guessing(gold_rulebook: Rulebook):
    """Items are normalized for case and punctuation, but unmatched items are not guessed."""
    facts = [
        ClaimFact(
            name="non_payable_items_breakdown",
            value=[
                # Mixed case, punctuation, hyphens: should match "gloves" and "face_masks"
                {"item": "GLOVES!", "amount": 350.0},
                {"item": "Face-Masks.", "amount": 150.0},
                # Unmatched item: should NOT be fuzzy-guessed as gloves or sanitizers
                {"item": "Sterile Surgical Gown Extra Large", "amount": 2500.0},
            ],
            source=SourceRef(document="bill.pdf", page=1, quote="Itemized items"),
        )
    ]
    findings = evaluate(gold_rulebook, facts, ["RULE_NON_PAYABLE_ITEMS"])
    assert len(findings) == 1
    f = findings[0]
    assert f.status == FindingStatus.VIOLATED.value
    # Exactly 350 + 150 = 500.0; the surgical gown is allowable/unmatched
    assert f.estimated_impact == 500.0
    steps = " ".join(f.calculation_steps)
    assert "Sterile Surgical Gown Extra Large" in steps
    assert "Reported allowable/unmatched" in steps


# -----------------------------------------------------------------------------
# Test 7: Conflict check scoping - distinct subtotals are NOT a conflict
# -----------------------------------------------------------------------------
def test_distinct_subtotals_do_not_conflict(gold_rulebook: Rulebook):
    """Different billing subtotals (room rent vs prof fees) must not trigger false conflict."""
    facts = [
        ClaimFact(
            name="room_rent_billing",
            value={"daily_rate": 5000.0, "days": 2, "total_amount": 10000.0},
            source=SourceRef(document="hospital_bill.pdf", page=1, quote="Room rent charges"),
        ),
        ClaimFact(
            name="professional_fees_billing",
            value={"total_amount": 20000.0},
            source=SourceRef(document="hospital_bill.pdf", page=1, quote="Doctor fees"),
        ),
        ClaimFact(
            name="claim_form_summary",
            value={"claimed_amount": 30000.0},
            source=SourceRef(document="claim_form.pdf", page=1, quote="Total claimed"),
        ),
        ClaimFact(
            name="hospital_bill_summary",
            value={"billed_amount": 30000.0},
            source=SourceRef(document="hospital_bill.pdf", page=1, quote="Total billed"),
        ),
    ]
    findings = evaluate(gold_rulebook, facts, ["RULE_ROOM_RENT_CAP"])
    assert len(findings) == 1
    f = findings[0]
    # Distinct subtotals (10000 vs 20000) must not cause needs_review
    assert f.status == FindingStatus.SATISFIED.value
    assert f.estimated_impact == 0.0


# -----------------------------------------------------------------------------
# Test 8: Conflict check scoping - different room rent rates ARE a conflict
# -----------------------------------------------------------------------------
def test_different_room_rent_rates_are_a_conflict(gold_rulebook: Rulebook):
    """Two conflicting room rent facts with different rates must trigger needs_review."""
    facts = [
        ClaimFact(
            name="room_rent_billing",
            value={"daily_rate": 4000.0, "days": 3},
            source=SourceRef(document="bill_1.pdf", page=1, quote="Rate 4000"),
        ),
        ClaimFact(
            name="room_rent_billing",
            value={"daily_rate": 8000.0, "days": 3},
            source=SourceRef(document="bill_2.pdf", page=1, quote="Rate 8000"),
        ),
    ]
    findings = evaluate(gold_rulebook, facts, ["RULE_ROOM_RENT_CAP"])
    assert len(findings) == 1
    f = findings[0]
    assert f.status == FindingStatus.NEEDS_REVIEW.value
    assert "conflicting" in f.explanation.lower() or "duplicate" in f.explanation.lower()
