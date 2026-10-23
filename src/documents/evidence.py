"""Citation verification for ClaimCheck 2.0.

Checks that a SourceRef's quote really appears on the page it cites.
Used to verify gold rules today and AI-generated rules (Nemotron) later.
"""

from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel

from src.documents.pdf_extractor import DocumentExtraction
from src.schemas import SourceRef


class CitationCheck(BaseModel):
    """Result of checking one citation against an extracted document."""
    verified: bool
    cited_page: int
    found_on_page: Optional[int] = None
    reason: str  # "verified", "wrong_page", "page_out_of_range", "not_found"


def normalize_whitespace(text: str) -> str:
    """Collapse line breaks and repeated spaces so PDF layout doesn't break matching."""
    return re.sub(r"\s+", " ", text).strip()


def find_quote_page(extraction: DocumentExtraction, quote: str) -> Optional[int]:
    """Return the first 1-based page containing the quote, or None."""
    target = normalize_whitespace(quote)
    if not target:
        return None
    for page in extraction.pages:
        if target in normalize_whitespace(page.text):
            return page.page_number
    return None


def check_citation(extraction: DocumentExtraction, source: SourceRef) -> CitationCheck:
    """Check a citation and explain the result."""
    found = find_quote_page(extraction, source.quote)
    pages = {p.page_number for p in extraction.pages}

    if source.page not in pages:
        reason = "page_out_of_range"
    elif found is None:
        reason = "not_found"
    elif found == source.page:
        reason = "verified"
    else:
        cited_text = next(p.text for p in extraction.pages if p.page_number == source.page)
        if normalize_whitespace(source.quote) in normalize_whitespace(cited_text):
            found, reason = source.page, "verified"
        else:
            reason = "wrong_page"

    return CitationCheck(
        verified=(reason == "verified"),
        cited_page=source.page,
        found_on_page=found,
        reason=reason,
    )


def verify_citation(extraction: DocumentExtraction, source: SourceRef) -> bool:
    """True only if the quote appears verbatim on the cited page."""
    return check_citation(extraction, source).verified