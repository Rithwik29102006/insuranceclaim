"""Offline tests for the claim document OCR and rasterisation path.

Tests that claim documents with image-only PDF pages are properly rasterised
and passed to the OCR module, and that the extracted text is populated with
source_type='ocr'. Runs completely offline with mocked OCR calls.
"""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch
from PIL import Image
import pymupdf as fitz
import pytest

from src.ai.claim_loader import (
    load_claim_document,
    rasterise_page_to_image,
)
from src.documents.ocr import OCRError


def _create_image_only_pdf_bytes(width: int = 400, height: int = 600) -> bytes:
    """Generate a synthetic 1-page PDF containing only an image and no text."""
    # Create a simple in-memory PNG
    img = Image.new("RGB", (width, height), color=(240, 240, 240))
    img_buf = io.BytesIO()
    img.save(img_buf, format="PNG")
    img_bytes = img_buf.getvalue()

    # Create PDF and insert image
    doc = fitz.open()
    page = doc.new_page(width=width, height=height)
    page.insert_image(fitz.Rect(0, 0, width, height), stream=img_bytes)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def test_rasterise_page_to_image():
    """Verify rasterise_page_to_image correctly turns a PDF page into a PIL Image."""
    pdf_bytes = _create_image_only_pdf_bytes(width=200, height=300)
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        pil_img = rasterise_page_to_image(doc, page_number=1, dpi=150)
        assert isinstance(pil_img, Image.Image)
        assert pil_img.size[0] > 0 and pil_img.size[1] > 0
    finally:
        doc.close()


def test_load_claim_document_rasterises_and_runs_mocked_ocr():
    """Verify image-only claim PDF is rasterised and passed to extract_text_from_image."""
    pdf_bytes = _create_image_only_pdf_bytes()
    mock_ocr_text = (
        "APEX HOSPITAL INPATIENT BILL\n"
        "Room and Board Charges: 3 days @ INR 4000.00/day = Total INR 12000.00.\n"
        "Pharmacy and nursing sundries: INR 3500.00."
    )

    with patch("src.ai.claim_loader.is_tesseract_available", return_value=True), \
         patch("src.ai.claim_loader.extract_text_from_image", return_value=mock_ocr_text) as mock_ocr:

        extraction = load_claim_document(
            pdf_bytes,
            document_id="hospital_bill.pdf",
            ocr_fallback=True,
            dpi=150,
        )

        # Assert OCR was invoked once on a PIL Image
        assert mock_ocr.call_count == 1
        args, kwargs = mock_ocr.call_args
        assert isinstance(args[0], Image.Image)

        # Assert page extraction attributes
        assert extraction.total_pages == 1
        page = extraction.pages[0]
        assert page.page_number == 1
        assert page.source_type == "ocr"
        assert not page.needs_ocr
        assert "Room and Board Charges" in page.text


def test_load_claim_document_without_ocr_fallback():
    """Verify that when ocr_fallback=False, image-only pages remain un-OCRed."""
    pdf_bytes = _create_image_only_pdf_bytes()

    with patch("src.ai.claim_loader.is_tesseract_available", return_value=True), \
         patch("src.ai.claim_loader.extract_text_from_image") as mock_ocr:

        extraction = load_claim_document(
            pdf_bytes,
            document_id="hospital_bill.pdf",
            ocr_fallback=False,
        )

        assert mock_ocr.call_count == 0
        assert extraction.pages[0].needs_ocr is True
        assert extraction.pages[0].source_type == "pdf_text"


def test_load_claim_document_when_tesseract_unavailable():
    """Verify that when Tesseract is unavailable, pages remain flagged needs_ocr=True."""
    pdf_bytes = _create_image_only_pdf_bytes()

    with patch("src.ai.claim_loader.is_tesseract_available", return_value=False), \
         patch("src.ai.claim_loader.extract_text_from_image") as mock_ocr:

        extraction = load_claim_document(
            pdf_bytes,
            document_id="hospital_bill.pdf",
            ocr_fallback=True,
        )

        assert mock_ocr.call_count == 0
        assert extraction.pages[0].needs_ocr is True


def test_load_claim_document_ocr_error_does_not_crash():
    """Verify that OCR execution error keeps the page flagged without raising an exception."""
    pdf_bytes = _create_image_only_pdf_bytes()

    with patch("src.ai.claim_loader.is_tesseract_available", return_value=True), \
         patch("src.ai.claim_loader.extract_text_from_image", side_effect=OCRError("Simulated OCR failure")):

        extraction = load_claim_document(
            pdf_bytes,
            document_id="hospital_bill.pdf",
            ocr_fallback=True,
        )

        assert extraction.total_pages == 1
        assert extraction.pages[0].needs_ocr is True
