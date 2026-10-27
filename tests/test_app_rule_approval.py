"""Drives app.py headlessly (Streamlit AppTest) through the live-mode approval flow
with a fake Nemotron client: compile -> review -> approve -> analyze. No network."""

from __future__ import annotations

import pytest

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402

from tests.test_ui_pipeline import _FakeNemotron  # noqa: E402

from pathlib import Path  # noqa: E402

APP_PATH = Path(__file__).resolve().parent.parent / "app.py"


@pytest.fixture
def live_env(monkeypatch):
    monkeypatch.setenv("NEBIUS_API_KEY", "dummy-live-key")
    monkeypatch.setenv("NEBIUS_MODEL_FAST", "fake-nemotron-fast")
    monkeypatch.setenv("NEBIUS_MODEL_REASONING", "fake-nemotron-reasoning")
    fake = _FakeNemotron("packet_08")
    monkeypatch.setattr("src.ai.policy_compiler.get_client", lambda: fake)
    monkeypatch.setattr("src.ai.claim_extractor.get_client", lambda: fake)
    return fake


def _start_live(at: AppTest) -> AppTest:
    at.run(timeout=60)
    next(r for r in at.sidebar.radio if r.label == "Check mode").set_value("Live AI (NVIDIA Nemotron)").run(timeout=60)
    at.sidebar.selectbox[0].set_value("packet_08").run(timeout=60)
    return at


def _button(at: AppTest, label_start: str):
    return next(b for b in at.button if b.label.startswith(label_start))


def _violations(at: AppTest) -> int:
    result = at.session_state["result"]
    return sum(1 for f in result.findings if str(getattr(f.status, "value", f.status)) == "violated")


def test_live_flow_requires_approval_then_applies_rules(live_env):
    at = _start_live(AppTest.from_file(str(APP_PATH), default_timeout=60))

    _button(at, "Read the policy with AI").click().run(timeout=60)
    assert at.session_state["compilation"] is not None
    assert any("Check the rules the AI read" in h.value for h in at.subheader)
    assert len(at.checkbox) == 11
    assert all(cb.value for cb in at.checkbox)  # verified rules are pre-ticked for review

    # Check before approving: nothing is decided
    _button(at, "Check my claim").click().run(timeout=60)
    assert _violations(at) == 0

    # Approve, then check again: the non-payable rule is applied
    _button(at, "Approve selected rules").click().run(timeout=60)
    assert len(at.session_state["approved_rule_ids"]) == 11
    _button(at, "Check my claim").click().run(timeout=60)
    assert _violations(at) >= 1
    assert at.session_state["result"].approved_rule_ids


def test_unticked_rule_is_not_approved(live_env):
    at = _start_live(AppTest.from_file(str(APP_PATH), default_timeout=60))
    _button(at, "Read the policy with AI").click().run(timeout=60)
    next(cb for cb in at.checkbox if cb.key == "approve_RULE_NON_PAYABLE_ITEMS").uncheck()
    _button(at, "Approve selected rules").click().run(timeout=60)
    assert "RULE_NON_PAYABLE_ITEMS" not in at.session_state["approved_rule_ids"]
    _button(at, "Check my claim").click().run(timeout=60)
    assert _violations(at) == 0


def test_failed_live_check_shows_error_not_a_result(live_env, monkeypatch):
    def broken(*args, **kwargs):
        from src.ai.nebius_client import NebiusResponseError
        raise NebiusResponseError("Model returned invalid JSON: test")
    monkeypatch.setattr("src.ai.claim_extractor.chat_json", broken)
    at = _start_live(AppTest.from_file(str(APP_PATH), default_timeout=60))
    _button(at, "Check my claim").click().run(timeout=60)
    assert any("could not be checked" in e.value for e in at.error)
    assert not any('class="cc-hero"' in m.value for m in at.markdown)
