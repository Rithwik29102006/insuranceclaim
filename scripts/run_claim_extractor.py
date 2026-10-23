"""Run the Nemotron claim fact extractor on the sample claim PDFs.

Usage:  python scripts/run_claim_extractor.py [pdf ...]
Defaults to every PDF in data/sample_claims (create them with scripts/make_sample_claim.py).
Needs NEBIUS_API_KEY and NEBIUS_MODEL_FAST in .env. Makes ONE real Token Factory call.
"""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.ai.claim_extractor import extract_claim_facts  # noqa: E402
from src.documents.policy_document import load_document  # noqa: E402


def main():
    paths = [Path(p) for p in sys.argv[1:]] or sorted((ROOT / "data" / "sample_claims").glob("*.pdf"))
    if not paths:
        sys.exit("No claim PDFs found. Run: python scripts/make_sample_claim.py")

    documents = [load_document(p) for p in paths]
    print("Documents:", ", ".join(d.document_id for d in documents))

    gold = json.loads((ROOT / "data" / "gold_rulebook.json").read_text(encoding="utf-8"))
    non_payable = next(
        (rule["parameters"].get("excluded_items", []) for rule in gold["rules"]
         if rule["rule_type"] == "non_payable_items"),
        [],
    )

    start = time.time()
    result = extract_claim_facts(documents, non_payable_items=non_payable)
    seconds = time.time() - start

    print(f"Model: {result.model}   time: {seconds:.1f}s")
    print(f"Facts extracted: {len(result.facts)}   rejected: {len(result.rejected)}")
    print(f"Citations verified: {result.verified_count}/{len(result.facts)}")

    print("\nFacts:")
    for fact in result.facts:
        check = result.citation_checks[fact.name]
        mark = "OK " if check.verified else "BAD"
        print(f"  [{mark}] {fact.name}  ({fact.source.document} p{fact.source.page}: {check.reason})")
        print(f"        {json.dumps(fact.value)}")

    for msg in result.rejected:
        print("  rejected:", msg)

    out = ROOT / "evaluation" / "claim_extractor_run.json"
    out.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
