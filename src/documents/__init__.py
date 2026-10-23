"""Document processing and extraction modules for ClaimCheck 2.0."""

from .pdf_extractor import extract_text_from_pdf, DocumentExtraction, PageExtraction, PDFExtractionError
from .ocr import extract_text_from_image, is_tesseract_available, TesseractNotFoundError, OCRError

__all__ = [
    "extract_text_from_pdf",
    "DocumentExtraction",
    "PageExtraction",
    "PDFExtractionError",
    "extract_text_from_image",
    "is_tesseract_available",
    "TesseractNotFoundError",
    "OCRError",
]
