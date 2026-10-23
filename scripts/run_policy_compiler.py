"""Run the Nemotron policy compiler on the synthetic policy and compare with the gold rulebook.

Usage:  python scripts/run_policy_compiler.py
Needs NEBIUS_API_KEY and NEBIUS_MODEL_REASONING in .env. Makes ONE real Token Factory call.
"""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.ai.policy_compiler import compile_policy_rules  # noqa: E402
from src.documents.policy_document import load_document  # noqa: E402
from src.schemas import Rulebook  # noqa: E402


def main():
    policy = load_document(ROOT / "data" / "synthetic_policy.pdf")
    gold = Rulebook.model_validate(
        json.loads((ROOT / "data" / "gold_rulebook.json").read_text(encoding="utf-8"))
    )

    start = time.time()
    result = compile_policy_rules(policy, policy_id=gold.policy_id)
    seconds = time.time() - start

    gold_types = {r.rule_type for r in gold.rules}
    found_types = {r.rule_type for r in result.rules}

    print(f"Model: {result.model}   time: {seconds:.1f}s")
    print(f"Rules extracted: {len(result.rules)}   rejected: {len(result.rejected)}")
    print(f"Citations verified: {result.verified_count}/{len(result.rules)}")
    print(f"Rule types matched: {len(gold_types & found_types)}/{len(gold_types)}")
    if gold_types - found_types:
        print("Missing types:", ", ".join(sorted(gold_types - found_types)))

    print("\nPer rule:")
    for rule in result.rules:
        check = result.citation_checks[rule.rule_id]
        mark = "OK " if check.verified else "BAD"
        print(f"  [{mark}] {rule.rule_id} ({rule.rule_type}) page {rule.source.page}: {check.reason}")

    print("\nParameters vs gold:")
    for g in gold.rules:
        match = next((r for r in result.rules if r.rule_type == g.rule_type), None)
        print(f"  {g.rule_type}")
        print(f"    gold:     {g.parameters}")
        print(f"    nemotron: {match.parameters if match else 'MISSING'}")

    for msg in result.rejected:
        print("  rejected:", msg)

    out = ROOT / "evaluation" / "policy_compiler_run.json"
    out.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()