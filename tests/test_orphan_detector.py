"""Tests for the post-render orphan-line detector.

Builds synthetic one-page PDFs with fitz at known (x, y) positions and
verifies that ``detect_orphan_lines`` flags only the geometric pattern
we care about: a short line (≤ 3 words, < 50% page width) sitting
immediately under a wide line (> 50% page width) with tight y-spacing.
"""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from jobplanner.latex.compiler import detect_orphan_lines


# ---- helpers ---------------------------------------------------------------

# Letter-sized page: 612pt wide, 792pt tall.
PAGE_W = 612.0
PAGE_H = 792.0


def _make_pdf(tmp_path: Path, lines: list[tuple[float, float, str]]) -> Path:
    """Create a test PDF with one page and the given (x, y, text) placements.

    ``y`` is the text baseline (fitz convention).
    """
    doc = fitz.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    for x, y, text in lines:
        page.insert_text((x, y), text, fontsize=10)
    out = tmp_path / "test.pdf"
    doc.save(str(out))
    doc.close()
    return out


# The "wide line" string must render to > 50% of PAGE_W to satisfy the
# detector's "previous line is full" gate. At 10pt Helvetica in fitz this
# string is ~500pt wide, well over the 306pt threshold.
WIDE_LINE = (
    "Added quality checks and pipeline documentation that cut data "
    "delivery from months to weeks and helped"
)


# ---- tests -----------------------------------------------------------------


def test_detects_orphan_after_wide_line(tmp_path: Path) -> None:
    """A 1-word line 12pt below a wide line is an orphan."""
    pdf = _make_pdf(
        tmp_path,
        [
            (72, 100, WIDE_LINE),
            (72, 112, "faster."),
        ],
    )
    orphans = detect_orphan_lines(pdf)
    assert len(orphans) == 1
    assert "faster." in orphans[0]


def test_detects_two_word_orphan(tmp_path: Path) -> None:
    """A 2-word orphan (e.g. 'AWS, DevOps') is also flagged."""
    pdf = _make_pdf(
        tmp_path,
        [
            (72, 100, WIDE_LINE),
            (72, 112, "AWS, DevOps"),
        ],
    )
    orphans = detect_orphan_lines(pdf)
    assert len(orphans) == 1
    assert "AWS, DevOps" in orphans[0]


def test_no_orphan_when_lines_are_far_apart(tmp_path: Path) -> None:
    """A short line well below a wide line is not an orphan — different paragraph."""
    pdf = _make_pdf(
        tmp_path,
        [
            (72, 100, WIDE_LINE),
            (72, 300, "faster."),  # 200pt gap: clearly not the same paragraph
        ],
    )
    orphans = detect_orphan_lines(pdf)
    assert orphans == []


def test_no_orphan_for_section_heading(tmp_path: Path) -> None:
    """A heading token right after a wide line is not an orphan."""
    pdf = _make_pdf(
        tmp_path,
        [
            (72, 100, WIDE_LINE),
            (72, 112, "SKILLS"),
        ],
    )
    orphans = detect_orphan_lines(pdf)
    assert orphans == []


def test_no_orphan_when_previous_line_is_short(tmp_path: Path) -> None:
    """A short line under a short line is not an orphan — just a short paragraph."""
    pdf = _make_pdf(
        tmp_path,
        [
            (72, 100, "Short previous"),  # only 2 words — not a "full" line
            (72, 112, "tail."),
        ],
    )
    orphans = detect_orphan_lines(pdf)
    assert orphans == []


def test_clean_pdf_has_no_orphans(tmp_path: Path) -> None:
    """A PDF with well-formed multi-word lines reports zero orphans."""
    pdf = _make_pdf(
        tmp_path,
        [
            (72, 100, "This is a normal line of body text with plenty of content"),
            (72, 115, "Another normal line with enough words to not trip the detector"),
            (72, 200, "A separated paragraph further down that also has many words"),
        ],
    )
    orphans = detect_orphan_lines(pdf)
    assert orphans == []


def test_missing_pdf_raises(tmp_path: Path) -> None:
    """Detector surfaces errors for a bogus path — caller must handle."""
    with pytest.raises(Exception):
        detect_orphan_lines(tmp_path / "does_not_exist.pdf")


def test_no_orphan_for_paired_entry_header(tmp_path: Path) -> None:
    """A new entry header (left=Org, right=Dates at same y) is NOT an orphan.

    Regression test for the "University of Toronto" false positive: a
    multi-line PyMuPDF block contained the Yale coursework wide line
    immediately followed by the next education entry's header row. The
    next-entry header is two lines at the SAME y-baseline (split by
    ``\\hfill`` in LaTeX). The detector must skip any line that shares a
    y-baseline with another line in the same block.
    """
    pdf = _make_pdf(
        tmp_path,
        [
            # Wide "Relevant Coursework: ..." line wrapping to line 2 in the block
            (72, 100, WIDE_LINE),
            # Next entry header: left-side org, right-side date, SAME baseline.
            (72, 112, "University of Toronto"),
            (460, 112, "September 2020 – June 2024"),
        ],
    )
    orphans = detect_orphan_lines(pdf)
    assert orphans == []


def test_detects_four_word_near_orphan(tmp_path: Path) -> None:
    """A 4-word tail (e.g. 'then ship the PDF.') is flagged under the widened threshold.

    The forbidden zone isn't just 1-3 word tails — 4-5 word tails still waste
    vertical space and must be caught. The Google paradox (100% forbidden-zone
    bullets, 0 detected orphans under the old 1-3 threshold) was the
    motivating case.
    """
    pdf = _make_pdf(
        tmp_path,
        [
            (72, 100, WIDE_LINE),
            (72, 112, "then ship the PDF."),
        ],
    )
    orphans = detect_orphan_lines(pdf)
    assert len(orphans) == 1
    assert "then ship the PDF." in orphans[0]


def test_detects_five_word_near_orphan(tmp_path: Path) -> None:
    """A 5-word tail is flagged — the upper bound of the widened threshold."""
    pdf = _make_pdf(
        tmp_path,
        [
            (72, 100, WIDE_LINE),
            (72, 112, "into a one page PDF."),
        ],
    )
    orphans = detect_orphan_lines(pdf)
    assert len(orphans) == 1
    assert "into a one page PDF." in orphans[0]


def test_no_orphan_for_six_word_line(tmp_path: Path) -> None:
    """A 6-word second line is treated as legitimate two-line body content."""
    pdf = _make_pdf(
        tmp_path,
        [
            (72, 100, WIDE_LINE),
            (72, 112, "and finally ship the final PDF."),
        ],
    )
    orphans = detect_orphan_lines(pdf)
    assert orphans == []


def test_orphan_still_flagged_alongside_paired_row(tmp_path: Path) -> None:
    """A legit orphan in the same block should still be flagged even when
    another unrelated line happens to be paired-y below it.
    """
    pdf = _make_pdf(
        tmp_path,
        [
            (72, 100, WIDE_LINE),
            (72, 112, "faster."),  # genuine orphan
            # Paired row further down — should NOT affect the orphan above.
            (72, 140, "University of Toronto"),
            (460, 140, "September 2020 – June 2024"),
        ],
    )
    orphans = detect_orphan_lines(pdf)
    assert len(orphans) == 1
    assert "faster." in orphans[0]
