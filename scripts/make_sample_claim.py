"""Generate a synthetic sample claim (3 PDFs) for demos of the claim fact extractor.

Usage:  python scripts/make_sample_claim.py
Writes data/sample_claims/{claim_form,hospital_bill,discharge_summary}.pdf.
All names and numbers are fictional. The case mirrors scenario 06 (room rent above
the INR 5000/day cap) plus two non-payable items, so the rule engine has work to do.
"""

from pathlib import Path

import pymupdf as fitz

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "sample_claims"

DOCUMENTS = {
    "claim_form.pdf": [
        "AURA HEALTH INSURANCE - REIMBURSEMENT CLAIM FORM",
        "Policy number: POL-AURA-2026-001",
        "Insured person: Synthetic Patient A",
        "Policy inception date: 2026-01-01",
        "Claim type: Hospitalization reimbursement",
        "Documents enclosed: Claim Form, Hospital Bill, Discharge Summary",
        "Signature of insured: [signed]",
    ],
    "hospital_bill.pdf": [
        "CITY CARE HOSPITAL - FINAL ITEMIZED BILL",
        "Bill number: CCH-2026-04417",
        "Patient: Synthetic Patient A",
        "Executive Suite Room Charges: 4 days @ INR 7500.00 per day = INR 30000.00.",
        "Consultation charges: INR 6000.00",
        "Pharmacy and consumables: INR 8400.00",
        "Admission processing charges: INR 1200.00",
        "Luxury patient amenity kit: INR 1800.00",
        "Total billed: INR 47400.00",
        "Payment received in full. Receipt number: RCPT-88213",
    ],
    "discharge_summary.pdf": [
        "CITY CARE HOSPITAL - DISCHARGE SUMMARY",
        "Patient: Synthetic Patient A",
        "Date of admission: 2026-02-15",
        "Date of discharge: 2026-02-19",
        "Cause of hospitalization: Illness",
        "Diagnosis: Acute viral gastroenteritis",
        "Treatment: IV fluids, antiemetics, observation",
        "Condition at discharge: Stable",
    ],
}


def write_pdf(path: Path, lines: list[str]) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(fitz.Point(40, 72), "\n".join(lines), fontsize=10)
    doc.save(str(path))
    doc.close()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, lines in DOCUMENTS.items():
        write_pdf(OUT / name, lines)
        print(f"Wrote {OUT / name}")


if __name__ == "__main__":
    main()
