"""Emoji and Decorative Unicode Symbol Scanner Test for ClaimCheck 2.0.

Scans:
1. app.py
2. All python files in src/
3. README.md
4. Output of report_generator.generate_markdown_report

Fails if any emoji, pictograph, dingbat, decorative arrow, or checkmark is found.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
import pytest

from src.reports.report_generator import generate_markdown_report
from src.schemas import Finding, FindingStatus, SourceRef

ROOT_DIR = Path(__file__).resolve().parent.parent

# Regex covering emojis, dingbats, miscellaneous symbols, decorative arrows, checkmarks, warning signs
EMOJI_AND_SYMBOL_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001F9FF"  # Symbols and Pictographs Extended
    "\U0001FA00-\U0001FAFF"  # Symbols and Pictographs Extended-A
    "\U00002600-\U000027BF"  # Misc Symbols & Dingbats (checkmarks, warnings, crossmarks)
    "\U00002300-\U000023FF"  # Misc Technical
    "\U00002B00-\U00002BFF"  # Misc Symbols and Arrows
    "\U00002190-\U000021FF"  # Arrows
    "\U0000FE00-\U0000FE0F"  # Variation Selectors
    "]"
)


def _scan_text_for_symbols(text: str, filename: str) -> list[str]:
    """Find any emoji or symbol occurrences with line numbers."""
    violations = []
    lines = text.splitlines()
    for idx, line in enumerate(lines, start=1):
        matches = EMOJI_AND_SYMBOL_PATTERN.findall(line)
        if matches:
            violations.append(f"{filename}:{idx}: Found symbol(s) {matches!r} in: {line.strip()[:60]}")
    return violations


def test_no_emojis_in_app():
    """Verify app.py contains zero emojis or decorative symbols."""
    app_path = ROOT_DIR / "app.py"
    assert app_path.exists()
    content = app_path.read_text(encoding="utf-8")
    violations = _scan_text_for_symbols(content, "app.py")
    assert not violations, "\n".join(violations)


def test_no_emojis_in_src():
    """Verify all Python modules under src/ contain zero emojis or decorative symbols."""
    src_dir = ROOT_DIR / "src"
    assert src_dir.exists()
    all_violations = []

    for py_file in src_dir.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        rel_path = py_file.relative_to(ROOT_DIR)
        violations = _scan_text_for_symbols(content, str(rel_path))
        all_violations.extend(violations)

    assert not all_violations, "\n".join(all_violations)


def test_no_emojis_in_readme():
    """Verify README.md contains zero emojis or decorative symbols."""
    readme_path = ROOT_DIR / "README.md"
    assert readme_path.exists()
    content = readme_path.read_text(encoding="utf-8")
    violations = _scan_text_for_symbols(content, "README.md")
    assert not violations, "\n".join(violations)


def test_no_emojis_in_report_generator_output():
    """Verify report_generator output contains zero emojis or decorative symbols."""
    findings = [
        Finding(
            rule_id="RULE_ROOM_RENT_CAP",
            status=FindingStatus.VIOLATED,
            explanation="Room rent exceeds 5000 cap.",
            inputs_used={"daily_rate": 8000},
            calculation_steps=["Deduction calculated"],
            source=SourceRef(document="policy.pdf", page=2, quote="Room rent cap"),
            estimated_impact=3000.0,
        ),
        Finding(
            rule_id="RULE_WAITING_PERIOD",
            status=FindingStatus.SATISFIED,
            explanation="Waiting period satisfied.",
            inputs_used={"days": 45},
            calculation_steps=["45 >= 30"],
            source=SourceRef(document="policy.pdf", page=1, quote="Waiting period"),
            estimated_impact=0.0,
        ),
        Finding(
            rule_id="RULE_AMB",
            status=FindingStatus.NEEDS_REVIEW,
            explanation="Review needed.",
            inputs_used={},
            source=SourceRef(document="policy.pdf", page=4, quote="PED"),
            estimated_impact=None,
        ),
    ]

    report = generate_markdown_report(
        policy_name="synthetic_policy.pdf",
        claim_names=["claim_form.pdf", "hospital_bill.pdf"],
        findings=findings,
        unresolved_items=["Item 1 needs review"],
        mode="MOCK",
        claim_id="TEST_CLAIM",
        policy_id="test_policy",
        external_guidance=[
            {
                "query": "IRDAI PED",
                "url": "https://irdai.gov.in/guidelines",
                "title": "Guidelines",
                "snippet": "Statutory rules",
            }
        ],
    )

    violations = _scan_text_for_symbols(report, "report_output")
    assert not violations, "\n".join(violations)
