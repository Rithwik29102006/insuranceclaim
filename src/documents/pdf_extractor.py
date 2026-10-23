"""PDF Text Extraction Module for ClaimCheck 2.0.

Extracts text page by page from PDF file bytes using PyMuPDF (fitz)
and flags pages that may require Optical Character Recognition (OCR).
"""

from __future__ import annotations

import io
import uuid
from typing import List, Optional, Union
from pydantic import BaseModel, Field
import pymupdf as fitz


class PageExtraction(BaseModel):
    """Structured extraction result for an individual document page."""
    page_number: int = Field(..., description="1-based page index in the document.")
    text: str = Field(..., description="Raw text extracted from the page.")
    source_type: str = Field(default="pdf_text", description="Source of extraction ('pdf_text' or 'ocr').")
    needs_ocr: bool = Field(default=False, description="Whether this page has little/no extractable text.")


class DocumentExtraction(BaseModel):
    """Structured extraction result for a complete document."""
    document_id: str = Field(..., description="Unique synthetic document identifier.")
    total_pages: int = Field(..., description="Total number of pages processed.")
    pages: List[PageExtraction] = Field(default_factory=list, description="Extracted pages.")


class PDFExtractionError(Exception):
    """Raised when PDF bytes cannot be parsed or extraction fails."""
    pass


def extract_text_from_pdf(
    pdf_bytes: Union[bytes, io.BytesIO],
    document_id: Optional[str] = None,
    min_chars_threshold: int = 50,
) -> DocumentExtraction:
    """Extract text page-by-page from in-memory PDF bytes.

    Args:
        pdf_bytes: Raw bytes or BytesIO stream of the PDF file.
        document_id: Optional synthetic identifier. If omitted, a synthetic ID is generated.
        min_chars_threshold: Minimum non-whitespace characters to consider text adequate.
            Pages with fewer characters are flagged as `needs_ocr=True`.

    Returns:
        DocumentExtraction: Validated Pydantic model with page-level extractions.

    Raises:
        PDFExtractionError: If PDF stream is invalid, empty, or corrupted.
    """
    if pdf_bytes is None:
        raise PDFExtractionError("PDF data is None; expected bytes or BytesIO stream.")

    if isinstance(pdf_bytes, io.BytesIO):
        data = pdf_bytes.getvalue()
    elif isinstance(pdf_bytes, bytes):
        data = pdf_bytes
    else:
        raise PDFExtractionError(
            f"Unsupported data type for PDF extraction: {type(pdf_bytes).__name__}. "
            "Expected bytes or io.BytesIO."
        )

    if len(data) == 0:
        raise PDFExtractionError("Provided PDF byte stream is empty (0 bytes).")

    # Generate synthetic local identifier if not provided
    doc_id = document_id or f"synthetic_doc_{uuid.uuid4().hex[:8]}"

    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise PDFExtractionError(f"Failed to open PDF stream: {str(exc)}") from exc

    try:
        pages: List[PageExtraction] = []
        total_pages = len(doc)

        if total_pages == 0:
            raise PDFExtractionError("PDF contains 0 pages.")

        for idx, page in enumerate(doc, start=1):
            raw_text = page.get_text()
            stripped_len = len(raw_text.strip())
            needs_ocr = stripped_len < min_chars_threshold

            pages.append(
                PageExtraction(
                    page_number=idx,
                    text=raw_text,
                    source_type="pdf_text",
                    needs_ocr=needs_ocr,
                )
            )

        return DocumentExtraction(
            document_id=doc_id,
            total_pages=total_pages,
            pages=pages,
        )
    except PDFExtractionError:
        raise
    except Exception as exc:
        raise PDFExtractionError(f"Error extracting text from PDF: {str(exc)}") from exc
    finally:
        doc.close()
