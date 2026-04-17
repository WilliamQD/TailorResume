# JobPlanner

Automated resume tailoring CLI. Paste a job description → get a tailored, ATS-compliant, 1-page PDF resume.

## Project Structure
- `src/jobplanner/` — main package
  - `llm/` — LLM abstraction (Claude + OpenAI providers)
  - `bank/` — experience bank schema, loader, locator (path resolution), AI-assisted updater, persistent suggestions
  - `parser/` — job description parser
  - `tailor/` — resume tailoring agent, prompt enrichment, hallucination validator, and programmatic line-fill gate (`length_gate.py`)
  - `latex/` — Jinja2 renderer + tectonic PDF compiler
  - `checker/` — ATS text extraction, proofreader, and post-tailor `critic.py` (feeds `length_gate.py`)
  - `market/` — skill tracker DB layer (shared with `bank/suggestions.py`)
  - `config.py` — model alias resolution + `JOBPLANNER_MODEL` env var reader
  - `pipeline.py` — end-to-end orchestrator
  - `cli.py` / `__main__.py` — Click CLI entry points (`python -m jobplanner ...`)
  - `app.py` — Streamlit web UI
- `data/experience.yaml` — THE source of truth for all resume content (gitignored; copy from `experience.example.yaml`)
- `data/templates/` — Jinja2 LaTeX templates
- `output/` — generated resumes, organized as `output/YYYY-MM-DD/{company}_{title}/` (gitignored)

## Commands
```bash
pip install -e ".[dev]"                          # Install in dev mode
python -m jobplanner tailor --jd job.txt         # Full pipeline (default: gpt-5.4-mini)
python -m jobplanner tailor --jd job.txt --model claude-sonnet-4-6  # Use Claude
python -m jobplanner bank validate               # Validate experience.yaml
python -m jobplanner bank update                 # AI-assisted bank update
python -m jobplanner bank show                   # Show bank summary
python -m jobplanner preview --jd job.txt        # Dry run (no PDF)
python -m jobplanner ats-check resume.pdf        # ATS check only
pytest                                           # Run tests
pip install -e ".[web]"                          # Install with web UI
streamlit run src/jobplanner/app.py              # Launch web UI
```

## API Keys

Keys are resolved in order: **env var → Python `keyring` → PowerShell SecretStore fallback**.
The keyring tier is cross-platform (macOS Keychain, Windows Credential Manager,
Linux Secret Service); the PowerShell tier is Windows-only and skipped on other
platforms.

| Provider | Env var | Keyring/SecretStore name |
|----------|---------|--------------------------|
| Claude | `ANTHROPIC_API_KEY` | `JP-claude-apikey` (service: `jobplanner`) |
| OpenAI | `OPENAI_API_KEY` | `JP-openai-apikey` (service: `jobplanner`) |

**Keyring setup (cross-platform, recommended for Mac/Linux):**
```bash
python -c "import keyring; keyring.set_password('jobplanner', 'JP-claude-apikey', 'sk-ant-...')"
python -c "import keyring; keyring.set_password('jobplanner', 'JP-openai-apikey', 'sk-...')"
```

**PowerShell SecretStore setup (Windows-only, still supported as fallback):**
```powershell
Install-Module Microsoft.PowerShell.SecretManagement -Scope CurrentUser -Force
Install-Module Microsoft.PowerShell.SecretStore -Scope CurrentUser -Force
Register-SecretVault -Name 'SecretStore' -ModuleName 'Microsoft.PowerShell.SecretStore' -DefaultVault
Set-SecretStoreConfiguration -Authentication None -Confirm:$false   # passwordless access
Set-Secret -Name 'JP-claude-apikey' -Secret '<your-key>'
Set-Secret -Name 'JP-openai-apikey' -Secret '<your-key>'
```

## Other Environment Variables
- `JOBPLANNER_MODEL` — default model (default: `gpt-5.4-mini`)
- `JOBPLANNER_DATA_DIR` — personal-data root directory (default: repo's `data/`).
  When set, `experience.yaml` and `market/skill_tracker.db` are read from this
  location instead of the repo. Templates and guidelines stay under the repo's
  `data/` regardless. See "Personal Data Sync" below for cross-machine setup.

## Personal Data Sync (Cross-Laptop)
The experience bank and skill-tracker DB are personal data that can be synced
across machines via Google Drive for Desktop (or any folder-sync tool) by
pointing `JOBPLANNER_DATA_DIR` at a shared location.

**Windows (William's setup):**
```powershell
[Environment]::SetEnvironmentVariable('JOBPLANNER_DATA_DIR', 'D:\w4343\Documents\JobPlannerData', 'User')
# Restart shell / VS Code so the new env var is picked up
```

**Mac (William's setup):**
```bash
echo 'export JOBPLANNER_DATA_DIR="$HOME/Documents/Github/JobPlannerData"' >> ~/.zshrc
source ~/.zshrc
```

The synced directory layout must mirror the repo's `data/`:
```
JobPlannerData/
├── experience.yaml
└── market/
    └── skill_tracker.db
```

**Concurrency caveat:** the SQLite tracker DB is binary and cannot be merged.
Wait for Google Drive to fully sync before switching laptops mid-edit, or you
risk a conflict copy that loses bank suggestions. The `output/` folder is
intentionally **not** synced — it's regenerable per-machine.

## Experience Bank Schema (V2 — Synthesis Mode)
- Bullets in `experience.yaml` contain **factual descriptions** (`description`), not resume-ready text
- Each bullet has: `description`, `tech_stack`, `skills`, `metrics`, `context`
- The tailor agent **synthesizes** resume bullets from facts based on the JD
- `inferred_skills` section: skills inferred from coursework with `basis` and `confidence`
  - Inferred skills may appear in the **skills section** for keyword matching
  - They must NEVER be used to fabricate experience bullets
- `source_bullet_indices` (list) on tailored bullets: one output may draw from multiple sources

## Token Optimization
- Bank serialization strips `context` field (saves ~200 tokens per prompt)
- Global `skills` section omitted from prompts (redundant with per-bullet skills)
- All experiences always included; projects filtered by relevance + anchor IDs
- Anchor projects (marked with `anchor: true` in experience.yaml) always included regardless of tag overlap
- Coursework → skill inference done offline by Claude Code, not by API at runtime
- `report.json` includes `inferred_skills_used` list showing which inferred skills appeared

## Web UI (`app.py`)
- Two-tab layout: "Resume Tailor" (JD input + pipeline + results) and "Bank Health" (persistent suggestions)
- Streamlit dark theme — all custom CSS lives in the `<style>` block at the top of `app.py`
- After every UI change, visually verify the running app in a browser before considering the change done
- Streamlit uses BaseWeb components — dropdown/popover/tab selectors require `[data-baseweb="..."]` overrides
- All colors must reference `--bg-*`/`--text-*`/`--accent-*` CSS variables for consistency
- No Streamlit `icon=` parameters — Streamlit rejects Unicode symbols (e.g. `\u2713`), only accepts emoji
- **Framework-first**: Work WITH Streamlit's native layout, not against it. Never override `position`, `overflow`, or `height` on framework containers (`.stApp`, `stAppViewContainer`, `stMain`, `stSidebar`). Only override `background-color` and cosmetic styles.
- **Failed-fix hygiene**: If a CSS fix doesn't work, remove it. Don't layer more fixes on top. Don't encode unverified theories as permanent comments or instructions.
- **Label rule**: Form-widget labels use a SINGLE global rule. Never scope to sidebar only. Add new widget classes to the global rule.
- **Textarea override**: Both `[data-baseweb="textarea"]` and `[data-baseweb="base-input"]` must be overridden to `var(--bg-card)` — their defaults leak light.
- **PDF-preview crop**: `render_pdf_preview()` clips to the content bbox. Gated by `tests/test_app_pdf_preview.py`.
- **PDF embed**: The preview `<img>` must be inside the same `st.markdown` call as its wrapper `<div>` — splitting breaks the wrapper.

## UI Verification Workflow
Two test gates catch visual regressions that don't crash the app:

1. **Smoke test** — [tests/test_app_smoke.py](tests/test_app_smoke.py): in-memory `AppTest`, catches crashes and missing widgets (~25s).
2. **Visual test** — [tests/test_app_visual.py](tests/test_app_visual.py): headless Chromium via Playwright, screenshot to `.jp_ui_screenshot/app.png`, asserts no large white elements and dark backgrounds (~15s). Setup: `pip install playwright && python -m playwright install chromium`.

**Fixture** — [tests/fixtures/ui_fixture.py](tests/fixtures/ui_fixture.py): `build_ui_fixture(path)` produces a full `PipelineResult` from `experience.example.yaml` with zero LLM calls. Eyeball locally with:
```bash
JOBPLANNER_UI_FIXTURE=1 streamlit run src/jobplanner/app.py
```

## Bank Suggestions
- Bank improvement suggestions are persisted in SQLite (`data/market/skill_tracker.db`) alongside market data
- Suggestions accumulate across JD runs: upsert on (source_id, bullet_index, issue), tracking seen_count and source JDs
- Status lifecycle: `active` → `stale` (when experience.yaml changes) → `active` (if re-seen) or `dismissed`
- Bank Health tab shows all accumulated suggestions, sortable by frequency/priority/recency

## Coursework Selection
- Max 4 courses per school, 8 total across all schools
- Concept-level dedup: strips common prefixes ("Intro to", "Advanced", etc.) and checks substring overlap across schools
- Safety-net dedup in renderer catches anything the LLM misses

## Page Fill
- Target: 93% fill ratio (progressive escalation over 3 retries)
- Retry 1: bump project bullets to 3; Retry 2: bump experience bullets to 4; Retry 3: allow a 3rd project
- Anchor projects (`anchor: true` in experience.yaml) always get 3 bullets — enforced in the tailor prompt, not a config field. Non-anchor projects get the default `max_bullets_per_project` cap (2).
- Bottom page margin is 0.4in (tightened from 0.5in) to eat more bottom whitespace.
- No user-facing page-target or tone controls — the pipeline is always strict one-page, and the prompt bakes in a single HR-friendly plain-English voice.

## Conventions
- Pydantic v2 for all data models
- YAML for human-editable data (experience bank)
- Jinja2 custom delimiters (`<< >>`, `<% %>`) for LaTeX templates
- All AI calls go through `llm/base.py` LLMClient protocol
- Every tailored bullet must cite its source via `source_id` + `source_bullet_indices`
- Audience-aware tailoring: bullets are framed differently depending on the JD's discipline — but the voice is ALWAYS plain HR-friendly English, never discipline jargon piled into clusters
- **Line-fill rule** (measured programmatically, NOT by the LLM): every bullet either fits one printed line (≤ 105 chars) or fills two (≥ 185 chars). The 106-184 forbidden zone wraps with 1-5-word tails and wastes space. LLMs cannot reliably count characters, so enforcement is Python-side via `tailor/length_gate.py` — it runs after the critic, flags any forbidden-zone bullet, and issues one batched LLM rewrite call per round (max 2 rounds). Zero extra API cost on clean runs. The tailor prompt and critic prompt carry only soft guidance — the gate is authoritative.
- **LaTeX orphan-wrap invariants**: `data/templates/resume.tex.j2` loads `ragged2e` and `microtype` with `protrusion=true,final`, then sets `\tolerance=2000`, `\emergencystretch=5em`, `\hyphenpenalty=1000`, `\exhyphenpenalty=1000`. Bulleted lists use `before=\RaggedRight` via enumitem. The skills (`sections/skills.tex.j2`) and coursework (`sections/education.tex.j2`) blocks wrap their `{\small ...}` body in `\RaggedRight`. **Never remove any of these** — they form the LaTeX-level safety net that catches the shallowest overflows (~106-117 chars) before the length gate sees them. **Do NOT add `expansion=true` to the microtype options** — it's incompatible with XeTeX (which tectonic uses) and fails compilation. After compile, `detect_orphan_lines()` in `latex/compiler.py` scans the rendered PDF for 1-5-word tails and surfaces them as warnings in `PipelineResult.orphan_warnings`. Bullets the length gate couldn't fix are surfaced separately as `PipelineResult.length_warnings`. Both appear as yellow banners in the Streamlit results column and are persisted to `report.json`.
- **Skills-line cap**: maximum 7 skills per line AND the full rendered line (label + joined skills) must be ≤ 110 characters. Enforced in the tailor prompt's `# SKILLS SECTION — CRITICAL` block. An 8-skill line at ~130 chars always wraps with 1-2 orphan words.
