"""Independent ground-truth calculator and packet specifications for the ClaimCheck benchmark.

This module computes ground-truth facts and expected findings directly and
deterministically without importing or calling `src.engine.rule_engine`.
All values are computed from first principles according to the policy definitions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
import re
from typing import Any, Dict, List, Optional

from src.schemas import (
    Rulebook,
    Rule,
    ClaimFact,
    Finding,
    FindingStatus,
    SourceRef,
)


@dataclass
class PacketDocumentContent:
    """Document text content and metadata used to render synthetic PDFs."""
    title: str
    doc_type: str
    header_info: Dict[str, str]
    body_paragraphs: List[str]
    table_data: Optional[List[List[str]]] = None
    footer_text: Optional[str] = None


@dataclass
class PacketSpec:
    """Complete specification of a benchmark packet."""
    packet_id: str
    scenario_id: str
    description: str
    patient_name: str
    claim_number: str
    policy_number: str
    documents: Dict[str, PacketDocumentContent]
    claim_facts: List[ClaimFact]
    applicable_rule_ids: List[str]
    is_rasterised_bill: bool = False


def _to_decimal(val: Any) -> Optional[Decimal]:
    """Convert input safely to Decimal."""
    if val is None:
        return None
    try:
        return Decimal(str(val))
    except Exception:
        return None


def _normalize_name(name: str) -> str:
    """Normalize item name for matching: lowercase, strip punctuation to underscores."""
    if not name:
        return ""
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", name.strip().lower())
    return cleaned.strip("_")


def independently_compute_expected_findings(
    packet_spec: PacketSpec,
    rulebook: Rulebook,
) -> List[Finding]:
    """Compute expected findings independently from scenario facts and rulebook clauses.

    This function implements policy evaluation logic independently of `rule_engine.py`
    to provide an uncorrupted benchmark standard.
    """
    findings: List[Finding] = []
    facts_by_name: Dict[str, ClaimFact] = {}
    for f in packet_spec.claim_facts:
        facts_by_name[f.name] = f

    rules_by_id: Dict[str, Rule] = {r.rule_id: r for r in rulebook.rules}
    ambiguities_by_id = {a.ambiguity_id: a for a in rulebook.ambiguities}

    # Check for cross-fact amount conflicts (Variant 8 / packet 20)
    amounts: Dict[str, Decimal] = {}
    for f in packet_spec.claim_facts:
        if isinstance(f.value, dict):
            for k in ("claimed_amount", "billed_amount", "total_claimed"):
                if k in f.value and f.value[k] is not None:
                    amt = _to_decimal(f.value[k])
                    if amt is not None:
                        amounts[f"{f.name}.{k}"] = amt

    has_amount_conflict = False
    conflict_desc = ""
    if len(amounts) >= 2:
        vals = list(amounts.values())
        if any(v != vals[0] for v in vals[1:]):
            has_amount_conflict = True
            diffs = ", ".join(f"{k}=INR {v}" for k, v in amounts.items())
            conflict_desc = f"Conflicting total amounts detected across claim documents: {diffs}"

    for target_id in packet_spec.applicable_rule_ids:
        # Check if target is an ambiguity
        if target_id in ambiguities_by_id:
            amb = ambiguities_by_id[target_id]
            findings.append(
                Finding(
                    rule_id=target_id,
                    status=FindingStatus.NEEDS_REVIEW,
                    inputs_used={"ambiguity_id": target_id, "section": amb.section},
                    calculation_steps=[
                        f"Identified unresolved policy ambiguity: {amb.issue}.",
                        "Ambiguous policy clause requires manual human claims adjuster review.",
                    ],
                    explanation=f"Policy ambiguity in {amb.section} ({amb.issue}) cannot be resolved deterministically.",
                    source=amb.source,
                    estimated_impact=None,
                )
            )
            continue

        rule = rules_by_id.get(target_id)
        if not rule:
            continue

        # If there's an amount conflict, rule engine flags needs_review
        if has_amount_conflict:
            findings.append(
                Finding(
                    rule_id=rule.rule_id,
                    status=FindingStatus.NEEDS_REVIEW,
                    inputs_used={},
                    calculation_steps=[
                        f"Detected conflicting claim facts across documents: {conflict_desc}.",
                        "Conflicting financial facts require human review prior to rule adjudication.",
                    ],
                    explanation=f"Conflict detected in claim facts: {conflict_desc}",
                    source=rule.source,
                    estimated_impact=None,
                )
            )
            continue

        if rule.rule_type == "required_documents":
            doc_fact = facts_by_name.get("submitted_documents")
            req_docs = rule.parameters.get("required_documents", ["claim_form", "hospital_bill", "discharge_summary"])
            submitted = doc_fact.value if doc_fact and isinstance(doc_fact.value, list) else []
            norm_submitted = {_normalize_name(d) for d in submitted}
            norm_required = [_normalize_name(d) for d in req_docs]
            missing = [d for d in norm_required if d not in norm_submitted]

            if missing:
                findings.append(
                    Finding(
                        rule_id=rule.rule_id,
                        status=FindingStatus.VIOLATED,
                        inputs_used={"submitted_documents": submitted},
                        calculation_steps=[
                            f"Identified mandatory document list: {', '.join(req_docs)}.",
                            f"Found {len(submitted)} documents present.",
                            f"Missing required document: {', '.join(missing)}.",
                            "In accordance with Section 1.1, missing mandatory documents render the claim incomplete and inadmissible.",
                        ],
                        explanation=f"The mandatory {missing[0]} is missing from the claim submission.",
                        source=rule.source,
                        estimated_impact=None,
                    )
                )
            else:
                findings.append(
                    Finding(
                        rule_id=rule.rule_id,
                        status=FindingStatus.SATISFIED,
                        inputs_used={"submitted_documents": submitted},
                        calculation_steps=[
                            f"Checked submitted documents against mandatory list: {', '.join(req_docs)}.",
                            f"All {len(req_docs)} required documents are present in submission.",
                        ],
                        explanation="All three mandatory documents required by Section 1.1 are present in the claim submission.",
                        source=rule.source,
                        estimated_impact=0.0,
                    )
                )

        elif rule.rule_type == "waiting_period":
            hosp_fact = facts_by_name.get("hospitalization_details")
            val = hosp_fact.value if hosp_fact and isinstance(hosp_fact.value, dict) else {}
            cause = val.get("cause", "")
            duration_days = int(rule.parameters.get("duration_days", 30))

            if "accident" in cause.lower():
                findings.append(
                    Finding(
                        rule_id=rule.rule_id,
                        status=FindingStatus.SATISFIED,
                        inputs_used=val,
                        calculation_steps=[
                            "Identified hospitalization cause: accidental injury.",
                            "Applied policy exception: accidental injuries are exempt from initial waiting period.",
                        ],
                        explanation="Hospitalization was caused by accidental injury, which is explicitly exempt from the 30-day initial waiting period under Section 2.1.",
                        source=rule.source,
                        estimated_impact=0.0,
                    )
                )
            else:
                days_elapsed = val.get("days_elapsed")
                if days_elapsed is None and "admission_date" in val and "policy_inception_date" in val:
                    d_adm = datetime.strptime(val["admission_date"], "%Y-%m-%d").date()
                    d_inc = datetime.strptime(val["policy_inception_date"], "%Y-%m-%d").date()
                    days_elapsed = (d_adm - d_inc).days

                if days_elapsed is not None and days_elapsed <= duration_days:
                    findings.append(
                        Finding(
                            rule_id=rule.rule_id,
                            status=FindingStatus.VIOLATED,
                            inputs_used=val,
                            calculation_steps=[
                                f"Calculated elapsed days from policy inception: {days_elapsed} days.",
                                f"Evaluated against waiting period duration: {duration_days} days.",
                                f"Day {days_elapsed} falls within the 30-day exclusion window.",
                            ],
                            explanation=f"Hospitalization occurred on day {days_elapsed} following policy inception, within the 30-day initial waiting period.",
                            source=rule.source,
                            estimated_impact=None,
                        )
                    )
                else:
                    findings.append(
                        Finding(
                            rule_id=rule.rule_id,
                            status=FindingStatus.SATISFIED,
                            inputs_used=val,
                            calculation_steps=[
                                f"Calculated elapsed days from policy inception: {days_elapsed} days.",
                                f"Evaluated against waiting period duration: {duration_days} days.",
                                f"Day {days_elapsed} is beyond the 30-day initial waiting period.",
                            ],
                            explanation=f"Hospitalization occurred on day {days_elapsed} following policy inception, safely after the 30-day initial waiting period.",
                            source=rule.source,
                            estimated_impact=0.0,
                        )
                    )

        elif rule.rule_type == "room_rent_cap":
            rent_fact = facts_by_name.get("room_rent_billing")
            val = rent_fact.value if rent_fact and isinstance(rent_fact.value, dict) else {}
            daily_rate = _to_decimal(val.get("daily_rate")) or Decimal("0.0")
            days = _to_decimal(val.get("days"))
            cap = _to_decimal(rule.parameters.get("cap") or rule.parameters.get("daily_limit_inr") or 5000.0)

            if daily_rate <= cap:
                findings.append(
                    Finding(
                        rule_id=rule.rule_id,
                        status=FindingStatus.SATISFIED,
                        inputs_used={"daily_rate_billed": float(daily_rate), "days": int(days) if days else None, "daily_cap": float(cap)},
                        calculation_steps=[
                            f"Compared billed daily room rent (INR {daily_rate:.2f}) against policy daily cap (INR {cap:.2f}).",
                            f"INR {daily_rate:.2f} <= INR {cap:.2f}: Billed daily room rent is within the permissible limit.",
                            "Excess room rent deduction = INR 0.00.",
                        ],
                        explanation=f"The daily room rent of INR {daily_rate:.0f} does not exceed the policy limit of INR {cap:.0f} per day.",
                        source=rule.source,
                        estimated_impact=0.0,
                    )
                )
            elif days is None or days <= Decimal("0.0"):
                findings.append(
                    Finding(
                        rule_id=rule.rule_id,
                        status=FindingStatus.NEEDS_REVIEW,
                        inputs_used={"daily_rate_billed": float(daily_rate), "days": None, "daily_cap": float(cap)},
                        calculation_steps=[
                            f"Identified billed daily room rent: INR {daily_rate:.2f}.",
                            f"Daily rate exceeds cap of INR {cap:.2f}.",
                            "Attempted deduction calculation: duration in days is unknown or invalid.",
                            "Financial impact cannot be computed without total days of stay.",
                        ],
                        explanation=f"Daily room rent of INR {daily_rate:.0f} exceeds INR {cap:.0f} daily limit, but total stay duration is missing from submitted records.",
                        source=rule.source,
                        estimated_impact=None,
                    )
                )
            else:
                daily_excess = daily_rate - cap
                excess_room_rent = daily_excess * days

                # Professional fees and OT charges
                prof_fact = facts_by_name.get("professional_fees_billing")
                prof_total = Decimal("0.0")
                if prof_fact and isinstance(prof_fact.value, dict):
                    prof_total = _to_decimal(prof_fact.value.get("total_amount")) or Decimal("0.0")

                ot_fact = facts_by_name.get("operation_theatre_billing")
                ot_total = Decimal("0.0")
                if ot_fact and isinstance(ot_fact.value, dict):
                    ot_total = _to_decimal(ot_fact.value.get("ot_charges") or ot_fact.value.get("total_amount")) or Decimal("0.0")

                payable_ratio = cap / daily_rate
                disallow_ratio = Decimal("1.0") - payable_ratio
                prof_deduction = (prof_total * disallow_ratio) if prof_total > 0 else Decimal("0.0")
                ot_deduction = (ot_total * disallow_ratio) if ot_total > 0 else Decimal("0.0")
                total_deduction = excess_room_rent + prof_deduction + ot_deduction
                rounded_impact = float(total_deduction.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

                calc_steps = [
                    f"Billed daily room rent: INR {daily_rate:.2f}; Policy cap: INR {cap:.2f}.",
                    f"Daily room rent excess: INR {daily_rate:.2f} - INR {cap:.2f} = INR {daily_excess:.2f}/day.",
                    f"Excess room rent for {days:.0f} days: {days:.0f} * INR {daily_excess:.2f} = INR {excess_room_rent:.2f}.",
                ]
                if prof_total > 0 or ot_total > 0:
                    calc_steps.extend([
                        f"Proportional deduction ratio: 5000 / {daily_rate:.0f} = {payable_ratio:.4f} payable ({disallow_ratio:.4f} disallowed).",
                        f"Professional fees disallowed: INR {prof_total:.2f} * {disallow_ratio:.4f} = INR {prof_deduction:.2f}.",
                        f"OT charges disallowed: INR {ot_total:.2f} * {disallow_ratio:.4f} = INR {ot_deduction:.2f}.",
                        f"Total deduction: INR {excess_room_rent:.2f} + INR {prof_deduction:.2f} + INR {ot_deduction:.2f} = INR {total_deduction:.2f}.",
                    ])

                findings.append(
                    Finding(
                        rule_id=rule.rule_id,
                        status=FindingStatus.VIOLATED,
                        inputs_used={"daily_rate_billed": float(daily_rate), "days": int(days), "daily_cap": float(cap)},
                        calculation_steps=calc_steps,
                        explanation=f"Daily room rent of INR {daily_rate:.0f} exceeds INR {cap:.0f} cap by INR {daily_excess:.0f}/day.",
                        source=rule.source,
                        estimated_impact=rounded_impact,
                    )
                )

        elif rule.rule_type == "sub_limit":
            surg_fact = facts_by_name.get("surgical_expenses")
            val = surg_fact.value if surg_fact and isinstance(surg_fact.value, dict) else {}
            billed = _to_decimal(val.get("total_cataract_billed") or val.get("total_billed")) or Decimal("0.0")
            limit = _to_decimal(rule.parameters.get("max_limit_inr") or 40000.0)

            if billed <= limit:
                findings.append(
                    Finding(
                        rule_id=rule.rule_id,
                        status=FindingStatus.SATISFIED,
                        inputs_used={"procedure": val.get("procedure"), "total_billed": float(billed), "sublimit_per_eye": float(limit)},
                        calculation_steps=[
                            f"Billed amount for cataract surgery: INR {billed:.2f}.",
                            f"Policy sub-limit: INR {limit:.2f}.",
                            f"INR {billed:.2f} <= INR {limit:.2f}: Billed amount is within sub-limit.",
                        ],
                        explanation=f"Billed expenses of INR {billed:.0f} do not exceed the policy sub-limit of INR {limit:.0f}.",
                        source=rule.source,
                        estimated_impact=0.0,
                    )
                )
            else:
                excess = billed - limit
                rounded_excess = float(excess.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
                findings.append(
                    Finding(
                        rule_id=rule.rule_id,
                        status=FindingStatus.VIOLATED,
                        inputs_used={"procedure": val.get("procedure"), "total_billed": float(billed), "sublimit_per_eye": float(limit)},
                        calculation_steps=[
                            f"Billed amount for cataract surgery: INR {billed:.0f}.",
                            f"Policy sub-limit per eye: INR {limit:.0f}.",
                            f"Excess over sub-limit: INR {billed:.0f} - INR {limit:.0f} = INR {excess:.2f} non-payable.",
                        ],
                        explanation=f"Billed cataract surgery expenses of INR {billed:.0f} exceed the policy sub-limit of INR {limit:.0f} per eye by INR {excess:.0f}.",
                        source=rule.source,
                        estimated_impact=rounded_excess,
                    )
                )

        elif rule.rule_type == "non_payable_items":
            fact = facts_by_name.get("non_payable_items_breakdown") or facts_by_name.get("hospital_breakdown")
            items_list = fact.value if fact and isinstance(fact.value, list) else []
            raw_excluded = rule.parameters.get("excluded_items", [])
            norm_excluded = {_normalize_name(x) for x in raw_excluded}

            matched_names = []
            matched_amounts = []
            unmatched_names = []
            total_deduction = Decimal("0.0")

            for entry in items_list:
                if isinstance(entry, dict):
                    raw_name = entry.get("item") or entry.get("name") or entry.get("description") or ""
                    amt_val = entry.get("amount") or entry.get("cost") or 0
                else:
                    raw_name = str(entry)
                    amt_val = 0
                norm_name = _normalize_name(raw_name)
                amt_dec = _to_decimal(amt_val) or Decimal("0.0")

                if norm_name in norm_excluded:
                    matched_names.append(raw_name)
                    matched_amounts.append(float(amt_dec))
                    total_deduction += amt_dec
                else:
                    unmatched_names.append(raw_name)

            if not matched_names:
                findings.append(
                    Finding(
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
                )
            else:
                rounded_impact = float(total_deduction.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
                calc_steps = [
                    f"Identified invoiced line items matching Section 3.2 non-payable schedule: {', '.join(matched_names)}.",
                    f"Summed non-payable amounts: {' + '.join(f'INR {a:.0f}' for a in matched_amounts)} = INR {total_deduction:.2f} non-payable deduction.",
                ]
                if unmatched_names:
                    calc_steps.append(f"Reported allowable/unmatched billed items: {', '.join(unmatched_names)}.")

                findings.append(
                    Finding(
                        rule_id=rule.rule_id,
                        status=FindingStatus.VIOLATED,
                        inputs_used={"items_detected": matched_names, "amounts": matched_amounts},
                        calculation_steps=calc_steps,
                        explanation=f"Invoiced expenses include {', '.join(matched_names)}, which are explicitly non-payable under Section 3.2.",
                        source=rule.source,
                        estimated_impact=rounded_impact,
                    )
                )

    return findings


def get_all_packet_specs() -> List[PacketSpec]:
    """Return specifications for all 20 benchmark packets (12 core + 8 variants)."""
    return [
        # Packet 01: All documents present
        PacketSpec(
            packet_id="packet_01",
            scenario_id="SCENARIO_01_ALL_DOCUMENTS_PRESENT",
            description="Claimant submitted all three mandatory documents: Claim Form, original Hospital Bill with receipt, and Hospital Discharge Summary.",
            patient_name="Aarav Sharma",
            claim_number="CLM-2026-0001",
            policy_number="POL-AURA-2026-001",
            documents={
                "claim_form.pdf": PacketDocumentContent(
                    title="HEALTH INSURANCE REIMBURSEMENT CLAIM FORM",
                    doc_type="Claim Form (Form CF-101)",
                    header_info={"Patient": "Aarav Sharma", "Claim No": "CLM-2026-0001", "Policy No": "POL-AURA-2026-001"},
                    body_paragraphs=[
                        "Enclosed documents: Claim Form (Form CF-101), Original Hospital Final Bill (Inv #9821), and Discharge Summary (IPD-4412).",
                        "The claimant certifies that all details provided in this reimbursement submission are true, complete, and verifiable against primary hospital records.",
                    ],
                ),
                "hospital_bill.pdf": PacketDocumentContent(
                    title="APEX MEMORIAL HOSPITAL - INPATIENT FINAL BILL",
                    doc_type="Hospital Bill (Inv #9821)",
                    header_info={"Patient": "Aarav Sharma", "Invoice No": "INV-9821", "Total Billed": "INR 28500.00"},
                    body_paragraphs=[
                        "Hospitalization summary for treatment of acute viral illness. Bill paid in full via online bank transfer.",
                        "Itemized room, investigation, and nursing charges are certified by hospital finance.",
                    ],
                ),
                "discharge_summary.pdf": PacketDocumentContent(
                    title="HOSPITAL DISCHARGE SUMMARY",
                    doc_type="Discharge Summary (IPD-4412)",
                    header_info={"Patient": "Aarav Sharma", "IPD No": "IPD-4412", "Admission": "2026-02-10", "Discharge": "2026-02-13"},
                    body_paragraphs=[
                        "Clinical discharge summary for patient Aarav Sharma. Treatment completed successfully with standard oral medication.",
                        "Discharge condition stable. Follow-up consultation advised in 7 days.",
                    ],
                ),
            },
            claim_facts=[
                ClaimFact(
                    name="submitted_documents",
                    value=["claim_form", "hospital_bill", "discharge_summary"],
                    source=SourceRef(
                        document="claim_form.pdf",
                        page=1,
                        quote="Enclosed documents: Claim Form (Form CF-101), Original Hospital Final Bill (Inv #9821), and Discharge Summary (IPD-4412).",
                    ),
                )
            ],
            applicable_rule_ids=["RULE_REQ_DOCS"],
            is_rasterised_bill=False,
        ),

        # Packet 02: Required document missing
        PacketSpec(
            packet_id="packet_02",
            scenario_id="SCENARIO_02_REQUIRED_DOCUMENT_MISSING",
            description="Claim submission contains Claim Form and Hospital Bill, but lacks mandatory Hospital Discharge Summary.",
            patient_name="Priya Patel",
            claim_number="CLM-2026-0002",
            policy_number="POL-AURA-2026-001",
            documents={
                "claim_form.pdf": PacketDocumentContent(
                    title="HEALTH INSURANCE REIMBURSEMENT CLAIM FORM",
                    doc_type="Claim Form (Form CF-101)",
                    header_info={"Patient": "Priya Patel", "Claim No": "CLM-2026-0002", "Policy No": "POL-AURA-2026-001"},
                    body_paragraphs=[
                        "Attached documents: Claim Form and Hospital Inpatient Bill. Note: Discharge summary is currently awaited from medical records department.",
                        "Claimant requests expedited preliminary scrutiny while medical records prepares official discharge docket.",
                    ],
                ),
                "hospital_bill.pdf": PacketDocumentContent(
                    title="CITY GENERAL HOSPITAL - INPATIENT TAX INVOICE",
                    doc_type="Hospital Bill (Inv #5512)",
                    header_info={"Patient": "Priya Patel", "Invoice No": "INV-5512", "Total Billed": "INR 34000.00"},
                    body_paragraphs=[
                        "Original final hospitalization invoice with complete payment acknowledgement.",
                        "Charges include diagnostic panels and inpatient pharmacy consumables.",
                    ],
                ),
                "discharge_summary.pdf": PacketDocumentContent(
                    title="DOCUMENT NOTICE - DISCHARGE SUMMARY",
                    doc_type="Notice of Missing Document",
                    header_info={"Patient": "Priya Patel", "Status": "AWAITED"},
                    body_paragraphs=[
                        "NOTICE: The official Hospital Discharge Summary was not provided at the time of claim submission.",
                        "Hospital administration indicates records are undergoing clinical review prior to release.",
                    ],
                ),
            },
            claim_facts=[
                ClaimFact(
                    name="submitted_documents",
                    value=["claim_form", "hospital_bill"],
                    source=SourceRef(
                        document="claim_form.pdf",
                        page=1,
                        quote="Attached documents: Claim Form and Hospital Inpatient Bill. Note: Discharge summary is currently awaited from medical records department.",
                    ),
                )
            ],
            applicable_rule_ids=["RULE_REQ_DOCS"],
            is_rasterised_bill=False,
        ),

        # Packet 03: Waiting period satisfied
        PacketSpec(
            packet_id="packet_03",
            scenario_id="SCENARIO_03_WAITING_PERIOD_SATISFIED",
            description="Hospitalization for viral gastroenteritis occurred on day 45 following policy inception, safely after the 30-day initial waiting period.",
            patient_name="Vikram Sethi",
            claim_number="CLM-2026-0003",
            policy_number="POL-AURA-2026-001",
            documents={
                "claim_form.pdf": PacketDocumentContent(
                    title="HEALTH INSURANCE REIMBURSEMENT CLAIM FORM",
                    doc_type="Claim Form (Form CF-101)",
                    header_info={"Patient": "Vikram Sethi", "Claim No": "CLM-2026-0003", "Policy Inception": "2026-01-01"},
                    body_paragraphs=[
                        "Claim submission for acute viral gastroenteritis hospitalization at Care Hospital.",
                        "Policy inception date confirmed as 01-Jan-2026 under Aura Health Assure Plan B.",
                    ],
                ),
                "hospital_bill.pdf": PacketDocumentContent(
                    title="CARE HOSPITAL - FINAL INPATIENT BILL",
                    doc_type="Hospital Bill",
                    header_info={"Patient": "Vikram Sethi", "Invoice": "INV-7719", "Total Amount": "INR 22500.00"},
                    body_paragraphs=[
                        "Inpatient billing for intravenous hydration, electrolyte correction, and semi-private room stay.",
                    ],
                ),
                "discharge_summary.pdf": PacketDocumentContent(
                    title="CARE HOSPITAL - DISCHARGE SUMMARY",
                    doc_type="Discharge Summary",
                    header_info={"Patient": "Vikram Sethi", "Admission": "2026-02-15", "Discharge": "2026-02-18"},
                    body_paragraphs=[
                        "Patient admitted on 15-Feb-2026 for acute viral gastroenteritis with moderate dehydration. Discharged on 18-Feb-2026.",
                        "Course in hospital uneventful. Discharged in hemodynamically stable condition.",
                    ],
                ),
            },
            claim_facts=[
                ClaimFact(
                    name="hospitalization_details",
                    value={
                        "policy_inception_date": "2026-01-01",
                        "admission_date": "2026-02-15",
                        "days_elapsed": 45,
                        "cause": "illness",
                        "diagnosis": "acute viral gastroenteritis",
                    },
                    source=SourceRef(
                        document="discharge_summary.pdf",
                        page=1,
                        quote="Patient admitted on 15-Feb-2026 for acute viral gastroenteritis with moderate dehydration. Discharged on 18-Feb-2026.",
                    ),
                )
            ],
            applicable_rule_ids=["RULE_WAITING_PERIOD"],
            is_rasterised_bill=False,
        ),

        # Packet 04: Waiting period not satisfied
        PacketSpec(
            packet_id="packet_04",
            scenario_id="SCENARIO_04_WAITING_PERIOD_NOT_SATISFIED",
            description="Hospitalization for acute appendicitis (illness) occurred on day 14 following policy inception, falling within the 30-day exclusion window.",
            patient_name="Sneha Rao",
            claim_number="CLM-2026-0004",
            policy_number="POL-AURA-2026-001",
            documents={
                "claim_form.pdf": PacketDocumentContent(
                    title="HEALTH INSURANCE REIMBURSEMENT CLAIM FORM",
                    doc_type="Claim Form (Form CF-101)",
                    header_info={"Patient": "Sneha Rao", "Claim No": "CLM-2026-0004", "Policy Inception": "2026-01-01"},
                    body_paragraphs=[
                        "Reimbursement application for emergency appendectomy hospitalization.",
                        "Policy coverage commenced on 01-Jan-2026.",
                    ],
                ),
                "hospital_bill.pdf": PacketDocumentContent(
                    title="ST. JUDE MEDICAL CENTER - INPATIENT INVOICE",
                    doc_type="Hospital Bill",
                    header_info={"Patient": "Sneha Rao", "Invoice": "INV-3301", "Amount": "INR 48000.00"},
                    body_paragraphs=[
                        "Surgical invoice covering laparoscopic appendectomy and postoperative care.",
                    ],
                ),
                "discharge_summary.pdf": PacketDocumentContent(
                    title="ST. JUDE MEDICAL CENTER - CLINICAL DISCHARGE SUMMARY",
                    doc_type="Discharge Summary",
                    header_info={"Patient": "Sneha Rao", "Admission Date": "2026-01-15", "Discharge Date": "2026-01-18"},
                    body_paragraphs=[
                        "Date of Admission: 15-Jan-2026. Diagnosis: Acute appendicitis. Emergency laparoscopic appendectomy performed.",
                        "Histopathology confirmed acute suppurative appendicitis. Patient discharged in good health.",
                    ],
                ),
            },
            claim_facts=[
                ClaimFact(
                    name="hospitalization_details",
                    value={
                        "policy_inception_date": "2026-01-01",
                        "admission_date": "2026-01-15",
                        "days_elapsed": 14,
                        "cause": "illness",
                        "diagnosis": "acute appendicitis",
                    },
                    source=SourceRef(
                        document="discharge_summary.pdf",
                        page=1,
                        quote="Date of Admission: 15-Jan-2026. Diagnosis: Acute appendicitis. Emergency laparoscopic appendectomy performed.",
                    ),
                )
            ],
            applicable_rule_ids=["RULE_WAITING_PERIOD"],
            is_rasterised_bill=False,
        ),

        # Packet 05: Room rent within limit
        PacketSpec(
            packet_id="packet_05",
            scenario_id="SCENARIO_05_ROOM_RENT_WITHIN_LIMIT",
            description="Patient occupied a twin-sharing room billed at INR 4000 per day for 3 days, which is within the INR 5000 daily limit.",
            patient_name="Rohan Verma",
            claim_number="CLM-2026-0005",
            policy_number="POL-AURA-2026-001",
            documents={
                "claim_form.pdf": PacketDocumentContent(
                    title="HEALTH INSURANCE REIMBURSEMENT CLAIM FORM",
                    doc_type="Claim Form (Form CF-101)",
                    header_info={"Patient": "Rohan Verma", "Claim No": "CLM-2026-0005"},
                    body_paragraphs=[
                        "Claim submitted for medical management of dengue fever without complications.",
                    ],
                ),
                "hospital_bill.pdf": PacketDocumentContent(
                    title="METRO HEALTHCARE HOSPITAL - ITEMIZED BILL",
                    doc_type="Hospital Bill",
                    header_info={"Patient": "Rohan Verma", "Bill No": "MHH-1044", "Total": "INR 26000.00"},
                    body_paragraphs=[
                        "Room and Board (Twin Sharing): 3 days @ INR 4000.00/day = Total INR 12000.00.",
                        "Investigation, medication, and nursing charges totaling INR 14000.00. Paid in full.",
                    ],
                ),
                "discharge_summary.pdf": PacketDocumentContent(
                    title="METRO HEALTHCARE HOSPITAL - DISCHARGE SUMMARY",
                    doc_type="Discharge Summary",
                    header_info={"Patient": "Rohan Verma", "Stay": "3 Days", "Outcome": "Recovered"},
                    body_paragraphs=[
                        "Patient treated for dengue fever with supportive IV hydration and monitoring.",
                    ],
                ),
            },
            claim_facts=[
                ClaimFact(
                    name="room_rent_billing",
                    value={
                        "room_type": "twin_sharing",
                        "daily_rate": 4000.0,
                        "days": 3,
                        "total_amount": 12000.0,
                    },
                    source=SourceRef(
                        document="hospital_bill.pdf",
                        page=1,
                        quote="Room and Board (Twin Sharing): 3 days @ INR 4000.00/day = Total INR 12000.00.",
                    ),
                )
            ],
            applicable_rule_ids=["RULE_ROOM_RENT_CAP"],
            is_rasterised_bill=False,
        ),

        # Packet 06: Room rent above limit (Rasterised Bill 1/6)
        PacketSpec(
            packet_id="packet_06",
            scenario_id="SCENARIO_06_ROOM_RENT_ABOVE_LIMIT",
            description="Patient occupied a private suite billed at INR 7500 per day for 4 days with no associated surgical fees. Excess room rent is INR 10000.",
            patient_name="Meera Sen",
            claim_number="CLM-2026-0006",
            policy_number="POL-AURA-2026-001",
            documents={
                "claim_form.pdf": PacketDocumentContent(
                    title="HEALTH INSURANCE REIMBURSEMENT CLAIM FORM",
                    doc_type="Claim Form (Form CF-101)",
                    header_info={"Patient": "Meera Sen", "Claim No": "CLM-2026-0006"},
                    body_paragraphs=[
                        "Reimbursement claim for inpatient treatment of lobar pneumonia.",
                    ],
                ),
                "hospital_bill.pdf": PacketDocumentContent(
                    title="ROYAL ORCHID HOSPITAL - EXECUTIVE INVOICE",
                    doc_type="Hospital Bill (Rasterised Scan)",
                    header_info={"Patient": "Meera Sen", "Invoice No": "ROH-8821"},
                    body_paragraphs=[
                        "Executive Suite Room Charges: 4 days @ INR 7500.00 per day = INR 30000.00.",
                        "Total invoice amount: INR 30000.00 paid via debit card on discharge.",
                    ],
                ),
                "discharge_summary.pdf": PacketDocumentContent(
                    title="ROYAL ORCHID HOSPITAL - DISCHARGE SUMMARY",
                    doc_type="Discharge Summary",
                    header_info={"Patient": "Meera Sen", "Stay": "4 Days"},
                    body_paragraphs=[
                        "Clinical resolution of right lower lobe pneumonia following antibiotic therapy.",
                    ],
                ),
            },
            claim_facts=[
                ClaimFact(
                    name="room_rent_billing",
                    value={
                        "room_type": "private_suite",
                        "daily_rate": 7500.0,
                        "days": 4,
                        "total_amount": 30000.0,
                    },
                    source=SourceRef(
                        document="hospital_bill.pdf",
                        page=1,
                        quote="Executive Suite Room Charges: 4 days @ INR 7500.00 per day = INR 30000.00.",
                    ),
                )
            ],
            applicable_rule_ids=["RULE_ROOM_RENT_CAP"],
            is_rasterised_bill=True,
        ),

        # Packet 07: Sublimit exceeded
        PacketSpec(
            packet_id="packet_07",
            scenario_id="SCENARIO_07_SUBLIMIT_EXCEEDED",
            description="Claimant underwent unilateral cataract surgery on left eye billed at INR 55000, exceeding INR 40000 sublimit by INR 15000.",
            patient_name="Kishore Iyer",
            claim_number="CLM-2026-0007",
            policy_number="POL-AURA-2026-001",
            documents={
                "claim_form.pdf": PacketDocumentContent(
                    title="HEALTH INSURANCE REIMBURSEMENT CLAIM FORM",
                    doc_type="Claim Form (Form CF-101)",
                    header_info={"Patient": "Kishore Iyer", "Claim No": "CLM-2026-0007"},
                    body_paragraphs=[
                        "Claim for unilateral left eye cataract surgery with premium foldable IOL.",
                    ],
                ),
                "hospital_bill.pdf": PacketDocumentContent(
                    title="VISION PLUS EYE HOSPITAL - SURGICAL INVOICE",
                    doc_type="Hospital Bill",
                    header_info={"Patient": "Kishore Iyer", "Surgery Date": "2026-03-01"},
                    body_paragraphs=[
                        "Procedure: Phacoemulsification with Foldable IOL (Left Eye). Surgeon Fee: INR 30000, OT: INR 10000, Lens: INR 15000. Total Cataract Charges: INR 55000.00.",
                    ],
                ),
                "discharge_summary.pdf": PacketDocumentContent(
                    title="VISION PLUS EYE HOSPITAL - DAY CARE SUMMARY",
                    doc_type="Discharge Summary",
                    header_info={"Patient": "Kishore Iyer", "Eye": "Left"},
                    body_paragraphs=[
                        "Uneventful left eye phacoemulsification with posterior chamber foldable IOL implantation.",
                    ],
                ),
            },
            claim_facts=[
                ClaimFact(
                    name="surgical_expenses",
                    value={
                        "procedure": "cataract_surgery",
                        "eye": "left",
                        "surgeon_fee": 30000.0,
                        "ot_charges": 10000.0,
                        "lens_cost": 15000.0,
                        "total_cataract_billed": 55000.0,
                    },
                    source=SourceRef(
                        document="hospital_bill.pdf",
                        page=1,
                        quote="Procedure: Phacoemulsification with Foldable IOL (Left Eye). Surgeon Fee: INR 30000, OT: INR 10000, Lens: INR 15000. Total Cataract Charges: INR 55000.00.",
                    ),
                )
            ],
            applicable_rule_ids=["RULE_CATARACT_SUBLIMIT"],
            is_rasterised_bill=False,
        ),

        # Packet 08: Non-payable items present
        PacketSpec(
            packet_id="packet_08",
            scenario_id="SCENARIO_08_NON_PAYABLE_ITEM_PRESENT",
            description="Hospital bill contains non-payable items: admission processing charges (INR 1200) and luxury patient amenity kits (INR 1800), totaling INR 3000.",
            patient_name="Sunita Nair",
            claim_number="CLM-2026-0008",
            policy_number="POL-AURA-2026-001",
            documents={
                "claim_form.pdf": PacketDocumentContent(
                    title="HEALTH INSURANCE REIMBURSEMENT CLAIM FORM",
                    doc_type="Claim Form (Form CF-101)",
                    header_info={"Patient": "Sunita Nair", "Claim No": "CLM-2026-0008"},
                    body_paragraphs=[
                        "Reimbursement application for laparoscopic cholecystectomy inpatient expenses.",
                    ],
                ),
                "hospital_bill.pdf": PacketDocumentContent(
                    title="APEX SURGICAL HOSPITAL - ITEMIZED BREAKDOWN",
                    doc_type="Hospital Bill",
                    header_info={"Patient": "Sunita Nair", "Bill No": "ASH-9912"},
                    body_paragraphs=[
                        "Non-medical sundries: Admission processing charges INR 1200.00, Luxury patient amenity kits INR 1800.00.",
                        "Total non-medical charges of INR 3000.00 included in final settlement.",
                    ],
                ),
                "discharge_summary.pdf": PacketDocumentContent(
                    title="APEX SURGICAL HOSPITAL - DISCHARGE SUMMARY",
                    doc_type="Discharge Summary",
                    header_info={"Patient": "Sunita Nair", "Diagnosis": "Gallstone pancreatitis"},
                    body_paragraphs=[
                        "Elective laparoscopic cholecystectomy completed without intraoperative complication.",
                    ],
                ),
            },
            claim_facts=[
                ClaimFact(
                    name="non_payable_items_breakdown",
                    value=[
                        {"item": "admission_processing_charges", "amount": 1200.0},
                        {"item": "luxury_patient_amenity_kits", "amount": 1800.0},
                    ],
                    source=SourceRef(
                        document="hospital_bill.pdf",
                        page=1,
                        quote="Non-medical sundries: Admission processing charges INR 1200.00, Luxury patient amenity kits INR 1800.00.",
                    ),
                )
            ],
            applicable_rule_ids=["RULE_NON_PAYABLE_ITEMS"],
            is_rasterised_bill=False,
        ),

        # Packet 09: Accidental injury waiting period exempt
        PacketSpec(
            packet_id="packet_09",
            scenario_id="SCENARIO_09_ACCIDENT_WAITING_PERIOD_EXEMPT",
            description="Emergency hospitalization on day 10 following road traffic accident; exempt from 30-day waiting period.",
            patient_name="Manish Gupta",
            claim_number="CLM-2026-0009",
            policy_number="POL-AURA-2026-001",
            documents={
                "claim_form.pdf": PacketDocumentContent(
                    title="HEALTH INSURANCE REIMBURSEMENT CLAIM FORM",
                    doc_type="Claim Form (Form CF-101)",
                    header_info={"Patient": "Manish Gupta", "Claim No": "CLM-2026-0009", "Policy Inception": "2026-01-01"},
                    body_paragraphs=[
                        "Emergency hospitalization claim following vehicular accident on public roadway.",
                    ],
                ),
                "hospital_bill.pdf": PacketDocumentContent(
                    title="TRAUMA EMERGENCY CENTER - HOSPITAL INVOICE",
                    doc_type="Hospital Bill",
                    header_info={"Patient": "Manish Gupta", "Invoice": "TEC-4411"},
                    body_paragraphs=[
                        "Emergency trauma billing for open reduction and internal fixation of tibial fracture.",
                    ],
                ),
                "discharge_summary.pdf": PacketDocumentContent(
                    title="TRAUMA EMERGENCY CENTER - EMERGENCY DISCHARGE REPORT",
                    doc_type="Discharge Summary",
                    header_info={"Patient": "Manish Gupta", "Admission": "2026-01-10"},
                    body_paragraphs=[
                        "Emergency Admission: 10-Jan-2026. Patient presented with compound tibial fracture following a vehicular road collision. Immediate surgical reduction required.",
                        "Post-operative neurovascular exam intact. Immobilization cast applied.",
                    ],
                ),
            },
            claim_facts=[
                ClaimFact(
                    name="hospitalization_details",
                    value={
                        "policy_inception_date": "2026-01-01",
                        "admission_date": "2026-01-10",
                        "days_elapsed": 10,
                        "cause": "accidental_injury",
                        "diagnosis": "tibial fracture due to road traffic accident",
                    },
                    source=SourceRef(
                        document="discharge_summary.pdf",
                        page=1,
                        quote="Emergency Admission: 10-Jan-2026. Patient presented with compound tibial fracture following a vehicular road collision. Immediate surgical reduction required.",
                    ),
                )
            ],
            applicable_rule_ids=["RULE_WAITING_PERIOD"],
            is_rasterised_bill=False,
        ),

        # Packet 10: Room rent unknown duration (Rasterised Bill 2/6)
        PacketSpec(
            packet_id="packet_10",
            scenario_id="SCENARIO_10_ROOM_RENT_UNKNOWN_DURATION",
            description="Claim indicates daily room rent of INR 7000 (exceeding INR 5000 limit) but stay duration is not stated. Requires human review.",
            patient_name="Ananya Roy",
            claim_number="CLM-2026-0010",
            policy_number="POL-AURA-2026-001",
            documents={
                "claim_form.pdf": PacketDocumentContent(
                    title="HEALTH INSURANCE REIMBURSEMENT CLAIM FORM",
                    doc_type="Claim Form (Form CF-101)",
                    header_info={"Patient": "Ananya Roy", "Claim No": "CLM-2026-0010"},
                    body_paragraphs=[
                        "Interim reimbursement claim submitted prior to final hospital bill consolidation.",
                    ],
                ),
                "hospital_bill.pdf": PacketDocumentContent(
                    title="HEART & VASCULAR INSTITUTE - INTERIM STATEMENT",
                    doc_type="Hospital Bill (Rasterised Scan)",
                    header_info={"Patient": "Ananya Roy", "Bill Type": "Interim Bill"},
                    body_paragraphs=[
                        "Interim Bill: Deluxe Room billed @ INR 7000.00/day. Total days pending final discharge calculation.",
                    ],
                ),
                "discharge_summary.pdf": PacketDocumentContent(
                    title="HEART & VASCULAR INSTITUTE - CLINICAL NOTE",
                    doc_type="Discharge Summary",
                    header_info={"Patient": "Ananya Roy"},
                    body_paragraphs=[
                        "Cardiac telemetry monitoring completed. Patient in stable condition awaiting final discharge clearance.",
                    ],
                ),
            },
            claim_facts=[
                ClaimFact(
                    name="room_rent_billing",
                    value={
                        "room_type": "deluxe_room",
                        "daily_rate": 7000.0,
                        "days": None,
                    },
                    source=SourceRef(
                        document="hospital_bill.pdf",
                        page=1,
                        quote="Interim Bill: Deluxe Room billed @ INR 7000.00/day. Total days pending final discharge calculation.",
                    ),
                )
            ],
            applicable_rule_ids=["RULE_ROOM_RENT_CAP"],
            is_rasterised_bill=True,
        ),

        # Packet 11: Room rent proportional deduction (Rasterised Bill 3/6 - EXPLICIT REQUIREMENT)
        PacketSpec(
            packet_id="packet_11",
            scenario_id="SCENARIO_11_ROOM_RENT_PROPORTIONAL_DEDUCTION",
            description="Deluxe Room at INR 10000/day for 2 days. Total deduction includes excess room rent INR 10000, plus 50% disallowance on prof fees (INR 10000) and OT charges (INR 7500), totaling INR 27500.",
            patient_name="Deepak Chopra",
            claim_number="CLM-2026-0011",
            policy_number="POL-AURA-2026-001",
            documents={
                "claim_form.pdf": PacketDocumentContent(
                    title="HEALTH INSURANCE REIMBURSEMENT CLAIM FORM",
                    doc_type="Claim Form (Form CF-101)",
                    header_info={"Patient": "Deepak Chopra", "Claim No": "CLM-2026-0011"},
                    body_paragraphs=[
                        "Reimbursement claim for elective orthopedic knee arthroplasty.",
                    ],
                ),
                "hospital_bill.pdf": PacketDocumentContent(
                    title="ORTHO-CARE SPECIALTY HOSPITAL - COMPREHENSIVE INVOICE",
                    doc_type="Hospital Bill (Rasterised Scan)",
                    header_info={"Patient": "Deepak Chopra", "Bill No": "OCSH-5520"},
                    body_paragraphs=[
                        "Deluxe Room Charges: 2 days @ INR 10000.00/day = Total INR 20000.00.",
                        "Professional Fees: Surgeon INR 12000, Anesthetist INR 5000, Physician INR 3000. Total INR 20000.00.",
                        "Operation Theatre Charges: Major OT booking and consumables = Total INR 15000.00.",
                    ],
                ),
                "discharge_summary.pdf": PacketDocumentContent(
                    title="ORTHO-CARE SPECIALTY HOSPITAL - DISCHARGE SUMMARY",
                    doc_type="Discharge Summary",
                    header_info={"Patient": "Deepak Chopra", "LOS": "2 Days"},
                    body_paragraphs=[
                        "Total knee arthroplasty performed successfully. Postoperative rehabilitation initiated.",
                    ],
                ),
            },
            claim_facts=[
                ClaimFact(
                    name="room_rent_billing",
                    value={
                        "room_type": "deluxe_room",
                        "daily_rate": 10000.0,
                        "days": 2,
                        "total_amount": 20000.0,
                    },
                    source=SourceRef(
                        document="hospital_bill.pdf",
                        page=1,
                        quote="Deluxe Room Charges: 2 days @ INR 10000.00/day = Total INR 20000.00.",
                    ),
                ),
                ClaimFact(
                    name="professional_fees_billing",
                    value={
                        "surgeon_fee": 12000.0,
                        "anesthetist_fee": 5000.0,
                        "consultant_fee": 3000.0,
                        "total_amount": 20000.0,
                    },
                    source=SourceRef(
                        document="hospital_bill.pdf",
                        page=1,
                        quote="Professional Fees: Surgeon INR 12000, Anesthetist INR 5000, Physician INR 3000. Total INR 20000.00.",
                    ),
                ),
                ClaimFact(
                    name="operation_theatre_billing",
                    value={
                        "ot_charges": 15000.0,
                    },
                    source=SourceRef(
                        document="hospital_bill.pdf",
                        page=1,
                        quote="Operation Theatre Charges: Major OT booking and consumables = Total INR 15000.00.",
                    ),
                ),
            ],
            applicable_rule_ids=["RULE_ROOM_RENT_CAP"],
            is_rasterised_bill=True,
        ),

        # Packet 12: Pre-existing condition ambiguity
        PacketSpec(
            packet_id="packet_12",
            scenario_id="SCENARIO_12_PRE_EXISTING_CONDITION_AMBIGUITY",
            description="Claim for chronic hypertensive crisis. Policy Section 4.1 refers to regulations without defining framework, requiring human review.",
            patient_name="Kavita Saxena",
            claim_number="CLM-2026-0012",
            policy_number="POL-AURA-2026-001",
            documents={
                "claim_form.pdf": PacketDocumentContent(
                    title="HEALTH INSURANCE REIMBURSEMENT CLAIM FORM",
                    doc_type="Claim Form (Form CF-101)",
                    header_info={"Patient": "Kavita Saxena", "Claim No": "CLM-2026-0012"},
                    body_paragraphs=[
                        "Claim submitted for emergency inpatient admission for acute hypertensive crisis.",
                    ],
                ),
                "hospital_bill.pdf": PacketDocumentContent(
                    title="APOLLO LIFE HOSPITAL - FINAL INPATIENT BILL",
                    doc_type="Hospital Bill",
                    header_info={"Patient": "Kavita Saxena", "Amount": "INR 18500.00"},
                    body_paragraphs=[
                        "Inpatient ICU step-down care and pharmacological stabilization.",
                    ],
                ),
                "discharge_summary.pdf": PacketDocumentContent(
                    title="APOLLO LIFE HOSPITAL - DISCHARGE SUMMARY",
                    doc_type="Discharge Summary",
                    header_info={"Patient": "Kavita Saxena"},
                    body_paragraphs=[
                        "Patient has a 24-month known history of hypertension under medical management. Admitted for emergency stabilization of acute hypertensive crisis.",
                        "Blood pressure stabilized with dual antihypertensive therapy.",
                    ],
                ),
            },
            claim_facts=[
                ClaimFact(
                    name="patient_medical_history",
                    value={
                        "diagnosis": "essential_hypertension",
                        "pre_existing_history": "Diagnosed 24 months prior to policy inception",
                        "hospitalization_cause": "acute hypertensive crisis",
                        "claimed_amount": 18500.0,
                    },
                    source=SourceRef(
                        document="discharge_summary.pdf",
                        page=1,
                        quote="Patient has a 24-month known history of hypertension under medical management. Admitted for emergency stabilization of acute hypertensive crisis.",
                    ),
                )
            ],
            applicable_rule_ids=["AMB_PRE_EXISTING_CONDITIONS"],
            is_rasterised_bill=False,
        ),

        # Packet 13: Variant 1 - Claim form missing from submission
        PacketSpec(
            packet_id="packet_13",
            scenario_id="SCENARIO_13_MISSING_CLAIM_FORM",
            description="Variant 1: Claim submission contains hospital bill and discharge summary, but claim form was omitted by claimant.",
            patient_name="Sanjay Mishra",
            claim_number="CLM-2026-0013",
            policy_number="POL-AURA-2026-001",
            documents={
                "claim_form.pdf": PacketDocumentContent(
                    title="DOCUMENT NOTICE - CLAIM FORM MISSING",
                    doc_type="Notice of Omitted Form",
                    header_info={"Patient": "Sanjay Mishra", "Notice": "CLAIM FORM OMITTED"},
                    body_paragraphs=[
                        "NOTICE: Official Claim Form CF-101 was not enclosed in the submission docket by claimant Sanjay Mishra.",
                        "Only the hospital bill and discharge summary were delivered to the claims department.",
                    ],
                ),
                "hospital_bill.pdf": PacketDocumentContent(
                    title="PRIME HOSPITAL - INPATIENT BILL",
                    doc_type="Hospital Bill",
                    header_info={"Patient": "Sanjay Mishra", "Amount": "INR 31000.00"},
                    body_paragraphs=[
                        "Final inpatient bill for medical treatment of acute gastroenteritis.",
                        "Submitted directly by patient without accompanying signed reimbursement form.",
                    ],
                ),
                "discharge_summary.pdf": PacketDocumentContent(
                    title="PRIME HOSPITAL - DISCHARGE SUMMARY",
                    doc_type="Discharge Summary",
                    header_info={"Patient": "Sanjay Mishra", "IPD": "IPD-8822"},
                    body_paragraphs=[
                        "Patient treated with intravenous fluids and discharged in stable condition.",
                    ],
                ),
            },
            claim_facts=[
                ClaimFact(
                    name="submitted_documents",
                    value=["hospital_bill", "discharge_summary"],
                    source=SourceRef(
                        document="claim_form.pdf",
                        page=1,
                        quote="NOTICE: Official Claim Form CF-101 was not enclosed in the submission docket by claimant Sanjay Mishra.",
                    ),
                )
            ],
            applicable_rule_ids=["RULE_REQ_DOCS"],
            is_rasterised_bill=False,
        ),

        # Packet 14: Variant 2 - Hospital bill missing from submission
        PacketSpec(
            packet_id="packet_14",
            scenario_id="SCENARIO_14_MISSING_HOSPITAL_BILL",
            description="Variant 2: Claim submission contains signed claim form and discharge summary, but hospital bill was not submitted.",
            patient_name="Divya Nair",
            claim_number="CLM-2026-0014",
            policy_number="POL-AURA-2026-001",
            documents={
                "claim_form.pdf": PacketDocumentContent(
                    title="HEALTH INSURANCE REIMBURSEMENT CLAIM FORM",
                    doc_type="Claim Form (Form CF-101)",
                    header_info={"Patient": "Divya Nair", "Claim No": "CLM-2026-0014"},
                    body_paragraphs=[
                        "Claim submitted with discharge summary. Itemized hospital bill is currently pending from accounts section.",
                    ],
                ),
                "hospital_bill.pdf": PacketDocumentContent(
                    title="DOCUMENT NOTICE - HOSPITAL BILL OMITTED",
                    doc_type="Notice of Missing Bill",
                    header_info={"Patient": "Divya Nair", "Status": "MISSING"},
                    body_paragraphs=[
                        "NOTICE: The itemized original Hospital Bill with receipt was not submitted with this claim packet.",
                        "Reimbursement processing cannot proceed until complete invoice documentation is submitted.",
                    ],
                ),
                "discharge_summary.pdf": PacketDocumentContent(
                    title="GALAXY HOSPITAL - DISCHARGE SUMMARY",
                    doc_type="Discharge Summary",
                    header_info={"Patient": "Divya Nair", "Diagnosis": "Renal Colic"},
                    body_paragraphs=[
                        "Patient treated conservatively for acute left renal calculus with complete symptom relief.",
                    ],
                ),
            },
            claim_facts=[
                ClaimFact(
                    name="submitted_documents",
                    value=["claim_form", "discharge_summary"],
                    source=SourceRef(
                        document="hospital_bill.pdf",
                        page=1,
                        quote="NOTICE: The itemized original Hospital Bill with receipt was not submitted with this claim packet.",
                    ),
                )
            ],
            applicable_rule_ids=["RULE_REQ_DOCS"],
            is_rasterised_bill=False,
        ),

        # Packet 15: Variant 3 - Bill item names with case and punctuation differences (Rasterised Bill 4/6)
        PacketSpec(
            packet_id="packet_15",
            scenario_id="SCENARIO_15_NON_PAYABLE_CASE_PUNCTUATION",
            description="Variant 3: Invoiced line items have non-standard casing and punctuation (GLOVES!, Face-Masks., Admission - Processing Charges). All 3 match Section 3.2.",
            patient_name="Alok Tandon",
            claim_number="CLM-2026-0015",
            policy_number="POL-AURA-2026-001",
            documents={
                "claim_form.pdf": PacketDocumentContent(
                    title="HEALTH INSURANCE REIMBURSEMENT CLAIM FORM",
                    doc_type="Claim Form (Form CF-101)",
                    header_info={"Patient": "Alok Tandon", "Claim No": "CLM-2026-0015"},
                    body_paragraphs=[
                        "Reimbursement claim for general surgical inpatient hospitalization.",
                    ],
                ),
                "hospital_bill.pdf": PacketDocumentContent(
                    title="CITY SPECIALTY HOSPITAL - SUNDRIES SCHEDULE",
                    doc_type="Hospital Bill (Rasterised Scan)",
                    header_info={"Patient": "Alok Tandon", "Bill No": "CSH-3390"},
                    body_paragraphs=[
                        "Sundries breakdown: GLOVES! INR 800.00, Face-Masks. INR 600.00, Admission - Processing Charges INR 1500.00.",
                        "Total consumable and non-medical surcharge: INR 2900.00.",
                    ],
                ),
                "discharge_summary.pdf": PacketDocumentContent(
                    title="CITY SPECIALTY HOSPITAL - DISCHARGE SUMMARY",
                    doc_type="Discharge Summary",
                    header_info={"Patient": "Alok Tandon"},
                    body_paragraphs=[
                        "General surgical procedure completed without complications.",
                    ],
                ),
            },
            claim_facts=[
                ClaimFact(
                    name="non_payable_items_breakdown",
                    value=[
                        {"item": "GLOVES!", "amount": 800.0},
                        {"item": "Face-Masks.", "amount": 600.0},
                        {"item": "Admission - Processing Charges", "amount": 1500.0},
                    ],
                    source=SourceRef(
                        document="hospital_bill.pdf",
                        page=1,
                        quote="Sundries breakdown: GLOVES! INR 800.00, Face-Masks. INR 600.00, Admission - Processing Charges INR 1500.00.",
                    ),
                )
            ],
            applicable_rule_ids=["RULE_NON_PAYABLE_ITEMS"],
            is_rasterised_bill=True,
        ),

        # Packet 16: Variant 4 - Bill item synonyms (unmatched items reported, no fuzzy guessing)
        PacketSpec(
            packet_id="packet_16",
            scenario_id="SCENARIO_16_NON_PAYABLE_SYNONYMS",
            description="Variant 4: Bill contains synonym terms (sanitizing_gel, latex_hand_wear) that do not match exact policy terms and are reported as unmatched.",
            patient_name="Neelam Bhatia",
            claim_number="CLM-2026-0016",
            policy_number="POL-AURA-2026-001",
            documents={
                "claim_form.pdf": PacketDocumentContent(
                    title="HEALTH INSURANCE REIMBURSEMENT CLAIM FORM",
                    doc_type="Claim Form (Form CF-101)",
                    header_info={"Patient": "Neelam Bhatia", "Claim No": "CLM-2026-0016"},
                    body_paragraphs=[
                        "Reimbursement application for medical ward stay.",
                    ],
                ),
                "hospital_bill.pdf": PacketDocumentContent(
                    title="MEDICARE COMMUNITY HOSPITAL - ITEMIZED BILL",
                    doc_type="Hospital Bill",
                    header_info={"Patient": "Neelam Bhatia", "Invoice": "MCH-7744"},
                    body_paragraphs=[
                        "Sundries breakdown: sanitizing_gel INR 500.00, latex_hand_wear INR 400.00.",
                        "Total consumables billed: INR 900.00.",
                    ],
                ),
                "discharge_summary.pdf": PacketDocumentContent(
                    title="MEDICARE COMMUNITY HOSPITAL - DISCHARGE SUMMARY",
                    doc_type="Discharge Summary",
                    header_info={"Patient": "Neelam Bhatia"},
                    body_paragraphs=[
                        "Patient recovered from seasonal viral bronchitis.",
                    ],
                ),
            },
            claim_facts=[
                ClaimFact(
                    name="non_payable_items_breakdown",
                    value=[
                        {"item": "sanitizing_gel", "amount": 500.0},
                        {"item": "latex_hand_wear", "amount": 400.0},
                    ],
                    source=SourceRef(
                        document="hospital_bill.pdf",
                        page=1,
                        quote="Sundries breakdown: sanitizing_gel INR 500.00, latex_hand_wear INR 400.00.",
                    ),
                )
            ],
            applicable_rule_ids=["RULE_NON_PAYABLE_ITEMS"],
            is_rasterised_bill=False,
        ),

        # Packet 17: Variant 5 - Room rent exactly at cap (Rasterised Bill 5/6)
        PacketSpec(
            packet_id="packet_17",
            scenario_id="SCENARIO_17_ROOM_RENT_EXACTLY_AT_CAP",
            description="Variant 5: Daily room rent billed is exactly INR 5000 per day for 4 days, equal to the policy cap.",
            patient_name="Rajendra Prasad",
            claim_number="CLM-2026-0017",
            policy_number="POL-AURA-2026-001",
            documents={
                "claim_form.pdf": PacketDocumentContent(
                    title="HEALTH INSURANCE REIMBURSEMENT CLAIM FORM",
                    doc_type="Claim Form (Form CF-101)",
                    header_info={"Patient": "Rajendra Prasad", "Claim No": "CLM-2026-0017"},
                    body_paragraphs=[
                        "Claim for standard private room inpatient care.",
                    ],
                ),
                "hospital_bill.pdf": PacketDocumentContent(
                    title="LOTUS MULTISPECIALTY HOSPITAL - FINAL INVOICE",
                    doc_type="Hospital Bill (Rasterised Scan)",
                    header_info={"Patient": "Rajendra Prasad", "Bill": "LMH-9011"},
                    body_paragraphs=[
                        "Room Rent (Standard Private): 4 days @ INR 5000.00/day = Total INR 20000.00.",
                        "Total room and nursing charges: INR 20000.00. Settled in full.",
                    ],
                ),
                "discharge_summary.pdf": PacketDocumentContent(
                    title="LOTUS MULTISPECIALTY HOSPITAL - DISCHARGE SUMMARY",
                    doc_type="Discharge Summary",
                    header_info={"Patient": "Rajendra Prasad", "Days": "4"},
                    body_paragraphs=[
                        "Patient treated for complicated urinary tract infection.",
                    ],
                ),
            },
            claim_facts=[
                ClaimFact(
                    name="room_rent_billing",
                    value={
                        "room_type": "standard_private",
                        "daily_rate": 5000.0,
                        "days": 4,
                        "total_amount": 20000.0,
                    },
                    source=SourceRef(
                        document="hospital_bill.pdf",
                        page=1,
                        quote="Room Rent (Standard Private): 4 days @ INR 5000.00/day = Total INR 20000.00.",
                    ),
                )
            ],
            applicable_rule_ids=["RULE_ROOM_RENT_CAP"],
            is_rasterised_bill=True,
        ),

        # Packet 18: Variant 6 - Admission on Day 30 post-inception (violated)
        PacketSpec(
            packet_id="packet_18",
            scenario_id="SCENARIO_18_WAITING_PERIOD_DAY_30_BOUNDARY",
            description="Variant 6: Admission occurred exactly on day 30 post-inception for illness, which falls inside the 30-day initial exclusion.",
            patient_name="Pooja Kulkarni",
            claim_number="CLM-2026-0018",
            policy_number="POL-AURA-2026-001",
            documents={
                "claim_form.pdf": PacketDocumentContent(
                    title="HEALTH INSURANCE REIMBURSEMENT CLAIM FORM",
                    doc_type="Claim Form (Form CF-101)",
                    header_info={"Patient": "Pooja Kulkarni", "Claim No": "CLM-2026-0018", "Inception Date": "2026-01-01"},
                    body_paragraphs=[
                        "Inpatient hospitalization claim for acute respiratory illness.",
                    ],
                ),
                "hospital_bill.pdf": PacketDocumentContent(
                    title="BREATHE WELL PULMONARY HOSPITAL - INVOICE",
                    doc_type="Hospital Bill",
                    header_info={"Patient": "Pooja Kulkarni", "Invoice": "BWPH-2201"},
                    body_paragraphs=[
                        "Inpatient billing for oxygen therapy and nebulization rounds.",
                    ],
                ),
                "discharge_summary.pdf": PacketDocumentContent(
                    title="BREATHE WELL PULMONARY HOSPITAL - DISCHARGE SUMMARY",
                    doc_type="Discharge Summary",
                    header_info={"Patient": "Pooja Kulkarni", "Admission Date": "2026-01-31"},
                    body_paragraphs=[
                        "Patient admitted on 31-Jan-2026 for acute bronchitis. Policy inception date: 01-Jan-2026 (30 days elapsed).",
                        "Bronchitis resolved following bronchodilator treatment.",
                    ],
                ),
            },
            claim_facts=[
                ClaimFact(
                    name="hospitalization_details",
                    value={
                        "policy_inception_date": "2026-01-01",
                        "admission_date": "2026-01-31",
                        "days_elapsed": 30,
                        "cause": "illness",
                        "diagnosis": "acute bronchitis",
                    },
                    source=SourceRef(
                        document="discharge_summary.pdf",
                        page=1,
                        quote="Patient admitted on 31-Jan-2026 for acute bronchitis. Policy inception date: 01-Jan-2026 (30 days elapsed).",
                    ),
                )
            ],
            applicable_rule_ids=["RULE_WAITING_PERIOD"],
            is_rasterised_bill=False,
        ),

        # Packet 19: Variant 7 - Admission on Day 31 post-inception (satisfied)
        PacketSpec(
            packet_id="packet_19",
            scenario_id="SCENARIO_19_WAITING_PERIOD_DAY_31_BOUNDARY",
            description="Variant 7: Admission occurred on day 31 post-inception for illness, satisfying the 30-day initial waiting period.",
            patient_name="Tariq Mansoor",
            claim_number="CLM-2026-0019",
            policy_number="POL-AURA-2026-001",
            documents={
                "claim_form.pdf": PacketDocumentContent(
                    title="HEALTH INSURANCE REIMBURSEMENT CLAIM FORM",
                    doc_type="Claim Form (Form CF-101)",
                    header_info={"Patient": "Tariq Mansoor", "Claim No": "CLM-2026-0019", "Inception Date": "2026-01-01"},
                    body_paragraphs=[
                        "Claim submitted for acute infectious illness hospitalization.",
                    ],
                ),
                "hospital_bill.pdf": PacketDocumentContent(
                    title="HEALTH FIRST CLINIC - INPATIENT STATEMENT",
                    doc_type="Hospital Bill",
                    header_info={"Patient": "Tariq Mansoor", "Bill No": "HFC-9901"},
                    body_paragraphs=[
                        "Hospitalization invoice for intravenous antibiotic course and bed charges.",
                    ],
                ),
                "discharge_summary.pdf": PacketDocumentContent(
                    title="HEALTH FIRST CLINIC - DISCHARGE SUMMARY",
                    doc_type="Discharge Summary",
                    header_info={"Patient": "Tariq Mansoor", "Admission Date": "2026-02-01"},
                    body_paragraphs=[
                        "Patient admitted on 01-Feb-2026 for acute bronchitis. Policy inception date: 01-Jan-2026 (31 days elapsed).",
                        "Infection controlled with clinical recovery on discharge.",
                    ],
                ),
            },
            claim_facts=[
                ClaimFact(
                    name="hospitalization_details",
                    value={
                        "policy_inception_date": "2026-01-01",
                        "admission_date": "2026-02-01",
                        "days_elapsed": 31,
                        "cause": "illness",
                        "diagnosis": "acute bronchitis",
                    },
                    source=SourceRef(
                        document="discharge_summary.pdf",
                        page=1,
                        quote="Patient admitted on 01-Feb-2026 for acute bronchitis. Policy inception date: 01-Jan-2026 (31 days elapsed).",
                    ),
                )
            ],
            applicable_rule_ids=["RULE_WAITING_PERIOD"],
            is_rasterised_bill=False,
        ),

        # Packet 20: Variant 8 - Amount differing between claim form and bill (Rasterised Bill 6/6)
        PacketSpec(
            packet_id="packet_20",
            scenario_id="SCENARIO_20_CONFLICTING_AMOUNTS",
            description="Variant 8: Claim form declares INR 50000 claimed while hospital bill totals INR 30000, creating cross-document financial discrepancy requiring human review.",
            patient_name="Rajesh Kumar",
            claim_number="CLM-2026-0020",
            policy_number="POL-AURA-2026-001",
            documents={
                "claim_form.pdf": PacketDocumentContent(
                    title="HEALTH INSURANCE REIMBURSEMENT CLAIM FORM",
                    doc_type="Claim Form (Form CF-101)",
                    header_info={"Patient": "Rajesh Kumar", "Claim No": "CLM-2026-0020"},
                    body_paragraphs=[
                        "Total Reimbursement Claimed by Insured: INR 50000.00 for Patient Rajesh Kumar.",
                        "Claimant signed statement of incurred medical costs.",
                    ],
                ),
                "hospital_bill.pdf": PacketDocumentContent(
                    title="PRINCE ALBERT HOSPITAL - OFFICIAL INVOICE",
                    doc_type="Hospital Bill (Rasterised Scan)",
                    header_info={"Patient": "Rajesh Kumar", "Invoice": "PAH-6002"},
                    body_paragraphs=[
                        "Executive Suite: 5 days @ INR 6000.00/day = Total INR 30000.00.",
                        "Settled in full by patient. Note difference from claimed amount.",
                    ],
                ),
                "discharge_summary.pdf": PacketDocumentContent(
                    title="PRINCE ALBERT HOSPITAL - DISCHARGE SUMMARY",
                    doc_type="Discharge Summary",
                    header_info={"Patient": "Rajesh Kumar", "LOS": "5 Days"},
                    body_paragraphs=[
                        "Post-operative observation completed with uneventful recovery.",
                    ],
                ),
            },
            claim_facts=[
                ClaimFact(
                    name="claim_form_summary",
                    value={
                        "claimed_amount": 50000.0,
                        "patient_name": "Rajesh Kumar",
                    },
                    source=SourceRef(
                        document="claim_form.pdf",
                        page=1,
                        quote="Total Reimbursement Claimed by Insured: INR 50000.00 for Patient Rajesh Kumar.",
                    ),
                ),
                ClaimFact(
                    name="hospital_bill_summary",
                    value={
                        "billed_amount": 30000.0,
                    },
                    source=SourceRef(
                        document="hospital_bill.pdf",
                        page=1,
                        quote="Executive Suite: 5 days @ INR 6000.00/day = Total INR 30000.00.",
                    ),
                ),
                ClaimFact(
                    name="room_rent_billing",
                    value={
                        "room_type": "private_suite",
                        "daily_rate": 6000.0,
                        "days": 5,
                        "total_amount": 30000.0,
                    },
                    source=SourceRef(
                        document="hospital_bill.pdf",
                        page=1,
                        quote="Executive Suite: 5 days @ INR 6000.00/day = Total INR 30000.00.",
                    ),
                ),
            ],
            applicable_rule_ids=["RULE_ROOM_RENT_CAP"],
            is_rasterised_bill=True,
        ),
    ]
