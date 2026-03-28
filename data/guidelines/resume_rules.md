# Resume Writing Guidelines

These rules are injected into the tailoring prompt and critic pass.
The universal sections apply to all role types. Only the matching
sector section is injected into the tailor prompt; the full document
is given to the critic.

---

## Bullet Writing

**The formula:** [Strong verb] + [what you built/did] + [scale/method] + [impact/result]

Rules:
- Lead with the **strongest action verb** that accurately describes the work.
  Verb hierarchy: Designed > Built > Implemented > Developed > Contributed > Helped
- **Impact-first** when you have a metric: lead with what changed, then how.
  Bad: "Used Redis caching to reduce database load"
  Good: "Reduced database load by 70% by introducing Redis caching for hot-path queries"
- **Quantify everything possible.** If the source has a number, use it.
  Numbers that impress: throughput (req/s, events/s), latency (ms), scale (users, rows, GB),
  improvement (%, 2x, 10x), time saved (hours/week), money ($), team size (N engineers).
- **One accomplishment per bullet.** Never cram two achievements into one line.
- **Never write "responsible for".** Write what you did, not your job description.
  Bad: "Responsible for maintaining data pipelines and fixing ETL bugs"
  Good: "Reduced ETL failure rate from 12% to 0.3% by adding idempotent retry logic"
- **No filler phrases.** Delete on sight:
  "Leveraged cutting-edge", "Spearheaded innovative", "Collaborated cross-functionally",
  "Utilized best practices", "Drove impact", "Synergized", "Results-driven"
- **Bullet length:** ~130–160 characters (1–1.5 printed lines). Dense single-liners beat
  sprawling paragraphs. If it wraps to 3 lines, split or cut.

Before/after examples:

| Bad | Good |
|-----|------|
| "Responsible for backend services" | "Redesigned auth service handling 50K req/s, reducing P99 latency from 400ms to 18ms" |
| "Used ML to improve recommendations" | "Lifted CTR 23% by training two-tower retrieval model on 500M interaction records" |
| "Helped with data pipeline work" | "Built real-time Kafka→ClickHouse pipeline processing 2M events/day for fraud detection" |

---

## 6-Second Scan Optimization

Recruiters spend ~6 seconds on a first pass. What they scan:
1. **Name / contact** — top line
2. **Skills section** — ctrl+F for required tech
3. **Job titles** — do they match?
4. **Top bullet of first experience** — sets the bar for the whole resume

Rules:
- Top 1/3 of page must contain your strongest selling points.
- Most relevant experience should come first within each section.
- Most impactful bullet must come first within each experience.
- Skills section: JD-matching skills must appear in the first positions of each line.
- Never bury your best bullet at position 3 if you have 3.
- Coursework should only include courses a hiring manager would recognize as relevant —
  cut anything generic (Intro to Programming, Writing, Statistics I if applying to SWE).

---

## Sector-Specific Rules

### Data Science / Statistics (`ds`, `biostats`)
- **Lead with methodology**, not tools. "Used Python" tells nothing; the method tells everything.
  Bad: "Used Python and scikit-learn to build a model"
  Good: "Fitted penalized Cox regression (LASSO, λ selected by 10-fold CV) predicting 90-day readmission"
- Show statistical rigor: mention study design, validation strategy, sample sizes, effect sizes.
- Quantify model performance with discipline-appropriate metrics (AUC, RMSE, calibration, p-values).
- For clinical/biostats work: mention IRB, regulatory context, and clinical impact when present.
- **Minimize** DevOps jargon — don't lead bullets with "Docker", "K8s", "CI/CD".
- Vocabulary that signals DS/stats competence: "cross-validated", "confounding", "power analysis",
  "Bayesian", "hierarchical model", "causal inference", "A/B test", "treatment effect".

### Software Engineering (`swe`)
- **Lead with scale and system design.** The hiring manager wants to know: how big? how complex?
  Bad: "Built a service that handles user requests"
  Good: "Designed event-driven microservice processing 500K req/s with <10ms P99 at 99.9% uptime"
- Emphasize: architecture decisions, system boundaries, trade-offs made, production reliability.
- Lead with tech stack when it's impressive or JD-specific.
- Show progression: individual contributor → system owner → cross-team impact.
- Strong SWE verbs: Designed, Architected, Built, Implemented, Optimized, Migrated, Scaled.

### ML Engineering (`mle`)
- Balance both DS and SWE concerns: model quality AND production readiness.
- Show the full lifecycle: data → training → evaluation → deployment → monitoring.
- Key MLE concerns: latency at inference time, model versioning, feature store, drift detection,
  A/B experimentation infrastructure, batch vs real-time serving.
- Vocabulary: "model serving", "feature store", "MLflow", "experiment tracking", "canary deployment",
  "shadow mode", "online learning", "model registry".

### Data Engineering (`de`)
- Emphasize: throughput, reliability, latency, and schema/data quality.
- Show: pipeline orchestration, fault tolerance, exactly-once semantics, backfill strategies.
- Key DE concerns: SLA adherence, data freshness, backpressure handling.

### Finance / Analyst (`finance`, `analyst`)
- **Lead with the business problem and business impact**, not the technical solution.
  Bad: "Built a Python model using XGBoost"
  Good: "Identified $4.2M in underpriced credit risk by building XGBoost PD model on 3-year loan history"
- Quantify in business terms: revenue, cost, margin, risk ($), time-to-decision.
- Show domain knowledge: P&L, Greeks, alpha, factor exposure, regulatory capital.
- Tech stack goes at the end of bullets, not the beginning.

---

## ATS & Human Reader

**ATS (automated screening):**
- Use the **exact phrasing from the JD** for required skills. "Machine Learning" and "ML" are
  different strings to a keyword scanner. If the JD says "Machine Learning", use that.
- Standard section headers only — "EXPERIENCE", "EDUCATION", "SKILLS". Never "Work History",
  "Background", "Technical Proficiencies" (ATS parsers may miss them).
- Avoid tables, columns, and text boxes — many ATS systems extract text linearly and scramble them.
- Special characters in skill names are fine (C++, C#, .NET).

**Human HR first-pass (AI-assisted in 2025–2026):**
- AI screening tools now summarize and score resumes. They reward: keyword density, coherent
  narrative, quantified impact. Vague bullets score lower than specific ones even if correct.
- The skills section is machine-read first; put JD keywords there explicitly.
- Consistent formatting matters — ATS and humans both notice mixed date formats or inconsistent
  capitalization.

---

## Common Mistakes

1. **Duty list instead of accomplishment list.** Describe outcomes, not responsibilities.
2. **Skill dump without context.** Listing 30 skills signals you know all of them superficially.
   The skills section should reflect what the JD values, not everything you've ever touched.
3. **Inconsistent tense.** Current role: present tense. All previous: past tense. No mixing.
4. **Inconsistent date format.** Pick one: "Jan 2024 – Present" or "January 2024 – Present".
5. **Passive voice.** "Was responsible for", "work was done by". Active verbs only.
6. **Generic project names.** "Personal Project" tells nothing. Name it and add a URL.
7. **Coursework that doesn't signal anything.** Only list courses a hiring manager in this role
   would recognize as directly relevant. 4–6 courses max, never more.
8. **Burying the best bullet.** Bullet order matters. Lead with your most impressive work.
