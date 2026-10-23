"""Policy/claim document loader with OCR fallback for ClaimCheck 2.0.

Wraps the protected extractor (pdf_extractor.py) and OCR utility (ocr.py)
without modifying them. Pages that the extractor flags as needs_ocr are
rendered to an image and passed through Tesseract when it is available.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Optional, Union

import pymupdf as fitz
from PIL import Image

from src.documents.pdf_extractor import (
    DocumentExtraction,
    PageExtraction,
    extract_text_from_pdf,
)
from src.documents.ocr import (
    OCRError,
    TesseractNotFoundError,
    extract_text_from_image,
    is_tesseract_available,
)

MIN_CHARS = 50  # same default threshold as the extractor


def load_document(
    source: Union[str, Path, bytes, io.BytesIO],
    document_id: Optional[str] = None,
    ocr_fallback: bool = True,
    dpi: int = 200,
) -> DocumentExtraction:
    """Extract text page by page, using OCR for low-text pages when possible.

    Args:
        source: File path, raw PDF bytes, or BytesIO stream.
        document_id: Optional ID. Defaults to the file name when a path is given.
        ocr_fallback: If False, behaves exactly like extract_text_from_pdf.
        dpi: Render resolution for OCR.

    Returns:
        DocumentExtraction with 1-based page numbers. OCR'd pages have
        source_type="ocr". Pages that still have little text stay needs_ocr=True.

    Raises:
        FileNotFoundError: If a path is given and the file does not exist.
        PDFExtractionError: If the PDF cannot be parsed (from the extractor).
    """
    if isinstance(source, (str, Path)):
        path = Path(source)
        data = path.read_bytes()
        document_id = document_id or path.name
    elif isinstance(source, io.BytesIO):
        data = source.getvalue()
    else:
        data = source

    result = extract_text_from_pdf(data, document_id=document_id)

    if not ocr_fallback or not any(p.needs_ocr for p in result.pages):
        return result
    if not is_tesseract_available():
        return result  # pages stay flagged needs_ocr=True

    pdf = fitz.open(stream=data, filetype="pdf")
    try:
        pages = []
        for page in result.pages:
            if page.needs_ocr:
                page = _ocr_page(pdf, page, dpi)
            pages.append(page)
    finally:
        pdf.close()

    return DocumentExtraction(
        document_id=result.document_id,
        total_pages=result.total_pages,
        pages=pages,
    )


def _ocr_page(pdf, page: PageExtraction, dpi: int) -> PageExtraction:
    """OCR one page. On OCR failure, return the original flagged page."""
    pix = pdf[page.page_number - 1].get_pixmap(dpi=dpi)
    image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    try:
        text = extract_text_from_image(image)
    except (OCRError, TesseractNotFoundError):
        return page
    return PageExtraction(
        page_number=page.page_number,
        text=text,
        source_type="ocr",
        needs_ocr=len(text.strip()) < MIN_CHARS,
    )