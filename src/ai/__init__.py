"""AI integration package for ClaimCheck 2.0.

Contains modules for compiling policies, extracting claim facts,
loading claim documents with OCR fallback, and local mock clients.
"""

from src.ai.claim_extractor import extract_claim_facts
from src.ai.claim_loader import load_claim_document, rasterise_page_to_image
from src.ai.policy_compiler import compile_policy_rules

__all__ = [
    "extract_claim_facts",
    "load_claim_document",
    "rasterise_page_to_image",
    "compile_policy_rules",
]
