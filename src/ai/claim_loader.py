"""Claim Document Loader and OCR Rasteriser for ClaimCheck 2.0.

Provides document ingestion for claim files (hospital bills, discharge summaries, claim forms).
Rasterises image-only PDF pages using PyMuPDF and extracts text using the existing OCR module.
Implemented in `src/ai/` to maintain the immutability of protected directories (`src/documents/`).
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import List, Optional, Union

from PIL import Image
import pymupdf as fitz

from src.documents.ocr import (
    OCRError,
    TesseractNotFoundError,
    extract_text_from_image,
    is_tesseract_available,
)
from src.documents.pdf_extractor import (
    DocumentExtraction,
    PageExtraction,
    extract_text_from_pdf,
)

MIN_CHARS_THRESHOLD = 50


def rasterise_page_to_image(pdf_doc: fitz.Document, page_number: int, dpi: int = 200) -> Image.Image:
    """Rasterise a single 1-based page from a PyMuPDF Document into a PIL Image."""
    page_idx = page_number - 1
    if page_idx < 0 or page_idx >= len(pdf_doc):
        raise ValueError(f"Page number {page_number} out of range (total pages: {len(pdf_doc)})")

    fitz_page = pdf_doc[page_idx]
    pix = fitz_page.get_pixmap(dpi=dpi)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def ocr_rasterised_page(
    pdf_doc: fitz.Document,
    page: PageExtraction,
    dpi: int = 200,
    lang: str = "eng",
) -> PageExtraction:
    """Rasterise an image-only PDF page and extract text using the existing OCR utility.

    Returns the updated PageExtraction with source_type='ocr', or the original page on OCR error.
    """
    image = rasterise_page_to_image(pdf_doc, page.page_number, dpi=dpi)
    try:
        ocr_text = extract_text_from_image(image, lang=lang)
    except (OCRError, TesseractNotFoundError):
        return page

    stripped_len = len(ocr_text.strip())
    return PageExtraction(
        page_number=page.page_number,
        text=ocr_text,
        source_type="ocr",
        needs_ocr=stripped_len < MIN_CHARS_THRESHOLD,
    )


def load_claim_document(
    source: Union[str, Path, bytes, io.BytesIO],
    document_id: Optional[str] = None,
    ocr_fallback: bool = True,
    dpi: int = 200,
    lang: str = "eng",
) -> DocumentExtraction:
    """Load a claim document from file path or bytes, with automated OCR rasterisation for image-only pages.

    Args:
        source: File path, raw PDF bytes, or BytesIO buffer.
        document_id: Optional identifier (defaults to file basename if path given).
        ocr_fallback: Whether to rasterise and OCR image-only pages.
        dpi: Resolution for page rasterisation (default: 200 DPI).
        lang: Tesseract language code (default: 'eng').

    Returns:
        DocumentExtraction with page text and OCR flags populated.
    """
    if isinstance(source, (str, Path)):
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"Claim document not found: {path}")
        data = path.read_bytes()
        doc_id = document_id or path.name
    elif isinstance(source, io.BytesIO):
        data = source.getvalue()
        doc_id = document_id
    elif isinstance(source, bytes):
        data = source
        doc_id = document_id
    else:
        raise TypeError(f"Unsupported source type for claim document: {type(source).__name__}")

    # Step 1: Initial digital extraction
    extraction = extract_text_from_pdf(data, document_id=doc_id)

    # Step 2: If no pages need OCR or fallback is disabled, return extraction directly
    pages_needing_ocr = [p for p in extraction.pages if p.needs_ocr]
    if not ocr_fallback or not pages_needing_ocr:
        return extraction

    # Step 3: Check if OCR is available
    if not is_tesseract_available(lang=lang):
        return extraction

    # Step 4: Rasterise and run OCR on pages requiring text extraction
    pdf_doc = fitz.open(stream=data, filetype="pdf")
    try:
        updated_pages: List[PageExtraction] = []
        for page in extraction.pages:
            if page.needs_ocr:
                updated = ocr_rasterised_page(pdf_doc, page, dpi=dpi, lang=lang)
                updated_pages.append(updated)
            else:
                updated_pages.append(page)
    finally:
        pdf_doc.close()

    return DocumentExtraction(
        document_id=extraction.document_id,
        total_pages=extraction.total_pages,
        pages=updated_pages,
    )
