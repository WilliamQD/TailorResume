"""Compile LaTeX to PDF and check page count."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import fitz  # PyMuPDF


def find_compiler() -> str | None:
    """Find available LaTeX compiler. Returns binary name or None."""
    for name in ["tectonic", "pdflatex"]:
        if shutil.which(name):
            return name
    # Check common user-local install paths on Windows
    home_bin = Path.home() / ".local" / "bin" / "tectonic.exe"
    if home_bin.exists():
        return str(home_bin)
    return None


def compile_latex(tex_path: Path, compiler: str | None = None) -> Path:
    """Compile a .tex file to PDF. Returns the path to the PDF.

    Raises ``RuntimeError`` if compilation fails.
    """
    if compiler is None:
        compiler = find_compiler()
    if compiler is None:
        raise RuntimeError(
            "No LaTeX compiler found. Install tectonic:\n"
            "  Download from https://github.com/tectonic-typesetting/tectonic/releases\n"
            "  Place tectonic.exe in ~/.local/bin/ or add to PATH."
        )

    tex_path = tex_path.resolve()
    output_dir = tex_path.parent

    if "tectonic" in compiler:
        cmd = [compiler, str(tex_path), "--outdir", str(output_dir)]
    else:
        # pdflatex
        cmd = [
            compiler,
            "-interaction=nonstopmode",
            f"-output-directory={output_dir}",
            str(tex_path),
        ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=120,
    )

    pdf_path = tex_path.with_suffix(".pdf")

    if not pdf_path.exists():
        raise RuntimeError(
            f"LaTeX compilation failed.\n"
            f"Command: {' '.join(cmd)}\n"
            f"STDOUT:\n{result.stdout[-2000:]}\n"
            f"STDERR:\n{result.stderr[-2000:]}"
        )

    return pdf_path


def get_page_count(pdf_path: Path) -> int:
    """Return the number of pages in a PDF."""
    doc = fitz.open(str(pdf_path))
    count = len(doc)
    doc.close()
    return count


def get_page_fill_ratio(pdf_path: Path) -> float:
    """Estimate how full the first page is (0.0-1.0).

    Uses the y-coordinate of the lowest text block on page 1 relative
    to the page height.
    """
    doc = fitz.open(str(pdf_path))
    page = doc[0]
    page_height = page.rect.height

    blocks = page.get_text("blocks")
    if not blocks:
        doc.close()
        return 0.0

    # blocks are (x0, y0, x1, y1, text, block_no, block_type)
    max_y1 = max(b[3] for b in blocks if b[6] == 0)  # type 0 = text
    doc.close()

    # Account for bottom margin (~0.5in = 36pt on letter paper)
    usable_height = page_height - 36
    return min(max_y1 / usable_height, 1.0)


# Common typographic ligatures → their ASCII equivalents
_LIGATURE_MAP = {
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
    "\ufb05": "st",
    "\ufb06": "st",
}


def _normalize_ligatures(text: str) -> str:
    """Replace typographic ligatures with their ASCII equivalents for ATS."""
    for lig, replacement in _LIGATURE_MAP.items():
        text = text.replace(lig, replacement)
    return text


def extract_text(pdf_path: Path) -> str:
    """Extract all text from a PDF (for ATS checking).

    Normalizes ligature characters to plain ASCII so keyword matching
    works correctly (e.g., 'ﬁnancial' → 'financial').
    """
    doc = fitz.open(str(pdf_path))
    text_parts: list[str] = []
    for page in doc:
        text_parts.append(page.get_text())
    doc.close()
    return _normalize_ligatures("\n".join(text_parts))


# Tokens that identify a line as a heading — not a body-text orphan even if short.
_HEADING_TOKENS = (
    "EDUCATION",
    "SKILLS",
    "PROFESSIONAL",
    "EXPERIENCE",
    "PROJECTS",
    "EXTRACURRICULARS",
    "WILLIAM ZHANG",
)


def detect_orphan_lines(pdf_path: Path) -> list[str]:
    """Detect short orphan wrap lines on the rendered PDF.

    An "orphan" is a short final line in a wrapped paragraph — a bullet
    whose last 1-5 words dangle on line 2 of the same paragraph. We identify
    these by looking **inside a single PyMuPDF text block** (one LaTeX
    paragraph / bullet / skills line) and flagging a final short line that
    follows at least one wide line in the same block.

    **Threshold rationale**: the rule is "every bullet fits one line OR
    nearly fills two lines." Earlier the threshold was 1-3 words, which
    missed cases like 4-5 short-word tails (e.g. "then ship the final PDF.")
    that still waste vertical space. 1-5 words matches the full orphan
    spectrum: anything shorter than half a line below a full line is wasted
    space, regardless of exact word count. Bullets whose line 2 carries 6+
    words are treated as legitimate two-line content.

    **Why block-scoped**: earlier versions compared every adjacent pair of
    lines on the page, which produced false positives across block
    boundaries (e.g. the last wrapped coursework line immediately followed
    by the next education entry's header). PyMuPDF puts each paragraph in
    its own block, so restricting the comparison to within-block pairs
    eliminates those false positives without weakening detection.

    This is the post-render safety net. The primary defense is the
    programmatic length gate in ``src/jobplanner/tailor/length_gate.py``
    (runs before render); this function verifies the combined gate +
    LaTeX preamble defense worked.

    Returns a list of human-readable strings, one per orphan, so the
    pipeline can surface them as warnings. Returns an empty list on success.
    """
    doc = fitz.open(str(pdf_path))
    orphans: list[str] = []

    try:
        for page in doc:
            page_width = page.rect.width
            page_dict = page.get_text("dict")

            for block in page_dict.get("blocks", []):
                if block.get("type") != 0:  # 0 = text block
                    continue

                # Collect lines *within this block only*. A block corresponds
                # to a single LaTeX paragraph / bullet / skills line, so any
                # multi-line wrap happens inside one block — that's where
                # real orphans live.
                block_lines: list[dict] = []
                for line in block.get("lines", []):
                    text = "".join(
                        span.get("text", "") for span in line.get("spans", [])
                    ).strip()
                    if not text:
                        continue
                    bbox = line.get("bbox", (0.0, 0.0, 0.0, 0.0))
                    block_lines.append(
                        {
                            "x0": bbox[0],
                            "y0": bbox[1],
                            "x1": bbox[2],
                            "y1": bbox[3],
                            "text": text,
                        }
                    )

                if len(block_lines) < 2:
                    continue

                # Sort top-to-bottom, left-to-right inside the block.
                block_lines.sort(key=lambda ln: (round(ln["y0"], 1), ln["x0"]))

                # Identify "paired" lines — two lines sharing the same y-baseline
                # inside one block. These are the left+right halves of an
                # ``\entry{Org}\hfill\textbf{Dates}`` / ``\textit{Role}\hfill
                # \textit{Loc}`` header row, split by ``\hfill``. They must
                # never be flagged as orphans, and they must never be used as
                # the "previous wide line" that a real orphan wraps from.
                paired_y: set[float] = set()
                for a in range(len(block_lines)):
                    for b in range(a + 1, len(block_lines)):
                        if abs(block_lines[a]["y0"] - block_lines[b]["y0"]) < 1.5:
                            paired_y.add(round(block_lines[a]["y0"], 1))
                            paired_y.add(round(block_lines[b]["y0"], 1))

                for i in range(1, len(block_lines)):
                    cur = block_lines[i]
                    prev = block_lines[i - 1]

                    # Skip entry-header paired rows (Yale University | dates).
                    if round(cur["y0"], 1) in paired_y:
                        continue
                    if round(prev["y0"], 1) in paired_y:
                        continue

                    # Adjacent in the visual flow: vertical gap <= 0.8 line-heights.
                    line_height = cur["y1"] - cur["y0"]
                    if line_height <= 0:
                        continue
                    y_gap = cur["y0"] - prev["y1"]
                    if y_gap > line_height * 0.8:
                        continue

                    cur_words = cur["text"].split()
                    prev_words = prev["text"].split()

                    # Orphan characteristic: 1-5 words on the short line.
                    # Widened from 1-3 to catch near-orphans that still waste
                    # space (e.g. "then ship the final PDF.").
                    if not 1 <= len(cur_words) <= 5:
                        continue
                    # Previous line must be "full enough" to be the body of a paragraph.
                    if len(prev_words) < 8:
                        continue

                    # Skip heading lines (SKILLS, EDUCATION, ...).
                    upper_cur = cur["text"].upper()
                    if any(tok in upper_cur for tok in _HEADING_TOKENS):
                        continue

                    # Skip date-like lines (year present, e.g. "2024 -- 2026").
                    if sum(ch.isdigit() for ch in cur["text"]) >= 4:
                        continue

                    # Geometric check — previous line occupies > 50% of page width
                    # (i.e. it's a full body line, not an inline date/location).
                    prev_width = prev["x1"] - prev["x0"]
                    if prev_width < page_width * 0.5:
                        continue
                    # Current line occupies < 50% of page width (i.e. it's genuinely short).
                    cur_width = cur["x1"] - cur["x0"]
                    if cur_width > page_width * 0.5:
                        continue

                    prev_preview = prev["text"]
                    if len(prev_preview) > 60:
                        prev_preview = prev_preview[:57] + "..."
                    orphans.append(
                        f"'{cur['text']}' orphaned after '{prev_preview}'"
                    )
    finally:
        doc.close()

    return orphans
