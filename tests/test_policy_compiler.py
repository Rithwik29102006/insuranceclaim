"""Offline tests for the Nemotron policy compiler using a fake client."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.ai.nebius_client import NebiusConfigError, NebiusResponseError, get_client
from src.ai.policy_compiler import PolicyCompilerError, compile_policy_rules
from src.documents.policy_document import load_document
from src.schemas import Rulebook

ROOT = Path(__file__).resolve().parent.parent


class FakeClient:
    """Mimics client.chat.completions.create and records the calls."""

    def __init__(self, content):
        self.content = content
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        message = SimpleNamespace(content=self.content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


@pytest.fixture(scope="module")
def policy():
    return load_document(ROOT / "data" / "synthetic_policy.pdf", ocr_fallback=False)


@pytest.fixture(scope="module")
def gold():
    text = (ROOT / "data" / "gold_rulebook.json").read_text(encoding="utf-8")
    return Rulebook.model_validate(json.loads(text))


def _gold_as_model_output(gold):
    return [
        {
            "rule_id": r.rule_id,
            "rule_type": r.rule_type,
            "description": r.description,
            "parameters": r.parameters,
            "exceptions": r.exceptions,
            "source": {"page": r.source.page, "quote": r.source.quote},
        }
        for r in gold.rules
    ]


def _compile(policy, rules=None, content=None):
    client = FakeClient(content if content is not None else json.dumps({"rules": rules}))
    result = compile_policy_rules(policy, "POL-TEST", client=client, model="test-nemotron")
    return result, client


def test_correct_output_is_fully_verified(policy, gold):
    result, client = _compile(policy, _gold_as_model_output(gold))
    assert len(result.rules) == 5
    assert result.verified_count == 5
    assert result.rejected == []
    assert all(r.validation_status == "draft" for r in result.rules)
    assert not any(r.human_review_required for r in result.rules)
    assert client.calls[0]["model"] == "test-nemotron"
    assert "=== PAGE 1 ===" in client.calls[0]["messages"][1]["content"]
    assert "daily_limit_inr" in client.calls[0]["messages"][1]["content"]


def test_invented_quote_is_flagged_for_review(policy, gold):
    rules = _gold_as_model_output(gold)
    rules[0]["source"]["quote"] = "This policy pays every claim in full without documents."
    result, _ = _compile(policy, rules)
    first = result.rules[0]
    assert first.human_review_required is True
    assert result.citation_checks[first.rule_id].reason == "not_found"
    assert result.verified_count == 4


def test_wrong_page_is_flagged_for_review(policy, gold):
    rules = _gold_as_model_output(gold)
    rules[0]["source"]["page"] = rules[0]["source"]["page"] % policy.total_pages + 1
    result, _ = _compile(policy, rules)
    assert result.rules[0].human_review_required is True
    assert result.citation_checks[result.rules[0].rule_id].reason == "wrong_page"


def test_invalid_rule_type_is_rejected_not_crashing(policy, gold):
    rules = _gold_as_model_output(gold)
    rules[1]["rule_type"] = "free_money"
    result, _ = _compile(policy, rules)
    assert len(result.rules) == 4
    assert len(result.rejected) == 1


def test_duplicate_rule_id_is_rejected(policy, gold):
    rules = _gold_as_model_output(gold)
    rules.append(dict(rules[0]))
    result, _ = _compile(policy, rules)
    assert len(result.rules) == 5
    assert any("duplicate" in msg for msg in result.rejected)


def test_think_block_and_code_fence_are_ignored(policy, gold):
    payload = json.dumps({"rules": _gold_as_model_output(gold)})
    content = f"<think>Let me read the policy {{carefully}}.</think>\n```json\n{payload}\n```"
    result, _ = _compile(policy, content=content)
    assert len(result.rules) == 5


def test_missing_rules_key_raises(policy):
    with pytest.raises(PolicyCompilerError):
        _compile(policy, content='{"answer": "no rules"}')


def test_non_json_reply_raises(policy):
    with pytest.raises(NebiusResponseError):
        _compile(policy, content="Sorry, I cannot help with that.")


def test_result_converts_to_rulebook(policy, gold):
    result, _ = _compile(policy, _gold_as_model_output(gold))
    rulebook = result.to_rulebook()
    assert rulebook.policy_id == "POL-TEST"
    assert len(rulebook.rules) == 5


def test_missing_api_key_gives_clear_error(monkeypatch):
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    with patch("src.ai.nebius_client.load_dotenv"):
        with pytest.raises(NebiusConfigError):
            get_client()