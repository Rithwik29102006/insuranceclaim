# ClaimCheck 2.0 — Person 2: Data and Ground-Truth Validation Audit Report

**Author / Role:** Senior QA Engineer, Data-Validation Engineer, and Python Test Engineer (Person 2)  
**Date:** 2026-10-27  
**Repository:** ClaimCheck 2.0 (`claimcheck`)  
**Target Policy:** Apex Care General Insurance Ltd. — Aura Health Assure Policy (Plan B), Synthetic Test Contract (`POL-AURA-2026-001`)  
**Source Document:** `data/synthetic_policy.pdf` (4 Pages, Digital Vector PDF)  
**Canonical Rulebook:** `data/gold_rulebook.json`  

---

## 1. Executive Summary

As part of the Person 2 responsibility (*Data and Ground-Truth Validation*), this report provides an evidence-backed, reproducible validation of the synthetic insurance policy, gold rulebook, test scenarios, financial deduction algorithms, and regression test suites.

### Key Audit Findings:
1. **Policy Ground Truth:** All 5 operative policy rules and 1 documented policy ambiguity were verified against `data/synthetic_policy.pdf`. Quotations match verbatim on the cited 1-based PDF pages (which match printed page numbers 1 through 4 exactly).
2. **Ambiguity Adjudication:** Section 4.1 (`AMB_PRE_EXISTING_CONDITIONS`) references *"as defined under applicable regulations"* without providing the governing statutory framework or waiting period duration. Per project requirements, this ambiguity is explicitly preserved as `needs_review` with `estimated_impact=None`.
3. **Scenario Audit & Expansion:** All 12 initial scenarios were audited and confirmed compliant with policy conditions. 8 new edge cases (`SCENARIO_13` to `SCENARIO_20`) were added to `data/test_cases/`, covering cataract within sub-limit, bilateral cataract surgery with explicit per-eye allocation, pure allowable billings, exact room rent cap boundaries, missing claim form, boundary days 30 vs 31, and isolated professional fees proportional deductions.
4. **Test Suite Expansion & Count Reconciliation:** `tests/test_gold_rulebook.py` was extended from 13 test functions to 25 test functions (the comment labels range from Test 1 to Test 26 because the original test suite combined Test 5 & 6 into a single function `test_quotations_appear_verbatim_on_referenced_pages`). All 25 test functions pass deterministically.
5. **Deterministic Arithmetic:** All financial deductions strictly follow policy clauses using Python `Decimal` arithmetic. Rate excess is strictly distinguished from total claim deductions; missing durations or timeline facts reliably produce `needs_review` with `estimated_impact=None`.

---

## 2. Baseline Test Results & Dependency Diagnostics

### Baseline Diagnostics:
* **Initial Blocker:** The host Python environment (`Python 3.14.3` on Windows) initially lacked required dependencies (`pydantic`, `pymupdf`, `python-dotenv`, `reportlab`, `pillow`, `pytesseract`, `openai`, `streamlit`). Running `pytest` initially failed during test collection with:
  ```text
  ModuleNotFoundError: No module named 'pydantic'
  ```
* **Remediation:** Pinned dependencies from `requirements.txt` were installed into the environment without arbitrary upgrades or downgrades.
* **Pre-Change Baseline Test Results:**
  * `python -m pytest tests/test_gold_rulebook.py -v`: **13 passed, 0 failed** in 40.54s.
  * Full Suite `python -m pytest -v`: **150 passed, 1 skipped, 1 failed** in 13.72s (`test_benchmark_packets.py::test_benchmark_generation_repeatability` failed because generated PDF bytes differ; the exact root cause has not been confirmed).
* **Post-Change Test Results:**
  * `python -m pytest tests/test_gold_rulebook.py -v`: **25 passed, 0 failed, 0 skipped** in 1.39s.
  * `python -m pytest tests/test_rule_engine.py -v`: **8 passed, 0 failed, 0 skipped** in 0.13s (evaluating all 20 scenarios dynamically discovered from `data/test_cases/`).
  * Full Suite `python -m pytest -v`: **162 passed, 1 skipped, 1 failed** in 11.30s. The failure in `test_benchmark_packets.py::test_benchmark_generation_repeatability` is still under investigation. Its root cause and whether it existed before these changes have not yet been established.
---

## 3. Verified Policy Rule Matrix

Every rule from `data/gold_rulebook.json` was audited against `data/synthetic_policy.pdf`.

| Rule / Ambiguity ID | Rule Type | Policy Section | PDF Page | Printed Page | Verbatim Quotation Verified | Validation Status | Human Review Flag | Audit Verdict & Evidence Summary |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **`RULE_REQ_DOCS`** | `required_documents` | Section 1.1 | 1 | Page 1 of 4 | **YES** | `validated` | `false` | **VERIFIED.** Mandates all 3 documents: Claim Form, itemized original Hospital Bill with receipt, and official Hospital Discharge Summary. Incomplete/unprocessed if any is missing. |
| **`RULE_WAITING_PERIOD`** | `waiting_period` | Section 2.1 | 2 | Page 2 of 4 | **YES** | `validated` | `false` | **VERIFIED.** Mandatory 30-day initial waiting period from inception (00:00 day 1 to 23:59 day 30). Illness covered from day 31+. Accidental injury sustained post-inception is explicitly exempt. |
| **`RULE_ROOM_RENT_CAP`** | `room_rent_cap` | Section 2.2 | 2 | Page 2 of 4 | **YES** | `validated` | `false` | **VERIFIED.** Maximum eligible room rent is INR 5000/day. Excess borne by insured. Proportional deduction `5000 / actual_rate` applies strictly to professional fees and OT charges. Other charges (medicines, tests, consumables) explicitly exempt. |
| **`RULE_CATARACT_SUBLIMIT`** | `sub_limit` | Section 3.1 | 3 | Page 3 of 4 | **YES** | `validated` | `false` | **VERIFIED.** Strict monetary sub-limit of INR 40000 per eye, inclusive of surgeon fees, OT charges, and IOL costs. Bilateral cataract surgery evaluated independently per eye (INR 80000 combined ceiling). |
| **`RULE_NON_PAYABLE_ITEMS`** | `non_payable_items` | Section 3.2 | 3 | Page 3 of 4 | **YES** | `validated` | `false` | **VERIFIED.** Lists exactly 7 non-payable items: registration fees, admission processing charges, gloves, face masks, sanitizers, thermometer charges, luxury patient amenity kits. Disallowed in full. |
| **`AMB_PRE_EXISTING_CONDITIONS`** | Ambiguity | Section 4.1 | 4 | Page 4 of 4 | **YES** | `N/A` | `true` (Adjudication) | **VERIFIED REQUIREMENT FOR HUMAN REVIEW.** Section 4.1 excludes pre-existing conditions *"as defined under applicable regulations"* until expiration of statutory waiting period. Regulations and waiting duration are undefined in contract. |

### Page Numbering Convention
* The PDF contains 4 pages.
* Extracted 1-based page indices (`page_number: 1..4`) match the printed footer (`"Page X of 4"`) on every page.
* There is zero offset or discrepancy between physical page indices and printed page numbers.

---

## 4. Scenario Audit Matrix (Scenarios 1 through 20)

Every test scenario in `data/test_cases/` was audited against the policy rules, evidence facts, and financial calculation correctness.

| Scenario ID | Applicable Rules | Finding Status | Claim Facts & Evidence | Missing Info Required | Human Review | Financial Impact | Audit Verdict |
| :--- | :--- | :--- | :--- | :---: | :---: | :---: | :--- |
| **`SCENARIO_01_ALL_DOCUMENTS_PRESENT`** | `RULE_REQ_DOCS` | `satisfied` | Submitted CF-101, Inv #9821, and IPD-4412 | False | False | INR 0.00 | **PASS.** All 3 mandatory documents present. |
| **`SCENARIO_02_REQUIRED_DOCUMENT_MISSING`** | `RULE_REQ_DOCS` | `violated` | Claim Form and Bill submitted; Discharge Summary missing | True | True | `None` | **PASS.** Incomplete claim; financial adjudication suspended. |
| **`SCENARIO_03_WAITING_PERIOD_SATISFIED`** | `RULE_WAITING_PERIOD` | `satisfied` | Admission 45 days post-inception for gastroenteritis (illness) | False | False | INR 0.00 | **PASS.** 45 > 30 days threshold. |
| **`SCENARIO_04_WAITING_PERIOD_NOT_SATISFIED`** | `RULE_WAITING_PERIOD` | `violated` | Admission 14 days post-inception for appendicitis (illness) | False | True | `None` | **PASS.** Illness within waiting period; claim inadmissible. |
| **`SCENARIO_05_ROOM_RENT_WITHIN_LIMIT`** | `RULE_ROOM_RENT_CAP` | `satisfied` | Twin sharing room at INR 4000/day for 3 days | False | False | INR 0.00 | **PASS.** INR 4000 <= INR 5000 cap. |
| **`SCENARIO_06_ROOM_RENT_ABOVE_LIMIT`** | `RULE_ROOM_RENT_CAP` | `violated` | Private suite at INR 7500/day for 4 days; zero fees | False | False | INR 10000.00 | **PASS.** (7500 - 5000) * 4 = INR 10000 excess. |
| **`SCENARIO_07_SUBLIMIT_EXCEEDED`** | `RULE_CATARACT_SUBLIMIT` | `violated` | Left eye cataract billed INR 55000 (surgeon 30k, OT 10k, lens 15k) | False | False | INR 15000.00 | **PASS.** 55000 - 40000 = INR 15000 excess disallowed. |
| **`SCENARIO_08_NON_PAYABLE_ITEM_PRESENT`** | `RULE_NON_PAYABLE_ITEMS` | `violated` | Admission charges (1200) + amenity kits (1800) | False | False | INR 3000.00 | **PASS.** Invoiced excluded items disallowed in full (1200 + 1800 = 3000). |
| **`SCENARIO_09_ACCIDENT_WAITING_PERIOD_EXEMPT`** | `RULE_WAITING_PERIOD` | `satisfied` | Admission on day 10 for tibial fracture from RTA | False | False | INR 0.00 | **PASS.** Accidental injury exception to waiting period applies. |
| **`SCENARIO_10_ROOM_RENT_UNKNOWN_DURATION`** | `RULE_ROOM_RENT_CAP` | `needs_review` | Room rate INR 7000/day; duration `days: None` | True | True | `None` | **PASS.** Known rate excess (INR 2000/day) cannot compute total deduction without duration. |
| **`SCENARIO_11_ROOM_RENT_PROPORTIONAL_DEDUCTION`** | `RULE_ROOM_RENT_CAP` | `violated` | Room 10000/day (2 days), prof fees 20000, OT 15000 | False | False | INR 27500.00 | **PASS.** Excess rent 10000 + prof fee deduction 10000 + OT deduction 7500 = 27500. |
| **`SCENARIO_12_PRE_EXISTING_CONDITION_AMBIGUITY`** | `AMB_PRE_EXISTING_CONDITIONS` | `needs_review` | Essential hypertension with 24-month pre-policy onset | True | True | `None` | **PASS.** Regulatory framework undefined; suspended for human adjuster. |
| **`SCENARIO_13_CATARACT_WITHIN_SUBLIMIT`** *(New)* | `RULE_CATARACT_SUBLIMIT` | `satisfied` | Left eye cataract surgery billed at INR 35000 | False | False | INR 0.00 | **PASS.** INR 35000 <= INR 40000 cap; zero deduction. |
| **`SCENARIO_14_NON_PAYABLE_SCHEDULE_ALL_ALLOWABLE`** *(New)* | `RULE_NON_PAYABLE_ITEMS` | `satisfied` | Itemized bill: consultation (2500), ultrasound (3500), medicines (4500) | False | False | INR 0.00 | **PASS.** Zero non-payable items matched; fully payable. |
| **`SCENARIO_15_ROOM_RENT_EXACT_CAP_BOUNDARY`** *(New)* | `RULE_ROOM_RENT_CAP` | `satisfied` | Room rent billed at exactly INR 5000.00/day for 5 days | False | False | INR 0.00 | **PASS.** Rate == Cap is compliant; zero deduction. |
| **`SCENARIO_16_MANDATORY_DOCUMENTS_CLAIM_FORM_MISSING`** *(New)* | `RULE_REQ_DOCS` | `violated` | Hospital Bill & Discharge Summary present; Claim Form missing | True | True | `None` | **PASS.** Mandatory claim form missing; incomplete claim. |
| **`SCENARIO_17_WAITING_PERIOD_BOUNDARY_DAY_30_VIOLATED`** *(New)* | `RULE_WAITING_PERIOD` | `violated` | Admission on day 30 post-inception for illness | False | True | `None` | **PASS.** Day 30 <= 30-day waiting period; excluded. |
| **`SCENARIO_18_WAITING_PERIOD_BOUNDARY_DAY_31_SATISFIED`** *(New)* | `RULE_WAITING_PERIOD` | `satisfied` | Admission on day 31 post-inception for illness | False | False | INR 0.00 | **PASS.** Day 31 > 30-day waiting period; satisfied. |
| **`SCENARIO_19_CATARACT_BILATERAL_SURGERY_EXCEEDED`** *(New)* | `RULE_CATARACT_SUBLIMIT` | `violated` | Bilateral surgery billed at INR 47500 per eye (total INR 95000) | False | False | INR 15000.00 | **PASS.** Each eye independently exceeds INR 40000 by INR 7500; total excess = INR 15000.00. |
| **`SCENARIO_20_ROOM_RENT_PROPORTIONAL_ONLY_SURGEON_FEE`** *(New)* | `RULE_ROOM_RENT_CAP` | `violated` | Room 8000/day (3 days), surgeon fee 16000, OT 0 | False | False | INR 15000.00 | **PASS.** Excess rent 9000 + prof fee deduction 6000 + OT deduction 0 = 15000. |

---

## 5. Financial Correctness and Boundary Analysis

### 1. Distinction Between Rate Excess and Final Claim Deduction
* A room rent excess rate (e.g. ₹7,500/day billed vs ₹5,000/day cap = ₹2,500/day excess) is deterministic **per day**.
* A final total deduction requires confirmed length of stay (`days`).
* In `SCENARIO_10`, where duration is missing (`days: None`), the rule engine correctly rejects calculating speculative deductions and flags `status: needs_review` with `estimated_impact: null`.

### 2. Proportional Deduction Applicability & Isolation
* Under Section 2.2:
  $$\text{Payable Ratio} = \frac{5000}{\text{Actual Daily Rate}}$$
  $$\text{Disallowance Ratio} = 1.0 - \text{Payable Ratio}$$
* The policy explicitly limits this deduction to **associated professional fees and operation theatre charges**.
* Tested in `test_proportional_deduction_exempts_other_hospital_charges`: Inpatient pharmacy charges of ₹20,000 remain 100% untouched while professional fees are proportionally reduced.

### 3. Cataract Surgery Sub-Limit & Bilateral Per-Eye Allocation
* Single eye limit: ₹40,000.
  * ₹40,000 billed $\rightarrow$ ₹0 deduction (`satisfied`).
  * ₹40,001 billed $\rightarrow$ ₹1 deduction (`violated`).
* Bilateral cataract surgery (Section 3.1):
  * The `RULE_CATARACT_SUBLIMIT` rulebook parameter `unit: "per_eye"` establishes that the ₹40,000 sub-limit is applied independently to each eye. Section 3.1 of the policy states: *"Reimbursement for cataract surgery shall be subject to a strict monetary sub-limit of INR 40000 per eye"* — the phrase "per eye" is the textual basis for independent per-eye evaluation. No additional bilateral-specific clause has been identified in the policy text; the per-eye application follows directly from the `unit: "per_eye"` parameter.
  * In `SCENARIO_19`, the claim facts explicitly allocate the ₹95,000 procedure charges per eye: Left Eye = ₹47,500 and Right Eye = ₹47,500.
  * Left Eye excess over ₹40,000 sub-limit: ₹47,500 - ₹40,000 = ₹7,500.
  * Right Eye excess over ₹40,000 sub-limit: ₹47,500 - ₹40,000 = ₹7,500.
  * Total combined non-payable deduction: ₹7,500 + ₹7,500 = ₹15,000.00. This calculation strictly follows from the policy's independent per-eye evaluation clause and the itemized claim facts.

### 4. Non-Payable Items Disallowance
* Only the 7 items explicitly enumerated in Section 3.2 are disallowed: registration fees, admission processing charges, gloves, face masks, sanitizers, thermometer charges, and luxury patient amenity kits.
* Tested with both isolated non-payable items (`SCENARIO_08`, `test_all_seven_non_payable_items_recognized`) and completely allowable bills (`SCENARIO_14`).

---

## 6. Test Suite Architecture & Count Reconciliation

### Test Count Reconciliation in `tests/test_gold_rulebook.py`:
* The test file contains **25 test functions** in total:
  * **Original test suite (13 test functions):** Comments labeled `# Test 1` through `# Test 14` because `# Test 5 & 6` was a single test function (`test_quotations_appear_verbatim_on_referenced_pages`).
  * **Person 2 additions (12 test functions):** Comments labeled `# Test 15` through `# Test 26`.
  * Total test functions collected and executed by `pytest`: **13 + 12 = 25 test functions**.
* All 25 test functions pass deterministically:
  1. `test_synthetic_pdf_exists_and_parseable`
  2. `test_gold_rulebook_schema_validation`
  3. `test_all_five_rule_types_represented`
  4. `test_rule_ids_unique`
  5. `test_quotations_appear_verbatim_on_referenced_pages` (covers Tests 5 & 6)
  6. `test_claim_scenarios_load_and_validate` (Test 7)
  7. `test_scenarios_reference_valid_rule_ids` (Test 8)
  8. `test_all_required_scenario_categories_covered` (Test 9)
  9. `test_expected_findings_use_permitted_statuses` (Test 10)
  10. `test_financial_impacts_justified_and_grounded` (Test 11)
  11. `test_room_rent_rule_parameters` (Test 12)
  12. `test_scenario_11_proportional_deduction` (Test 13)
  13. `test_scenario_12_ambiguity_needs_review` (Test 14)
  14. `test_all_rules_parameter_types_and_values` (Test 15)
  15. `test_quotation_mismatch_fails_verification` (Test 16)
  16. `test_citation_page_out_of_bounds_detected` (Test 17)
  17. `test_quotation_on_wrong_page_detected` (Test 18)
  18. `test_schema_rejects_unsupported_rule_type` (Test 19)
  19. `test_room_rent_rate_boundaries` (Test 20)
  20. `test_room_rent_above_cap_missing_duration_keeps_impact_unknown` (Test 21)
  21. `test_cataract_sublimit_boundaries_and_bilateral` (Test 22)
  22. `test_proportional_deduction_exempts_other_hospital_charges` (Test 23)
  23. `test_all_seven_non_payable_items_recognized` (Test 24)
  24. `test_unverified_rule_status_forces_human_review` (Test 25)
  25. `test_ambiguity_requires_review_without_guessing` (Test 26)

### Active Scenario Discovery:
* All 20 scenarios in `data/test_cases/` are dynamically loaded by `TEST_CASES_DIR.glob("scenario_*.json")` in `test_gold_rulebook.py` and `test_rule_engine.py`.
* In `test_rule_engine.py::test_all_scenarios_evaluation_matches_expected`, all 20 scenarios are evaluated against `evaluate(gold_rulebook, sc.claim_facts, sc.applicable_rule_ids)`, verifying finding status, estimated impact, and calculation steps against the deterministic rule engine.

---

## 7. Files Changed and Git Working Tree

### Modified Files:
* `tests/test_gold_rulebook.py` (+319 lines): Added 12 new validation tests covering parameter schemas, boundary conditions, citation tampering, and human review flags.
* `docs/audit_report.md` (New): This comprehensive Person 2 audit report.

### New Test Cases Added (`data/test_cases/`):
* `scenario_13_cataract_within_sublimit.json`
* `scenario_14_non_payable_schedule_all_allowable.json`
* `scenario_15_room_rent_exact_cap_boundary.json`
* `scenario_16_mandatory_documents_claim_form_missing.json`
* `scenario_17_waiting_period_boundary_day_30_violated.json`
* `scenario_18_waiting_period_boundary_day_31_satisfied.json`
* `scenario_19_cataract_bilateral_surgery_exceeded.json`
* `scenario_20_room_rent_proportional_only_surgeon_fee.json`

### Git Handoff Information:
* **Current Branch:** `main`
* **Working Tree Status:** Clean modifications in `tests/test_gold_rulebook.py`, untracked new scenarios in `data/test_cases/`, and audit report in `docs/audit_report.md`.
* **Staged Changes:** None (strictly per rule: no automatic staging or committing without user authorization).
* **Recommended Commit Message:**
  ```text
  test(validation): complete person 2 data and ground-truth audit with 8 edge cases and 12 regression tests
  
  - Audit all 5 policy rules and Section 4.1 ambiguity against synthetic_policy.pdf
  - Add scenarios 13-20 covering cataract bilateral, allowable items, cap boundaries, and missing documents
  - Allocate bilateral cataract expenses per eye in scenario 19 under Section 3.1
  - Extend test_gold_rulebook.py to 25 tests with citation verification, parameter types, and fee isolation
  - Document complete audit matrix, financial arithmetic, and baseline results in docs/audit_report.md
  ```
