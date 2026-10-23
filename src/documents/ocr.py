"""OCR Module for ClaimCheck 2.0.

Provides Optical Character Recognition (OCR) utilities using Pillow and pytesseract.
Supports environment-variable path configuration and fails safely with explicit errors
when Tesseract is unavailable or OCR fails.
"""

from __future__ import annotations

import os
import shutil
from typing import Optional
from PIL import Image
import pytesseract


class TesseractNotFoundError(Exception):
    """Raised when the Tesseract OCR executable is not found or cannot be invoked."""
    pass


class OCRError(Exception):
    """Raised when OCR processing fails on an image."""
    pass


def _resolve_tesseract_cmd() -> Optional[str]:
    """Resolve the path to the Tesseract executable.

    Checks:
    1. TESSERACT_CMD environment variable.
    2. pytesseract.pytesseract.tesseract_cmd (if already pointing to an existing file).
    3. System PATH lookup for 'tesseract'.
    4. Common default Windows installation directories.

    Returns:
        Optional[str]: Absolute path or command name if found, else None.
    """
    # 1. Environment variable override
    env_cmd = os.getenv("TESSERACT_CMD")
    if env_cmd and os.path.exists(env_cmd):
        return env_cmd

    # 2. Existing configured pytesseract command
    current_cmd = pytesseract.pytesseract.tesseract_cmd
    if current_cmd and os.path.exists(current_cmd):
        return current_cmd

    # 3. System PATH lookup
    path_lookup = shutil.which("tesseract")
    if path_lookup:
        return path_lookup

    # 4. Standard Windows locations
    win_paths = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for win_path in win_paths:
        if os.path.exists(win_path):
            return win_path

    return None


def is_tesseract_available(lang: Optional[str] = "eng") -> bool:
    """Check if Tesseract OCR is installed, configured, and has language traineddata.

    Args:
        lang: Specific language code to verify (e.g. 'eng'). If None, checks for any language.

    Returns:
        bool: True if Tesseract executable is found and operational with language data, False otherwise.
    """
    cmd = _resolve_tesseract_cmd()
    if not cmd:
        return False

    try:
        pytesseract.pytesseract.tesseract_cmd = cmd
        version = pytesseract.get_tesseract_version()
        if not version:
            return False
        available_langs = pytesseract.get_languages()
        if not available_langs:
            return False
        if lang and lang not in available_langs:
            return False
        return True
    except Exception:
        return False


def extract_text_from_image(image: Image.Image, lang: str = "eng") -> str:
    """Extract text from a PIL Image using Tesseract OCR.

    Args:
        image: PIL Image object.
        lang: Language code for OCR (defaults to 'eng').

    Returns:
        str: Extracted textual content.

    Raises:
        TesseractNotFoundError: If Tesseract executable is not installed, configured, or missing traineddata.
        OCRError: If OCR processing encounters an unexpected failure.
    """
    cmd = _resolve_tesseract_cmd()
    if not cmd:
        raise TesseractNotFoundError(
            "Tesseract OCR is not installed or not found on PATH. "
            "Please install Tesseract OCR and set the TESSERACT_CMD environment variable "
            "or ensure it is accessible in your system PATH."
        )

    pytesseract.pytesseract.tesseract_cmd = cmd

    if image is None:
        raise OCRError("Input image is None; expected a valid PIL Image.")

    try:
        available_langs = pytesseract.get_languages()
        if lang and lang not in available_langs:
            raise TesseractNotFoundError(
                f"Tesseract is installed at '{cmd}', but language model '{lang}.traineddata' "
                f"is not found in the tessdata directory. "
                "Download eng.traineddata into your Tesseract tessdata folder or set TESSDATA_PREFIX."
            )
        extracted = pytesseract.image_to_string(image, lang=lang)
        return extracted
    except pytesseract.TesseractNotFoundError as exc:
        raise TesseractNotFoundError(
            f"Tesseract executable at '{cmd}' failed to execute: {str(exc)}"
        ) from exc
    except (TesseractNotFoundError, OCRError):
        raise
    except Exception as exc:
        raise OCRError(f"OCR execution failed: {str(exc)}") from exc
