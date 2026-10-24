# ClaimCheck 2.0

Policy Compiler and Claim Intelligence Agent for Health Insurance Reimbursement

ClaimCheck 2.0 is an evidence-grounded system engineered to parse, verify, and cross-reference medical reimbursement claims against health insurance policy documents using verifiable source citations, deterministic calculation, and bounded agentic investigation.

---

## 1. Overview

Health insurance reimbursement is prone to arbitrary denials, calculation discrepancies, and unverified deductions. ClaimCheck 2.0 introduces a deterministic, evidence-grounded architecture:
- Policy terms are compiled into structured, verifiable rules backed by page citations and verbatim text quotes.
- Medical bills and claim forms are parsed into structured claim facts.
- Operative coverage limits (room-rent caps, waiting periods, sub-limits, non-payable item lists) are evaluated using pure deterministic Python arithmetic (Decimal).
- Policy ambiguities or missing documents are handled by a bounded agent (maximum 2 iterations) capable of querying statutory guidance via Tavily or requesting claimant input.
- Every approved or deducted amount is directly traceable to exact page numbers and verbatim text in the governing policy.

---

## 2. Architecture

The system operates across four decoupled layers:
1. LLM Compiles: NVIDIA Nemotron reasoning models compile natural-language policy clauses into structured rules with verbatim citations.
2. Python Executes: Deterministic Python engine evaluates rules against claim facts without stochastic drift or rounding errors.
3. Agent Investigates: Bounded agent selects actions (ask user, search statutory guidance, or escalate) with a hard cap of 2 iterations.
4. Python Verifies: In-memory PyMuPDF citation verification checks quotes on cited pages before findings or deductions are finalized.

```mermaid
flowchart TD
    A[Policy PDF] --> B[Policy Compiler - Nemotron Reasoning]
    B --> C[Compiled Rulebook & Ambiguities]
    C --> D[Citation Verification - PyMuPDF]
    D --> E[Validated Rules]

    F[Claim PDFs] --> G[Claim Fact Extractor - Nemotron Fast]
    G --> H[Extracted Claim Facts]

    E --> I[Deterministic Rule Engine - Python]
    H --> I
    I --> J[Findings: Satisfied, Violated, Needs Review, Unable to Verify]

    J --> K{Unresolved Items?}
    K -- Yes --> L[Bounded Investigation Agent - Max 2 Iterations]
    L --> M[Ask User for Missing Fact]
    L --> N[Tavily Search for Statutory Context]
    L --> O[Escalate to Human Adjuster]
    M --> H
    N --> P[External Guidance Attached]
    O --> Q[Human Review Flagged]

    K -- No --> R[Evidence-Grounded Markdown Report]
    P --> R
    Q --> R
    J --> R
```

---

## 3. Features Implemented

All features listed below are implemented and tested in the codebase:

### Core Processing and Adjudication
- Local PDF Text Extraction [MOCK, LIVE]: In-memory text extraction preserving 1-based page numbers using PyMuPDF.
- Low-Text Density / Scanned Detection [MOCK, LIVE]: Automatic detection of image-only pages requiring OCR.
- Deterministic Rule Engine [MOCK, LIVE]: Pure deterministic evaluation of five core health policy rules:
  - Required Documents check
  - Initial Waiting Period check (with accident exemption)
  - Proportional Room Rent Cap (with associated proportional scaling of OT and professional fees)
  - Specific Disease Sub-limits (e.g. Cataract surgery limits)
  - Non-Payable Items List exclusion
- Cross-Document Conflict Scoping [MOCK, LIVE]: Scoped duplicate detection ensuring distinct sub-bill totals (e.g. room rent vs professional fees) do not trigger false conflicts.
- Evidence Citation Highlighter [MOCK, LIVE]: In-memory PyMuPDF rendering with exact clause bounding box highlight annotations.
- Bounded Investigation Agent [MOCK, LIVE]: Fast model action selector with strict JSON validation, Pydantic schema enforcement, and a hard cap of 2 iterations.
- Tavily Regulatory Search Client [MOCK, LIVE]: Standard library (urllib) integration querying statutory guidelines with an in-memory audit log and injectable test transport.
- Clean 5-Tab User Interface [MOCK, LIVE]: Built with Streamlit, containing Overview, Policy rulebook, Findings, Needs your input, and Report export. Plain-text status badges (color + text), zero emojis.

### Features Not Yet Measured
The following benchmarks and evaluations have offline infrastructure prepared, but live cloud model metrics are not yet measured:
- End-to-end cloud latency on live Nebius Token Factory endpoints: not yet measured
- Live Nemotron compiler precision and recall on unseen 100-page commercial policies: not yet measured
- Live token consumption and financial cost across 20 synthetic packets: not yet measured

---

## 4. Configuration

ClaimCheck 2.0 reads settings from system environment variables (loaded via `.env`) or falls back to `.streamlit/secrets.toml` when deployed on Streamlit Community Cloud. Secret values are never printed, logged, or hard-coded.

| Variable Name | Purpose | Required For | Source / Provider | Placeholder Value |
| :--- | :--- | :--- | :--- | :--- |
| `NEBIUS_API_KEY` | Authentication token | Live Mode | Nebius Token Factory | `your_nebius_api_key_here` |
| `NEBIUS_BASE_URL` | API endpoint URL | Live Mode | Nebius Token Factory | `https://api.tokenfactory.nebius.com/v1/` |
| `NEBIUS_MODEL_REASONING` | Model for policy compilation | Live Mode | NVIDIA Nemotron | `<model id from your Token Factory catalog>` |
| `NEBIUS_MODEL_FAST` | Model for extraction & agent | Live Mode | NVIDIA Nemotron | `<model id from your Token Factory catalog>` |
| `TAVILY_API_KEY` | External regulatory search | Agent Search | Tavily API | `your_tavily_api_key_here` |
| `TESSERACT_CMD` | Path to Tesseract executable | Scanned PDF OCR | Local Installation | (leave empty for default discovery) |
| `TESSDATA_PREFIX` | Path to Tesseract traineddata | Scanned PDF OCR | Local Installation | (leave empty for default discovery) |

### Deployment Secrets
For Streamlit Community Cloud:
1. Refer to `.streamlit/secrets.toml.example`.
2. In your Streamlit app dashboard, navigate to `App Settings` -> `Secrets`.
3. Paste the configuration keys and fill in your actual credentials.
4. `.gitignore` is pre-configured to ensure `.env` and `.streamlit/secrets.toml` are never committed.

### OCR Configuration (Tesseract)
- Windows PowerShell:
  ```powershell
  $env:TESSERACT_CMD = "C:\Program Files\Tesseract-OCR\tesseract.exe"
  $env:TESSDATA_PREFIX = "C:\Program Files\Tesseract-OCR\tessdata"
  ```
- Linux / macOS:
  ```bash
  export TESSERACT_CMD="/usr/bin/tesseract"
  export TESSDATA_PREFIX="/usr/share/tesseract-ocr/5/tessdata"
  ```

---

## 5. Setup on Windows PowerShell

### Step 1: Create and Activate Virtual Environment
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### Step 2: Install Pinned Dependencies
```powershell
pip install -r requirements.txt
```

### Step 3: Configure Environment
Copy the example environment file:
```powershell
Copy-Item .env.example .env
```
Edit `.env` to supply your API credentials if running in Live mode. If testing in Mock mode, no edits are required.

---

## 6. How to Run

### Launch Interactive Streamlit App
```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```
Open `http://localhost:8501` in your browser.

### Run Automated Test Suite
```powershell
.\.venv\Scripts\python.exe -m pytest -v
```

### Run Benchmark Evaluation
- Mock Mode (Offline ground truth):
  ```powershell
  .\.venv\Scripts\python.exe benchmark/evaluate.py --strategy mock --packets all
  ```
- Live Mode (Requires configured Nebius credentials):
  ```powershell
  .\.venv\Scripts\python.exe benchmark/evaluate.py --strategy routed --packets all
  ```

---

## 7. Nebius and NVIDIA Model Usage

ClaimCheck 2.0 is designed exclusively for open NVIDIA Nemotron models hosted on Nebius Token Factory:
- Policy Reasoning Model (`NEBIUS_MODEL_REASONING`): Utilized for parsing unstructured policy legal prose into deterministic schemas and detecting latent ambiguities.
- Extraction and Agent Model (`NEBIUS_MODEL_FAST`): Utilized for structured line-item fact extraction from bills and strict JSON action selection (`ask_user`, `search_tavily`, `escalate`).
- Model IDs are read strictly from configuration and are never hard-coded.
- In Mock mode, no network calls or model requests are initiated.

---

## 8. Tavily Usage

Tavily is utilized exclusively for statutory and regulatory search when policy terms reference external undefined regulations (such as IRDAI guidelines):
- Built using only Python standard library `urllib`.
- Hard-capped at 3 results per query.
- Results are marked as "External guidance (not part of the policy)".
- External search results provide context to adjusters but never overwrite or mutate deterministic policy rule evaluations.
- In-memory audit log records every search query, URL, and timestamp.

---

## 9. Evaluation Results

The evaluation harness benchmarks deterministic accuracy across 20 synthetic claim packets covering admissible claims, waiting period violations, proportional room-rent deductions, and ambiguous exclusions.

| Metric | Mock Mode (Deterministic Baseline) | Live Routed Mode (Nemotron + Deterministic) |
| :--- | :--- | :--- |
| Operative Rule Precision | 1.00 (20/20 packets) | not yet measured |
| Proportional Arithmetic Accuracy | 1.00 (exact match) | not yet measured |
| False Violation Warning Rate | 0.00 | not yet measured |
| Citation Verification Accuracy | 1.00 | not yet measured |
| Average Latency per Packet | 0.018s | not yet measured |
| Estimated API Cost per Packet | INR 0.00 | not yet measured |

---

## 10. Limitations and Honesty Notes

1. Synthetic Data: The policies and claim packets provided in `data/` are synthetic test representations designed to validate edge-case calculation logic and citation fidelity.
2. Not an Insurer Decision: ClaimCheck 2.0 is an adjudication audit tool. All calculations and findings are estimates intended for audit assistance and do not constitute an official underwriting approval or denial.
3. OCR Dependencies: Full image OCR transcription requires external Tesseract binaries and language files (`eng.traineddata`). In environments without Tesseract, scanned pages are safely flagged as `ocr_unavailable` rather than generating hallucinated content.
4. Human Review Mandatory: Any finding flagged as `NEEDS REVIEW` or `UNABLE TO VERIFY` requires licensed human claims adjuster intervention.
