"""Time each live AI step separately (policy compile with Super, claim extraction with Nano).

Usage:  python scripts/time_live.py [demo_case_folder_name]
Prints timings only; never prints the API key.
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ai import nebius_client  # noqa: E402

# Wrap the API call so we can see each request's duration and token use.
_orig = nebius_client.chat_json


def timed_chat_json(client, model, system, user, **kw):
    real_create = client.chat.completions.create

    def create(**args):
        t = time.time()
        r = real_create(**args)
        u = getattr(r, "usage", None)
        print(f"   call {args['model'].split('/')[-1]}  max_tokens={args.get('max_tokens')}  "
              f"{time.time() - t:5.1f}s  finish={r.choices[0].finish_reason}  "
              f"out_tokens={getattr(u, 'completion_tokens', '?')}", flush=True)
        return r

    client.chat.completions.create = create
    return _orig(client, model, system, user, **kw)


import src.ai.policy_compiler as pc  # noqa: E402
import src.ai.claim_extractor as ce  # noqa: E402
pc.chat_json = timed_chat_json
ce.chat_json = timed_chat_json

from src.pipeline import compile_policy  # noqa: E402
from src.ai.claim_loader import load_claim_document  # noqa: E402

case = sys.argv[1] if len(sys.argv) > 1 else None
cases = sorted(p for p in (ROOT / "data" / "demo_cases").iterdir() if p.is_dir())
folder = next((c for c in cases if case and case in c.name), cases[0])
policy = (ROOT / "data" / "synthetic_policy.pdf").read_bytes()

print("1) Policy compile (Nemotron Super)...", flush=True)
t = time.time()
comp = compile_policy(policy)
print(f"   -> {len(comp.to_rulebook().rules)} rules in {time.time() - t:.1f}s\n", flush=True)

pdfs = sorted(folder.glob("*.pdf"))
print(f"2) Claim extraction (Nemotron Nano) for {folder.name}, {len(pdfs)} documents...", flush=True)
t = time.time()
docs = [load_claim_document(p.read_bytes(), document_id=p.name) for p in pdfs]
res = ce.extract_claim_facts(docs)
print(f"   -> {len(res.facts)} facts in {time.time() - t:.1f}s", flush=True)
