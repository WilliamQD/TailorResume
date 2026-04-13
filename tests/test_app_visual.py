"""Playwright-based visual smoke test for the Streamlit UI.

**Why this exists**: The AppTest-based smoke test at ``tests/test_app_smoke.py``
catches crashes and missing widgets, but it runs in-memory and has zero
visibility into CSS — so pure visual bugs (white band on a dark theme,
light-on-light text, a popover with the wrong background) slip through.
This test launches a real headless Chromium, loads the Streamlit app with
the UI fixture active (no LLM calls, no tokens spent), takes a full-page
screenshot, and runs a set of **DOM-level color invariants** against it:

    * The Streamlit main container has a dark background.
    * The status widget, when collapsed, has a dark background.
    * The results section headers are dark, not white.
    * Every visible element > 200x200 px has a background that is not
      pure white (the common regression signature).

The tests are skipped if playwright isn't installed or the chromium
browser isn't available — install with::

    pip install playwright
    python -m playwright install chromium

To run manually::

    pytest tests/test_app_visual.py -v

The screenshot lands at ``.jp_ui_screenshot/app.png`` under the repo root
so it's easy to eyeball after a failing run.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

from tests.fixtures.ui_fixture import build_ui_fixture  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parent.parent
APP_PATH = REPO_ROOT / "src" / "jobplanner" / "app.py"
SCREENSHOT_DIR = REPO_ROOT / ".jp_ui_screenshot"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_port(host: str, port: int, timeout_s: float) -> bool:
    end = time.time() + timeout_s
    while time.time() < end:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return True
        except OSError:
            time.sleep(0.3)
    return False


@pytest.fixture(scope="module")
def fixture_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("ui_fixture_visual")
    build_ui_fixture(root)
    yield root
    shutil.rmtree(root, ignore_errors=True)


@pytest.fixture(scope="module")
def streamlit_server(fixture_dir: Path):
    """Launch ``streamlit run`` as a subprocess with the fixture env set."""
    port = _free_port()
    env = os.environ.copy()
    env["JOBPLANNER_UI_FIXTURE"] = "1"
    env["JOBPLANNER_UI_FIXTURE_DIR"] = str(fixture_dir)
    env["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    env["STREAMLIT_SERVER_HEADLESS"] = "true"
    # On Windows the subprocess needs PYTHONIOENCODING set so streamlit's
    # logging doesn't crash on non-ASCII tracebacks.
    env.setdefault("PYTHONIOENCODING", "utf-8")

    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(APP_PATH),
        f"--server.port={port}",
        "--server.headless=true",
        "--browser.gatherUsageStats=false",
        "--server.fileWatcherType=none",
        "--global.developmentMode=false",
    ]
    proc = subprocess.Popen(
        cmd,
        env=env,
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        if not _wait_for_port("127.0.0.1", port, timeout_s=45):
            out, _ = proc.communicate(timeout=5)
            raise RuntimeError(
                f"Streamlit server did not start in time.\n"
                f"Output: {out.decode('utf-8', errors='replace')[:2000]}"
            )
        # A tiny extra delay — Streamlit listens on the port slightly before
        # the script finishes its first execution.
        time.sleep(1.5)
        yield f"http://127.0.0.1:{port}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture(scope="module")
def page(streamlit_server: str):
    """Launch a headless chromium page pointed at the streamlit server."""
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as exc:
            pytest.skip(f"Chromium not available: {exc}")
        context = browser.new_context(viewport={"width": 1600, "height": 1200})
        pg = context.new_page()
        pg.goto(streamlit_server, wait_until="networkidle", timeout=60_000)
        # Wait for the results section to appear — this confirms the
        # fixture loaded and the app finished its first script run.
        pg.wait_for_selector("text=Results", timeout=30_000)
        # Give BaseWeb components a beat to settle their dark theme.
        pg.wait_for_timeout(500)
        pg.screenshot(path=str(SCREENSHOT_DIR / "app.png"), full_page=True)
        yield pg
        context.close()
        browser.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def _bg_color(page, selector: str) -> str:
    """Return the computed ``background-color`` of the first matching element."""
    handle = page.query_selector(selector)
    if handle is None:
        return ""
    return page.evaluate(
        "(el) => getComputedStyle(el).backgroundColor",
        handle,
    )


def _element_bottom_vs_document(page, selector: str) -> dict[str, float] | None:
    """Return an element's document-bottom position and the page scroll height."""
    return page.evaluate(
        """
        (selector) => {
            const el = document.querySelector(selector);
            if (!el) return null;
            const rect = el.getBoundingClientRect();
            return {
                bottom: rect.bottom + window.scrollY,
                scrollHeight: Math.max(
                    document.documentElement.scrollHeight,
                    document.body.scrollHeight
                ),
            };
        }
        """,
        selector,
    )


def _parse_rgb(value: str) -> tuple[int, int, int, float] | None:
    """Parse a ``rgb(...)`` or ``rgba(...)`` string into an (r, g, b, a) tuple."""
    value = value.strip()
    if not value.startswith("rgb"):
        return None
    inside = value[value.find("(") + 1 : value.rfind(")")]
    parts = [p.strip() for p in inside.split(",")]
    if len(parts) == 3:
        r, g, b = (int(p) for p in parts)
        return (r, g, b, 1.0)
    if len(parts) == 4:
        r, g, b = (int(p) for p in parts[:3])
        return (r, g, b, float(parts[3]))
    return None


def _is_near_white(rgba: tuple[int, int, int, float] | None) -> bool:
    """Return True if the color is "white-ish" AND opaque enough to paint."""
    if rgba is None:
        return False
    r, g, b, a = rgba
    return a > 0.5 and r >= 240 and g >= 240 and b >= 240


def _is_dark(rgba: tuple[int, int, int, float] | None) -> bool:
    """Return True if the color is plausibly part of the dark theme."""
    if rgba is None:
        return False
    r, g, b, _ = rgba
    return max(r, g, b) < 80


def test_app_loads_and_shows_results(page) -> None:
    """The fixture-loaded app must render the Results section."""
    assert page.is_visible("text=Results")
    # The PDF preview img must be present in the DOM.
    assert page.query_selector(".pdf-frame img") is not None, \
        "PDF preview image missing — fixture did not flow through to the results panel."


def test_app_has_two_tabs(page) -> None:
    assert page.is_visible("text=Resume Tailor")
    assert page.is_visible("text=Bank Health")


def test_main_container_is_dark(page) -> None:
    """``stApp`` must render with a dark background, not the default white."""
    rgba = _parse_rgb(_bg_color(page, ".stApp"))
    assert rgba is not None, "Could not read .stApp background-color"
    assert _is_dark(rgba), f".stApp is not dark: {rgba}"


def test_app_shell_reaches_document_bottom(page) -> None:
    """The themed app shell must extend to the full document height."""
    geom = _element_bottom_vs_document(page, ".stApp")
    assert geom is not None, "Could not measure .stApp geometry"
    gap = abs(geom["scrollHeight"] - geom["bottom"])
    assert gap <= 16, (
        f".stApp stops {gap:.1f}px away from the document bottom "
        f"(bottom={geom['bottom']:.1f}, scrollHeight={geom['scrollHeight']:.1f}). "
        "This reintroduces the masked full-height shell bug where fallback "
        "body/html background shows under the results."
    )


def test_sidebar_shell_reaches_document_bottom(page) -> None:
    """The outer sidebar rail must extend to the document bottom too."""
    geom = _element_bottom_vs_document(page, 'section[data-testid="stSidebar"]')
    if geom is None:
        pytest.skip("sidebar shell not present")
    gap = abs(geom["scrollHeight"] - geom["bottom"])
    assert gap <= 16, (
        f"Sidebar shell stops {gap:.1f}px away from the document bottom "
        f"(bottom={geom['bottom']:.1f}, scrollHeight={geom['scrollHeight']:.1f}). "
        "This is the visible seam where the draggable sidebar rail no longer "
        "matches the rest of the page height."
    )


def test_html_body_background_is_dark(page) -> None:
    """``html`` and ``body`` must paint dark as defense-in-depth.

    This ensures the browser-default white doesn't leak through if any
    Streamlit container shell fails to cover the full document height.
    ``test_no_large_white_elements`` iterates ``body *`` and therefore
    excludes ``body`` and ``html`` themselves — this test fills that gap.
    """
    for selector in ("html", "body"):
        rgba = _parse_rgb(_bg_color(page, selector))
        assert rgba is not None, f"Could not read {selector} background-color"
        assert not _is_near_white(rgba), (
            f"{selector} background is white: {rgba} — the scroll-safety "
            "block is missing `background-color: var(--bg-primary)` on html/body."
        )


def test_status_widget_is_dark(page) -> None:
    """Status widget (pipeline progress) must be dark even when collapsed."""
    sel = '[data-testid="stStatusWidget"]'
    if page.query_selector(sel) is None:
        pytest.skip("status widget not present with fixture load — skipped")
    rgba = _parse_rgb(_bg_color(page, sel))
    assert rgba is not None
    assert not _is_near_white(rgba), f"Status widget is white: {rgba}"


def test_no_large_white_elements(page) -> None:
    """No visible element larger than 200x200 px may have a pure-white opaque background.

    This is the invariant that catches the recurring "white background bug":
    when a Streamlit update introduces a new widget whose CSS selector our
    dark-theme overrides don't cover, it shows up as a large white rectangle
    against the dark app. That pattern was user-reported twice before this
    test landed; this check is the regression gate.

    Exception: the ``<img>`` element inside ``.pdf-frame`` (the rendered
    resume page) IS supposed to be white — resumes are printed on white
    paper. The frame *wrapper* and everything else must stay dark.
    """
    offenders = page.evaluate(
        """
        () => {
            const results = [];
            const all = document.querySelectorAll('body *');
            for (const el of all) {
                // Skip ONLY the <img> inside .pdf-frame — resumes are white
                // on purpose. The .pdf-frame wrapper and its siblings still
                // count.
                if (el.tagName === 'IMG' && el.closest('.pdf-frame')) continue;
                const rect = el.getBoundingClientRect();
                if (rect.width < 200 || rect.height < 200) continue;
                const cs = getComputedStyle(el);
                const bg = cs.backgroundColor;
                const m = bg.match(/rgba?\\(([^)]+)\\)/);
                if (!m) continue;
                const parts = m[1].split(',').map(s => parseFloat(s.trim()));
                const [r, g, b] = parts;
                const a = parts.length === 4 ? parts[3] : 1;
                if (a > 0.5 && r >= 240 && g >= 240 && b >= 240) {
                    results.push({
                        tag: el.tagName,
                        cls: (el.className || '').toString().slice(0, 80),
                        id: el.id,
                        w: Math.round(rect.width),
                        h: Math.round(rect.height),
                        bg: bg,
                        selector: (el.getAttribute('data-testid') || ''),
                    });
                }
                if (results.length >= 10) break;
            }
            return results;
        }
        """
    )
    assert offenders == [], (
        f"Found {len(offenders)} white-background element(s) in the dark theme:\n"
        + "\n".join(
            f"  <{o['tag']} class='{o['cls']}' id='{o['id']}' "
            f"testid='{o['selector']}' {o['w']}x{o['h']} bg={o['bg']}>"
            for o in offenders
        )
    )


def test_section_headers_are_visible_on_dark(page) -> None:
    """Section header text must be visible — not white-on-white."""
    handle = page.query_selector(".section-header")
    if handle is None:
        pytest.skip(".section-header not found")
    color = page.evaluate("(el) => getComputedStyle(el).color", handle)
    rgba = _parse_rgb(color)
    assert rgba is not None
    # The section-header color is var(--accent) = amber #c9953a. Any non-white
    # opaque color is fine; we just need to reject white (which would be
    # invisible on the dark background).
    assert not _is_near_white(rgba), f".section-header color is white: {rgba}"
