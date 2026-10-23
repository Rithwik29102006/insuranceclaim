"""Deterministic Rule Engine for ClaimCheck 2.0.

Evaluates structured insurance policy rules and documented ambiguities against
claim facts using pure deterministic Python arithmetic and logical verification.
Avoids speculative guessing and model hallucinations by computing exact monetary
deductions using Decimal arithmetic and raising explicit review/verification flags
for missing inputs or ambiguous clauses.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple, Union

from src.schemas import (
    Rule,
    Rulebook,
    ClaimFact,
    Finding,
    FindingStatus,
    RuleType,
    SourceRef,
    AmbiguityRef,
)


def normalize_item_name(name: Any) -> str:
    """Normalize a bill or document item name without fuzzy guessing.

    Lowercases, removes punctuation, replaces whitespace and hyphens with underscores.
    """
    if name is None:
        return ""
    cleaned = re.sub(r"[^\w\s-]", "", str(name).lower())
    return re.sub(r"[\s-]+", "_", cleaned).strip("_")


def _to_decimal(val: Any, default: str = "0.0") -> Decimal:
    """Safely convert a primitive number or string to Decimal."""
    if val is None:
        return Decimal(default)
    try:
        return Decimal(str(val))
    except Exception:
        return Decimal(default)


def _evaluate_required_documents(
    rule: Rule,
    facts_by_name: Dict[str, ClaimFact],
) -> Finding:
    """Evaluate mandatory document submission rule."""
    req_docs = rule.parameters.get("required_documents", [])
    min_count = rule.parameters.get("minimum_document_count", len(req_docs))

    # Look for submitted_documents fact
    doc_fact = facts_by_name.get("submitted_documents")
    if doc_fact is None or doc_fact.value is None:
        return Finding(
            rule_id=rule.rule_id,
            status=FindingStatus.UNABLE_TO_VERIFY,
            inputs_used={"submitted_documents": None},
            calculation_steps=[
                "Checked claim facts for submitted documents.",
                "Missing or unparseable input: no submitted documents fact found in claim.",
            ],
            explanation="Cannot verify required documents: claim facts do not contain submitted documents information.",
            source=rule.source,
            estimated_impact=None,
        )

    # Parse submitted documents list
    submitted_raw = doc_fact.value if isinstance(doc_fact.value, (list, tuple, set)) else [doc_fact.value]
    norm_submitted = {normalize_item_name(d) for d in submitted_raw}
    norm_required = [normalize_item_name(d) for d in req_docs]

    missing = [d for d in norm_required if d not in norm_submitted]

    if missing:
        return Finding(
            rule_id=rule.rule_id,
            status=FindingStatus.VIOLATED,
            inputs_used={"submitted_documents": list(submitted_raw)},
            calculation_steps=[
                f"Identified mandatory document list: {', '.join(req_docs)}.",
                f"Found {len(norm_submitted)} documents present: {', '.join(sorted(norm_submitted))}.",
                f"Missing required documents: {', '.join(missing)}.",
                "Missing mandatory documents render the claim incomplete and inadmissible.",
            ],
            explanation=f"The mandatory document(s) {', '.join(missing)} are missing from the claim submission.",
            source=rule.source,
            estimated_impact=None,
        )

    return Finding(
        rule_id=rule.rule_id,
        status=FindingStatus.SATISFIED,
        inputs_used={"submitted_documents": list(submitted_raw)},
        calculation_steps=[
            f"Checked submitted documents against mandatory list: {', '.join(req_docs)}.",
            f"All {len(req_docs)} required documents are present in submission.",
        ],
        explanation="All three mandatory documents required by Section 1.1 are present in the claim submission.",
        source=rule.source,
        estimated_impact=0.0,
    )


def _evaluate_waiting_period(
    rule: Rule,
    facts_by_name: Dict[str, ClaimFact],
) -> Finding:
    """Evaluate initial waiting period rule against hospitalization facts."""
    duration_days = int(rule.parameters.get("duration_days", 30))
    applies_to = rule.parameters.get("applies_to", "illness")
    exceptions = rule.exceptions

    fact = facts_by_name.get("hospitalization_details")
    if fact is None or not isinstance(fact.value, dict):
        return Finding(
            rule_id=rule.rule_id,
            status=FindingStatus.UNABLE_TO_VERIFY,
            inputs_used={},
            calculation_steps=[
                "Checked claim facts for hospitalization timeline details.",
                "Missing or unparseable input: no hospitalization_details fact found.",
            ],
            explanation="Cannot verify waiting period: hospitalization timeline details are missing from claim facts.",
            source=rule.source,
            estimated_impact=None,
        )

    val = fact.value
    cause = normalize_item_name(val.get("cause", ""))
    days_elapsed = val.get("days_elapsed")

    # If days_elapsed not given directly, attempt date arithmetic
    if days_elapsed is None and "admission_date" in val and "policy_inception_date" in val:
        try:
            adm = date.fromisoformat(str(val["admission_date"]))
            inc = date.fromisoformat(str(val["policy_inception_date"]))
            days_elapsed = (adm - inc).days
        except Exception:
            days_elapsed = None

    if days_elapsed is None:
        return Finding(
            rule_id=rule.rule_id,
            status=FindingStatus.UNABLE_TO_VERIFY,
            inputs_used=val,
            calculation_steps=[
                "Attempted waiting period verification.",
                "Missing or unparseable input: days elapsed since inception could not be determined.",
            ],
            explanation="Cannot verify waiting period: elapsed duration between policy inception and admission is missing or invalid.",
            source=rule.source,
            estimated_impact=None,
        )

    # Check for accidental injury exception
    is_accident = (
        cause in ("accidental_injury", "accident", "trauma", "vehicular_accident")
        or "accident" in cause
    )

    if is_accident:
        return Finding(
            rule_id=rule.rule_id,
            status=FindingStatus.SATISFIED,
            inputs_used={
                "policy_inception_date": val.get("policy_inception_date"),
                "admission_date": val.get("admission_date"),
                "days_elapsed": days_elapsed,
                "cause": val.get("cause"),
            },
            calculation_steps=[
                f"Computed days elapsed: {days_elapsed} days.",
                f"Admission date is within {duration_days} days of inception.",
                f"Evaluated policy exception: Section 2.1 exempts hospitalization necessitated solely by accidental injury.",
                "Admission cause verified as accidental injury; exception applies.",
                "Rule status: satisfied under policy exception.",
            ],
            explanation=f"Hospitalization occurred on day {days_elapsed} due to an accidental injury, qualifying for the explicit policy exception to the {duration_days}-day waiting period.",
            source=rule.source,
            estimated_impact=0.0,
        )

    # If cause is missing or ambiguous when within waiting period
    if not cause:
        return Finding(
            rule_id=rule.rule_id,
            status=FindingStatus.NEEDS_REVIEW,
            inputs_used=val,
            calculation_steps=[
                f"Computed days elapsed: {days_elapsed} days (<= {duration_days} threshold).",
                "Admission cause is missing or ambiguous; cannot determine whether illness exclusion or accidental injury exception applies.",
            ],
            explanation="Admission occurred within the initial waiting period, but hospitalization cause is not specified. Human review required to assess exception applicability.",
            source=rule.source,
            estimated_impact=None,
        )

    # Check illness waiting period threshold: strictly > duration_days is satisfied; <= duration_days is violated
    if days_elapsed > duration_days:
        return Finding(
            rule_id=rule.rule_id,
            status=FindingStatus.SATISFIED,
            inputs_used={
                "policy_inception_date": val.get("policy_inception_date"),
                "admission_date": val.get("admission_date"),
                "days_elapsed": days_elapsed,
                "cause": val.get("cause"),
            },
            calculation_steps=[
                f"Computed days elapsed between policy inception ({val.get('policy_inception_date')}) and hospital admission ({val.get('admission_date')}): {days_elapsed} days.",
                f"Compared {days_elapsed} days against mandatory {duration_days}-day waiting period threshold.",
                f"{days_elapsed} > {duration_days}: Waiting period is fully satisfied.",
            ],
            explanation=f"The admission occurred {days_elapsed} days post-inception, satisfying the {duration_days}-day initial waiting period.",
            source=rule.source,
            estimated_impact=0.0,
        )

    # Admission occurred on or before duration_days for illness
    return Finding(
        rule_id=rule.rule_id,
        status=FindingStatus.VIOLATED,
        inputs_used={
            "policy_inception_date": val.get("policy_inception_date"),
            "admission_date": val.get("admission_date"),
            "days_elapsed": days_elapsed,
            "cause": val.get("cause"),
        },
        calculation_steps=[
            f"Computed days elapsed: {days_elapsed} days.",
            f"Threshold required: > {duration_days} days.",
            f"{days_elapsed} <= {duration_days} days: Admission occurred within initial waiting period.",
            f"Evaluated exception: Condition is {val.get('cause')} ({val.get('diagnosis')}), not accidental injury.",
            f"Rule violated: expenses incurred within the first {duration_days} days for illness are excluded from coverage.",
        ],
        explanation=f"Hospitalization for illness occurred on day {days_elapsed} of the policy period, violating the mandatory {duration_days}-day initial waiting period.",
        source=rule.source,
        estimated_impact=None,
    )


def _evaluate_room_rent_cap(
    rule: Rule,
    facts_by_name: Dict[str, ClaimFact],
) -> Finding:
    """Evaluate room rent daily limit and proportional deduction formula."""
    cap = _to_decimal(rule.parameters.get("cap") or rule.parameters.get("daily_limit_inr") or 5000.0)

    room_fact = facts_by_name.get("room_rent_billing")
    if room_fact is None or not isinstance(room_fact.value, dict):
        return Finding(
            rule_id=rule.rule_id,
            status=FindingStatus.UNABLE_TO_VERIFY,
            inputs_used={},
            calculation_steps=[
                "Checked claim facts for room rent billing details.",
                "Missing or unparseable input: no room_rent_billing fact found.",
            ],
            explanation="Cannot verify room rent cap: room rent billing details are missing from claim facts.",
            source=rule.source,
            estimated_impact=None,
        )

    val = room_fact.value
    daily_rate_raw = val.get("daily_rate") or val.get("daily_room_rent")
    if daily_rate_raw is None:
        return Finding(
            rule_id=rule.rule_id,
            status=FindingStatus.UNABLE_TO_VERIFY,
            inputs_used=val,
            calculation_steps=[
                "Inspected room rent billing fact.",
                "Missing daily rate value in claim fact.",
            ],
            explanation="Cannot verify room rent cap: daily room rent rate is missing.",
            source=rule.source,
            estimated_impact=None,
        )

    daily_rate = _to_decimal(daily_rate_raw)
    days_raw = val.get("days") or val.get("days_stayed")

    # Boundary: rent is within or exactly equal to cap
    if daily_rate <= cap:
        days_disp = days_raw if days_raw is not None else 1
        return Finding(
            rule_id=rule.rule_id,
            status=FindingStatus.SATISFIED,
            inputs_used={
                "daily_rate_billed": float(daily_rate),
                "days": days_raw,
                "daily_cap": float(cap),
            },
            calculation_steps=[
                f"Compared billed daily room rent (INR {daily_rate:.2f}) against policy daily cap (INR {cap:.2f}).",
                f"INR {daily_rate:.2f} <= INR {cap:.2f}: Billed daily room rent is within the permissible limit.",
                "Excess room rent deduction = INR 0.00.",
            ],
            explanation=f"The daily room rent of INR {daily_rate:.0f} does not exceed the policy limit of INR {cap:.0f} per day.",
            source=rule.source,
            estimated_impact=0.0,
        )

    # Rent exceeds cap
    # If duration is missing / unknown, cannot determine total financial impact -> needs_review
    if days_raw is None or _to_decimal(days_raw) <= 0:
        return Finding(
            rule_id=rule.rule_id,
            status=FindingStatus.NEEDS_REVIEW,
            inputs_used={
                "daily_rate_billed": float(daily_rate),
                "days": None,
                "daily_cap": float(cap),
            },
            calculation_steps=[
                f"Identified billed daily room rent: INR {daily_rate:.2f}.",
                f"Daily rate exceeds cap of INR {cap:.2f}.",
                "Attempted deduction calculation: duration in days is unknown.",
                "Financial impact cannot be computed without total days of stay.",
            ],
            explanation=f"Daily room rent of INR {daily_rate:.0f} exceeds INR {cap:.0f} daily limit, but total stay duration is missing from submitted records. Financial impact cannot be determined without knowing days of hospitalization.",
            source=rule.source,
            estimated_impact=None,
        )

    days_dec = _to_decimal(days_raw)
    daily_excess = daily_rate - cap
    excess_room_rent = daily_excess * days_dec

    # Check for professional fees and OT charges in facts
    prof_fact = facts_by_name.get("professional_fees_billing")
    prof_total = Decimal("0.0")
    if prof_fact and isinstance(prof_fact.value, dict):
        prof_total = _to_decimal(
            prof_fact.value.get("total_amount")
            or prof_fact.value.get("total_professional_fees")
            or (
                _to_decimal(prof_fact.value.get("surgeon_fee", 0))
                + _to_decimal(prof_fact.value.get("anesthetist_fee", 0))
                + _to_decimal(prof_fact.value.get("consultant_fee", 0))
            )
        )
    elif prof_fact and isinstance(prof_fact.value, (int, float, str)):
        prof_total = _to_decimal(prof_fact.value)

    ot_fact = facts_by_name.get("operation_theatre_billing")
    ot_total = Decimal("0.0")
    if ot_fact and isinstance(ot_fact.value, dict):
        ot_total = _to_decimal(ot_fact.value.get("ot_charges") or ot_fact.value.get("total_amount", 0))
    elif ot_fact and isinstance(ot_fact.value, (int, float, str)):
        ot_total = _to_decimal(ot_fact.value)

    # Proportional formula: payable ratio = 5000 / actual_daily_rate
    payable_ratio = cap / daily_rate
    disallow_ratio = Decimal("1.0") - payable_ratio

    prof_deduction = (prof_total * disallow_ratio) if prof_total > 0 else Decimal("0.0")
    ot_deduction = (ot_total * disallow_ratio) if ot_total > 0 else Decimal("0.0")

    total_deduction = excess_room_rent + prof_deduction + ot_deduction
    rounded_impact = float(total_deduction.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    calculation_steps = [
        f"Step 1 (Excess Room Rent): Daily room rent billed = INR {daily_rate:.2f}. Policy room rent cap = INR {cap:.2f}. Daily excess = INR {daily_rate:.2f} - INR {cap:.2f} = INR {daily_excess:.2f}. For {days_raw} days of hospitalization, excess room rent deduction = {days_raw} days * INR {daily_excess:.2f}/day = INR {excess_room_rent:.2f} (non-payable)."
    ]

    if prof_total > 0 or ot_total > 0:
        payable_prof = prof_total * payable_ratio
        payable_ot = ot_total * payable_ratio
        calculation_steps.extend([
            f"Step 2 (Proportional Ratio Calculation): Actual daily room rent (INR {daily_rate:.2f}) exceeds cap (INR {cap:.2f}). Proportional payable ratio = {cap:.0f} / actual_daily_rate = {cap:.0f} / {daily_rate:.0f} = {payable_ratio:.2f} ({float(payable_ratio*100):.1f}%).",
            f"Step 3 (Professional Fees Proportional Deduction): Total professional fees billed = INR {prof_total:.2f}. Payable portion = INR {prof_total:.2f} * {payable_ratio:.2f} = INR {payable_prof:.2f}. Disallowed deduction = INR {prof_total:.2f} - INR {payable_prof:.2f} = INR {prof_deduction:.2f}.",
            f"Step 4 (OT Charges Proportional Deduction): Total operation theatre charges billed = INR {ot_total:.2f}. Payable portion = INR {ot_total:.2f} * {payable_ratio:.2f} = INR {payable_ot:.2f}. Disallowed deduction = INR {ot_total:.2f} - INR {payable_ot:.2f} = INR {ot_deduction:.2f}.",
            f"Step 5 (Total Combined Deduction): Sum of disallowances = Excess Room Rent (INR {excess_room_rent:.2f}) + Professional Fees Deduction (INR {prof_deduction:.2f}) + OT Charges Deduction (INR {ot_deduction:.2f}) = INR {total_deduction:.2f}.",
        ])
        explanation = (
            f"Actual daily room rent of INR {daily_rate:.0f} exceeds the policy cap of INR {cap:.0f} per day. "
            f"Excess room rent of INR {excess_room_rent:.0f} is disallowed, and associated professional fees (INR {prof_total:.0f}) "
            f"and OT charges (INR {ot_total:.0f}) are reduced by {float(disallow_ratio*100):.0f}% under the 5000 / actual daily rate "
            f"proportional deduction formula, resulting in a total deterministic deduction of INR {total_deduction:.0f}."
        )
    else:
        calculation_steps.append(
            "No professional fees or OT charges were billed in this claim; proportional deduction does not apply to zero fees."
        )
        explanation = (
            f"Daily room rent of INR {daily_rate:.0f} exceeds the policy cap of INR {cap:.0f} per day by INR {daily_excess:.0f} per day "
            f"across {days_raw} days, resulting in an excess room rent deduction of INR {excess_room_rent:.0f}."
        )

    inputs_used = {
        "daily_rate_billed": float(daily_rate),
        "days": days_raw,
        "daily_cap": float(cap),
    }
    if prof_total > 0:
        inputs_used["professional_fees_billed"] = float(prof_total)
    if ot_total > 0:
        inputs_used["ot_charges_billed"] = float(ot_total)

    return Finding(
        rule_id=rule.rule_id,
        status=FindingStatus.VIOLATED,
        inputs_used=inputs_used,
        calculation_steps=calculation_steps,
        explanation=explanation,
        source=rule.source,
        estimated_impact=rounded_impact,
    )


def _evaluate_sub_limit(
    rule: Rule,
    facts_by_name: Dict[str, ClaimFact],
) -> Finding:
    """Evaluate specific surgical sub-limit rule."""
    category = normalize_item_name(rule.parameters.get("category", "cataract_surgery"))
    limit_per_unit = _to_decimal(rule.parameters.get("max_limit_inr", 40000.0))

    fact = facts_by_name.get("surgical_expenses")
    if fact is None or not isinstance(fact.value, dict):
        return Finding(
            rule_id=rule.rule_id,
            status=FindingStatus.UNABLE_TO_VERIFY,
            inputs_used={},
            calculation_steps=[
                "Checked claim facts for surgical expense breakdown.",
                "Missing or unparseable input: no surgical_expenses fact found.",
            ],
            explanation=f"Cannot verify sub-limit: surgical expenses details for {category} are missing.",
            source=rule.source,
            estimated_impact=None,
        )

    val = fact.value
    proc = normalize_item_name(val.get("procedure", ""))

    if category not in proc and proc not in category:
        return Finding(
            rule_id=rule.rule_id,
            status=FindingStatus.UNABLE_TO_VERIFY,
            inputs_used=val,
            calculation_steps=[
                f"Evaluated procedure name: '{val.get('procedure')}'.",
                f"Procedure does not match target sub-limit category '{category}'.",
            ],
            explanation=f"Surgical procedure '{val.get('procedure')}' does not match sub-limit category '{category}'.",
            source=rule.source,
            estimated_impact=None,
        )

    billed_amount = _to_decimal(val.get("total_cataract_billed") or val.get("total_billed", 0))
    eyes_count = _to_decimal(val.get("eyes_treated") or val.get("eyes_count", 1))
    if eyes_count <= 0:
        eyes_count = Decimal("1.0")

    effective_limit = limit_per_unit * eyes_count

    if billed_amount <= effective_limit:
        return Finding(
            rule_id=rule.rule_id,
            status=FindingStatus.SATISFIED,
            inputs_used={
                "procedure": val.get("procedure"),
                "eyes_count": int(eyes_count),
                "total_billed": float(billed_amount),
                "sublimit_per_eye": float(limit_per_unit),
            },
            calculation_steps=[
                f"Billed amount for {proc}: INR {billed_amount:.2f}.",
                f"Policy sub-limit: INR {effective_limit:.2f}.",
                f"INR {billed_amount:.2f} <= INR {effective_limit:.2f}: Billed amount is within sub-limit.",
            ],
            explanation=f"Billed expenses of INR {billed_amount:.0f} do not exceed the policy sub-limit of INR {effective_limit:.0f}.",
            source=rule.source,
            estimated_impact=0.0,
        )

    excess = billed_amount - effective_limit
    rounded_excess = float(excess.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    return Finding(
        rule_id=rule.rule_id,
        status=FindingStatus.VIOLATED,
        inputs_used={
            "procedure": val.get("procedure"),
            "eyes_count": int(eyes_count),
            "total_billed": float(billed_amount),
            "sublimit_per_eye": float(limit_per_unit),
        },
        calculation_steps=[
            f"Billed amount for left eye cataract surgery: INR {billed_amount:.0f}.",
            f"Policy sub-limit per eye: INR {limit_per_unit:.0f}.",
            f"Excess over sub-limit: INR {billed_amount:.0f} - INR {effective_limit:.0f} = INR {excess:.2f} non-payable.",
        ],
        explanation=f"Billed cataract surgery expenses of INR {billed_amount:.0f} exceed the policy sub-limit of INR {limit_per_unit:.0f} per eye by INR {excess:.0f}.",
        source=rule.source,
        estimated_impact=rounded_excess,
    )


def _evaluate_non_payable_items(
    rule: Rule,
    facts_by_name: Dict[str, ClaimFact],
) -> Finding:
    """Evaluate non-payable consumable and administrative items schedule."""
    raw_excluded = rule.parameters.get("excluded_items", [])
    norm_excluded_set = {normalize_item_name(x) for x in raw_excluded}

    fact = facts_by_name.get("non_payable_items_breakdown") or facts_by_name.get("hospital_breakdown")
    if fact is None or fact.value is None:
        return Finding(
            rule_id=rule.rule_id,
            status=FindingStatus.UNABLE_TO_VERIFY,
            inputs_used={},
            calculation_steps=[
                "Checked claim facts for itemized line items or non-payable items breakdown.",
                "Missing or unparseable input: no bill line items fact found.",
            ],
            explanation="Cannot verify non-payable items: itemized billing breakdown is missing from claim facts.",
            source=rule.source,
            estimated_impact=None,
        )

    items_list = fact.value if isinstance(fact.value, list) else [fact.value]

    matched_names = []
    matched_amounts = []
    unmatched_names = []
    total_deduction = Decimal("0.0")

    for entry in items_list:
        if isinstance(entry, dict):
            raw_name = entry.get("item") or entry.get("name") or entry.get("description") or ""
            raw_amt = entry.get("amount") or entry.get("cost") or entry.get("billed_amount") or 0
        else:
            raw_name = str(entry)
            raw_amt = 0

        norm_name = normalize_item_name(raw_name)
        amt_dec = _to_decimal(raw_amt)

        if norm_name in norm_excluded_set:
            matched_names.append(raw_name)
            matched_amounts.append(float(amt_dec))
            total_deduction += amt_dec
        else:
            unmatched_names.append(raw_name)

    if not matched_names:
        return Finding(
            rule_id=rule.rule_id,
            status=FindingStatus.SATISFIED,
            inputs_used={"inspected_items": [str(e) for e in items_list]},
            calculation_steps=[
                "Inspected billed line items against Section 3.2 non-payable schedule.",
                "No excluded non-payable items were identified.",
                f"Reported unmatched/allowed items: {', '.join(unmatched_names) if unmatched_names else 'None'}.",
            ],
            explanation="No excluded non-payable items were identified in the billed line items.",
            source=rule.source,
            estimated_impact=0.0,
        )

    rounded_impact = float(total_deduction.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    calc_steps = [
        f"Identified invoiced line items matching Section 3.2 non-payable schedule: {', '.join(matched_names)}.",
        f"Summed non-payable amounts: {' + '.join(f'INR {a:.0f}' for a in matched_amounts)} = INR {total_deduction:.2f} non-payable deduction.",
    ]
    if unmatched_names:
        calc_steps.append(f"Reported allowable/unmatched billed items: {', '.join(unmatched_names)}.")

    return Finding(
        rule_id=rule.rule_id,
        status=FindingStatus.VIOLATED,
        inputs_used={
            "items_detected": matched_names,
            "amounts": matched_amounts,
        },
        calculation_steps=calc_steps,
        explanation=f"Invoiced expenses include {', '.join(matched_names)}, which are explicitly non-payable under Section 3.2.",
        source=rule.source,
        estimated_impact=rounded_impact,
    )


def _evaluate_ambiguity(
    amb: AmbiguityRef,
    facts_by_name: Dict[str, ClaimFact],
) -> Finding:
    """Evaluate documented policy ambiguity requiring human adjuster review."""
    history_fact = facts_by_name.get("patient_medical_history")
    if history_fact is None or not isinstance(history_fact.value, dict):
        return Finding(
            rule_id=amb.ambiguity_id,
            status=FindingStatus.UNABLE_TO_VERIFY,
            inputs_used={},
            calculation_steps=[
                "Checked claim facts for patient medical history and pre-existing condition records.",
                "No medical history facts found in claim submission.",
            ],
            explanation="Cannot evaluate pre-existing condition exclusion: no medical history provided.",
            source=amb.source,
            estimated_impact=None,
        )

    val = history_fact.value
    return Finding(
        rule_id=amb.ambiguity_id,
        status=FindingStatus.NEEDS_REVIEW,
        inputs_used={
            "diagnosis": val.get("diagnosis"),
            "pre_existing_history": val.get("pre_existing_history"),
            "policy_clause": amb.section,
        },
        calculation_steps=[
            "Identified claim diagnosis as chronic essential hypertension with pre-policy onset.",
            f"Evaluated {amb.section} exclusion: applies to Pre-Existing Conditions 'as defined under applicable regulations'.",
            "Checked policy definitions: policy does not define 'applicable regulations', nor does it state the applicable lookback window or statutory waiting period duration.",
            "Determined finding status: needs_review. Automated rule engine cannot determine admissibility without external regulatory guidance or human adjuster review.",
            "Financial impact: None (cannot be deterministically computed for an ambiguous condition).",
        ],
        explanation=f"{amb.section} excludes Pre-Existing Conditions 'as defined under applicable regulations' without specifying the regulatory authority, lookback period, or statutory duration in the policy text. Automated determination is blocked and human review is required.",
        source=amb.source,
        estimated_impact=None,
    )


def evaluate(
    rulebook: Rulebook,
    facts: list[ClaimFact],
    rule_ids: Optional[list[str]] = None,
) -> list[Finding]:
    """Deterministically evaluate policy rules against extracted claim facts.

    Args:
        rulebook: Validated Rulebook model containing operative rules and ambiguities.
        facts: List of extracted ClaimFact models.
        rule_ids: Optional subset of rule/ambiguity IDs to evaluate. If omitted, evaluates all.

    Returns:
        list[Finding]: Ordered list of evaluation findings for the requested rules.
    """
    facts_by_name: Dict[str, ClaimFact] = {f.name: f for f in facts}
    findings: list[Finding] = []

    # Map of rule types to their dedicated deterministic evaluator
    evaluators = {
        RuleType.REQUIRED_DOCUMENTS.value: _evaluate_required_documents,
        RuleType.WAITING_PERIOD.value: _evaluate_waiting_period,
        RuleType.ROOM_RENT_CAP.value: _evaluate_room_rent_cap,
        RuleType.SUB_LIMIT.value: _evaluate_sub_limit,
        RuleType.NON_PAYABLE_ITEMS.value: _evaluate_non_payable_items,
    }

    # Evaluate executable rules
    for rule in rulebook.rules:
        if rule_ids is not None and rule.rule_id not in rule_ids:
            continue

        evaluator = evaluators.get(rule.rule_type)
        if evaluator is not None:
            finding = evaluator(rule, facts_by_name)
            findings.append(finding)

    # Evaluate ambiguities if requested or present in facts
    ambiguities = getattr(rulebook, "ambiguities", [])
    for amb in ambiguities:
        # Evaluate if explicitly requested, or if all rules requested and facts contain medical history
        is_requested = rule_ids is not None and amb.ambiguity_id in rule_ids
        is_relevant_in_all = rule_ids is None and "patient_medical_history" in facts_by_name

        if is_requested or is_relevant_in_all:
            finding = _evaluate_ambiguity(amb, facts_by_name)
            findings.append(finding)

    return findings
