"""Automated tests for PDF extraction in ClaimCheck 2.0."""

import io
import pymupdf as fitz
import pytest

from src.documents.pdf_extractor import (
    extract_text_from_pdf,
    PDFExtractionError,
    DocumentExtraction,
    PageExtraction,
)


def _create_sample_pdf(pages_text: list[str]) -> bytes:
    """Helper to programmatically generate a multi-page PDF in memory."""
    doc = fitz.open()
    for text in pages_text:
        page = doc.new_page()
        if text:
            # Insert text at top-left
            page.insert_text(fitz.Point(50, 72), text, fontsize=12)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def test_extract_valid_single_page():
    """Test extracting text from a single-page valid PDF."""
    content = "This is a synthetic insurance policy covering hospitalization up to $50,000."
    pdf_bytes = _create_sample_pdf([content])

    result = extract_text_from_pdf(pdf_bytes, document_id="test_doc_1")

    assert isinstance(result, DocumentExtraction)
    assert result.document_id == "test_doc_1"
    assert result.total_pages == 1
    assert len(result.pages) == 1

    page = result.pages[0]
    assert page.page_number == 1
    assert "hospitalization" in page.text
    assert page.source_type == "pdf_text"
    assert page.needs_ocr is False


def test_preserving_page_numbers_multi_page():
    """Test preserving 1-based sequential page numbers across multiple pages."""
    pages_content = [
        "Page 1: Policyholder Agreement and Schedule of Benefits with detailed descriptions.",
        "Page 2: Covered Services and Emergency Care Inpatient Exclusions for claim check.",
        "Page 3: Co-payments, Annual Deductible and Maximum Out-of-Pocket Expenditure guidelines.",
    ]
    pdf_bytes = _create_sample_pdf(pages_content)

    result = extract_text_from_pdf(pdf_bytes)

    assert result.total_pages == 3
    assert len(result.pages) == 3

    for idx, page in enumerate(result.pages, start=1):
        assert page.page_number == idx
        assert f"Page {idx}" in page.text
        assert page.needs_ocr is False


def test_detect_page_with_little_or_no_text():
    """Test detecting pages with little extractable text that require OCR."""
    pages_content = [
        "Normal detailed text exceeding the minimum character threshold easily for this page.",
        "Hi",  # Only 2 characters: below 50 char threshold
        "",    # Completely blank page (0 characters)
    ]
    pdf_bytes = _create_sample_pdf(pages_content)

    result = extract_text_from_pdf(pdf_bytes, min_chars_threshold=50)

    assert result.total_pages == 3
    assert result.pages[0].needs_ocr is False
    assert result.pages[1].needs_ocr is True
    assert result.pages[2].needs_ocr is True


def test_handle_invalid_pdf_bytes():
    """Test graceful handling of invalid / corrupted PDF bytes."""
    corrupted_bytes = b"NOT_A_VALID_PDF_HEADER_AND_CORRUPTED_STREAM"

    with pytest.raises(PDFExtractionError) as exc_info:
        extract_text_from_pdf(corrupted_bytes)

    assert "Failed to open PDF stream" in str(exc_info.value)


def test_handle_empty_stream():
    """Test graceful error handling for empty byte streams."""
    with pytest.raises(PDFExtractionError) as exc_info:
        extract_text_from_pdf(b"")

    assert "empty (0 bytes)" in str(exc_info.value)


def test_handle_bytes_io_input():
    """Test that io.BytesIO stream is supported seamlessly."""
    content = "Hospital Bill Invoice: Room and Board charges total $1,200.00."
    pdf_bytes = _create_sample_pdf([content])
    stream = io.BytesIO(pdf_bytes)

    result = extract_text_from_pdf(stream, document_id="bytesio_doc")
    assert result.document_id == "bytesio_doc"
    assert result.total_pages == 1
    assert "Room and Board" in result.pages[0].text
