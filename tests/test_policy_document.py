"""Tests for the document loader with OCR fallback."""

from pathlib import Path
from unittest.mock import patch

import pymupdf as fitz
import pytest

from src.documents.ocr import OCRError
from src.documents.pdf_extractor import PDFExtractionError
from src.documents.policy_document import load_document

ROOT = Path(__file__).resolve().parent.parent
POLICY_PDF = ROOT / "data" / "synthetic_policy.pdf"
MOD = "src.documents.policy_document"

LONG_TEXT = "Normal detailed text exceeding the minimum character threshold easily for this page."
OCR_TEXT = "Scanned hospital bill: room charges 7500 per day for four days, total 30000."


def _make_pdf(pages_text):
    doc = fitz.open()
    for text in pages_text:
        page = doc.new_page()
        if text:
            page.insert_text(fitz.Point(50, 72), text, fontsize=12)
    data = doc.tobytes()
    doc.close()
    return data


def test_loads_synthetic_policy_from_path():
    result = load_document(POLICY_PDF)
    assert result.document_id == "synthetic_policy.pdf"
    assert result.total_pages >= 1
    assert [p.page_number for p in result.pages] == list(range(1, result.total_pages + 1))
    assert all(p.source_type == "pdf_text" and not p.needs_ocr for p in result.pages)


def test_blank_page_is_filled_by_ocr():
    pdf = _make_pdf([LONG_TEXT, ""])
    with patch(f"{MOD}.is_tesseract_available", return_value=True), \
         patch(f"{MOD}.extract_text_from_image", return_value=OCR_TEXT) as ocr:
        result = load_document(pdf, document_id="claim_1")

    assert ocr.call_count == 1  # only the blank page
    assert result.pages[0].source_type == "pdf_text"
    assert result.pages[1].page_number == 2
    assert result.pages[1].source_type == "ocr"
    assert result.pages[1].text == OCR_TEXT
    assert result.pages[1].needs_ocr is False


def test_ocr_returning_little_text_stays_flagged():
    pdf = _make_pdf([""])
    with patch(f"{MOD}.is_tesseract_available", return_value=True), \
         patch(f"{MOD}.extract_text_from_image", return_value="  "):
        result = load_document(pdf)
    assert result.pages[0].source_type == "ocr"
    assert result.pages[0].needs_ocr is True


def test_without_tesseract_original_result_is_returned():
    pdf = _make_pdf([LONG_TEXT, ""])
    with patch(f"{MOD}.is_tesseract_available", return_value=False), \
         patch(f"{MOD}.extract_text_from_image") as ocr:
        result = load_document(pdf)
    ocr.assert_not_called()
    assert result.pages[1].needs_ocr is True
    assert result.pages[1].source_type == "pdf_text"


def test_ocr_fallback_can_be_disabled():
    pdf = _make_pdf([""])
    with patch(f"{MOD}.extract_text_from_image") as ocr:
        result = load_document(pdf, ocr_fallback=False)
    ocr.assert_not_called()
    assert result.pages[0].needs_ocr is True


def test_ocr_error_keeps_page_flagged_instead_of_crashing():
    pdf = _make_pdf([""])
    with patch(f"{MOD}.is_tesseract_available", return_value=True), \
         patch(f"{MOD}.extract_text_from_image", side_effect=OCRError("boom")):
        result = load_document(pdf)
    assert result.pages[0].source_type == "pdf_text"
    assert result.pages[0].needs_ocr is True


def test_invalid_pdf_raises_extraction_error():
    with pytest.raises(PDFExtractionError):
        load_document(b"not a pdf")


def test_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        load_document(ROOT / "data" / "does_not_exist.pdf")