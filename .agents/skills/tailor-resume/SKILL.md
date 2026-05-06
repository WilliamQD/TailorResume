---
name: tailor-resume
description: Run JobPlanner's full tailoring pipeline against a pasted job description. Reads data/experience.yaml, produces an ATS-checked PDF, and reports keyword coverage plus bank-improvement suggestions. Use when the user wants a resume tailored to a specific JD from inside Codex.
---

# tailor-resume

A thin wrapper around JobPlanner's `python -m jobplanner tailor` CLI.
This skill does **not** replace the pipeline; it just drives it from inside
Codex so the user does not have to switch terminals.

## When to invoke

The user says something like "tailor my resume for this JD", pastes a job
posting, or explicitly runs `/tailor-resume`.

## Inputs you need from the user

1. **JD text or file path.** If they paste text, write it to a tempfile first.
   If they give a path, pass it through unchanged.
2. **Optional knobs** (all have sensible defaults; only ask if the user
   mentions them):
   - `exclude_roles` - list of source_ids to hard-filter out of the bank
   - `emphasize_roles` - list of source_ids to soft-boost in the tailor prompt
   - `skip_proofread` / `skip_critic` - skip optional LLM review stages
   - `model` - override `JOBPLANNER_MODEL` (passed before the subcommand)

## How to run the pipeline

1. If the JD is pasted inline, write it to a temp file under `./output/.tmp_jd.txt`
   (create the dir if missing; do not use `/tmp` on Windows).
2. Build the command:
   ```bash
   python -m jobplanner [--model <model>] tailor --jd <path> \
     [--skip-proofread] \
     [--skip-critic] \
     [--exclude-roles <id> --exclude-roles <id> ...] \
     [--emphasize-roles <id> ...]
   ```
   Only include flags the user actually specified; omit the rest so the CLI
   falls back to `Settings` defaults.
3. Run from the repo root with the active shell. The pipeline prints progress inline.
4. On success, the final stage prints the output directory:
   `output/YYYY-MM-DD/<company>_<title>/`. Read `report.json` from that dir.

## What to report back to the user

Keep the summary terse; they already saw the stdout. Report:

- **PDF path** (clickable link via markdown).
- **Page count** and fill ratio.
- **ATS score** and keyword coverage (from `report.json` -> `ats`).
- **Top 3 keyword misses** (from `report.json` -> `ats.missing_keywords`).
- **Top 3 bank-improvement suggestions** (from `report.json` ->
  `bank_suggestions`, sorted by `priority` desc).
- **Any errors or warnings** from the validator / proofreader.

If the pipeline halted with an error (e.g. source-citation validator failure),
show the error verbatim and stop; do not try to "fix" the bank automatically.

## Things NOT to do

- Do **not** hand-write bullets or edit `experience.yaml` unless the user
  explicitly asks. The bank is the source of truth; the pipeline synthesizes
  from it.
- Do **not** re-run the pipeline more than twice without telling the user
  what changed between runs. Each run costs tokens.
- Do **not** suggest adopting buzzwords or generic phrasing; the critic and
  style-gate validator exist specifically to remove those.
- Do **not** parse PDF contents yourself. Use `report.json`; it already has
  extracted keyword coverage and ATS scoring.

## Troubleshooting

- **"LLM refused to synthesize" / validator halted with source-citation errors** ->
  the bank is missing facts the LLM tried to cite. Surface the error, point
  the user at `data/experience.yaml`, and suggest `python -m jobplanner bank update`.
- **Page fill ratio < 90%** -> the pipeline already retried with progressive
  escalation. Point the user at the report and suggest adding source-bank facts
  if the bank does not contain enough role-relevant material.
- **"Missing ANTHROPIC_API_KEY"** -> point at `CLAUDE.md` -> "API Keys" section.
