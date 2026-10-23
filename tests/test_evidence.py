"""Tests for citation verification against the synthetic policy."""

import json
from pathlib import Path

import pytest

from src.documents.evidence import check_citation, find_quote_page, verify_citation
from src.documents.policy_document import load_document
from src.schemas import Rulebook, SourceRef

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def policy():
    return load_document(ROOT / "data" / "synthetic_policy.pdf", ocr_fallback=False)


@pytest.fixture(scope="module")
def rulebook():
    text = (ROOT / "data" / "gold_rulebook.json").read_text(encoding="utf-8")
    return Rulebook.model_validate(json.loads(text))


def test_every_gold_citation_verifies(policy, rulebook):
    for rule in rulebook.rules:
        result = check_citation(policy, rule.source)
        assert result.verified, f"{rule.rule_id}: {result.reason}"


def test_wrong_page_is_detected(policy, rulebook):
    src = rulebook.rules[0].source
    wrong_page = src.page % policy.total_pages + 1
    bad = SourceRef(document=src.document, page=wrong_page, quote=src.quote)

    result = check_citation(policy, bad)
    assert verify_citation(policy, bad) is False
    assert result.reason == "wrong_page"
    assert result.found_on_page == src.page


def test_invented_quote_is_rejected(policy):
    fake = SourceRef(
        document="synthetic_policy.pdf",
        page=1,
        quote="All claims are approved automatically without any documents.",
    )
    result = check_citation(policy, fake)
    assert result.verified is False
    assert result.reason == "not_found"
    assert result.found_on_page is None


def test_page_out_of_range(policy, rulebook):
    src = rulebook.rules[0].source
    bad = SourceRef(document=src.document, page=99, quote=src.quote)
    result = check_citation(policy, bad)
    assert result.verified is False
    assert result.reason == "page_out_of_range"


def test_line_breaks_in_quote_are_tolerated(policy, rulebook):
    src = rulebook.rules[0].source
    messy = SourceRef(document=src.document, page=src.page, quote=src.quote.replace(" ", "\n  "))
    assert verify_citation(policy, messy) is True


def test_find_quote_page_returns_correct_page(policy, rulebook):
    for rule in rulebook.rules:
        assert find_quote_page(policy, rule.source.quote) == rule.source.page