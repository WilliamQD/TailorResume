"""ATS compliance checker — extracts text from PDF and validates readability."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from jobplanner.bank.schema import ParsedJD
from jobplanner.latex.compiler import extract_text


@dataclass
class ATSReport:
    """Results of ATS compliance checking."""

    score: int = 0  # 0-100
    extracted_text: str = ""
    keyword_hits: list[str] = field(default_factory=list)
    keyword_misses: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    sections_found: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.score >= 60 and not any("CRITICAL" in w for w in self.warnings)


def _check_garbled_characters(text: str) -> list[str]:
    """Detect garbled/non-ASCII sequences that suggest encoding issues."""
    warnings: list[str] = []

    # Check for common ligature encoding issues (fi, fl, etc.)
    suspicious = re.findall(r"[\ufb00-\ufb06]", text)
    if suspicious:
        warnings.append(
            f"Found {len(suspicious)} ligature characters that some ATS may not parse: "
            f"{suspicious[:5]}"
        )

    # Check for replacement characters
    if "\ufffd" in text:
        count = text.count("\ufffd")
        warnings.append(f"CRITICAL: Found {count} replacement character(s) (U+FFFD) — text is garbled")

    # Check for excessive non-ASCII
    non_ascii = re.findall(r"[^\x00-\x7f]", text)
    # Filter out common legitimate non-ASCII (em-dash, bullet, etc.)
    legitimate = set("–—•·''""…±×÷≈≤≥")
    suspicious_non_ascii = [c for c in non_ascii if c not in legitimate]
    if len(suspicious_non_ascii) > 10:
        warnings.append(
            f"Found {len(suspicious_non_ascii)} unusual non-ASCII characters — "
            "may cause ATS parsing issues"
        )

    return warnings


def _check_sections(text: str) -> list[str]:
    """Check that standard resume sections are present."""
    expected = ["EDUCATION", "SKILLS", "EXPERIENCE"]
    found: list[str] = []
    text_upper = text.upper()
    for section in expected:
        if section in text_upper:
            found.append(section)
    return found


def check_ats(pdf_path: Path, jd: ParsedJD | None = None) -> ATSReport:
    """Run ATS compliance checks on a PDF resume.

    If a ParsedJD is provided, also checks keyword coverage.
    """
    text = extract_text(pdf_path)
    report = ATSReport(extracted_text=text)

    # Garbled character check
    report.warnings.extend(_check_garbled_characters(text))

    # Section check
    report.sections_found = _check_sections(text)
    expected_sections = {"EDUCATION", "SKILLS", "EXPERIENCE"}
    missing = expected_sections - set(report.sections_found)
    if missing:
        report.warnings.append(f"Missing resume sections: {missing}")

    # Keyword coverage (if JD provided)
    if jd is not None:
        text_lower = text.lower()
        all_keywords = list(set(jd.required_skills + jd.keywords))

        for kw in all_keywords:
            if kw.lower() in text_lower:
                report.keyword_hits.append(kw)
            else:
                report.keyword_misses.append(kw)

        if all_keywords:
            coverage = len(report.keyword_hits) / len(all_keywords) * 100
        else:
            coverage = 100

        # Score: base 50 for sections, up to 50 for keyword coverage
        section_score = min(len(report.sections_found) / 3 * 50, 50)
        keyword_score = coverage / 100 * 50
        report.score = int(section_score + keyword_score)

        # Penalize for critical warnings
        for w in report.warnings:
            if "CRITICAL" in w:
                report.score = max(0, report.score - 20)
    else:
        # Without JD, score based on sections and character quality only
        section_score = min(len(report.sections_found) / 3 * 100, 100)
        report.score = int(section_score)
        for w in report.warnings:
            if "CRITICAL" in w:
                report.score = max(0, report.score - 30)

    return report
