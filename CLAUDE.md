# JobPlanner

Automated resume tailoring CLI. Paste a job description → get a tailored, ATS-compliant, 1-page PDF resume.

## Project Structure
- `src/jobplanner/` — main package
  - `llm/` — LLM abstraction (Claude + OpenAI providers)
  - `bank/` — experience bank schema, loader, AI-assisted updater, persistent suggestions
  - `parser/` — job description parser
  - `tailor/` — resume tailoring agent + hallucination validator
  - `latex/` — Jinja2 renderer + tectonic PDF compiler
  - `checker/` — ATS text extraction + proofreader
  - `pipeline.py` — end-to-end orchestrator
  - `cli.py` — Click CLI entry point
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
- Target: 90% fill ratio (progressive escalation over 3 retries)
- Retry 1: bump project bullets to 3; Retry 2: bump experience bullets to 4; Retry 3: allow a 3rd project

## Conventions
- Pydantic v2 for all data models
- YAML for human-editable data (experience bank)
- Jinja2 custom delimiters (`<< >>`, `<% %>`) for LaTeX templates
- All AI calls go through `llm/base.py` LLMClient protocol
- Every tailored bullet must cite its source via `source_id` + `source_bullet_indices`
- Audience-aware tailoring: bullets are framed differently depending on the JD's discipline
