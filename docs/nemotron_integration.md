# How ClaimCheck uses NVIDIA Nemotron on Nebius Token Factory

ClaimCheck does not trust model output on its own. Nemotron reads the documents and proposes
structured rules and facts; deterministic code then checks every citation against the PDF text
before anything reaches the rule engine.

## Pipeline

```
Policy PDF ──► load_document() ──► Nemotron 3 Super ──► Rules ──► check_citation() ──┐
                (PyMuPDF + OCR)    (policy_compiler)                                 ├──► Rule engine ──► Findings
Claim PDFs ──► load_document() ──► Nemotron 3 Nano ───► Facts ──► check_citation() ──┘
                                   (claim_extractor)
```

| Step | Module | Model | Why this model |
|---|---|---|---|
| Policy → rules | `src/ai/policy_compiler.py` | `nvidia/nemotron-3-super-120b-a12b` | Runs once per policy; needs careful reading of clauses and exceptions |
| Claim → facts | `src/ai/claim_extractor.py` | Nemotron 3 Nano 30B-A3B | Runs on every claim; fast and cheap |
| Citation check | `src/documents/evidence.py` | none (deterministic) | A quote must appear verbatim on the cited page, or the item is flagged for human review |

All calls go through `src/ai/nebius_client.py`, using Token Factory's OpenAI-compatible API.
Model IDs are configured in `.env` (`NEBIUS_MODEL_REASONING`, `NEBIUS_MODEL_FAST`).

## Guardrails

- **Verified citations.** Every rule and fact carries a document, page and verbatim quote. A quote that is
  not on the cited page (invented, paraphrased or wrong page) is flagged, never silently accepted.
- **AI rules are drafts.** Compiled rules are saved with `validation_status="draft"`; rules with unverified
  citations are also marked `human_review_required=True`.
- **No model arithmetic.** Derived values such as days since policy inception are recomputed in code.
- **Schema validation.** Responses are validated with Pydantic; malformed or unknown items are rejected
  with a reason instead of crashing.
- **Offline tests.** The test suite uses a fake client, so it runs without an API key or network.

## Results on the synthetic policy

| Measure | Result |
|---|---|
| Rule types found | 5 / 5 |
| Citations verified verbatim on the cited page | 5 / 5 |
| Key values (30-day wait, ₹5,000/day room cap, ₹40,000/eye cataract limit, 7 non-payable items) | all correct |
| Time for one compile call (Nemotron 3 Super) | about 11 s |

Claim extractor on `data/sample_claims/`: _fill in after running `python scripts/run_claim_extractor.py`_.

## Try it

```bash
cp .env.example .env            # add NEBIUS_API_KEY and the two Nemotron model IDs
python scripts/run_policy_compiler.py
python scripts/make_sample_claim.py
python scripts/run_claim_extractor.py
python -m pytest -v             # offline, no API key needed
```
