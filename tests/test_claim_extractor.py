"""Offline tests for the Nemotron claim fact extractor using a fake client."""

import copy
import json
from types import SimpleNamespace
from unittest.mock import patch

import pymupdf as fitz
import pytest

from src.ai.claim_extractor import ClaimExtractorError, extract_claim_facts
from src.documents.policy_document import load_document

ROOM_QUOTE = "Executive Suite Room Charges: 4 days @ INR 7500.00 per day = INR 30000.00."
ADMIT_QUOTE = "Date of admission: 2026-02-15"


class FakeClient:
    def __init__(self, content):
        self.content = content
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        message = SimpleNamespace(content=self.content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _pdf(lines):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(fitz.Point(40, 72), "\n".join(lines), fontsize=10)
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture(scope="module")
def documents():
    bill = load_document(_pdf([
        "CITY CARE HOSPITAL - FINAL BILL",
        ROOM_QUOTE,
        "Admission processing charges: INR 1200.00",
    ]), document_id="hospital_bill.pdf", ocr_fallback=False)
    summary = load_document(_pdf([
        "DISCHARGE SUMMARY",
        "Policy inception date: 2026-01-01",
        ADMIT_QUOTE,
        "Diagnosis: acute viral gastroenteritis (illness)",
    ]), document_id="discharge_summary.pdf", ocr_fallback=False)
    return [bill, summary]


GOOD_FACTS = [
    {
        "name": "room_rent_billing",
        "value": {"room_type": "executive_suite", "daily_rate": 7500, "days": 4, "total_amount": 30000},
        "source": {"document": "hospital_bill.pdf", "page": 1, "quote": ROOM_QUOTE},
    },
    {
        "name": "hospitalization_details",
        "value": {"policy_inception_date": "2026-01-01", "admission_date": "2026-02-15",
                  "cause": "illness", "diagnosis": "acute viral gastroenteritis", "days_elapsed": 999},
        "source": {"document": "discharge_summary.pdf", "page": 1, "quote": ADMIT_QUOTE},
    },
]


def _run(documents, facts=None, content=None, model="test-nano"):
    client = FakeClient(content if content is not None else json.dumps({"facts": facts}))
    return extract_claim_facts(documents, client=client, model=model), client


def test_correct_facts_are_verified(documents):
    result, client = _run(documents, GOOD_FACTS)
    assert [f.name for f in result.facts] == ["room_rent_billing", "hospitalization_details"]
    assert result.verified_count == 2
    assert result.needs_review == []
    assert result.rejected == []
    assert result.fact("room_rent_billing").value["daily_rate"] == 7500
    prompt = client.calls[0]["messages"][1]["content"]
    assert "=== DOCUMENT hospital_bill.pdf | PAGE 1 ===" in prompt
    assert "room_rent_billing" in prompt


def test_days_elapsed_is_computed_not_trusted(documents):
    result, _ = _run(documents, GOOD_FACTS)
    assert result.fact("hospitalization_details").value["days_elapsed"] == 45


def test_missing_date_gives_unknown_days_elapsed(documents):
    facts = copy.deepcopy(GOOD_FACTS)
    facts[1]["value"]["policy_inception_date"] = None
    result, _ = _run(documents, facts)
    assert result.fact("hospitalization_details").value["days_elapsed"] is None


def test_invented_quote_needs_review(documents):
    facts = copy.deepcopy(GOOD_FACTS)
    facts[0]["source"]["quote"] = "Room charges: 4 days at INR 3000 per day."
    result, _ = _run(documents, facts)
    assert "room_rent_billing" in result.needs_review
    assert result.citation_checks["room_rent_billing"].reason == "not_found"


def test_unknown_document_needs_review(documents):
    facts = copy.deepcopy(GOOD_FACTS)
    facts[0]["source"]["document"] = "made_up_invoice.pdf"
    result, _ = _run(documents, facts)
    assert result.citation_checks["room_rent_billing"].reason == "unknown_document"
    assert "room_rent_billing" in result.needs_review


def test_unknown_fact_name_is_rejected(documents):
    facts = copy.deepcopy(GOOD_FACTS) + [{
        "name": "patient_mood", "value": "happy",
        "source": {"document": "hospital_bill.pdf", "page": 1, "quote": ROOM_QUOTE},
    }]
    result, _ = _run(documents, facts)
    assert len(result.facts) == 2
    assert any("patient_mood" in msg for msg in result.rejected)


def test_duplicate_fact_is_rejected(documents):
    facts = copy.deepcopy(GOOD_FACTS) + [copy.deepcopy(GOOD_FACTS[0])]
    result, _ = _run(documents, facts)
    assert len(result.facts) == 2
    assert any("duplicate" in msg for msg in result.rejected)


def test_single_document_fills_missing_document_name(documents):
    facts = [copy.deepcopy(GOOD_FACTS[0])]
    del facts[0]["source"]["document"]
    result, _ = _run(documents[:1], facts)
    assert result.facts[0].source.document == "hospital_bill.pdf"
    assert result.verified_count == 1


def test_no_documents_raises():
    with pytest.raises(ClaimExtractorError):
        extract_claim_facts([], client=FakeClient("{}"), model="m")


def test_missing_facts_key_raises(documents):
    with pytest.raises(ClaimExtractorError):
        _run(documents, content='{"result": []}')


def test_uses_fast_model_by_default(documents):
    fake = FakeClient(json.dumps({"facts": GOOD_FACTS}))
    with patch("src.ai.claim_extractor.get_model", return_value="nano-id") as get_model:
        result = extract_claim_facts(documents, client=fake)
    get_model.assert_called_once_with("fast")
    assert result.model == "nano-id"
