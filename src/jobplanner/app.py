"""JobPlanner — Streamlit web UI for the resume tailoring pipeline."""

from __future__ import annotations

import base64
import html
import json
import os
from pathlib import Path

import fitz
import streamlit as st

from jobplanner.bank.loader import load_bank, validate_bank
from jobplanner.config import load_settings
from jobplanner.pipeline import PipelineResult, run_pipeline

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="JobPlanner",
    page_icon="\u25A0",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Theme — dark industrial with amber accents
# ---------------------------------------------------------------------------

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:ital,wght@0,400;0,500;0,700;1,400&family=Source+Serif+4:opsz,wght@8..60,400;8..60,500;8..60,600&display=swap');

/* ---- Root palette ---- */
:root {
    color-scheme: dark;  /* tells the browser to render native elements (details/summary/input) dark */
    --bg-primary: #0b0c0e;
    --bg-card: #131519;
    --bg-elevated: #1a1d23;
    --bg-hover: #1f232a;
    --border: #262a33;
    --border-accent: #33383f;
    --text-primary: #eeece7;
    --text-secondary: #a3a8b0;
    --text-muted: #6d727c;
    --accent: #c9953a;
    --accent-bright: #e0ad4e;
    --accent-dim: #a67b2e;
    --accent-glow: rgba(201, 149, 58, 0.08);
    --success: #3fcf70;
    --danger: #e85858;
    --warning: #e8b43a;
    --app-noise: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.025'/%3E%3C/svg%3E");
}

/* ---- Global ---- */
/* SCROLL-SAFETY: Noise texture is applied as a background-image directly on .stApp.
   Do NOT use a ::before pseudo-element with position:fixed — it creates a stacking
   context that breaks Streamlit's scroll container after results load, locking the
   page.  Do NOT add position:relative here either — it breaks Streamlit's layout.
   The SVG has opacity='0.025' baked in so no CSS opacity is needed. */
.stApp,
[data-testid="stAppViewContainer"],
[data-testid="stAppViewBlockContainer"] {
    background-color: var(--bg-primary) !important;
    background-image: var(--app-noise) !important;
    background-size: 256px 256px !important;
}
.stApp {
    font-family: 'Source Serif 4', Georgia, serif !important;
}

/* ---- Scrollbar ---- */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: var(--bg-primary); }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--border-accent); }

/* ---- Header / branding strip ---- */
header[data-testid="stHeader"] {
    display: none !important;
}
#MainMenu, footer { display: none !important; }

/* ---- Sidebar ---- */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, var(--bg-card) 0%, #0f1014 100%) !important;
    border-right: 1px solid var(--border) !important;
}
section[data-testid="stSidebar"] > div:first-child,
section[data-testid="stSidebar"] [data-testid="stSidebarContent"],
section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {
    background: transparent !important;
}
section[data-testid="stSidebar"] > div:first-child {
    padding-top: 1.6rem !important;
}
section[data-testid="stSidebar"] .stMarkdown p,
section[data-testid="stSidebar"] .stMarkdown li {
    color: var(--text-primary) !important;
    font-family: 'Source Serif 4', serif !important;
    font-size: 0.92rem !important;
}
section[data-testid="stSidebar"] .stMarkdown .stCaption p {
    color: var(--text-secondary) !important;
}
/*
 * IMPORTANT: Target only form control labels, NOT expander/button/summary elements.
 * Applying font-family to expander headers breaks Streamlit's icon font (renders as "arr").
 * Always use data-testid-scoped selectors here, never bare `label`.
 *
 * DEFENSE-IN-DEPTH: the rule below is GLOBAL (unscoped) so every form widget
 * anywhere in the app — sidebar, main tab, future tabs, modals — gets a
 * readable label by default. Previous bugs had labels scoped ONLY to
 * `section[data-testid="stSidebar"]`, which made every new widget added
 * outside the sidebar invisible until someone noticed and patched CSS.
 * Do NOT re-scope this rule. Add new widget classes here when Streamlit
 * ships new ones.
 */
.stSelectbox label,
.stMultiSelect label,
.stRadio > label,
.stCheckbox > label,
.stTextInput label,
.stNumberInput label,
.stTextArea label,
.stDateInput label,
.stTimeInput label,
.stSlider label,
.stColorPicker label,
.stFileUploader label,
.stToggle label {
    color: var(--text-primary) !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.82rem !important;
    text-transform: uppercase !important;
    letter-spacing: 0.1em !important;
}
section[data-testid="stSidebar"] hr {
    border-color: var(--border) !important;
    margin: 0.8rem 0 !important;
}

/* ---- Sidebar brand ---- */
.jp-brand {
    padding: 0 0 0.5rem 0;
}
.jp-title {
    font-family: 'JetBrains Mono', monospace;
    font-weight: 700;
    font-size: 1.5rem;
    letter-spacing: -0.04em;
    color: var(--accent);
    line-height: 1;
    margin: 0;
}
.jp-rule {
    width: 36px;
    height: 2px;
    background: var(--accent-dim);
    margin: 8px 0 6px 0;
    border: none;
}
.jp-subtitle {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.72rem;
    color: var(--text-primary);
    letter-spacing: 0.18em;
    text-transform: uppercase;
    margin: 0;
}

/* ---- Section headers ---- */
.section-header {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.75rem;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.18em;
    color: var(--accent);
    border-bottom: 1px solid var(--border);
    padding-bottom: 8px;
    margin-bottom: 14px;
    margin-top: 2px;
    display: flex;
    align-items: center;
    gap: 8px;
}
.section-header::before {
    content: '';
    width: 3px;
    height: 3px;
    background: var(--accent);
    border-radius: 50%;
    flex-shrink: 0;
}

/* ---- Text area ---- */
.stTextArea textarea,
.stTextArea textarea:disabled,
.stTextArea textarea[readonly] {
    font-family: 'Source Serif 4', serif !important;
    font-size: 0.95rem !important;
    line-height: 1.55 !important;
    background-color: var(--bg-card) !important;
    border: 1px solid var(--border) !important;
    color: var(--text-primary) !important;
    -webkit-text-fill-color: var(--text-primary) !important;
    opacity: 1 !important;
    border-radius: 4px !important;
    padding: 14px 16px !important;
    transition: border-color 0.2s ease, box-shadow 0.2s ease !important;
}
/* BaseWeb textarea wrapper — some Streamlit versions darken this on re-render.
 * Streamlit nests: stTextArea > stTextAreaRootElement[data-baseweb=textarea] >
 *   div[data-baseweb=base-input] > <textarea>
 * All three layers ship with rgb(240,242,246) by default and must be forced
 * to the dark card color, otherwise the base-input wrapper leaks light
 * through as a ~1138x218 white rectangle against the dark theme.
 * See tests/test_app_visual.py::test_no_large_white_elements — regression gate. */
.stTextArea [data-baseweb="textarea"],
.stTextArea [data-baseweb="base-input"] {
    background-color: var(--bg-card) !important;
}
.stTextArea textarea::placeholder {
    color: var(--text-secondary) !important;
    font-style: italic !important;
}
.stTextArea textarea:focus {
    border-color: var(--accent-dim) !important;
    box-shadow: 0 0 0 1px var(--accent-dim), 0 0 20px var(--accent-glow) !important;
}

/* ---- Selectbox ---- */
div[data-baseweb="select"] {
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.9rem !important;
}
div[data-baseweb="select"] > div {
    background-color: var(--bg-elevated) !important;
    border-color: var(--border) !important;
    color: var(--text-primary) !important;
}
div[data-baseweb="select"] span {
    color: var(--text-primary) !important;
}
div[data-baseweb="select"] svg {
    fill: var(--text-secondary) !important;
}
/* Selectbox dropdown popover */
div[data-baseweb="popover"] {
    background-color: var(--bg-elevated) !important;
    border: 1px solid var(--border) !important;
    border-radius: 4px !important;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5) !important;
}
div[data-baseweb="popover"] ul {
    background-color: var(--bg-elevated) !important;
}
div[data-baseweb="popover"] li,
ul[data-baseweb="menu"] li {
    background-color: var(--bg-elevated) !important;
    color: var(--text-primary) !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.88rem !important;
}
div[data-baseweb="popover"] li:hover,
ul[data-baseweb="menu"] li:hover {
    background-color: var(--bg-hover) !important;
}
div[data-baseweb="popover"] li[aria-selected="true"],
ul[data-baseweb="menu"] li[aria-selected="true"] {
    background-color: rgba(201, 149, 58, 0.12) !important;
    color: var(--accent-bright) !important;
}
/* Menu container */
ul[data-baseweb="menu"],
div[data-baseweb="menu"] {
    background-color: var(--bg-elevated) !important;
}

/* ---- Checkbox ---- */
.stCheckbox label span {
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.85rem !important;
    color: var(--text-primary) !important;
}

/* ---- Primary button (Generate) ---- */
.stButton > button[kind="primary"],
.stButton > button[data-testid="stBaseButton-primary"] {
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.88rem !important;
    letter-spacing: 0.1em !important;
    font-weight: 600 !important;
    background: linear-gradient(135deg, var(--accent) 0%, var(--accent-dim) 100%) !important;
    color: var(--bg-primary) !important;
    border: none !important;
    border-radius: 3px !important;
    padding: 0.65rem 1.5rem !important;
    transition: all 0.2s ease !important;
    position: relative;
    overflow: hidden;
}
.stButton > button[kind="primary"]:hover,
.stButton > button[data-testid="stBaseButton-primary"]:hover {
    background: linear-gradient(135deg, var(--accent-bright) 0%, var(--accent) 100%) !important;
    box-shadow: 0 4px 24px rgba(201, 149, 58, 0.25) !important;
    transform: translateY(-1px);
}
.stButton > button[kind="primary"]:active,
.stButton > button[data-testid="stBaseButton-primary"]:active {
    transform: translateY(0px);
}
.stButton > button[kind="primary"]:disabled,
.stButton > button[data-testid="stBaseButton-primary"]:disabled {
    background: var(--bg-elevated) !important;
    color: var(--text-muted) !important;
    box-shadow: none !important;
}

/* ---- Download buttons ---- */
.stDownloadButton > button {
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.82rem !important;
    letter-spacing: 0.08em !important;
    border: 1px solid var(--border-accent) !important;
    color: var(--accent) !important;
    background: var(--bg-card) !important;
    border-radius: 3px !important;
    transition: all 0.2s ease !important;
}
.stDownloadButton > button:hover {
    background: var(--bg-elevated) !important;
    border-color: var(--accent-dim) !important;
    box-shadow: 0 2px 12px rgba(201, 149, 58, 0.1) !important;
}

/* ---- Secondary buttons (Edit, Dismiss, Dismiss All Stale) ----
 * Use descendant (space) combinator rather than direct-child (>) — when
 * use_container_width=True is passed, Streamlit wraps the <button> in an
 * extra container, which would break `.stButton > button` matching.
 */
button[kind="secondary"],
button[data-testid="stBaseButton-secondary"] {
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.75rem !important;
    letter-spacing: 0.1em !important;
    text-transform: uppercase !important;
    font-weight: 500 !important;
    color: var(--text-secondary) !important;
    background: var(--bg-card) !important;
    border: 1px solid var(--border) !important;
    border-radius: 3px !important;
    padding: 0.45rem 0.8rem !important;
    min-height: 0 !important;
    transition: all 0.18s ease !important;
}
button[kind="secondary"]:hover,
button[data-testid="stBaseButton-secondary"]:hover {
    background: var(--bg-elevated) !important;
    border-color: var(--accent-dim) !important;
    color: var(--accent-bright) !important;
    box-shadow: 0 2px 12px rgba(201, 149, 58, 0.08) !important;
}
button[kind="secondary"]:active,
button[data-testid="stBaseButton-secondary"]:active {
    transform: translateY(0.5px) !important;
    background: var(--bg-hover) !important;
}
button[kind="secondary"]:focus,
button[data-testid="stBaseButton-secondary"]:focus {
    outline: none !important;
    box-shadow: 0 0 0 1px var(--accent-dim) !important;
}
/* Per-row Edit / × buttons — kill the label's inner <p> margin so the
 * glyph/text centers properly in the compact button box. */
button[kind="secondary"] p,
button[data-testid="stBaseButton-secondary"] p {
    margin: 0 !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.75rem !important;
    letter-spacing: 0.1em !important;
    line-height: 1 !important;
}

/* ---- Metric card ---- */
.metric-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 1.4rem 1.5rem;
    text-align: center;
    position: relative;
    overflow: hidden;
}
.metric-card::after {
    content: '';
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    height: 2px;
}
.metric-card.score-good::after { background: var(--success); }
.metric-card.score-ok::after { background: var(--warning); }
.metric-card.score-low::after { background: var(--danger); }
.metric-value {
    font-family: 'JetBrains Mono', monospace;
    font-size: 2.8rem;
    font-weight: 700;
    line-height: 1;
    margin-bottom: 0.3rem;
}
.metric-label {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.18em;
    color: var(--text-muted);
}

/* ---- JD summary card ---- */
.jd-card {
    margin-top: 14px;
    padding: 12px 16px;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-left: 3px solid var(--accent-dim);
    border-radius: 0 4px 4px 0;
}
.jd-title {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.95rem;
    color: var(--text-primary);
    font-weight: 600;
}
.jd-company {
    color: var(--text-secondary);
    font-family: 'Source Serif 4', serif;
    font-size: 0.9rem;
}
.jd-meta {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.75rem;
    color: var(--accent-dim);
    text-transform: uppercase;
    letter-spacing: 0.12em;
    margin-top: 4px;
}

/* ---- Keyword pills ---- */
.kw-wrap { display: flex; flex-wrap: wrap; gap: 4px; }
.kw-hit, .kw-miss {
    display: inline-block;
    padding: 4px 10px;
    border-radius: 2px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.8rem;
    letter-spacing: 0.02em;
}
.kw-hit {
    background: rgba(63, 207, 112, 0.08);
    color: var(--success);
    border: 1px solid rgba(63, 207, 112, 0.2);
}
.kw-miss {
    background: rgba(232, 88, 88, 0.06);
    color: var(--danger);
    border: 1px solid rgba(232, 88, 88, 0.15);
}

/* ---- Inferred skill cards ---- */
.inf-card {
    background: var(--bg-elevated);
    border-left: 2px solid var(--accent-dim);
    padding: 0.5rem 0.75rem;
    margin-bottom: 6px;
    border-radius: 0 3px 3px 0;
    transition: border-color 0.15s ease;
}
.inf-card:hover { border-left-color: var(--accent-bright); }
.inf-name {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.88rem;
    font-weight: 600;
    color: var(--text-primary);
}
.inf-basis {
    font-family: 'Source Serif 4', serif;
    font-size: 0.82rem;
    color: var(--text-secondary);
    margin-top: 2px;
    font-style: italic;
}
.inf-badge {
    display: inline-block;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.65rem;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    padding: 1px 6px;
    border-radius: 2px;
    margin-left: 6px;
    vertical-align: middle;
}
.inf-badge.high { background: rgba(63, 207, 112, 0.12); color: var(--success); }
.inf-badge.moderate { background: rgba(232, 180, 58, 0.12); color: var(--warning); }
.inf-badge.low { background: rgba(232, 88, 88, 0.08); color: var(--danger); }

/* ---- PDF preview frame ---- */
/* Shows the full PDF page — no max-height or overflow clipping. */
.pdf-frame {
    border: 1px solid var(--border);
    border-radius: 4px;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4), 0 2px 8px rgba(0, 0, 0, 0.2);
}

/* ---- Status widget (pipeline progress) ---- */
[data-testid="stStatusWidget"],
[data-testid="stStatusWidget"] > *,
[data-testid="stStatusWidget"] details,
[data-testid="stStatusWidget"] details > div,
[data-testid="stStatusWidget"] summary {
    background-color: var(--bg-card) !important;
    color-scheme: dark !important;
}
[data-testid="stStatusWidget"] {
    border: 1px solid var(--border) !important;
    border-radius: 4px !important;
    margin-bottom: 8px !important;
}
/* Tighten the default Streamlit vertical block gap in the main tab so the
   collapsed pipeline status widget sits directly above the results header
   instead of leaving ~40px of dead space. */
section[data-testid="stMain"] [data-testid="stVerticalBlock"] {
    gap: 0.5rem !important;
}
/* Code block used for progress log */
[data-testid="stCode"],
[data-testid="stCode"] pre,
[data-testid="stCode"] code {
    background-color: var(--bg-elevated) !important;
    color: var(--text-secondary) !important;
}

/* ---- Expander ---- */
/*
 * IMPORTANT: NEVER set font-family on `summary` or any element wrapping
 * Streamlit icon characters. Streamlit uses a private-use-area icon font
 * for expand/collapse arrows. Overriding font-family renders the icon as
 * garbled text (e.g. "arr"). Only set color/background, never font-family,
 * on summary or button elements containing icons.
 */
[data-testid="stExpander"] {
    border-color: var(--border) !important;
    background-color: var(--bg-card) !important;
}
[data-testid="stExpander"] details {
    background-color: var(--bg-card) !important;
    border-color: var(--border) !important;
}
[data-testid="stExpander"] details > div,
[data-testid="stExpanderContent"] {
    background-color: var(--bg-card) !important;
}
/* Color only on summary — no font-family (would break arrow icon) */
[data-testid="stExpander"] summary,
[data-testid="stExpander"] summary p,
[data-testid="stExpander"] summary > div {
    color: var(--text-primary) !important;
    background-color: var(--bg-card) !important;
    color-scheme: dark !important;
}
[data-testid="stExpander"] [data-testid="stMarkdownContainer"] p,
[data-testid="stExpander"] [data-testid="stMarkdownContainer"] li {
    color: var(--text-primary) !important;
}

/* ---- Force dark on all Streamlit containers ---- */
[data-testid="stVerticalBlock"],
[data-testid="stVerticalBlockBorderWrapper"],
[data-testid="element-container"],
[data-testid="stMarkdownContainer"] {
    background-color: transparent !important;
}
/* Sidebar content */
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
    background: transparent !important;
}
section[data-testid="stSidebar"] [data-testid="stExpander"] details,
section[data-testid="stSidebar"] [data-testid="stExpander"] details > div,
section[data-testid="stSidebar"] [data-testid="stExpanderContent"] {
    background-color: var(--bg-card) !important;
}
/* Caption text */
[data-testid="stCaptionContainer"] p,
.stCaption p {
    color: var(--text-secondary) !important;
    font-family: 'Source Serif 4', serif !important;
    font-size: 0.82rem !important;
}
/* Markdown bold */
[data-testid="stMarkdownContainer"] strong {
    color: var(--text-primary) !important;
}

/* ---- Streamlit layout theming ---- */
/* Streamlit's native layout uses absolute positioning + internal scrolling:
     .stApp / stAppViewContainer  →  position: absolute; inset: 0; overflow: hidden
     stMain                       →  height: 100dvh; overflow: auto  (THE scroll container)
     stSidebar                    →  flex-stretches to viewport height
   This is the correct model. Do NOT override position, overflow, or height on
   these containers — doing so breaks scroll containment and causes the sidebar
   and backgrounds to stop at the viewport boundary while content overflows.
   Only set background-color and cosmetic styles here. */
html, body {
    background-color: var(--bg-primary) !important;
}
.main .block-container,
.stMainBlockContainer,
[data-testid="stMainBlockContainer"] {
    padding-bottom: 5rem !important;
    max-width: none !important;
}

/* ---- Alert boxes ---- */
.stSuccess, .stError, .stWarning {
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.85rem !important;
    border-radius: 3px !important;
}

/* ---- Empty state hint ---- */
.empty-state {
    text-align: center;
    padding: 3rem 2rem;
    color: var(--text-muted);
}
.empty-state .hint-icon {
    font-size: 2rem;
    margin-bottom: 0.8rem;
    opacity: 0.4;
}
.empty-state .hint-text {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.82rem;
    letter-spacing: 0.1em;
    text-transform: uppercase;
}

/* ---- Validation passed badge ---- */
.validation-pass {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    background: rgba(63, 207, 112, 0.06);
    border: 1px solid rgba(63, 207, 112, 0.15);
    border-radius: 3px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.82rem;
    color: var(--success);
    margin-top: 12px;
}
.validation-fail {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    background: rgba(232, 88, 88, 0.06);
    border: 1px solid rgba(232, 88, 88, 0.15);
    border-radius: 3px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.82rem;
    color: var(--danger);
    margin-top: 12px;
}

/* ---- Orphan wrap warning banner ---- */
.orphan-warn {
    padding: 8px 12px;
    background: rgba(232, 180, 58, 0.08);
    border: 1px solid rgba(232, 180, 58, 0.25);
    border-radius: 3px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.78rem;
    color: var(--warning);
    margin-top: 12px;
}
.orphan-warn .orphan-title {
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    margin-bottom: 6px;
}
.orphan-warn .orphan-item {
    font-family: 'Source Serif 4', serif;
    font-size: 0.75rem;
    color: var(--text-secondary);
    margin-top: 3px;
}

/* ---- Pipeline mode radio (sidebar) ---- */
div[data-testid="stRadio"] > label {
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.78rem !important;
    text-transform: uppercase !important;
    letter-spacing: 0.1em !important;
    color: var(--text-primary) !important;
}
div[data-testid="stRadio"] div[role="radiogroup"] {
    gap: 6px !important;
    flex-direction: row !important;
    flex-wrap: nowrap;
}
div[data-testid="stRadio"] div[role="radiogroup"] label {
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.78rem !important;
    letter-spacing: 0.06em !important;
    text-transform: uppercase !important;
    color: #d8d4cd !important;
    background: #1f232a !important;
    border: 1px solid #3a3f4a !important;
    border-radius: 3px !important;
    padding: 5px 12px !important;
    min-width: 0 !important;
    transition: all 0.15s ease;
}
div[data-testid="stRadio"] div[role="radiogroup"] label:has(input:checked) {
    background: rgba(201, 149, 58, 0.18) !important;
    border-color: #c9953a !important;
    color: #e0ad4e !important;
}
/* Target the text node directly — Streamlit may override color on p */
div[data-testid="stRadio"] div[role="radiogroup"] label p,
div[data-testid="stRadio"] div[role="radiogroup"] label span,
div[data-testid="stRadio"] div[role="radiogroup"] label div {
    color: inherit !important;
    font-family: inherit !important;
    font-size: inherit !important;
    letter-spacing: inherit !important;
    text-transform: inherit !important;
    margin: 0 !important;
    white-space: nowrap;
}
/* Hide the radio circle — whole label is the affordance */
div[data-testid="stRadio"] div[role="radiogroup"] label input[type="radio"] {
    display: none !important;
}

/* ---- Critic summary quote block ---- */
.critic-summary {
    padding: 10px 14px 10px 16px;
    background: rgba(201, 149, 58, 0.04);
    border: 1px solid rgba(201, 149, 58, 0.14);
    border-left: 3px solid var(--accent-dim);
    border-radius: 0 3px 3px 0;
    font-family: 'Source Serif 4', serif;
    font-size: 0.87rem;
    font-style: italic;
    color: var(--text-secondary);
    line-height: 1.55;
    margin-bottom: 10px;
}

/* ---- QI stats row ---- */
.qi-stats {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    margin-bottom: 10px;
}
.qi-stat {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.72rem;
    color: var(--text-muted);
    padding: 3px 8px;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 2px;
}
.qi-stat strong {
    color: var(--text-secondary);
    font-weight: 500;
}
.qi-boost-pill {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.72rem;
    color: var(--accent);
    padding: 3px 8px;
    background: var(--accent-glow);
    border: 1px solid rgba(201, 149, 58, 0.2);
    border-radius: 2px;
}

/* ---- Suggestion cards (critic output) ---- */
.suggestion-card {
    position: relative;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-left: 3px solid var(--border-accent);
    border-radius: 0 4px 4px 0;
    padding: 9px 12px 10px 12px;
    margin-bottom: 7px;
    transition: background 0.15s ease;
}
.suggestion-card:hover { background: var(--bg-elevated); }
.suggestion-card.p-high  { border-left-color: var(--danger); }
.suggestion-card.p-medium { border-left-color: var(--warning); }
.suggestion-card.p-low   { border-left-color: var(--border-accent); }
.sug-header {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 5px;
}
.sug-source {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.77rem;
    color: var(--text-secondary);
    background: var(--bg-elevated);
    padding: 1px 7px;
    border-radius: 2px;
    border: 1px solid var(--border);
    flex-shrink: 0;
}
.sug-issue {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.67rem;
    text-transform: uppercase;
    letter-spacing: 0.09em;
    padding: 2px 6px;
    border-radius: 2px;
    flex-shrink: 0;
}
.sug-issue.thin_description    { color: var(--warning);    background: rgba(232,180,58,0.08); }
.sug-issue.missing_metrics     { color: var(--danger);     background: rgba(232,88,88,0.08); }
.sug-issue.vague_impact        { color: var(--warning);    background: rgba(232,180,58,0.08); }
.sug-issue.missing_tech_detail { color: var(--accent);     background: var(--accent-glow); }
.sug-priority {
    margin-left: auto;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.67rem;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    flex-shrink: 0;
}
.sug-priority.high   { color: var(--danger); }
.sug-priority.medium { color: var(--warning); }
.sug-priority.low    { color: var(--text-muted); }
.sug-text {
    font-family: 'Source Serif 4', serif;
    font-size: 0.86rem;
    color: var(--text-secondary);
    line-height: 1.5;
}

/* ---- Tabs (BaseWeb) ---- */
[data-baseweb="tab-list"] {
    background: transparent !important;
    border-bottom: 1px solid var(--border) !important;
    gap: 0 !important;
}
[data-baseweb="tab"] {
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.78rem !important;
    text-transform: uppercase !important;
    letter-spacing: 0.12em !important;
    color: var(--text-secondary) !important;
    background: transparent !important;
    border-bottom: 2px solid transparent !important;
    padding: 10px 20px !important;
}
[data-baseweb="tab"][aria-selected="true"] {
    color: var(--accent) !important;
    border-bottom-color: var(--accent) !important;
}
[data-baseweb="tab-highlight"] {
    background-color: var(--accent) !important;
}
[data-baseweb="tab-panel"] {
    background: transparent !important;
}

/* ---- Bank Health tab ---- */
.bh-stats {
    display: flex;
    gap: 16px;
    margin-bottom: 20px;
}
.bh-stat {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 12px 20px;
    text-align: center;
    flex: 1;
}
.bh-stat-value {
    font-family: 'JetBrains Mono', monospace;
    font-size: 1.6rem;
    font-weight: 700;
    line-height: 1;
    margin-bottom: 4px;
}
.bh-stat-label {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.65rem;
    text-transform: uppercase;
    letter-spacing: 0.15em;
    color: var(--text-muted);
}
.bh-stat-value.active { color: var(--accent); }
.bh-stat-value.stale  { color: var(--warning); }
.bh-stat-value.dismissed { color: var(--text-muted); }

.bh-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 12px 16px;
    margin-bottom: 10px;
}
.bh-card.stale-card {
    opacity: 0.6;
    border-style: dashed;
}
.bh-card-header {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 6px;
    flex-wrap: wrap;
}
.bh-source {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.78rem;
    color: var(--text-primary);
    font-weight: 500;
}
.bh-issue {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.67rem;
    color: var(--accent);
    background: var(--accent-glow);
    padding: 2px 8px;
    border-radius: 2px;
}
.bh-seen {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.67rem;
    color: var(--text-muted);
}
.bh-jds {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.65rem;
    color: var(--text-muted);
    margin-top: 6px;
}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

UI_MODELS: dict[str, str] = {
    "GPT-5.4": "gpt-5.4",
    "GPT-5.4 Mini": "gpt-5.4-mini",
    "GPT-5.4 Nano": "gpt-5.4-nano",
    "Claude Sonnet 4.6": "claude-sonnet-4-6",
    "Claude Haiku 4.5": "claude-haiku-4-5",
}


def render_pdf_preview(pdf_path: Path) -> bytes:
    """Render the first page of a PDF to PNG, cropped to its content bbox.

    Cropping to the content bbox keeps the preview tight around the resume
    content instead of rendering the full US Letter page with a blank white
    bottom strip.
    """
    doc = fitz.open(str(pdf_path))
    try:
        page = doc[0]
        blocks = page.get_text("blocks")
        if blocks:
            x0 = min(b[0] for b in blocks)
            y0 = min(b[1] for b in blocks)
            x1 = max(b[2] for b in blocks)
            y1 = max(b[3] for b in blocks)
            margin = 24.0  # ~0.33" cosmetic breathing room
            page_rect = page.rect
            clip = fitz.Rect(
                max(page_rect.x0, x0 - margin),
                max(page_rect.y0, y0 - margin),
                min(page_rect.x1, x1 + margin),
                min(page_rect.y1, y1 + margin),
            )
            pix = page.get_pixmap(dpi=150, clip=clip)
        else:
            pix = page.get_pixmap(dpi=150)
        return pix.tobytes("png")
    finally:
        doc.close()


def load_report(output_dir: Path) -> dict | None:
    """Read report.json if it exists."""
    rp = output_dir / "report.json"
    if rp.exists():
        return json.loads(rp.read_text(encoding="utf-8"))
    return None


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("""
    <div class="jp-brand">
        <p class="jp-title">JobPlanner</p>
        <div class="jp-rule"></div>
        <p class="jp-subtitle">Automated Resume Tailoring</p>
    </div>
    """, unsafe_allow_html=True)
    st.markdown("---")

    model_display = st.selectbox(
        "Model",
        options=list(UI_MODELS.keys()),
        index=1,  # default: GPT-5.4 Mini
    )
    model_alias = UI_MODELS[model_display]

    st.markdown("---")

    pipeline_mode = st.radio(
        "Pipeline Mode",
        options=["Quality", "Speed"],
        index=0,
        horizontal=True,
        help="Quality: runs critic/improve pass for stronger bullets. Speed: skips critic pass.",
    )
    skip_critic_ui = pipeline_mode == "Speed"
    st.caption("Quality runs a critic pass that rewrites weak bullets." if not skip_critic_ui
               else "Speed skips the critic pass — faster, slightly lower quality.")

    st.markdown("---")

    # Bank summary
    with st.expander("Experience Bank", expanded=False):
        try:
            settings_tmp = load_settings()
            bank = load_bank(settings_tmp.bank_path)
            st.markdown(f"**{bank.meta.name}**")
            st.caption(f"{len(bank.education)} education  /  "
                       f"{len(bank.experience)} experiences  /  "
                       f"{len(bank.projects)} projects")
            total = sum(len(e.bullets) for e in bank.experience) + \
                    sum(len(p.bullets) for p in bank.projects)
            st.caption(f"{total} source bullets  /  "
                       f"{len(bank.inferred_skills)} inferred skills")

            warnings = validate_bank(settings_tmp.bank_path)
            if warnings:
                for w in warnings:
                    st.warning(w)
            else:
                st.success("Bank is valid")
        except Exception as exc:
            st.error(f"Could not load bank: {exc}")


# ---------------------------------------------------------------------------
# UI-test fixture — populate session_state with a prebuilt PipelineResult
# without calling any LLM API. Enabled by setting JOBPLANNER_UI_FIXTURE=1.
#
# This is the hook used by tests/test_app_smoke.py and the Playwright visual
# smoke test. It's also useful during local UI development: export the env
# var and restart streamlit to eyeball every results-panel code path without
# spending tokens on a real pipeline run.
# ---------------------------------------------------------------------------

if os.environ.get("JOBPLANNER_UI_FIXTURE") == "1" and "result" not in st.session_state:
    try:
        # Import lazily so production runs don't pay for the test-only
        # import surface (tests/ is not shipped in the wheel).
        from tests.fixtures.ui_fixture import build_ui_fixture  # type: ignore

        fixture_root = Path(
            os.environ.get(
                "JOBPLANNER_UI_FIXTURE_DIR",
                str(Path.cwd() / ".jp_ui_fixture"),
            )
        )
        st.session_state["result"] = build_ui_fixture(fixture_root)
    except Exception as exc:  # surface, but don't block the app
        st.warning(f"UI fixture load failed: {exc}")


# ---------------------------------------------------------------------------
# Main area — tabs
# ---------------------------------------------------------------------------

tab_tailor, tab_health = st.tabs(["Resume Tailor", "Bank Health"])

# ---------------------------------------------------------------------------
# Tab 1: Resume Tailor
# ---------------------------------------------------------------------------

with tab_tailor:
    st.markdown('<div class="section-header">Job Description</div>', unsafe_allow_html=True)

    jd_text = st.text_area(
        "Paste the full job description",
        height=220,
        placeholder="Paste a job description here and click Generate...",
        label_visibility="collapsed",
    )

    # Stage 3: per-run tailoring controls
    st.markdown('<div class="section-header">Tailoring Controls</div>', unsafe_allow_html=True)

    # Role exclusion — populate from the bank if it loads cleanly
    _role_options: list[str] = []
    try:
        _bank_for_opts = load_bank(load_settings().bank_path)
        _role_options = [e.id for e in _bank_for_opts.experience] + \
                        [p.id for p in _bank_for_opts.projects]
    except Exception:
        pass
    exclude_roles_ui = st.multiselect(
        "Exclude experiences/projects",
        options=_role_options,
        default=[],
        help="source_ids to hard-exclude from this run (hidden from the LLM).",
    )

    generate = st.button(
        "GENERATE RESUME",
        type="primary",
        disabled=not jd_text.strip(),
        use_container_width=True,
    )

    # Pipeline execution
    if generate and jd_text.strip():
        settings = load_settings(model=model_alias)
        settings.exclude_roles = list(exclude_roles_ui)
        progress_lines: list[str] = []

        with st.status("Running pipeline...", expanded=True) as status:
            log_area = st.empty()

            def on_progress(msg: str) -> None:
                progress_lines.append(msg)
                log_area.code("\n".join(progress_lines), language=None)

            try:
                result = run_pipeline(
                    jd_text,
                    settings,
                    skip_critic=skip_critic_ui,
                    on_progress=on_progress,
                )
                st.session_state["result"] = result
                if result.pdf_path and result.pdf_path.exists():
                    status.update(label="Pipeline complete", state="complete", expanded=False)
                else:
                    status.update(label="Pipeline finished with issues", state="error", expanded=True)
            except Exception as exc:
                st.error(f"Pipeline error: {exc}")
                status.update(label="Pipeline failed", state="error", expanded=True)


    # -----------------------------------------------------------------------
    # Results display
    # -----------------------------------------------------------------------

    result: PipelineResult | None = st.session_state.get("result")

    if not result:
        st.markdown("""
        <div class="empty-state">
            <div class="hint-icon">\u25A0</div>
            <div class="hint-text">Paste a job description above to generate a tailored resume</div>
        </div>
        """, unsafe_allow_html=True)

    if result and result.pdf_path and result.pdf_path.exists():

        st.markdown('<div class="section-header">Results</div>', unsafe_allow_html=True)

        col_pdf, col_report = st.columns([3, 2], gap="large")

        # ---- Left column: PDF preview ----
        # SCROLL-SAFETY: The image MUST be embedded as base64 inside a single st.markdown
        # call so that the .pdf-frame div actually wraps the <img>.  Splitting across
        # separate st.markdown / st.image calls silently breaks — Streamlit renders each
        # call in its own DOM node, so the browser auto-closes the div before the image,
        # and the max-height / overflow CSS has no effect.  Never split this back out.
        with col_pdf:
            png_bytes = render_pdf_preview(result.pdf_path)
            b64 = base64.b64encode(png_bytes).decode()
            st.markdown(
                f'<div class="pdf-frame">'
                f'<img src="data:image/png;base64,{b64}" style="width:100%"/>'
                f'</div>',
                unsafe_allow_html=True,
            )

            # Download row
            dl1, dl2 = st.columns(2)
            with dl1:
                st.download_button(
                    "DOWNLOAD PDF",
                    data=result.pdf_path.read_bytes(),
                    file_name=result.pdf_path.name,
                    mime="application/pdf",
                    use_container_width=True,
                )
            with dl2:
                if result.tex_path and result.tex_path.exists():
                    st.download_button(
                        "DOWNLOAD .TEX",
                        data=result.tex_path.read_text(encoding="utf-8"),
                        file_name=result.tex_path.name,
                        mime="text/plain",
                        use_container_width=True,
                    )

        # ---- Right column: report ----
        with col_report:
            report = load_report(result.output_dir) if result.output_dir else None
            ats = result.ats_report

            # ATS Score metric
            if ats:
                score = ats.score
                if score >= 75:
                    color = "var(--success)"
                    score_class = "score-good"
                elif score >= 60:
                    color = "var(--warning)"
                    score_class = "score-ok"
                else:
                    color = "var(--danger)"
                    score_class = "score-low"

                st.markdown(f"""
                <div class="metric-card {score_class}">
                    <div class="metric-value" style="color:{color}">{score}</div>
                    <div class="metric-label">ATS Score / 100</div>
                </div>
                """, unsafe_allow_html=True)

            # JD summary
            if result.jd:
                st.markdown(f"""
                <div class="jd-card">
                    <span class="jd-title">{result.jd.title}</span>
                    <span class="jd-company">&nbsp;at {result.jd.company}</span>
                    <div class="jd-meta">
                        {result.jd.role_type} &middot; {result.jd.seniority}
                    </div>
                </div>
                """, unsafe_allow_html=True)

            # Keyword hits
            if ats and ats.keyword_hits:
                st.markdown('<div class="section-header">Keyword Hits</div>', unsafe_allow_html=True)
                pills = "".join(f'<span class="kw-hit">{kw}</span>' for kw in ats.keyword_hits)
                st.markdown(f'<div class="kw-wrap">{pills}</div>', unsafe_allow_html=True)

            # Keyword misses
            if ats and ats.keyword_misses:
                st.markdown('<div class="section-header">Keyword Misses</div>', unsafe_allow_html=True)
                pills = "".join(f'<span class="kw-miss">{kw}</span>' for kw in ats.keyword_misses)
                st.markdown(f'<div class="kw-wrap">{pills}</div>', unsafe_allow_html=True)

            # Inferred skills used
            if report and report.get("inferred_skills_used"):
                st.markdown('<div class="section-header">Inferred Skills Used</div>',
                            unsafe_allow_html=True)
                for sk in report["inferred_skills_used"]:
                    conf = sk.get("confidence", "moderate")
                    st.markdown(f"""
                    <div class="inf-card">
                        <span class="inf-name">{sk["name"]}</span>
                        <span class="inf-badge {conf}">{conf}</span>
                        <div class="inf-basis">{sk.get("basis", "")}</div>
                    </div>
                    """, unsafe_allow_html=True)

            # Validation status
            if result.validation:
                if result.validation.passed:
                    st.markdown(
                        '<div class="validation-pass">'
                        '\u2713 &nbsp;Validation passed \u2014 no hallucinations detected'
                        '</div>',
                        unsafe_allow_html=True,
                    )
                else:
                    errors_html = "".join(
                        f"<div style='font-size:0.68rem; color:var(--text-secondary); "
                        f"margin-top:4px;'>{w.source_id}[{w.bullet_index}]: {w.message}</div>"
                        for w in result.validation.errors
                    )
                    st.markdown(
                        f'<div class="validation-fail">'
                        f'\u2717 &nbsp;Validation failed{errors_html}'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

            # Orphan wrap warnings (short words dangling on line 2)
            if result.orphan_warnings:
                items_html = "".join(
                    f'<div class="orphan-item">{html.escape(o)}</div>'
                    for o in result.orphan_warnings
                )
                st.markdown(
                    f'<div class="orphan-warn">'
                    f'<div class="orphan-title">! {len(result.orphan_warnings)} '
                    f'orphan wrap(s) detected</div>'
                    f'{items_html}'
                    f'</div>',
                    unsafe_allow_html=True,
                )

            # ---- Quality Intelligence ----
            has_qi = (
                result.critic_result
                or (report and (report.get("enrichment_tokens") or report.get("market_boosted_skills")))
            )
            if has_qi:
                st.markdown('<div class="section-header">Quality Intelligence</div>',
                            unsafe_allow_html=True)

                # Critic summary quote
                if result.critic_result and result.critic_result.summary:
                    st.markdown(
                        f'<div class="critic-summary">{result.critic_result.summary}</div>',
                        unsafe_allow_html=True,
                    )

                # Enrichment + market stats row
                if report:
                    tokens = report.get("enrichment_tokens", 0)
                    boosted = report.get("market_boosted_skills") or []
                    stat_parts = []
                    if tokens:
                        stat_parts.append(
                            f'<span class="qi-stat"><strong>~{tokens:,}</strong> enrichment tokens</span>'
                        )
                    if boosted:
                        boost_pills = "".join(
                            f'<span class="qi-boost-pill">{s}</span>' for s in boosted[:6]
                        )
                        stat_parts.append(
                            f'<span class="qi-stat"><strong>{len(boosted)}</strong> market-boosted</span>'
                            + boost_pills
                        )
                    if stat_parts:
                        st.markdown(
                            f'<div class="qi-stats">{"".join(stat_parts)}</div>',
                            unsafe_allow_html=True,
                        )

                # Bank improvement suggestions (JD-specific)
                if result.critic_result and result.critic_result.bank_suggestions:
                    suggs = result.critic_result.bank_suggestions
                    n_high = sum(1 for s in suggs if s.priority == "high")
                    label = (
                        f"Experience Bank — {n_high} high-priority fix{'es' if n_high != 1 else ''}"
                        if n_high else
                        f"Experience Bank — {len(suggs)} suggestion{'s' if len(suggs) != 1 else ''}"
                    )
                    with st.expander(label, expanded=bool(n_high)):
                        for s in sorted(suggs, key=lambda x: {"high": 0, "medium": 1, "low": 2}[x.priority]):
                            issue_class = s.issue.replace(" ", "_")
                            st.markdown(
                                f'<div class="suggestion-card p-{s.priority}">'
                                f'  <div class="sug-header">'
                                f'    <span class="sug-source">{s.source_id} &middot; bullet {s.bullet_index}</span>'
                                f'    <span class="sug-issue {issue_class}">{s.issue.replace("_", " ")}</span>'
                                f'    <span class="sug-priority {s.priority}">{s.priority}</span>'
                                f'  </div>'
                                f'  <div class="sug-text">{s.suggestion}</div>'
                                f'</div>',
                                unsafe_allow_html=True,
                            )

# ---------------------------------------------------------------------------
# Tab 2: Bank Health
# ---------------------------------------------------------------------------

with tab_health:
    from jobplanner.bank.suggestions import (
        get_all_suggestions, get_suggestion_counts, dismiss_suggestion, dismiss_all_stale,
        check_for_conflicts,
    )
    from jobplanner.bank.locator import find_bullet_line, open_in_vscode

    _settings_tmp = load_settings()
    _tracker_db = _settings_tmp.tracker_db_path

    _conflicts = check_for_conflicts(_tracker_db)
    if _conflicts:
        _conflict_lines = "\n".join(f"- `{p.name}`" for p in _conflicts)
        st.error(
            "**Google Drive conflict copies detected next to "
            f"`{_tracker_db.name}`:**\n\n"
            f"{_conflict_lines}\n\n"
            "Pick the version you want to keep, rename it to "
            f"`{_tracker_db.name}`, and delete the others. "
            "SQLite databases can't be auto-merged, so any writes until you "
            "resolve this may be lost on the next sync."
        )

    if not _tracker_db.exists():
        st.markdown("""
        <div class="empty-state">
            <div class="hint-icon">\u25A0</div>
            <div class="hint-text">No suggestions yet. Generate a resume with the critic pass enabled to start accumulating bank improvement suggestions.</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        counts = get_suggestion_counts(_tracker_db)
        total = counts["active"] + counts["stale"] + counts["dismissed"]

        # Summary stats
        st.markdown(f"""
        <div class="bh-stats">
            <div class="bh-stat">
                <div class="bh-stat-value active">{counts["active"]}</div>
                <div class="bh-stat-label">Active</div>
            </div>
            <div class="bh-stat">
                <div class="bh-stat-value stale">{counts["stale"]}</div>
                <div class="bh-stat-label">Stale</div>
            </div>
            <div class="bh-stat">
                <div class="bh-stat-value dismissed">{counts["dismissed"]}</div>
                <div class="bh-stat-label">Dismissed</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # Bulk action
        if counts["stale"] > 0:
            if st.button("Dismiss All Stale", key="bh_dismiss_stale", type="secondary"):
                dismissed = dismiss_all_stale(_tracker_db)
                st.rerun()

        # Show active + stale suggestions
        suggestions = get_all_suggestions(_tracker_db, status="active")
        stale_suggestions = get_all_suggestions(_tracker_db, status="stale")

        if not suggestions and not stale_suggestions:
            st.markdown("""
            <div class="empty-state">
                <div class="hint-text">No active suggestions. Your experience bank looks good!</div>
            </div>
            """, unsafe_allow_html=True)

        for s in suggestions:
            jds = json.loads(s["source_jds"]) if isinstance(s["source_jds"], str) else s["source_jds"]
            jds_text = ", ".join(jds[-3:])  # show last 3 JDs
            if len(jds) > 3:
                jds_text = f"{jds_text} (+{len(jds) - 3} more)"

            col_card, col_edit, col_btn = st.columns([8, 1, 1])
            with col_card:
                st.markdown(
                    f'<div class="bh-card">'
                    f'  <div class="bh-card-header">'
                    f'    <span class="bh-source">{s["source_id"]} &middot; bullet {s["bullet_index"]}</span>'
                    f'    <span class="bh-issue">{s["issue"].replace("_", " ")}</span>'
                    f'    <span class="sug-priority {s["priority"]}">{s["priority"]}</span>'
                    f'    <span class="bh-seen">seen {s["seen_count"]}x</span>'
                    f'  </div>'
                    f'  <div class="sug-text">{s["suggestion"]}</div>'
                    f'  <div class="bh-jds">JDs: {jds_text}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            with col_edit:
                if st.button("Edit", key=f"bh_edit_{s['id']}",
                             help="Open experience.yaml at this bullet in VS Code",
                             type="secondary", use_container_width=True):
                    line = find_bullet_line(
                        _settings_tmp.bank_path, s["source_id"], s["bullet_index"],
                    )
                    if line is None:
                        st.warning(
                            f"Could not locate `{s['source_id']}` in "
                            f"`{_settings_tmp.bank_path}`. Open the file manually."
                        )
                    elif open_in_vscode(_settings_tmp.bank_path, line):
                        st.toast(f"Opened experience.yaml at line {line}")
                    else:
                        st.warning(
                            f"VS Code (`code`) not found on PATH. "
                            f"Open `{_settings_tmp.bank_path}` at line {line} manually."
                        )
            with col_btn:
                if st.button("\u00D7", key=f"bh_dismiss_{s['id']}",
                             help="Dismiss this suggestion",
                             type="secondary", use_container_width=True):
                    dismiss_suggestion(_tracker_db, s["id"])
                    st.rerun()

        # Stale suggestions (dimmed)
        if stale_suggestions:
            st.markdown('<div class="section-header">Stale (bank changed)</div>',
                        unsafe_allow_html=True)
            for s in stale_suggestions:
                jds = json.loads(s["source_jds"]) if isinstance(s["source_jds"], str) else s["source_jds"]
                jds_text = ", ".join(jds[-3:])

                col_card, col_edit, col_btn = st.columns([8, 1, 1])
                with col_card:
                    st.markdown(
                        f'<div class="bh-card stale-card">'
                        f'  <div class="bh-card-header">'
                        f'    <span class="bh-source">{s["source_id"]} &middot; bullet {s["bullet_index"]}</span>'
                        f'    <span class="bh-issue">{s["issue"].replace("_", " ")}</span>'
                        f'    <span class="bh-seen">seen {s["seen_count"]}x</span>'
                        f'  </div>'
                        f'  <div class="sug-text">{s["suggestion"]}</div>'
                        f'  <div class="bh-jds">JDs: {jds_text}</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                with col_edit:
                    if st.button("Edit", key=f"bh_edit_stale_{s['id']}",
                                 help="Open experience.yaml at this bullet in VS Code",
                                 type="secondary", use_container_width=True):
                        line = find_bullet_line(
                            _settings_tmp.bank_path, s["source_id"], s["bullet_index"],
                        )
                        if line is None:
                            st.warning(
                                f"Could not locate `{s['source_id']}` in "
                                f"`{_settings_tmp.bank_path}`. Open the file manually."
                            )
                        elif open_in_vscode(_settings_tmp.bank_path, line):
                            st.toast(f"Opened experience.yaml at line {line}")
                        else:
                            st.warning(
                                f"VS Code (`code`) not found on PATH. "
                                f"Open `{_settings_tmp.bank_path}` at line {line} manually."
                            )
                with col_btn:
                    if st.button("\u00D7", key=f"bh_dismiss_stale_{s['id']}",
                                 help="Dismiss this suggestion",
                                 type="secondary", use_container_width=True):
                        dismiss_suggestion(_tracker_db, s["id"])
                        st.rerun()
