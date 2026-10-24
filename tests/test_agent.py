"""Offline unit tests for ClaimCheck 2.0 Bounded Investigation Agent and Tavily Client.

Verifies:
1. Iteration cap strictly enforced (maximum 2 iterations).
2. Invalid actions rejected and escalated to human adjuster.
3. 'ask_user' action adds a ClaimFact and re-evaluates affected rules.
4. 'search_tavily' attaches external guidance while keeping finding status as 'needs_review'.
5. Escalate path marks item as requiring human review.
6. Missing TAVILY_API_KEY skips search with a clear message and never crashes.
7. Malformed model response handled gracefully.
8. API keys never appear in audit logs or return values.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Dict, List
import pytest

from src.agent import investigator, tavily_client
from src.agent.investigator import (
    ActionType,
    InvestigationAction,
    InvestigationResult,
    investigate,
)
from src.agent.tavily_client import AUDIT_LOG, TavilySearchResult, clear_audit_log, search
from src.schemas import (
    Ambiguity,
    ClaimFact,
    Finding,
    FindingStatus,
    Rule,
    RuleType,
    Rulebook,
    SourceRef,
    ValidationStatus,
)


@pytest.fixture(autouse=True)
def clean_audit():
    clear_audit_log()
    yield
    clear_audit_log()


@pytest.fixture
def sample_rulebook() -> Rulebook:
    return Rulebook(
        policy_id="test_policy",
        rules=[
            Rule(
                rule_id="RULE_REQ_DOCS",
                rule_type=RuleType.REQUIRED_DOCUMENTS,
                description="All mandatory claim documents must be submitted.",
                parameters={"required_documents": ["claim_form", "hospital_bill", "discharge_summary"]},
                source=SourceRef(document="policy.pdf", page=1, quote="Mandatory documents"),
                validation_status=ValidationStatus.VALIDATED,
            ),
            Rule(
                rule_id="RULE_ROOM_RENT",
                rule_type=RuleType.ROOM_RENT_CAP,
                description="Daily room rent capped at 5000.",
                parameters={"daily_room_rent_cap": 5000},
                source=SourceRef(document="policy.pdf", page=2, quote="Daily room rent capped"),
                validation_status=ValidationStatus.VALIDATED,
            ),
        ],
        ambiguities=[
            Ambiguity(
                ambiguity_id="AMB_01",
                section="4.1",
                description="Pre-existing disease exclusion refers to undefined regulations.",
                issue="Statutory definition of pre-existing condition under IRDAI regulations.",
                source=SourceRef(document="policy.pdf", page=4, quote="as defined under applicable regulations"),
            )
        ],
    )


def test_tavily_search_with_mock_transport():
    """Tavily search client should parse structured results from transport."""
    def fake_transport(payload: dict, timeout: float) -> dict:
        return {
            "results": [
                {
                    "url": "https://irdai.gov.in/guidelines/ped",
                    "title": "IRDAI Health Insurance PED Guidelines",
                    "snippet": "Pre-existing disease means any condition diagnosed within 48 months.",
                }
            ]
        }

    res = search("IRDAI pre-existing condition guidelines", api_key="fake-test-key", transport_fn=fake_transport)
    assert res.success is True
    assert len(res.results) == 1
    assert res.results[0].url == "https://irdai.gov.in/guidelines/ped"
    assert "48 months" in res.results[0].snippet

    # Verify audit log recorded query without key
    log = tavily_client.get_audit_log()
    assert len(log) == 1
    assert log[0]["query"] == "IRDAI pre-existing condition guidelines"
    assert "fake-test-key" not in json.dumps(log)


def test_tavily_search_missing_key_graceful(monkeypatch):
    """When TAVILY_API_KEY is not set, search returns clear notice without crashing."""
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    res = search("IRDAI regulations", api_key=None)
    assert res.success is False
    assert "TAVILY_API_KEY is not set" in (res.error or "")

    log = tavily_client.get_audit_log()
    assert len(log) == 1
    assert log[0]["success"] is False


def test_investigator_iteration_cap_enforced(sample_rulebook: Rulebook):
    """Investigator must stop after max 2 iterations even if items remain unresolved."""
    initial_findings = [
        Finding(
            rule_id="RULE_UNKNOWN",
            status=FindingStatus.NEEDS_REVIEW,
            explanation="Clinical necessity requires adjuster review.",
            inputs_used={},
            source=SourceRef(document="policy.pdf", page=1, quote="Clinical necessity"),
        )
    ]
    facts: List[ClaimFact] = []

    res = investigate(
        findings=initial_findings,
        rulebook=sample_rulebook,
        facts=facts,
        max_iterations=5,  # Requested 5, should be hard-capped at 2
    )

    assert res.iterations_run <= 2
    assert res.max_iterations_reached is True
    assert res.requires_human_review is True


def test_investigator_ask_user_adds_fact_and_resolves_finding(sample_rulebook: Rulebook):
    """When action is ask_user and an answer is provided, rule engine re-evaluates to satisfied."""
    initial_facts = [
        ClaimFact(
            name="submitted_documents",
            value=["claim_form", "hospital_bill"],
            source=SourceRef(document="claim_form.pdf", page=1, quote="submitted"),
        )
    ]
    from src.engine.rule_engine import evaluate
    findings = evaluate(sample_rulebook, initial_facts)
    assert any(f.rule_id == "RULE_REQ_DOCS" and f.status == FindingStatus.VIOLATED for f in findings)

    # User callback provides the missing discharge summary
    def mock_ask_user(question: str, missing_fact: str):
        if missing_fact == "submitted_documents":
            return ["claim_form", "hospital_bill", "discharge_summary"]
        return None

    res = investigate(
        findings=findings,
        rulebook=sample_rulebook,
        facts=initial_facts,
        ask_user=mock_ask_user,
        max_iterations=2,
    )

    # The new fact should be in updated facts
    assert any(f.name == "submitted_documents" and "discharge_summary" in f.value for f in res.facts)
    # The finding for RULE_REQ_DOCS should now be satisfied
    req_fnd = next((f for f in res.findings if f.rule_id == "RULE_REQ_DOCS"), None)
    assert req_fnd is not None
    assert str(getattr(req_fnd.status, "value", req_fnd.status)).lower() == "satisfied"


def test_investigator_tavily_guidance_attached_status_unchanged(sample_rulebook: Rulebook):
    """External guidance is attached to ambiguous items but never changes finding status."""
    def fake_transport(payload: dict, timeout: float) -> dict:
        return {
            "results": [
                {
                    "url": "https://irdai.gov.in/circular/ped",
                    "title": "IRDAI PED Master Circular",
                    "snippet": "Guidelines on pre-existing condition exclusions.",
                }
            ]
        }

    findings = [
        Finding(
            rule_id="RULE_ROOM_RENT",
            status=FindingStatus.NEEDS_REVIEW,
            explanation="Ambiguous room rent rate structure.",
            inputs_used={},
            source=SourceRef(document="policy.pdf", page=2, quote="Daily room rent capped"),
        )
    ]

    res = investigate(
        findings=findings,
        rulebook=sample_rulebook,
        facts=[],
        tavily_transport=fake_transport,
        max_iterations=1,
    )

    # Check ambiguity was investigated with Tavily
    amb_item = next((i for i in res.items if i.item_id == "AMB_01"), None)
    assert amb_item is not None
    assert len(amb_item.external_guidance) == 1
    assert "IRDAI PED" in amb_item.external_guidance[0]["title"]
    assert amb_item.requires_human_review is True

    # Finding status must remain needs_review
    rr_fnd = next((f for f in res.findings if f.rule_id == "RULE_ROOM_RENT"), None)
    assert rr_fnd is not None
    assert str(getattr(rr_fnd.status, "value", rr_fnd.status)).lower() == "needs_review"


def test_investigator_invalid_action_rejected_and_escalated(sample_rulebook: Rulebook, monkeypatch):
    """If fast model produces invalid action or invalid schema, it is rejected and escalated."""
    class FakeChoice:
        message = type("Msg", (), {"content": json.dumps({"action": "hallucinated_action", "reason": "invalid"})})()
        finish_reason = "stop"

    class FakeClient:
        class chat:
            class completions:
                @staticmethod
                def create(*args, **kwargs):
                    return type("Resp", (), {"choices": [FakeChoice()]})()

    monkeypatch.setenv("NEBIUS_MODEL_FAST", "nvidia/nemotron-mini-4b-instruct")

    findings = [
        Finding(
            rule_id="RULE_ROOM_RENT",
            status=FindingStatus.NEEDS_REVIEW,
            explanation="Unresolved room rent ambiguity.",
            inputs_used={},
            source=SourceRef(document="policy.pdf", page=2, quote="quote"),
        )
    ]

    res = investigate(
        findings=findings,
        rulebook=sample_rulebook,
        facts=[],
        model_client=FakeClient(),
        max_iterations=1,
    )

    # The item should be escalated
    fnd_item = next((i for i in res.items if i.item_id == "RULE_ROOM_RENT"), None)
    assert fnd_item is not None
    assert fnd_item.action is not None
    assert fnd_item.action.action == ActionType.ESCALATE
    assert fnd_item.requires_human_review is True


def test_investigator_malformed_model_reply_handled(sample_rulebook: Rulebook, monkeypatch):
    """If fast model returns non-JSON or broken text, handled gracefully without crashing."""
    class BrokenChoice:
        message = type("Msg", (), {"content": "This is not json at all <random text>"})()
        finish_reason = "stop"

    class BrokenClient:
        class chat:
            class completions:
                @staticmethod
                def create(*args, **kwargs):
                    return type("Resp", (), {"choices": [BrokenChoice()]})()

    monkeypatch.setenv("NEBIUS_MODEL_FAST", "nvidia/nemotron-mini-4b-instruct")

    findings = [
        Finding(
            rule_id="RULE_ROOM_RENT",
            status=FindingStatus.NEEDS_REVIEW,
            explanation="Review needed.",
            inputs_used={},
            source=SourceRef(document="policy.pdf", page=2, quote="quote"),
        )
    ]

    res = investigate(
        findings=findings,
        rulebook=sample_rulebook,
        facts=[],
        model_client=BrokenClient(),
        max_iterations=1,
    )

    fnd_item = next((i for i in res.items if i.item_id == "RULE_ROOM_RENT"), None)
    assert fnd_item is not None
    assert fnd_item.action.action == ActionType.ESCALATE
