"""Automated tests for OCR support in ClaimCheck 2.0."""

from unittest.mock import patch
import pytest
from PIL import Image

from src.documents.ocr import (
    extract_text_from_image,
    is_tesseract_available,
    TesseractNotFoundError,
    OCRError,
)


def test_tesseract_unavailable_handling():
    """Test that extract_text_from_image raises TesseractNotFoundError when not installed."""
    with patch("src.documents.ocr._resolve_tesseract_cmd", return_value=None):
        assert is_tesseract_available() is False

        img = Image.new("RGB", (100, 100), color="white")
        with pytest.raises(TesseractNotFoundError) as exc_info:
            extract_text_from_image(img)

        assert "Tesseract OCR is not installed" in str(exc_info.value)


def test_extract_text_none_image_handling():
    """Test that passing None as image raises OCRError when tesseract is configured."""
    with patch("src.documents.ocr._resolve_tesseract_cmd", return_value="dummy_path"):
        with patch("src.documents.ocr.pytesseract.get_tesseract_version", return_value="5.0.0"):
            with pytest.raises(OCRError) as exc_info:
                extract_text_from_image(None)  # type: ignore

            assert "Input image is None" in str(exc_info.value)


def test_mocked_successful_ocr():
    """Test successful OCR text extraction with mocked tesseract backend."""
    with patch("src.documents.ocr._resolve_tesseract_cmd", return_value="tesseract"):
        with patch("src.documents.ocr.pytesseract.get_languages", return_value=["eng"]):
            with patch("src.documents.ocr.pytesseract.image_to_string", return_value="CLAIM INVOICE #10294"):
                img = Image.new("RGB", (200, 50), color="white")
                result = extract_text_from_image(img)
                assert result == "CLAIM INVOICE #10294"


def test_missing_language_data_raises_error():
    """Test that missing traineddata raises an actionable TesseractNotFoundError."""
    with patch("src.documents.ocr._resolve_tesseract_cmd", return_value="tesseract"):
        with patch("src.documents.ocr.pytesseract.get_languages", return_value=[]):
            img = Image.new("RGB", (200, 50), color="white")
            with pytest.raises(TesseractNotFoundError) as exc_info:
                extract_text_from_image(img)
            assert "traineddata" in str(exc_info.value)


def test_live_tesseract_if_installed():
    """Test live OCR extraction only if Tesseract is actually installed on the system."""
    if not is_tesseract_available():
        pytest.skip("Tesseract is not available on this host environment.")

    # Create a simple synthetic image with a white canvas
    img = Image.new("RGB", (200, 100), color="white")
    result = extract_text_from_image(img)
    # A blank white image produces empty string or minimal whitespace
    assert isinstance(result, str)
