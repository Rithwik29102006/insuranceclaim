"""Drives app.py headlessly (Streamlit AppTest) through the live-mode approval flow
with a fake Nemotron client: read policy -> use verified rules -> analyze. No network."""

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


PAGES = ["1. Claim setup", "2. Policy rules", "3. Results & verdict"]


def _start_live(at: AppTest) -> AppTest:
    at.run(timeout=60)
    at.radio(key="w_mode").set_value("Live AI (NVIDIA Nemotron)").run(timeout=60)
    at.selectbox(key="w_case").set_value("packet_08").run(timeout=60)
    return at


def _goto(at: AppTest, page: str) -> AppTest:
    return at.radio(key="nav").set_value(page).run(timeout=60)


def _button(at: AppTest, label_start: str):
    return next(b for b in at.button if b.label.startswith(label_start))


def _violations(at: AppTest) -> int:
    result = at.session_state["result"]
    return sum(1 for f in result.findings if str(getattr(f.status, "value", f.status)) == "violated")


def test_live_check_reads_policy_and_uses_verified_rules(live_env):
    at = _start_live(AppTest.from_file(str(APP_PATH), default_timeout=60))
    _button(at, "Check my claim").click().run(timeout=60)
    assert at.session_state["compilation"] is not None
    assert at.session_state["nav"] == PAGES[2]
    result = at.session_state["result"]
    assert len(result.approved_rule_ids) == 11            # every quote-verified rule is used
    assert _violations(at) >= 1                           # the non-payable rule is applied
    text = " ".join(m.value for m in at.markdown)
    assert "is unverified (status:" not in text           # no engine wording on screen

    _goto(at, PAGES[1])                                   # rules page is read-only
    assert len(at.checkbox) == 0
    assert not at.exception


def test_failed_live_check_shows_error_not_a_result(live_env, monkeypatch):
    def broken(*args, **kwargs):
        from src.ai.nebius_client import NebiusResponseError
        raise NebiusResponseError("Model returned invalid JSON: test")
    monkeypatch.setattr("src.ai.claim_extractor.chat_json", broken)
    at = _start_live(AppTest.from_file(str(APP_PATH), default_timeout=60))
    _button(at, "Check my claim").click().run(timeout=60)
    assert any("could not be checked" in e.value for e in at.error)
    assert not any('class="cc-card cc-verdict"' in m.value for m in at.markdown)


def test_every_page_renders_for_every_demo_case():
    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    at.run(timeout=60)
    for claim in ("Reimbursement", "Cashless pre-approval"):
        at.radio(key="w_claim").set_value(claim).run(timeout=60)
        for case in [o for o in at.selectbox(key="w_case").options if o.startswith("case_")]:
            _goto(at, "1. Claim setup")
            at.selectbox(key="w_case").set_value(case).run(timeout=60)
            _button(at, "Check my claim").click().run(timeout=60)
            for page in at.radio(key="nav").options:
                _goto(at, page)
                assert not at.exception, (claim, case, page, at.exception[0].value if at.exception else "")
