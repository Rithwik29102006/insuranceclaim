"""ClaimCheck - health insurance claim checker (Streamlit app).

Upload a claim (reimbursement) or a cashless pre-approval request with any documents:
claim form, bills, prescriptions, lab reports, discharge summary, pre/post-hospitalisation
bills, ambulance bill, pre-authorisation form or the doctor's cost estimate.

ClaimCheck tells the user, in plain language:
  - how much is expected to be paid and why money was deducted,
  - mistakes in the documents to fix before submitting,
  - existing illnesses found in the records that were not declared,
  - which policy rules were checked, each backed by the exact policy quote.

Live mode uses NVIDIA Nemotron on Nebius Token Factory to read the policy and the documents.
A person approves the AI-compiled rules once per policy before they are applied.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import streamlit as st

from src import settings
from src.agent import tavily_client
from src.ai.config_check import inspect_configuration
from src.engine.coverage_rules import _date
from src.engine.document_checks import CHECK_LABELS
from src.engine.rule_engine import evaluate
from src.pipeline import AnalysisResult, analyze, approvable_rule_ids, compile_policy, render_page_with_highlight
from src.reports.report_generator import generate_markdown_report
from src.schemas import ClaimFact, Finding, SourceRef

ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
PACKETS_DIR = DATA_DIR / "packets"
DEMO_DIR = DATA_DIR / "demo_cases"
DEFAULT_POLICY_PATH = DATA_DIR / "synthetic_policy.pdf"

# Older benchmark packets (three documents each, reimbursement only).
PACKET_CATALOG = {
    "packet_01": "All three required documents",
    "packet_02": "Missing discharge summary",
    "packet_03": "Illness on day 45 (waiting period passed)",
    "packet_04": "Illness on day 14 (inside the waiting period)",
    "packet_05": "Room rent within the limit",
    "packet_06": "Private suite above the room limit (scanned bill)",
    "packet_07": "Cataract surgery above the limit",
    "packet_08": "Admission charges and amenity kit on the bill",
    "packet_09": "Road accident on day 10",
    "packet_10": "Room rent above the limit, days not stated (scanned)",
    "packet_11": "Deluxe room with proportional deduction (scanned)",
    "packet_12": "Hypertension with a pre-existing history",
    "packet_13": "Missing claim form",
    "packet_14": "Missing hospital bill",
    "packet_15": "Gloves and masks written oddly on the bill (scanned)",
    "packet_16": "Look-alike item names that are not excluded",
    "packet_17": "Room rent exactly at the limit (scanned)",
    "packet_18": "Illness on day 30 (still inside the waiting period)",
    "packet_19": "Illness on day 31 (waiting period passed)",
    "packet_20": "Claimed amount larger than the bill (scanned)",
}

STATUS_WORDS = {
    "satisfied": ("Passed", "ok"),
    "violated": ("Money deducted", "cut"),
    "failed": ("Not met", "cut"),
    "needs_review": ("Needs review", "review"),
    "unable_to_verify": ("Can't check yet", "muted"),
    "not_applicable": ("Not applicable", "muted"),
}

st.set_page_config(page_title="ClaimCheck", layout="wide", initial_sidebar_state="expanded")

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Serif:wght@500;600&display=swap');
:root {
  --ink: #172B4D; --muted: #5B6B7F; --line: #D8DEE6; --paper: #F4F6F8; --surface: #FFFFFF;
  --ok: #17803D; --ok-soft: #E3F2E8; --cut: #B42318; --cut-soft: #FBE7E5;
  --review: #9A5B06; --review-soft: #FDF1DC; --proof: #0F5FA6;
}
html, body, [class*="css"], .stMarkdown, .stText, button, input, label { font-family: 'IBM Plex Sans', sans-serif; }
.stApp { background: var(--paper); color: var(--ink); }
.block-container { max-width: 1120px; padding-top: 3.6rem; }
h1, h2, h3, h4 { color: var(--ink); font-family: 'IBM Plex Sans', sans-serif; font-weight: 600; letter-spacing: 0; }
.cc-brand { font-weight: 600; font-size: 1.05rem; color: var(--ink); margin-bottom: 0; }
.cc-sub { color: var(--muted); font-size: 0.9rem; margin-top: 0.1rem; }
.cc-hero { background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 1.6rem 1.8rem 1.3rem; margin: 0.6rem 0 1.2rem; }
.cc-verdict { display: inline-block; font-size: 0.85rem; font-weight: 600; padding: 0.2rem 0.65rem; border-radius: 999px; margin-bottom: 0.7rem; }
.cc-verdict.ok { background: var(--ok-soft); color: var(--ok); }
.cc-verdict.cut { background: var(--cut-soft); color: var(--cut); }
.cc-verdict.review { background: var(--review-soft); color: var(--review); }
.cc-hero p.cc-headline { font-family: 'IBM Plex Serif', serif !important; font-weight: 500; font-size: 2.1rem !important; line-height: 1.22 !important; margin: 0 0 1.1rem; max-width: 46ch; color: var(--ink); }
.cc-hero p.cc-headline b { font-weight: 600; }
.cc-strip { display: flex; height: 18px; border-radius: 4px; overflow: hidden; background: var(--line); margin: 0.2rem 0 0.6rem; }
.cc-strip span { display: block; height: 100%; }
.cc-strip .pay { background: var(--ok); }
.cc-strip .cut { background: var(--cut); border-left: 2px solid var(--surface); }
.cc-strip .cap { background: #7A869A; border-left: 2px solid var(--surface); }
.cc-legend { display: flex; flex-wrap: wrap; gap: 0.4rem 1.4rem; font-size: 0.88rem; color: var(--muted); }
.cc-legend i { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 6px; vertical-align: -1px; }
.cc-figures { display: flex; gap: 2.4rem; margin-top: 1rem; font-variant-numeric: tabular-nums; }
.cc-figures div { font-size: 0.85rem; color: var(--muted); }
.cc-figures b { display: block; font-size: 1.15rem; color: var(--ink); font-weight: 600; }
.cc-todo { background: var(--surface); border: 1px solid var(--line); border-left: 4px solid var(--review); border-radius: 8px; padding: 0.9rem 1.2rem; margin-bottom: 1.2rem; }
.cc-todo.cut { border-left-color: var(--cut); }
.cc-todo.ok { border-left-color: var(--ok); }
.cc-todo h4 { margin: 0 0 0.4rem; font-size: 1rem; }
.cc-todo li { margin: 0.2rem 0; }
.cc-row { display: flex; justify-content: space-between; gap: 1rem; align-items: baseline; }
.cc-status { font-size: 0.85rem; font-weight: 600; white-space: nowrap; }
.cc-status.ok { color: var(--ok); } .cc-status.cut { color: var(--cut); }
.cc-status.review { color: var(--review); } .cc-status.muted { color: var(--muted); }
.cc-amount { font-variant-numeric: tabular-nums; font-weight: 600; }
.cc-quote { border-left: 3px solid var(--proof); padding: 0.4rem 0.8rem; color: var(--ink); background: #EEF4FB; border-radius: 0 6px 6px 0; font-size: 0.92rem; }
.cc-note { color: var(--muted); font-size: 0.85rem; }
section[data-testid="stSidebar"] { background: var(--surface); border-right: 1px solid var(--line); }
section[data-testid="stSidebar"] h3 { font-size: 0.98rem; margin-bottom: 0.2rem; }
:focus-visible { outline: 2px solid var(--proof) !important; outline-offset: 2px; }
</style>
"""


# --------------------------------------------------------------------------- helpers
def inr(x: Optional[float]) -> str:
    return "-" if x is None else f"₹{x:,.0f}" if float(x).is_integer() else f"₹{x:,.2f}"


def status_of(f: Finding) -> str:
    return str(getattr(f.status, "value", f.status)).lower()


def demo_cases() -> List[dict]:
    cases = []
    if DEMO_DIR.exists():
        for folder in sorted(p for p in DEMO_DIR.iterdir() if p.is_dir()):
            meta = json.loads((folder / "expected.json").read_text(encoding="utf-8"))
            cases.append({"id": folder.name, "label": meta["label"], "story": meta["story"],
                          "claim_type": meta["claim_type"], "folder": folder})
    return cases


def load_case_files(folder: Path) -> Dict[str, bytes]:
    return {f.name: f.read_bytes() for f in sorted(folder.glob("*.pdf"))}


def rule_types(result: AnalysisResult) -> Dict[str, str]:
    if not result.rulebook:
        return {}
    return {r.rule_id: str(getattr(r.rule_type, "value", r.rule_type)) for r in result.rulebook.rules}


def rule_title(rule_id: str, result: AnalysisResult) -> str:
    """Plain-language name for a rule, built from its own numbers."""
    if rule_id in CHECK_LABELS:
        return CHECK_LABELS[rule_id]
    rule = next((r for r in (result.rulebook.rules if result.rulebook else []) if r.rule_id == rule_id), None)
    if rule is None:
        amb = next((a for a in result.ambiguities if a.ambiguity_id == rule_id), None)
        return f"Unclear policy wording ({amb.section})" if amb else rule_id
    t = str(getattr(rule.rule_type, "value", rule.rule_type))
    p = rule.parameters or {}

    def num(*keys):
        for k in keys:
            if p.get(k) is not None:
                try:
                    return float(p[k])
                except (TypeError, ValueError):
                    pass
        return None

    titles = {
        "required_documents": "Required documents submitted",
        "waiting_period": f"No illness claims in the first {int(num('duration_days') or 30)} days",
        "room_rent_cap": f"Room rent limit of {inr(num('cap', 'daily_limit_inr'))} a day",
        "sub_limit": f"Cataract surgery limit of {inr(num('max_limit_inr'))} per eye",
        "non_payable_items": "Items the policy never pays for",
        "pre_hospitalization": f"Bills up to {int(num('window_days') or 30)} days before admission",
        "post_hospitalization": f"Bills up to {int(num('window_days') or 60)} days after discharge",
        "ambulance_limit": f"Ambulance limit of {inr(num('max_limit_inr'))}",
        "sum_insured": f"Yearly sum insured of {inr(num('sum_insured_inr'))}",
        "cashless_preauthorization": "Cashless pre-approval request",
        "pre_existing_disclosure": "Existing illnesses declared",
    }
    return titles.get(t, rule.description)


def display_status(f: Finding, result: AnalysisResult) -> Tuple[str, str]:
    if f.rule_id in result.not_applicable_rule_ids:
        return STATUS_WORDS["not_applicable"]
    s = status_of(f)
    if s == "violated" and not f.estimated_impact:
        return STATUS_WORDS["failed"]
    return STATUS_WORDS.get(s, (s, "muted"))


def plain(text: str) -> str:
    """Show money the way people read it: INR 6,500.00 -> \u20b96,500."""
    import re as _re

    def fmt(m):
        value = float(m.group(1).replace(",", ""))
        return inr(value)

    return _re.sub(r"INR\s*([\d,]+(?:\.\d+)?)", fmt, text)


def explain(f: Finding, result: AnalysisResult) -> str:
    """Everyday-language explanation; the original wording stays in the proof."""
    import re as _re
    amb = next((a for a in result.ambiguities if a.ambiguity_id == f.rule_id), None)
    if amb is not None:
        return (f"{amb.section} of the policy is unclear: {amb.issue[0].lower() + amb.issue[1:]}. This claim mentions a "
                "related medical history, so a claims officer has to decide how that section applies.")
    if rule_types(result).get(f.rule_id) == "room_rent_cap" and status_of(f) == "violated":
        m = _re.search(r"room rent of INR\s*([\d,.]+) exceeds the policy cap of INR\s*([\d,.]+)", f.explanation)
        if m:
            rate, cap = float(m.group(1).replace(",", "")), float(m.group(2).replace(",", ""))
            text = (f"The room cost {inr(rate)} a day but the policy covers {inr(cap)} a day, so you pay the extra "
                    "room rent.")
            if "proportional" in f.explanation.lower():
                text += (f" Because the room was above the limit, the policy also pays only {cap / rate * 100:.1f}% of "
                         "the doctor and operation theatre fees.")
            return text + f" In total {inr(f.estimated_impact)} is not covered."
    return plain(f.explanation)


def find_doc_bytes(name: str) -> bytes:
    if name == "synthetic_policy.pdf" or "policy" in name.lower() and name not in st.session_state.claim_pdfs:
        return st.session_state.policy_bytes
    pdfs = st.session_state.claim_pdfs
    if name in pdfs:
        return pdfs[name]
    return next((v for k, v in pdfs.items() if k.lower() in name.lower() or name.lower() in k.lower()), b"")


def render_proof(f: Finding, key: str) -> None:
    """The evidence for one result: policy quote, the working, and the highlighted page."""
    src = f.source
    st.markdown(f'<div class="cc-quote">"{src.quote}"<br><span class="cc-note">{src.document}, page {src.page}</span></div>',
                unsafe_allow_html=True)
    if f.calculation_steps:
        st.markdown("**How this was worked out**")
        st.markdown("\n".join(f"{i}. {s}" for i, s in enumerate(f.calculation_steps, 1)))
    if st.checkbox("Show the page with the quote highlighted", key=f"page_{key}"):
        data = find_doc_bytes(src.document)
        if data:
            png, _, note = render_page_with_highlight(data, src.page, src.quote, dpi=120)
            if png:
                st.image(png, caption=f"{src.document}, page {src.page}: {note}", width="stretch")
            else:
                st.caption(note)
        else:
            st.caption("This document is not loaded, so the page cannot be shown.")


def result_row(f: Finding, result: AnalysisResult, key: str, expanded: bool = False) -> None:
    word, tone = display_status(f, result)
    amount = f" &nbsp;<span class='cc-amount'>-{inr(f.estimated_impact)}</span>" if (
        status_of(f) == "violated" and f.estimated_impact) else ""
    st.markdown(f"<div class='cc-row'><span><b>{rule_title(f.rule_id, result)}</b></span>"
                f"<span class='cc-status {tone}'>{word}{amount}</span></div>", unsafe_allow_html=True)
    st.write(explain(f, result))
    with st.expander("See the proof", expanded=expanded):
        if explain(f, result) != plain(f.explanation):
            st.caption(plain(f.explanation))
        render_proof(f, key)


# --------------------------------------------------------------------------- live mode: rule approval
def render_rule_approval() -> None:
    """Live mode: a person reviews the rules Nemotron read from the policy and approves them."""
    compilation = st.session_state.get("compilation")
    if compilation is None:
        return
    approvable = set(approvable_rule_ids(compilation))
    approved = st.session_state.get("approved_rule_ids")

    st.subheader("Check the rules the AI read from your policy")
    st.caption(f"NVIDIA Nemotron ({compilation.model}) found {len(compilation.rules)} rules. Every rule quotes the "
               "policy, and each quote was checked word for word against the page it cites. Only rules with a "
               "checked quote can be approved, and only approved rules are used on claims. You do this once per policy.")
    if approved is None:
        st.warning("Not approved yet. Until you approve the rules, every result will say Needs review.")
    else:
        st.success(f"{len(approved)} of {len(compilation.rules)} rules approved. Click Check my claim to use them.")

    with st.form("rule_approval_form"):
        selections: Dict[str, bool] = {}
        for rule in compilation.rules:
            verified = rule.rule_id in approvable
            check = compilation.citation_checks.get(rule.rule_id)
            badge = (f"quote found on page {rule.source.page}" if verified
                     else f"quote NOT found on page {rule.source.page}")
            with st.expander(f"{rule.description}  ({badge})", expanded=not verified):
                st.json(rule.parameters, expanded=True)
                if rule.exceptions:
                    st.write("Exceptions: " + "; ".join(rule.exceptions))
                st.markdown(f'<div class="cc-quote">"{rule.source.quote}"<br>'
                            f'<span class="cc-note">policy page {rule.source.page}</span></div>', unsafe_allow_html=True)
                if not verified and check is not None:
                    st.caption(f"Citation check result: {check.reason}")
                default = verified if approved is None else rule.rule_id in approved
                selections[rule.rule_id] = st.checkbox(
                    "Approve this rule" if verified else "Cannot approve: the quote was not found",
                    value=default and verified, disabled=not verified, key=f"approve_{rule.rule_id}")
        for amb in getattr(compilation, "ambiguities", []):
            st.info(f"Unclear wording in {amb.section} (page {amb.source.page}): {amb.issue}. "
                    "Claims touching this are always sent to a person.")
        if st.form_submit_button("Approve selected rules", type="primary"):
            st.session_state.approved_rule_ids = [rid for rid, ok in selections.items() if ok and rid in approvable]
            st.rerun()
    st.markdown("---")


# --------------------------------------------------------------------------- result sections
def render_hero(result: AnalysisResult) -> None:
    p = result.payout or {}
    verdict = p.get("verdict", "needs_review")
    tone = {"approved": "ok", "rejected": "cut", "incomplete": "cut", "fix_documents": "cut"}.get(verdict, "review")
    estimate = p.get("is_estimate")
    claimed, payable, deducted = p.get("claimed"), p.get("payable"), p.get("total_deducted", 0.0)

    if payable is not None and claimed:
        verb = "Estimated approval" if estimate else "Expected payout"
        headline = f"{verb} <b>{inr(payable)}</b> of {inr(claimed)} {'requested' if estimate else 'claimed'}"
    elif deducted:
        headline = f"<b>{inr(deducted)}</b> would be deducted under the policy"
    else:
        headline = "Here is what the policy says about this claim"
    if verdict == "rejected":
        headline = f"This claim is <b>not payable</b> under the policy"

    segments = ""
    legend = ""
    if claimed and payable is not None and verdict != "rejected":
        base = claimed
        segments += f'<span class="pay" style="width:{max(payable, 0) / base * 100:.2f}%"></span>'
        legend += f'<span><i style="background:var(--ok)"></i>{"Approved" if estimate else "Paid"} {inr(payable)}</span>'
        for d in p.get("deductions", []):
            segments += f'<span class="cut" style="width:{d["amount"] / base * 100:.2f}%"></span>'
            legend += f'<span><i style="background:var(--cut)"></i>{rule_title(d["rule_id"], result)}: {inr(d["amount"])}</span>'
        for label, amt in (("Above the bills", p.get("reduced_to_billed")), ("Above the sum insured", p.get("capped_by_sum_insured"))):
            if amt:
                segments += f'<span class="cap" style="width:{amt / base * 100:.2f}%"></span>'
                legend += f'<span><i style="background:#7A869A"></i>{label}: {inr(amt)}</span>'

    strip = f'<div class="cc-strip">{segments}</div><div class="cc-legend">{legend}</div>' if segments else ""
    figures = ""
    if claimed:
        figures = (f'<div class="cc-figures"><div>{"Requested" if estimate else "Claimed"}<b>{inr(claimed)}</b></div>'
                   f'<div>Deducted<b>{inr(deducted)}</b></div>'
                   f'<div>{"Estimated approval" if estimate else "Payable"}<b>{inr(payable)}</b></div></div>')
    st.markdown(f'<div class="cc-hero"><span class="cc-verdict {tone}">{p.get("verdict_text", "")}</span>'
                f'<p class="cc-headline">{headline}</p>{strip}{figures}</div>', unsafe_allow_html=True)


def render_todo(result: AnalysisResult) -> None:
    mistakes = [c for c in result.document_checks if status_of(c) == "violated"]
    blocking = [f for f in result.findings if status_of(f) == "violated" and not f.estimated_impact
                and f.rule_id in rule_types(result)]
    review = [f for f in result.findings + result.document_checks if status_of(f) == "needs_review"]
    missing = [f for f in result.findings if status_of(f) == "unable_to_verify"
               and f.rule_id not in result.not_applicable_rule_ids]
    if not (mistakes or blocking or review or missing):
        has_cuts = bool((result.payout or {}).get("total_deducted"))
        body = ("Nothing to fix in your documents. The deductions above follow the policy rules; see why below."
                if has_cuts else "Every check that applies to this claim passed.")
        st.markdown(f'<div class="cc-todo ok"><h4>No action needed</h4>{body}</div>', unsafe_allow_html=True)
        return
    items = []
    items += [f"<li><b>Fix:</b> {plain(c.explanation)}</li>" for c in mistakes]
    items += [f"<li><b>{rule_title(f.rule_id, result)}:</b> {explain(f, result)}</li>" for f in blocking]
    items += [f"<li><b>Review:</b> {explain(f, result) if f.rule_id in rule_types(result) or f.rule_id.startswith('AMB') else plain(f.explanation)}</li>" for f in review]
    items += [f"<li><b>Missing information:</b> {rule_title(f.rule_id, result)}. {plain(f.explanation)}</li>" for f in missing]
    tone = "cut" if (mistakes or blocking) else ""
    st.markdown(f'<div class="cc-todo {tone}"><h4>What needs attention</h4><ul>{"".join(items)}</ul></div>',
                unsafe_allow_html=True)


def tab_deductions(result: AnalysisResult) -> None:
    cut = [f for f in result.findings if status_of(f) == "violated" and f.estimated_impact
           and rule_types(result).get(f.rule_id) != "sum_insured"]
    if not cut:
        st.success("No money is deducted under the policy rules.")
    for i, f in enumerate(cut):
        result_row(f, result, f"ded{i}")
        st.markdown("---")
    p = result.payout or {}
    if p.get("reduced_to_billed"):
        st.info(f"{inr(p['reduced_to_billed'])} was claimed above what the bills add up to, so the payout starts "
                f"from the bills total of {inr(p.get('billed'))}.")
    if p.get("capped_by_sum_insured"):
        st.info(f"{inr(p['capped_by_sum_insured'])} is above what is left of the yearly sum insured.")


def tab_mistakes(result: AnalysisResult) -> None:
    if not result.document_checks:
        st.info("There was not enough detail in the documents to cross-check them. Upload the claim form, bills and "
                "discharge summary together to run these checks.")
        return
    order = {"violated": 0, "needs_review": 1, "satisfied": 2}
    for i, c in enumerate(sorted(result.document_checks, key=lambda c: order.get(status_of(c), 3))):
        word, tone = {"violated": ("Mistake found", "cut"), "needs_review": ("Please confirm", "review"),
                      "satisfied": ("No problem", "ok")}.get(status_of(c), (status_of(c), "muted"))
        st.markdown(f"<div class='cc-row'><span><b>{CHECK_LABELS.get(c.rule_id, c.rule_id)}</b></span>"
                    f"<span class='cc-status {tone}'>{word}</span></div>", unsafe_allow_html=True)
        st.write(plain(c.explanation))
        with st.expander("See the details"):
            render_proof(c, f"chk{i}")
        st.markdown("---")


def tab_medical(result: AnalysisResult) -> None:
    facts = {f.name: f for f in result.extracted_facts}
    found = facts.get("medical_conditions_found")
    declared = facts.get("declared_conditions")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Declared by the patient**")
        conds = declared.value.get("conditions", []) if declared and isinstance(declared.value, dict) else None
        st.write(", ".join(conds) if conds else ("None declared" if declared else "Not stated in the documents"))
    with col2:
        st.markdown("**Found in the medical records**")
        if found and isinstance(found.value, list) and found.value:
            for c in found.value:
                inferred = " (inferred from a long-term medicine)" if c.get("inferred_from_medicine") else ""
                st.write(f"{c.get('condition')}{inferred}: {c.get('evidence', '')}")
        else:
            st.write("No existing illness found")
    st.markdown("---")
    related = [f for f in result.findings if rule_types(result).get(f.rule_id) == "pre_existing_disclosure"
               or f.rule_id in {a.ambiguity_id for a in result.ambiguities}]
    related = [f for f in related if f.rule_id not in result.not_applicable_rule_ids]
    if not related:
        st.info("No medical-history rule applies to this claim.")
    for i, f in enumerate(related):
        result_row(f, result, f"med{i}")
        st.markdown("---")


def tab_timeline(result: AnalysisResult) -> None:
    facts = {f.name: f for f in result.extracted_facts}
    hosp = facts.get("hospitalization_details")
    adm = _date(hosp.value.get("admission_date")) if hosp and isinstance(hosp.value, dict) else None
    dis = _date(hosp.value.get("discharge_date")) if hosp and isinstance(hosp.value, dict) else None
    if adm is None:
        st.info("The admission date is not in the documents, so the coverage timeline cannot be drawn.")
        return
    rules = result.rulebook.rules if result.rulebook else []
    pre = next((int(r.parameters.get("window_days", 30)) for r in rules
                if str(getattr(r.rule_type, "value", r.rule_type)) == "pre_hospitalization"), 30)
    post = next((int(r.parameters.get("window_days", 60)) for r in rules
                 if str(getattr(r.rule_type, "value", r.rule_type)) == "post_hospitalization"), 60)
    end = dis or adm
    bands = [{"label": f"{pre} days before admission", "start": adm - timedelta(days=pre), "end": adm, "kind": "window"},
             {"label": "In hospital", "start": adm, "end": end + timedelta(days=1), "kind": "stay"}]
    if dis:
        bands.append({"label": f"{post} days after discharge", "start": dis, "end": dis + timedelta(days=post), "kind": "window"})
    st.caption("Bills inside the shaded windows are covered. Green dots are covered bills, red dots fall outside.")
    points = []
    for name, sign in (("pre_hospitalization_expenses", -1), ("post_hospitalization_expenses", 1)):
        fact = facts.get(name)
        for item in (fact.value if fact and isinstance(fact.value, list) else []):
            d = _date(item.get("date"))
            if d is None:
                continue
            inside = (adm - d).days <= pre if sign < 0 else (dis is not None and (d - dis).days <= post)
            points.append({"date": d, "label": f"{item.get('description')} ({inr(item.get('amount'))})",
                           "covered": "Covered" if inside else "Outside the window"})
    try:
        import altair as alt
        import pandas as pd
        bdf = pd.DataFrame(bands)
        rows = ["Bills"] + [b["label"] for b in bands] if points else [b["label"] for b in bands]
        y_scale = alt.Scale(domain=rows)
        layers = [alt.Chart(bdf).mark_bar(height=26, cornerRadius=3).encode(
            x=alt.X("start:T", title=None), x2="end:T",
            y=alt.Y("label:N", title=None, scale=y_scale, axis=alt.Axis(labelLimit=240)),
            color=alt.Color("kind:N", scale=alt.Scale(domain=["window", "stay"], range=["#CFE3F5", "#172B4D"]), legend=None),
            tooltip=["label:N", "start:T", "end:T"])]
        if points:
            pdf = pd.DataFrame(points)
            pdf["row"] = "Bills"
            layers.append(alt.Chart(pdf).mark_point(filled=True, size=140).encode(
                x="date:T", y=alt.Y("row:N", title=None, scale=y_scale),
                color=alt.Color("covered:N", scale=alt.Scale(domain=["Covered", "Outside the window"],
                                                             range=["#17803D", "#B42318"]), title=None),
                tooltip=["label:N", "date:T", "covered:N"]))
        st.altair_chart(alt.layer(*layers).resolve_scale(color="independent")
                        .properties(height=60 * (len(bands) + (1 if points else 0))),
                        width="stretch")
    except Exception:
        for b in bands:
            st.write(f"{b['label']}: {b['start']} to {b['end']}")
    for pt in sorted(points, key=lambda x: x["date"]):
        st.write(f"{pt['date'].strftime('%d %b %Y')}: {pt['label']} - {pt['covered'].lower()}")


def tab_all_rules(result: AnalysisResult) -> None:
    groups = {"Money deducted or not met": [], "Needs review": [], "Can't check yet": [], "Passed": [], "Not applicable": []}
    for f in result.findings:
        word, _ = display_status(f, result)
        key = {"Money deducted": "Money deducted or not met", "Not met": "Money deducted or not met"}.get(word, word)
        groups.setdefault(key, []).append(f)
    for name, items in groups.items():
        if not items:
            continue
        with st.expander(f"{name} ({len(items)})", expanded=name != "Not applicable"):
            for i, f in enumerate(items):
                result_row(f, result, f"all{name}{i}")
                st.markdown("---")


def tab_needs_input(result: AnalysisResult) -> None:
    open_items = [f for f in result.findings if status_of(f) in ("needs_review", "unable_to_verify")
                  and f.rule_id not in result.not_applicable_rule_ids and f.rule_id in rule_types(result)]
    if open_items:
        st.markdown("**Add missing information** and the rules are checked again straight away.")
    for f in open_items:
        st.markdown(f"**{rule_title(f.rule_id, result)}:** {f.explanation}")
        triggers = {"room_rent_cap": "room_rent_billing", "required_documents": "submitted_documents"}
        fact_name = triggers.get(rule_types(result).get(f.rule_id), "user_clarification")
        answer = st.text_input("Your answer", key=f"input_{f.rule_id}")
        if st.button("Add and re-check", key=f"btn_{f.rule_id}") and answer.strip() and result.rulebook:
            new_fact = ClaimFact(name=fact_name, value=answer.strip().split(",") if "," in answer else answer.strip(),
                                 source=SourceRef(document="user_clarification", page=1,
                                                  quote=f"User clarification: {answer.strip()}"))
            result.extracted_facts = list(result.extracted_facts) + [new_fact]
            result.findings = evaluate(result.rulebook, result.extracted_facts)
            st.session_state.result = result
            st.success("Added. The rules were checked again.")
            st.rerun()
        st.markdown("---")

    if result.ambiguities:
        st.markdown("**Unclear policy wording.** Search official guidance to help the reviewer decide. "
                    "Search results are shown separately and never change the policy result.")
        tavily_ready = settings.is_set("TAVILY_API_KEY")
        for amb in result.ambiguities:
            st.write(f"{amb.section}: {amb.description}")
            query = st.text_input("Search for", value=f"IRDAI health insurance regulations {amb.issue}",
                                  key=f"q_{amb.ambiguity_id}")
            if st.button("Search official guidance (Tavily)", key=f"tavily_btn_{amb.ambiguity_id}", disabled=not tavily_ready):
                with st.spinner("Searching..."):
                    st.session_state.tavily_results[amb.ambiguity_id] = tavily_client.search(query=query)
            if not tavily_ready:
                st.caption("Add TAVILY_API_KEY to enable the search.")
            res = st.session_state.tavily_results.get(amb.ambiguity_id)
            if res and res.success:
                for item in res.results:
                    st.markdown(f"- [{item.title}]({item.url}): {item.snippet}")
            elif res:
                st.warning(f"Search did not work: {res.error}")
    if not open_items and not result.ambiguities:
        st.success("Nothing needs your input.")


def tab_report(result: AnalysisResult) -> None:
    guidance = [{"query": r.query, "url": i.url, "title": i.title, "snippet": i.snippet}
                for r in st.session_state.tavily_results.values() if r.success for i in r.results]
    md = generate_markdown_report(policy_name="synthetic_policy.pdf", claim_names=list(st.session_state.claim_pdfs),
                                  findings=result.findings, unresolved_items=result.unresolved_items, mode=result.mode,
                                  claim_id=st.session_state.get("selected_case") or "uploaded_claim",
                                  policy_id=result.policy_number or result.policy_id, external_guidance=guidance)
    p = result.payout or {}
    summary = ["## Payout summary", "",
               f"- Claim type: {result.claim_type}",
               f"- Result: {p.get('verdict_text', '-')}",
               f"- {'Requested' if p.get('is_estimate') else 'Claimed'}: {inr(p.get('claimed'))}",
               f"- Deducted under the policy: {inr(p.get('total_deducted'))}",
               f"- {'Estimated approval' if p.get('is_estimate') else 'Payable'}: {inr(p.get('payable'))}", "",
               "## Document checks", ""]
    summary += [f"- {CHECK_LABELS.get(c.rule_id, c.rule_id)}: {status_of(c)}. {c.explanation}" for c in result.document_checks]
    full = "\n".join(summary) + "\n\n" + md
    st.download_button("Download the report", data=full, file_name="claimcheck_report.md", mime="text/markdown")
    st.markdown(full)


def render_how_checked(result: AnalysisResult, cfg) -> None:
    with st.expander("How this was checked"):
        if result.mode == "LIVE":
            st.write(f"Policy read by `{cfg.model_reasoning}` and documents read by `{cfg.model_fast}`, both NVIDIA "
                     f"Nemotron models on Nebius Token Factory (`{cfg.endpoint_host}`).")
        else:
            st.write("Demo data: the facts come from the case's answer key, so no AI was used for this run.")
        st.write("Every policy rule and every fact cites a page and a quote, checked word for word against the PDF. "
                 "All amounts are calculated by ordinary code, not by the AI.")
        t = result.timings
        if t:
            st.caption("Time taken: " + ", ".join(f"{k.replace('_sec', '')} {v:.1f}s" for k, v in t.items()))
        if result.ocr_warnings:
            for w in result.ocr_warnings:
                st.caption(w)


# --------------------------------------------------------------------------- page
def main() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    cfg = inspect_configuration()
    for key, default in (("result", None), ("policy_bytes", b""), ("claim_pdfs", {}), ("tavily_results", {}),
                         ("selected_case", None), ("compilation", None), ("approved_rule_ids", None)):
        st.session_state.setdefault(key, default)

    with st.sidebar:
        st.markdown('<p class="cc-brand">ClaimCheck</p><p class="cc-sub">Health insurance claim checker</p>',
                    unsafe_allow_html=True)
        st.markdown("### 1. What kind of claim?")
        claim_choice = st.radio("Claim type", ["Reimbursement (I already paid)", "Cashless pre-approval (before treatment)"],
                                label_visibility="collapsed")
        claim_type = "cashless" if claim_choice.startswith("Cashless") else "reimbursement"

        st.markdown("### 2. Your documents")
        source = st.radio("Documents", ["Use a demo case", "Upload my documents"], label_visibility="collapsed")
        policy_bytes = DEFAULT_POLICY_PATH.read_bytes() if DEFAULT_POLICY_PATH.exists() else b""
        claim_files: Dict[str, bytes] = {}
        case_id: Optional[str] = None
        if source == "Use a demo case":
            cases = [c for c in demo_cases() if c["claim_type"] == claim_type]
            options = [c["id"] for c in cases] + ([k for k in PACKET_CATALOG] if claim_type == "reimbursement" else [])
            labels = {c["id"]: c["label"] for c in cases} | {k: f"Test packet {k[-2:]}: {v}" for k, v in PACKET_CATALOG.items()}
            case_id = st.selectbox("Demo case", options, format_func=lambda k: labels.get(k, k))
            chosen = next((c for c in cases if c["id"] == case_id), None)
            if chosen:
                st.caption(chosen["story"])
                claim_files = load_case_files(chosen["folder"])
            else:
                claim_files = load_case_files(PACKETS_DIR / case_id)
            st.caption(f"{len(claim_files)} documents: " + ", ".join(claim_files))
        else:
            uploads = st.file_uploader("Claim form, bills, prescriptions, reports, discharge summary, estimate...",
                                       type=["pdf"], accept_multiple_files=True)
            for uf in uploads or []:
                claim_files[uf.name] = uf.read()
            own_policy = st.file_uploader("Your policy document (optional)", type=["pdf"])
            if own_policy:
                policy_bytes = own_policy.read()
            else:
                st.caption("Using the sample policy (Aura Health Assure, Plan B).")

        st.markdown("### 3. How to check")
        live_label = "Live AI (NVIDIA Nemotron)" if cfg.is_live_ready else "Live AI (add API keys to enable)"
        how = st.radio("Check mode", ["Demo data (no AI)", live_label], label_visibility="collapsed")
        mode = "live" if how == "Live AI (NVIDIA Nemotron)" else "mock"
        if how.startswith("Live AI (add"):
            st.caption("Live mode needs: " + ", ".join(cfg.missing_variables))
        if mode == "mock" and source == "Upload my documents":
            st.caption("Demo data only works with the demo cases. Choose Live AI to check your own documents.")

        if mode == "live" and policy_bytes:
            key = hash(policy_bytes)
            if st.session_state.get("compiled_policy_key") != key:
                st.session_state.compilation = None
                st.session_state.approved_rule_ids = None
            if st.button("Read the policy with AI", width="stretch"):
                with st.spinner("NVIDIA Nemotron is reading the policy..."):
                    try:
                        st.session_state.compilation = compile_policy(policy_bytes)
                        st.session_state.compiled_policy_key = key
                        st.session_state.approved_rule_ids = None
                    except Exception as exc:
                        st.error(f"Could not read the policy: {type(exc).__name__}: {exc}")

        run = st.button("Check my claim", type="primary", width="stretch")

    if run:
        if not claim_files:
            st.error("Add at least one document, or pick a demo case.")
        elif mode == "mock" and source == "Upload my documents":
            st.error("Demo data cannot read uploaded documents. Switch to Live AI in step 3.")
        else:
            with st.spinner("Checking the claim against the policy..."):
                st.session_state.policy_bytes = policy_bytes
                st.session_state.claim_pdfs = claim_files
                st.session_state.selected_case = case_id
                st.session_state.tavily_results = {}
                st.session_state.result = analyze(
                    policy_pdf_bytes=policy_bytes, claim_pdfs=claim_files, mode=mode,
                    packet_id=case_id if mode == "mock" else None, claim_type=claim_type,
                    compilation=st.session_state.compilation if mode == "live" else None,
                    approved_rule_ids=st.session_state.approved_rule_ids if mode == "live" else None)

    if mode == "live":
        render_rule_approval()

    result: Optional[AnalysisResult] = st.session_state.result
    if result is None:
        st.markdown("## Check a health insurance claim before you submit it")
        st.write("Pick the kind of claim, add the documents, and ClaimCheck tells you how much the policy is expected "
                 "to pay, what is deducted and why, which mistakes to fix, and which illnesses in the records were not "
                 "declared. Every answer quotes the policy page it comes from.")
        return

    if result.errors and not result.findings:
        st.error("The claim could not be checked.")
        for err in result.errors:
            st.caption(plain(err))
        st.write("Try **Check my claim** again. If it keeps failing, check the API key and model names in `.env`, "
                 "or switch to Demo data to see how the results look.")
        render_how_checked(result, inspect_configuration())
        return
    for err in result.errors:
        st.error(err)
    render_hero(result)
    render_todo(result)
    tabs = st.tabs(["Money deducted", "Document mistakes", "Medical history", "Coverage timeline",
                    "All policy rules", "Needs your input", "Report"])
    with tabs[0]:
        tab_deductions(result)
    with tabs[1]:
        tab_mistakes(result)
    with tabs[2]:
        tab_medical(result)
    with tabs[3]:
        tab_timeline(result)
    with tabs[4]:
        tab_all_rules(result)
    with tabs[5]:
        tab_needs_input(result)
    with tabs[6]:
        tab_report(result)
    render_how_checked(result, cfg)


if __name__ == "__main__":
    main()
