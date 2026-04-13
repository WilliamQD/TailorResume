"""Tests for ``jobplanner.app.render_pdf_preview``.

Verifies that the preview PNG is cropped to the content bounding box rather
than rendering the full US Letter page (which wastes space and embeds a
blank white bottom strip in the image).

These tests assert the result has:
    * a content-shaped aspect ratio (shorter than full US Letter), and
    * bounded whitespace at the bottom (no more than the cosmetic margin).
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

# Pillow and fitz are hard dependencies of the app path anyway — no importorskip.
from PIL import Image

from jobplanner.app import render_pdf_preview
from tests.fixtures.ui_fixture import build_ui_fixture


@pytest.fixture(scope="module")
def fixture_pdf(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build a real tailored-resume PDF once for the whole module."""
    root = tmp_path_factory.mktemp("pdf_preview_fixture")
    result = build_ui_fixture(root)
    assert result.pdf_path is not None and result.pdf_path.exists()
    return result.pdf_path


@pytest.fixture(scope="module")
def preview_image(fixture_pdf: Path) -> Image.Image:
    png_bytes = render_pdf_preview(fixture_pdf)
    return Image.open(io.BytesIO(png_bytes)).convert("RGB")


def test_preview_aspect_ratio(preview_image: Image.Image) -> None:
    """The cropped preview must be shorter than a full US Letter page.

    US Letter aspect ratio (h/w) = 11 / 8.5 ≈ 1.294. A content-cropped
    tailored resume strips at least the top + bottom margins (≈ 0.5" each),
    so its height/width should land well below 1.25. If someone reverts the
    crop and renders the full ``page.rect``, this assertion fires.
    """
    w, h = preview_image.size
    ratio = h / w
    assert ratio < 1.25, (
        f"PDF preview aspect ratio {ratio:.3f} is too tall — the preview is "
        "rendering the full page rect instead of cropping to the content "
        "bbox. This produces the 'white band at the bottom' bug. See "
        "CLAUDE.md → PDF-preview crop invariant."
    )


def test_preview_bottom_whitespace_is_bounded(preview_image: Image.Image) -> None:
    """The preview must not have a tall contiguous blank strip at the bottom.

    After cropping to content bbox with a ~0.33" cosmetic margin, the bottom
    of the image is at most that margin (~50 px at 150 dpi). A full-page
    render, by contrast, leaves the entire unfilled bottom of the page as
    hundreds of all-white rows at the bottom of the PNG. We count the
    consecutive all-white rows from the bottom up and require that count
    stays well under what a full-page regression would produce.

    Threshold: 120 px. The cosmetic margin is ~50 px; a full-page render of
    a 93%-filled letter page would leave ~115 px of whitespace from the
    0.77" bottom gap alone, and typical fixture resumes are much sparser
    than 93% fill, so the margin between "passing" and "regressing" is
    large and stable.
    """
    w, h = preview_image.size
    pixels = preview_image.load()
    blank_rows = 0
    for y in range(h - 1, -1, -1):
        all_white = True
        for x in range(w):
            r, g, b = pixels[x, y]
            if min(r, g, b) < 240:
                all_white = False
                break
        if not all_white:
            break
        blank_rows += 1
    assert blank_rows < 120, (
        f"PDF preview has {blank_rows} consecutive all-white rows at the "
        f"bottom (image {w}×{h}). The crop didn't take — the preview is "
        "still including the unfilled bottom of the page. See CLAUDE.md → "
        "PDF-preview crop invariant."
    )
