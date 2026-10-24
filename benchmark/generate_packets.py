"""Deterministic 20-packet benchmark generator for ClaimCheck 2.0.

Uses ReportLab and Pillow with fixed seed 20261022 to generate reproducible
packets for all 12 core scenarios and 8 variants under `data/packets/<packet_id>/`.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
import random
import sys
from typing import Dict, List

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from PIL import Image, ImageFilter
import pymupdf as fitz
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from benchmark.ground_truth import (
    PacketDocumentContent,
    PacketSpec,
    get_all_packet_specs,
    independently_compute_expected_findings,
)
from src.schemas import Rulebook

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
PACKETS_DIR = DATA_DIR / "packets"
RULEBOOK_PATH = DATA_DIR / "gold_rulebook.json"
BENCHMARK_SEED = 20261022


def _make_invariant_canvas(*args, **kwargs) -> canvas.Canvas:
    """Create a canvas with invariant=1 for deterministic PDF generation."""
    kwargs["invariant"] = 1
    return canvas.Canvas(*args, **kwargs)


def _build_digital_doc_story(
    content: PacketDocumentContent,
    spec: PacketSpec,
) -> List:
    """Build ReportLab flowables for a structured document."""
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=15,
        leading=19,
        textColor=colors.HexColor("#0f172a"),
        alignment=1,  # Center
        spaceAfter=6,
    )

    subtitle_style = ParagraphStyle(
        "DocSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#475569"),
        alignment=1,
        spaceAfter=12,
    )

    body_style = ParagraphStyle(
        "DocBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=15,
        textColor=colors.HexColor("#1e293b"),
        spaceAfter=8,
    )

    footer_style = ParagraphStyle(
        "DocFooter",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#94a3b8"),
        alignment=1,
    )

    story = [
        Spacer(1, 10),
        Paragraph(content.title, title_style),
        Paragraph(f"{content.doc_type} | Aura Health Assure (Plan B)", subtitle_style),
        HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#0284c7"), spaceAfter=12),
    ]

    # Metadata table
    if content.header_info:
        data = [[Paragraph(f"<b>{k}:</b> {v}", styles["Normal"])] for k, v in content.header_info.items()]
        # Arrange in 2-column format if possible
        table_rows = []
        for i in range(0, len(data), 2):
            row = [data[i][0]]
            if i + 1 < len(data):
                row.append(data[i + 1][0])
            else:
                row.append(Paragraph("", styles["Normal"]))
            table_rows.append(row)

        tbl = Table(table_rows, colWidths=[240, 240])
        tbl.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e2e8f0")),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ])
        )
        story.append(tbl)
        story.append(Spacer(1, 14))

    # Body paragraphs
    for para in content.body_paragraphs:
        story.append(Paragraph(para, body_style))
        story.append(Spacer(1, 6))

    # Optional table
    if content.table_data:
        tbl2 = Table(content.table_data)
        tbl2.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e0f2fe")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#0369a1")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ])
        )
        story.append(Spacer(1, 10))
        story.append(tbl2)

    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e1"), spaceAfter=8))
    footer_text = content.footer_text or (
        f"ClaimCheck 2.0 Benchmark Document | Packet: {spec.packet_id} | "
        f"Claim Ref: {spec.claim_number} | Deterministic Test Suite"
    )
    story.append(Paragraph(footer_text, footer_style))

    return story


def _render_digital_pdf_bytes(
    content: PacketDocumentContent,
    spec: PacketSpec,
) -> bytes:
    """Render a digital PDF into bytes with invariant=1."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54,
    )
    story = _build_digital_doc_story(content, spec)
    doc.build(story, canvasmaker=_make_invariant_canvas)
    return buf.getvalue()


def _render_rasterised_pdf_bytes(
    content: PacketDocumentContent,
    spec: PacketSpec,
    seed: int,
) -> bytes:
    """Render an image-only, rasterised PDF with seeded rotation, blur, and noise."""
    # 1. Render digital document to memory
    digital_bytes = _render_digital_pdf_bytes(content, spec)

    # 2. Extract pages as images using PyMuPDF
    doc_fitz = fitz.open(stream=digital_bytes, filetype="pdf")
    rng = random.Random(seed)

    out_buf = io.BytesIO()
    c = canvas.Canvas(out_buf, pagesize=letter, invariant=1)

    for page_idx, page in enumerate(doc_fitz):
        pix = page.get_pixmap(dpi=150)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        # Apply seeded rotation (-0.6 to +0.6 degrees)
        angle = rng.uniform(-0.6, 0.6)
        rotated = img.rotate(angle, resample=Image.Resampling.BICUBIC, expand=False, fillcolor="white")

        # Apply slight blur
        blurred = rotated.filter(ImageFilter.GaussianBlur(radius=0.45))

        # Apply deterministic salt-and-pepper / scan noise
        pixels = blurred.load()
        w, h = blurred.size
        # Add 3000 noise pixels
        for _ in range(3000):
            x = rng.randint(0, w - 1)
            y = rng.randint(0, h - 1)
            noise_val = rng.randint(210, 245)
            pixels[x, y] = (noise_val, noise_val, noise_val)

        # Save image as PNG in memory
        img_buf = io.BytesIO()
        blurred.save(img_buf, format="PNG")
        img_buf.seek(0)

        # Draw image to canvas without digital text
        from reportlab.lib.utils import ImageReader
        c.drawImage(ImageReader(img_buf), 0, 0, width=letter[0], height=letter[1])
        c.showPage()

    c.save()
    return out_buf.getvalue()


def generate_single_packet(
    spec: PacketSpec,
    rulebook: Rulebook,
    target_dir: Path,
    base_seed: int = BENCHMARK_SEED,
) -> Dict[str, Path]:
    """Generate all 5 files for a single benchmark packet."""
    target_dir.mkdir(parents=True, exist_ok=True)
    packet_seed = base_seed + int(spec.packet_id.replace("packet_", "")) * 73
    generated_files: Dict[str, Path] = {}

    # 1. Generate the 3 PDFs
    for doc_name, content in spec.documents.items():
        pdf_path = target_dir / doc_name
        is_raster = spec.is_rasterised_bill and (doc_name == "hospital_bill.pdf")

        if is_raster:
            pdf_bytes = _render_rasterised_pdf_bytes(content, spec, seed=packet_seed)
        else:
            pdf_bytes = _render_digital_pdf_bytes(content, spec)

        pdf_path.write_bytes(pdf_bytes)
        generated_files[doc_name] = pdf_path

    # 2. Generate ground_truth_facts.json
    facts_path = target_dir / "ground_truth_facts.json"
    facts_data = [f.model_dump() for f in spec.claim_facts]
    facts_path.write_text(json.dumps(facts_data, indent=2), encoding="utf-8")
    generated_files["ground_truth_facts.json"] = facts_path

    # 3. Generate expected_findings.json
    findings_path = target_dir / "expected_findings.json"
    expected_findings = independently_compute_expected_findings(spec, rulebook)
    findings_data = [f.model_dump() for f in expected_findings]
    findings_path.write_text(json.dumps(findings_data, indent=2), encoding="utf-8")
    generated_files["expected_findings.json"] = findings_path

    return generated_files


def generate_all_benchmark_packets(
    packets_dir: Path = PACKETS_DIR,
    rulebook_path: Path = RULEBOOK_PATH,
    seed: int = BENCHMARK_SEED,
) -> List[PacketSpec]:
    """Generate complete 20-packet benchmark dataset."""
    random.seed(seed)
    with open(rulebook_path, "r", encoding="utf-8") as f:
        rulebook = Rulebook.model_validate(json.load(f))

    specs = get_all_packet_specs()
    packets_dir.mkdir(parents=True, exist_ok=True)

    print(f"Generating {len(specs)} benchmark packets under {packets_dir}...")
    for idx, spec in enumerate(specs, start=1):
        target_dir = packets_dir / spec.packet_id
        generate_single_packet(spec, rulebook, target_dir, base_seed=seed)
        raster_note = " (Rasterised Scan)" if spec.is_rasterised_bill else ""
        print(f"  [{idx:02d}/20] {spec.packet_id}: {spec.scenario_id}{raster_note}")

    print("Generation complete! All 20 packets generated successfully.")
    return specs


if __name__ == "__main__":
    generate_all_benchmark_packets()
