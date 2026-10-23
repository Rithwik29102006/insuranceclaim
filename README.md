# ClaimCheck 2.0

> Evidence-Grounded Health Insurance Reimbursement Analysis System

ClaimCheck 2.0 is an evidence-grounded system engineered to parse, verify, and cross-reference medical reimbursement claims against health insurance policy documents with verifiable source citations and deterministic evaluation.

---

## 1. Project Status & Implemented Features

### ✅ Implemented Features (Phase 1 Foundation)
- **Local PDF Text Extraction (`src/documents/pdf_extractor.py`)**:
  - In-memory PDF parsing using PyMuPDF (`fitz`), eliminating unnecessary disk writes.
  - Page-by-page extraction preserving 1-based page numbers.
  - Structured output backed by validated Pydantic models (`DocumentExtraction`, `PageExtraction`).
  - Automatic detection of low-text density pages that require Optical Character Recognition (OCR).
  - Robust exception handling (`PDFExtractionError`) for corrupted, empty, or unparseable PDFs.
- **OCR Integration Layer (`src/documents/ocr.py`)**:
  - Image-based OCR utilities via Pillow and `pytesseract`.
  - Dynamic discovery of Tesseract OCR via `TESSERACT_CMD` environment variable, system PATH, and standard Windows paths.
  - Safe failure modes (`TesseractNotFoundError`, `OCRError`) without silent fake text generation.
- **Interactive Streamlit Development Interface (`app.py`)**:
  - Dual file uploaders for synthetic policy documents and synthetic claim documents.
  - Separate document processing pipelines for policy and claim inputs.
  - Page count metrics and expandable page-by-page text views.
  - Prominent visual alerts for pages flagged as needing OCR.
  - Safe local execution with zero remote API dependencies.
- **Automated Test Suite (`tests/`)**:
  - Pytest test cases generating synthetic PDF byte streams in memory.
  - Tests covering page numbering, text extraction, OCR threshold detection, corrupted PDF handling, and OCR fallback/mocking.

### ⏳ Features Not Yet Implemented (Future Phases)
- **NVIDIA Nemotron / Nebius Token Factory Pipeline**:
  - Integration with Nebius Token Factory is pending access approval and promotional credits.
  - No remote model calls or API completions are executed in this phase.
- **Policy Rule Compiler (`src/ai/policy_compiler.py`)**:
  - Currently a documented placeholder. Future versions will parse policy clauses into structured deterministic rules.
- **Claim Fact Extractor (`src/ai/claim_extractor.py`)**:
  - Currently a documented placeholder. Future versions will extract line-item charges and map them to exact document citations.
- **Deterministic Rule Engine (`src/engine/rule_engine.py`)**:
  - Currently a documented placeholder. Arithmetic, deductible rules, and coverage exclusions will be evaluated deterministically.
- **Bounded Investigation Agent (`src/agent/investigator.py`)**:
  - Currently a documented placeholder. Will handle ambiguities within bounded iteration limits (3–5 cycles).
- **Evidence-Grounded Reporting (`src/reports/report_generator.py`)**:
  - Currently a documented placeholder. Will output audit trails linking approved/deducted amounts to exact page quotes.

> [!IMPORTANT]
> **Pending Nebius Integration Notice**: Nebius Token Factory access and promotional credits are pending. No AI models have been connected or tested yet. The system currently runs completely locally without external API keys.

---

## 2. Prerequisites

1. **Python**: 3.10+ (tested with Python 3.11).
2. **Git**: Installed and accessible in PowerShell.
3. **Tesseract OCR (Optional for scanned image documents)**:
   - If installed on Windows, the default location is `C:\Program Files\Tesseract-OCR\tesseract.exe`.
   - Download installer: [UB-Mannheim Tesseract Releases](https://github.com/UB-Mannheim/tesseract/wiki).
   - If installed elsewhere or not added to PATH, configure `TESSERACT_CMD` in `.env`.

---

## 3. Windows PowerShell Setup Guide

Run the following commands from the project root (`claimcheck`):

### Step 1: Create Virtual Environment
```powershell
python -m venv .venv
```

### Step 2: Activate the Virtual Environment
```powershell
.\.venv\Scripts\Activate.ps1
```

> **PowerShell Execution Policy Note**:
> If PowerShell blocks script execution with an error like `File ... cannot be loaded because running scripts is disabled on this system`, you can run commands directly using the virtual environment's Python executable without altering system-wide execution policies:
> ```powershell
> .\.venv\Scripts\python.exe -m pip install -r requirements.txt
> .\.venv\Scripts\python.exe -m streamlit run app.py
> .\.venv\Scripts\python.exe -m pytest
> ```
> Or temporarily allow script execution in the current PowerShell process only:
> ```powershell
> Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
> .\.venv\Scripts\Activate.ps1
> ```

### Step 3: Upgrade pip and Install Dependencies
```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

To verify the installation:
```powershell
python -c "import streamlit, fitz, pydantic, PIL, pytesseract; print('All core dependencies imported successfully!')"
```

---

## 4. Environment Variables Configuration

Copy the example configuration to `.env`:
```powershell
Copy-Item .env.example .env
```

Contents of `.env.example`:
```env
NEBIUS_API_KEY=
NEBIUS_BASE_URL=https://api.tokenfactory.nebius.com/v1/
NEBIUS_MODEL_REASONING=
NEBIUS_MODEL_FAST=
TAVILY_API_KEY=
TESSERACT_CMD=
```

- Leave API keys blank during Phase 1. The application does not require any keys to run.
- If Tesseract is installed at a non-standard path, specify:
  ```env
  TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
  ```
- **Security**: `.env` and `.venv/` are strictly ignored by `.gitignore`. Never commit API keys.

---

## 5. Running the Streamlit Application

Start the local Streamlit dashboard:
```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```
Or with an activated virtual environment:
```powershell
streamlit run app.py
```

The app will launch at `http://localhost:8501`.

---

## 6. Running Automated Tests

Run the test suite with pytest:
```powershell
.\.venv\Scripts\python.exe -m pytest -v
```

All test cases generate synthetic in-memory PDFs and mock external dependencies, ensuring 100% deterministic local test execution.
