"""ClaimCheck 2.0 - Local Development Interface.

Evidence-grounded Health Insurance Reimbursement Analysis.
Phase 1: Local PDF text extraction and OCR readiness inspection.
"""

from __future__ import annotations

import io
from typing import Optional, Tuple
import streamlit as st

from src.documents.pdf_extractor import (
    extract_text_from_pdf,
    DocumentExtraction,
    PDFExtractionError,
)
from src.documents.ocr import is_tesseract_available


# Streamlit Page Configuration
st.set_page_config(
    page_title="ClaimCheck 2.0",
    page_icon="📋",
    layout="wide",
)


def process_policy_document(
    file_bytes: bytes,
    file_name: str,
) -> Tuple[Optional[DocumentExtraction], Optional[str]]:
    """Process an uploaded synthetic policy PDF document.

    Args:
        file_bytes: In-memory byte contents of the policy file.
        file_name: Display name of the file.

    Returns:
        Tuple of (DocumentExtraction, error_message).
    """
    try:
        doc_id = f"policy_{file_name.replace('.pdf', '')}"
        extraction = extract_text_from_pdf(file_bytes, document_id=doc_id)
        return extraction, None
    except PDFExtractionError as exc:
        return None, f"Failed to extract policy document '{file_name}': {str(exc)}"
    except Exception as exc:
        return None, f"Unexpected error processing policy document '{file_name}': {str(exc)}"


def process_claim_document(
    file_bytes: bytes,
    file_name: str,
) -> Tuple[Optional[DocumentExtraction], Optional[str]]:
    """Process an uploaded synthetic claim PDF document.

    Args:
        file_bytes: In-memory byte contents of the claim file.
        file_name: Display name of the file.

    Returns:
        Tuple of (DocumentExtraction, error_message).
    """
    try:
        doc_id = f"claim_{file_name.replace('.pdf', '')}"
        extraction = extract_text_from_pdf(file_bytes, document_id=doc_id)
        return extraction, None
    except PDFExtractionError as exc:
        return None, f"Failed to extract claim document '{file_name}': {str(exc)}"
    except Exception as exc:
        return None, f"Unexpected error processing claim document '{file_name}': {str(exc)}"


def render_document_results(title: str, extraction: DocumentExtraction) -> None:
    """Render extracted document pages with page count and OCR warnings.

    Args:
        title: Section title.
        extraction: DocumentExtraction result model.
    """
    st.subheader(title)
    st.caption(f"Document ID: `{extraction.document_id}`")

    # Metrics row
    col1, col2 = st.columns(2)
    with col1:
        st.metric(label="Total Pages", value=extraction.total_pages)
    with col2:
        ocr_flagged_count = sum(1 for p in extraction.pages if p.needs_ocr)
        st.metric(
            label="Pages Needing OCR",
            value=ocr_flagged_count,
            delta="Warning" if ocr_flagged_count > 0 else "OK",
            delta_color="inverse" if ocr_flagged_count > 0 else "normal",
        )

    # Page-by-page expandable view
    for page in extraction.pages:
        page_label = f"Page {page.page_number}"
        if page.needs_ocr:
            page_label += " ⚠️ (Low extractable text - OCR Recommended)"

        with st.expander(page_label, expanded=(extraction.total_pages == 1)):
            if page.needs_ocr:
                st.warning(
                    f"⚠️ **Low text density detected on Page {page.page_number}**: "
                    "This page contains little or no extractable digital text and may be a scanned image "
                    "or rasterized table requiring OCR processing."
                )

            if page.text.strip():
                st.text_area(
                    label="Extracted Text",
                    value=page.text,
                    height=200,
                    key=f"{extraction.document_id}_p{page.page_number}",
                    disabled=True,
                )
            else:
                st.info("ℹ️ No digital text characters found on this page.")


def main() -> None:
    """Main Streamlit application entry point."""
    st.title("ClaimCheck 2.0")
    st.markdown("### Evidence-grounded Health Insurance Reimbursement Analysis")

    # Development-mode banner
    st.warning(
        "🛠️ **Development Mode**: AI Analysis Pipeline is not connected yet. "
        "Nebius Token Factory access and promotional credits are pending. "
        "All extraction runs strictly locally in memory without external API keys or remote calls."
    )

    # Adjudication notice
    st.info(
        "ℹ️ **Testing Notice**: Extracted text displayed in this interface is for local parser "
        "verification and testing only. This software does not make claim approval or rejection decisions."
    )

    # Sidebar: System Environment Status
    with st.sidebar:
        st.header("System Status")
        tesseract_status = is_tesseract_available()
        if tesseract_status:
            st.success("✅ Tesseract OCR: Detected")
        else:
            st.error("❌ Tesseract OCR: Not Detected")
            st.caption(
                "Configure `TESSERACT_CMD` in `.env` if installed in a custom location."
            )
        st.markdown("---")
        st.markdown("**ClaimCheck 2.0 Foundation**")
        st.markdown("• In-memory PDF parsing")
        st.markdown("• Local OCR readiness checks")
        st.markdown("• Deterministic rule foundation")

    # Upload Section
    col_policy, col_claim = st.columns(2)

    with col_policy:
        st.markdown("#### 1. Insurance Policy Document")
        policy_file = st.file_uploader(
            "Upload synthetic policy PDF",
            type=["pdf"],
            key="policy_uploader",
            help="Upload a PDF of the insurance terms, deductibles, or policy clauses.",
        )

    with col_claim:
        st.markdown("#### 2. Claim & Supporting Documents")
        claim_file = st.file_uploader(
            "Upload synthetic claim PDF",
            type=["pdf"],
            key="claim_uploader",
            help="Upload a PDF of hospital bills, line-item charges, or clinical receipts.",
        )

    # Process Action
    process_clicked = st.button("🚀 Process Uploaded Documents", type="primary")

    if process_clicked:
        if not policy_file and not claim_file:
            st.warning("Please upload at least one PDF document (Policy or Claim) to process.")
            return

        st.markdown("---")
        st.subheader("Document Processing Results")

        # Process Policy if provided
        if policy_file:
            with st.spinner("Processing policy document..."):
                policy_bytes = policy_file.read()
                policy_extraction, policy_err = process_policy_document(
                    policy_bytes, policy_file.name
                )
                if policy_err:
                    st.error(policy_err)
                elif policy_extraction:
                    render_document_results("Policy Extraction", policy_extraction)

        # Process Claim if provided
        if claim_file:
            with st.spinner("Processing claim document..."):
                claim_bytes = claim_file.read()
                claim_extraction, claim_err = process_claim_document(
                    claim_bytes, claim_file.name
                )
                if claim_err:
                    st.error(claim_err)
                elif claim_extraction:
                    render_document_results("Claim Extraction", claim_extraction)


if __name__ == "__main__":
    main()
