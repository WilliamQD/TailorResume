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
