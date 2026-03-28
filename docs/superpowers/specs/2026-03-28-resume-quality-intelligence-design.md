# Resume Quality Intelligence Layer — Design Spec

## Context

JobPlanner generates tailored resumes that are technically correct (source citations, anti-hallucination validation, ATS keyword coverage, one-page auto-fit). However, the output quality has several gaps that reduce interview conversion:

- **Bullet language feels generic** — correct but lacking the punch of hand-crafted resumes
- **Wrong emphasis/framing** — experiences framed poorly for the target role type
- **Skills section misaligned** — doesn't reflect what the JD actually cares about
- **Weak overall strategy** — no coherent story arc or 6-second scan optimization
- **Coursework unfocused** — too many courses, not tailored enough
- **Project portfolio gaps** — existing projects may be outdated or misaligned with market demands

This design adds a **Resume Quality Intelligence Layer**: expert guidelines, exemplary materials, a post-tailor critic pass, and market intelligence from accumulated JD data. The goal is to close the gap between "technically valid resume" and "resume that gets interviews."

---

## Pipeline Changes

**Current:** Parse JD → Tailor → Validate → Render → Compile → ATS Check → Proofread

**New:** Parse JD → **Enrich Context** → Tailor (enhanced) → Validate → **Critic/Improve** → Re-validate → Render → Compile → ATS Check → Proofread → **Accumulate Market Data**

Three new stages:

1. **Enrich Context** — Loads resume guidelines, exemplary bullets, structure templates, and market-boosted skills for the detected `role_type`. Injects into the tailor prompt.
2. **Critic/Improve** — Post-tailor LLM call that evaluates the resume against quality criteria and rewrites weak bullets. Also generates bank improvement suggestions. Skippable via `--skip-critic`.
3. **Accumulate Market Data** — Appends parsed JD skills/keywords to the SQLite skill tracker. No LLM call.

---

## Component 1: Resume Guidelines System

**File:** `data/guidelines/resume_rules.md`

Structured Markdown document containing expert resume-writing rules organized by category. Sourced primarily from Claude's training knowledge, supplemented by user-provided tips (Rednote, career coaches, etc.).

### Structure

```markdown
# Resume Writing Guidelines

## Bullet Writing
- Lead with strongest action verb (built > developed > helped)
- Impact-first: what changed because of your work, then how
- Quantify everything possible: %, $, time saved, users served, scale
- One accomplishment per bullet — don't cram two achievements
- Avoid "responsible for" — show what you DID, not your job description
- [before/after examples per rule]

## 6-Second Scan Optimization
- Top 1/3 of resume must contain strongest selling points
- Most relevant experience first within each section
- Most impactful bullet first within each experience
- Skills section: JD-matching skills in first positions
- [visual density, whitespace rules]

## Sector-Specific Rules
### Data Science
- Lead with methodology and rigor, not tools
- [DS-specific before/after examples]
### Software Engineering
- Lead with scale and architecture decisions
- [SWE-specific examples]
### MLE / ML Infrastructure
- Balance: model performance + production readiness
### Finance / Analyst
- Lead with business problem, financial metrics
### Biostatistics
- Clinical rigor, regulatory awareness, study design

## ATS & Human Reader
- Exact keyword matching — use the JD's exact phrasing
- Standard section headers: EXPERIENCE, EDUCATION, SKILLS
- [current market insights about AI screening]

## Common Mistakes
- Listing duties instead of accomplishments
- Generic skills dumps
- Inconsistent formatting
```

### Usage

- Loaded at "Enrich Context" stage
- **Extraction logic:** Universal sections (Bullet Writing, 6-Second Scan, ATS & Human Reader, Common Mistakes) are always included. The matching sector subsection under "Sector-Specific Rules" is appended. Other sectors are excluded. This produces the condensed excerpt (~500-800 tokens).
- Full document given to critic pass for detailed evaluation
- User-editable — add rules anytime, changes take effect on next run

---

## Component 2: Exemplary Bullet Bank

**File:** `data/guidelines/exemplary_bullets.yaml`

Few-shot examples of great resume bullets per sector, with anti-patterns and annotations explaining why they're good or bad.

### Schema

```yaml
swe:
  bullets:
    - text: "Redesigned payment processing pipeline to handle 3x traffic during peak sales, reducing P99 latency from 800ms to 120ms by introducing async event processing with Kafka and circuit-breaker patterns"
      why_good: "Leads with impact (3x scale), quantifies before/after, names specific techniques"
    - text: "Built internal developer platform serving 200+ engineers, cutting deployment time from 45min to 3min through automated canary releases and infrastructure-as-code with Terraform"
      why_good: "Shows scale (200+ engineers), dramatic improvement (45→3min), concrete tools"
  anti_patterns:
    - text: "Responsible for maintaining backend services and fixing bugs"
      why_bad: "Duty description, no impact, no specifics"
    - text: "Leveraged cutting-edge cloud-native technologies to spearhead innovative solutions"
      why_bad: "Buzzword salad, zero substance"

ds:
  bullets:
    - text: "Developed mixed-effects survival model identifying 3 novel biomarkers predictive of treatment response (HR=0.62, p<0.001), directly informing Phase III trial stratification criteria"
      why_good: "Methodology-first, precise statistics, clear clinical impact"
  anti_patterns:
    - text: "Used Python and machine learning to analyze data and generate insights"
      why_bad: "Generic, no methodology, no impact, what insights?"

mle:
  bullets: [...]
  anti_patterns: [...]

# Additional sectors: de, finance, biostats, analyst
```

### Usage

- 3-4 good bullets + 1-2 anti-patterns injected into tailor prompt as few-shot examples (~300-500 tokens)
- `why_good` / `why_bad` annotations teach the LLM principles, not just patterns
- Critic also references these to calibrate its quality bar
- Initial seeding by Claude Code, reviewed and edited by user before committing

---

## Component 3: Resume Structure Templates

**File:** `data/guidelines/resume_structures.yaml`

Per-sector structural guidance covering story arc, section ordering, space allocation, and top-third scan strategy.

### Schema

```yaml
swe:
  story_arc: >
    "I build systems that scale and ship reliably."
    Lead with the most technically impressive or highest-scale experience.
    Show progression: individual contributor → system owner → cross-team impact.
  section_order: [skills, experience, projects, education]
  space_allocation:
    skills: "10% — 3 lines, tools-heavy, JD keywords front-loaded"
    experience: "55% — this is where you win or lose"
    projects: "20% — show initiative and breadth beyond work"
    education: "15% — degrees, relevant coursework, GPA if strong"
  top_third_strategy: >
    Name/contact → Skills (tools the hiring manager ctrl+F for) →
    Most impressive experience with scale/impact bullets.
    A SWE hiring manager scans for: languages, frameworks, scale numbers.
  bullet_ordering: "Lead with architecture/scale, then impact metrics, then collaboration"
  coursework_strategy: "Prioritize systems, algorithms, distributed computing. Skip intro courses."

ds:
  story_arc: >
    "I turn data into decisions with statistical rigor."
    Lead with the most methodologically sophisticated work.
    Show: rigorous methods → real-world impact → domain fluency.
  section_order: [education, skills, experience, projects]
  space_allocation:
    education: "20% — DS values credentials, methods courses, GPA"
    skills: "10% — methods first, tools second"
    experience: "50% — methodology-driven bullets"
    projects: "20% — shows independent analytical thinking"
  top_third_strategy: >
    Name/contact → Education (Yale MS signals rigor) →
    Skills (statistical methods first, then tools) →
    Most methodologically impressive experience.
    A DS hiring manager scans for: statistical methods, study design, domain knowledge.
  bullet_ordering: "Lead with methodology, then results/metrics, then tools used"
  coursework_strategy: "Prioritize statistics, ML, methods courses. Skip general CS intro."

mle:
  story_arc: >
    "I build ML systems that work in production."
    Balance: model development + infrastructure + deployment.
  section_order: [skills, experience, projects, education]
  # ...

finance:
  story_arc: >
    "I solve business problems with quantitative rigor."
    Lead with business impact, not technical implementation.
  section_order: [education, experience, skills, projects]
  # ...

biostats:
  story_arc: >
    "I design rigorous studies and extract clinical insights."
    Lead with study design, regulatory context, clinical impact.
  section_order: [education, skills, experience, projects]
  # ...
```

### Usage

- Loaded at "Enrich Context" stage alongside guidelines and exemplary bullets
- Injected into tailor prompt's structural guidance section (~200-300 tokens)
- Replaces the current brief "audience-aware tailoring" paragraphs with richer strategic guidance
- Critic uses it to evaluate whether overall resume structure matches sector expectations
- **Note on section ordering:** The current LaTeX template (`data/templates/resume.tex.j2`) has a hardcoded section order (Education → Skills → Experience → Projects). The `section_order` field here guides the LLM on what to *emphasize* and how to *allocate space*, but changing the actual rendered order requires template modifications (conditional block ordering in Jinja2). This is deferred to Phase 2 implementation — if the benefit is marginal, we keep the fixed order and use `section_order` purely as prompt guidance for emphasis/space allocation.

---

## Component 4: Critic/Improve Pass

**New module:** `src/jobplanner/checker/critic.py`

Post-tailor LLM call that evaluates the generated resume against quality criteria, rewrites weak bullets, and flags thin source material for bank improvement.

### Critic Prompt

```
You are a senior resume reviewer and career coach with 15 years of experience
helping candidates land interviews at top companies.

You will review a tailored resume and improve it. You MUST preserve all source
citations (source_id, source_bullet_indices) — you are improving language and
framing, not changing what experiences are cited.

## Quality Criteria
1. IMPACT-FIRST: Does each bullet lead with the result/impact, not the task?
2. SPECIFICITY: Are there concrete numbers, tools, scale indicators?
3. ACTION VERBS: Strong verbs (Designed, Built, Optimized) not weak ones (Helped, Worked on)?
4. JD ALIGNMENT: Does the language mirror the JD's vocabulary and priorities?
5. STORY COHERENCE: Does the resume tell a unified story of fit for THIS role?
6. 6-SECOND TEST: Would the top 1/3 hook a hiring manager scanning quickly?
7. NO FLUFF: Zero filler phrases, buzzwords, or vague claims?

## Guidelines
{resume_rules_content}

## Exemplary Bullets for {role_type}
{exemplary_bullets}

## Structure Template for {role_type}
{structure_template}

## Instructions
- Rewrite bullets that score poorly on the criteria above
- Reorder bullets within each experience if a more impactful one is buried
- Adjust skill line labels and ordering to better match JD vocabulary
- Trim coursework to only genuinely relevant courses
- Do NOT change source citations — keep source_id and source_bullet_indices intact
- Do NOT add skills or experiences not in the original tailored resume
- Flag source bullets that are too thin to produce strong output (bank feedback)
- Output the complete revised TailoredResume + bank improvement suggestions
```

### Output Schema

```python
@dataclass
class BankSuggestion:
    source_id: str                # Which experience/project
    bullet_index: int             # Which bullet in the bank
    issue: str                    # "thin_description" | "missing_metrics" | "vague_impact" | "missing_tech_detail"
    suggestion: str               # Natural language suggestion for improvement
    priority: str                 # "high" | "medium" | "low"

@dataclass
class CriticResult:
    improved_resume: TailoredResume
    bank_suggestions: list[BankSuggestion]
    summary: str                  # Brief overview of changes made
```

### Pipeline Integration

- Runs after hallucination validation passes, before LaTeX rendering
- Skippable via `--skip-critic` CLI flag (same pattern as `--skip-proofread`)
- Improved resume goes through hallucination validation again before use
- If critic output fails validation, falls back to pre-critic version (safe degradation)
- Uses same model as tailor by default (the model set via `--model` flag or `JOBPLANNER_MODEL` env var)

### Bank Suggestions Surfacing

- `report.json` — new `bank_improvement_suggestions` field
- CLI output — printed after pipeline completes
- Web UI — new expandable section "Improve Your Experience Bank"

---

## Component 5: Enhanced Tailor Prompt

The existing tailor prompt (`src/jobplanner/tailor/prompts.py`) keeps all mechanical rules (citation, metrics preservation, page-filling, character limits) but gains enriched context.

### New Enrichment Module

**File:** `src/jobplanner/tailor/enrichment.py`

```python
@dataclass
class EnrichedContext:
    guidelines_excerpt: str       # Condensed sector-relevant rules (~500-800 tokens)
    exemplary_bullets: str        # 3-4 good + 1-2 anti-patterns (~300-500 tokens)
    structure_template: str       # Sector story arc + strategy (~200-300 tokens)
    market_boost_skills: list[str]  # Skills to consider mentioning (~50-100 tokens)

def build_enriched_context(
    role_type: str,
    bank: ExperienceBank,
    tracker_db: Path | None,
    parsed_jd: ParsedJD,
) -> EnrichedContext:
    """Load and assemble all enrichment data for a given role type."""
```

### Injection Points in Tailor Prompt

1. **Guidelines excerpt** → appended after "REWRITING GUIDELINES" section
2. **Exemplary bullets** → new section between "REWRITING GUIDELINES" and "COURSEWORK SELECTION"
3. **Structure template** → replaces/enriches the current "AUDIENCE-AWARE TAILORING" section
4. **Market-boosted skills** → new paragraph in "SKILLS SECTION RULES"

### Token Budget

| Component | Tokens | Notes |
|---|---|---|
| Guidelines excerpt | ~500-800 | Sector-relevant rules only |
| Exemplary bullets | ~300-500 | 3-4 good + 1-2 anti-patterns |
| Structure template | ~200-300 | One sector only |
| Market-boosted skills | ~50-100 | Single sentence |
| **Total new** | **~1,050-1,700** | ~25-35% prompt growth |

Manageable within modern model context windows. The tailor gets calibration (examples + strategy), the critic handles detailed evaluation.

---

## Component 6: JD Skill Tracker

**New module:** `src/jobplanner/market/tracker.py`
**Data store:** `data/market/skill_tracker.db` (SQLite, gitignored)

### Database Schema

```sql
CREATE TABLE jd_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    role_type TEXT NOT NULL,
    seniority TEXT,
    industry TEXT,
    date_processed TEXT NOT NULL  -- ISO 8601
);

CREATE TABLE jd_skills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    jd_id INTEGER NOT NULL REFERENCES jd_entries(id),
    skill_name TEXT NOT NULL,       -- Normalized skill name
    skill_type TEXT NOT NULL         -- 'required' | 'preferred' | 'keyword'
);

CREATE INDEX idx_skills_name ON jd_skills(skill_name);
CREATE INDEX idx_skills_jd ON jd_skills(jd_id);
CREATE INDEX idx_entries_role ON jd_entries(role_type);
```

### Accumulation Logic

Runs at end of pipeline (no LLM call):

```python
def accumulate_jd(db_path: Path, parsed_jd: ParsedJD) -> None:
    """Insert parsed JD data into the skill tracker."""
    # Insert jd_entry
    # Insert required_skills with skill_type='required'
    # Insert preferred_skills with skill_type='preferred'
    # Insert keywords with skill_type='keyword'
    # Skill names normalized using the JD parser's existing normalization
    #   (e.g., "python3" → "Python", "pytorch framework" → "PyTorch")
    # Deduplication: skip if same company+title+role_type already exists
```

### Query Functions

```python
def get_sector_report(db_path: Path, role_type: str) -> SectorReport
def get_cross_sector_report(db_path: Path) -> CrossSectorReport
def get_skill_gaps(db_path: Path, role_type: str, bank: ExperienceBank) -> list[SkillGap]
def get_market_boost_skills(db_path: Path, role_type: str, bank: ExperienceBank, parsed_jd: ParsedJD, threshold: float = 0.5) -> list[str]
```

---

## Component 7: Gap Analysis & Market Reports

**New module:** `src/jobplanner/market/report.py`

### CLI Commands

```bash
# Per-sector report with gap analysis
python -m jobplanner market report --sector mle

# Cross-sector analysis (skills valuable across all target sectors)
python -m jobplanner market report --cross-sector

# Project suggestions to fill skill gaps
python -m jobplanner market suggest-projects --sector mle
```

### Per-Sector Report Output

```
MLE Market Report (8 JDs analyzed)
─────────────────────────────────
Top Skills:               You Have:    Gap:
Python (100%)             ✓
PyTorch (87%)             ✓
RAG (62%)                 ✗            ← MISSING
Kubernetes (62%)          ✓
LLM Fine-tuning (50%)    ✗            ← MISSING
MLflow (37%)              ✓

Suggested Actions:
- Build a RAG project to demonstrate retrieval-augmented generation
- Add LLM fine-tuning experience (consider a LoRA/QLoRA project)
```

### Cross-Sector Report Output

```
Cross-Sector Skill Demand
─────────────────────────
Skill             DS(10)  MLE(8)  SWE(6)  Overall
Python            100%    100%    83%     95%     ✓ You have this
SQL               80%     62%     67%     71%     ✓ You have this
Docker            40%     75%     83%     63%     ✗ GAP — high leverage
Git/CI-CD         30%     62%    100%     58%     ✓ You have this
AWS               50%     50%     67%     54%     ✗ GAP — high leverage

High-Leverage Gaps (appear in 3+ sectors):
- Docker/containerization — 63% overall
- AWS/cloud platforms — 54% overall
```

### Project Suggestion Command

Uses an LLM call to generate 2-3 project ideas that fill the biggest skill gaps:

```bash
python -m jobplanner market suggest-projects --sector mle
```

Input to LLM: skill gaps + existing bank (to avoid redundancy) + sector context.
Output: concrete project ideas with description, tech stack, and which gaps they fill.

---

## Component 8: Market-Informed Skill Boosting

### Logic

When the tracker has ≥10 JDs for a sector, the enrichment stage queries for boost candidates:

```python
def get_market_boost_skills(db_path, role_type, bank, parsed_jd, threshold=0.5):
    """Skills that appear in ≥50% of sector JDs AND exist in the bank,
    but are NOT in this specific JD's required/preferred skills."""
    market_common = query_skills_above_threshold(db_path, role_type, threshold)
    bank_skills = bank.all_skill_names()
    jd_skills = set(parsed_jd.required_skills + parsed_jd.preferred_skills)
    return [s for s in market_common if s in bank_skills and s not in jd_skills]
```

### Injection

Added to tailor prompt as soft suggestion:

> "The following skills are highly valued in {role_type} roles based on market data. The candidate has these skills. Consider mentioning them naturally if relevant, even though this specific JD doesn't list them: [list]"

### Guardrails

- Only skills the candidate actually has (verified against bank)
- Only when tracker has ≥10 JDs for this sector
- Phrased as suggestion, not requirement — LLM uses judgment
- JD's actual requirements always take priority

---

## Report Enhancements

`report.json` gains new fields:

```json
{
  "...existing fields...",
  "bank_improvement_suggestions": [
    {
      "source_id": "acme_analytics_swe",
      "bullet_index": 2,
      "issue": "missing_metrics",
      "suggestion": "Add specific throughput or latency numbers for the caching layer",
      "priority": "high"
    }
  ],
  "enrichment_tokens": 1247,
  "market_boosted_skills": ["Docker", "AWS"],
  "critic_summary": "Strengthened 3 bullets with impact-first rewriting, reordered skills section to lead with JD keywords, trimmed coursework from 8 to 5 courses"
}
```

---

## Implementation Phases

### Phase 1: Knowledge Foundation
- Create `data/guidelines/resume_rules.md` (Claude seeds, user reviews)
- Create `data/guidelines/exemplary_bullets.yaml` (Claude seeds, user reviews)
- Create `data/guidelines/resume_structures.yaml` (Claude seeds, user reviews)
- No code changes — just data files

### Phase 2: Enhanced Tailor Prompt
- Implement `src/jobplanner/tailor/enrichment.py`
- Modify `src/jobplanner/tailor/prompts.py` to accept enriched context
- Modify `src/jobplanner/tailor/agent.py` to load and inject enrichment
- Modify `src/jobplanner/pipeline.py` to add "Enrich Context" stage

### Phase 3: Critic/Improve Pass
- Implement `src/jobplanner/checker/critic.py`
- Define `BankSuggestion` and `CriticResult` models
- Integrate into pipeline (after validation, before rendering)
- Add `--skip-critic` flag to CLI
- Add bank suggestions to `report.json`, CLI output, and web UI

### Phase 4: Market Intelligence
- Implement `src/jobplanner/market/tracker.py` (SQLite tracker)
- Implement `src/jobplanner/market/report.py` (CLI reports)
- Add accumulation step to pipeline
- Add `market` CLI subcommand group (`report`, `suggest-projects`)
- Implement market-informed skill boosting in enrichment module
- Add `--cross-sector` flag to market report

---

## Verification Plan

### Phase 1 Verification
- Review all 3 data files for completeness and accuracy
- Validate YAML files parse correctly
- Ensure guidelines cover all supported role types

### Phase 2 Verification
- Run pipeline with enrichment on a real JD
- Compare output quality before/after enrichment (same JD, same model)
- Check enrichment token count is within budget (~1,050-1,700)
- Verify existing tests still pass

### Phase 3 Verification
- Run pipeline with critic enabled on a real JD
- Verify critic preserves source citations (validation must pass)
- Verify `--skip-critic` flag works
- Verify bank suggestions appear in report.json and CLI output
- Test safe degradation: if critic output fails validation, pre-critic version is used

### Phase 4 Verification
- Process 3+ JDs and verify skill_tracker.db accumulates correctly
- Run `market report --sector <type>` and verify gap analysis against bank
- Run `market report --cross-sector` and verify aggregation
- Run `market suggest-projects` and verify LLM generates sensible suggestions
- Process 10+ JDs for one sector and verify market-boosted skills appear in enrichment

### End-to-End
- Run full pipeline on 3 JDs (one each: DS, SWE, MLE) with all features enabled
- Compare ATS scores and keyword coverage before/after
- Manually review resume quality against guidelines
- Verify report.json contains all new fields
