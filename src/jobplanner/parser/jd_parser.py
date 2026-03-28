"""Parse a raw job description into a structured ParsedJD."""

from __future__ import annotations

from jobplanner.bank.schema import ParsedJD
from jobplanner.llm.base import LLMClient

SYSTEM_PROMPT = """\
You are a job description parser. Extract structured information from the
provided job posting.

Classification rules for role_type:
- "swe" — software engineering, backend, frontend, full-stack
- "ds" — data science, applied science, analytics with modeling
- "mle" — machine learning engineer, ML infrastructure
- "de" — data engineering, ETL, pipelines, data platform
- "biostats" — biostatistics, epidemiology, clinical trials
- "analyst" — business/data analyst, BI, reporting
- "research" — research scientist, academic research positions
- "finance" — quantitative analyst, fintech, banking tech roles
- "other" — if none of the above fit

Seniority rules:
- "intern" — internship, co-op
- "entry" — 0-2 years, new grad, junior, associate
- "mid" — 3-5 years, no "senior" in title
- "senior" — senior, staff, lead, principal, 5+ years

For skills: normalize names to common forms (e.g., "Python" not "python3",
"PyTorch" not "pytorch framework"). Include both explicit requirements and
skills clearly implied by the responsibilities.

For keywords: extract terms an ATS would likely scan for — job-specific
jargon, tool names, certifications, domain terms.

Return ALL fields; leave empty strings or empty lists where information
is not available rather than guessing.
"""


def parse_jd(client: LLMClient, raw_text: str) -> ParsedJD:
    """Parse a raw job description into structured form."""
    result = client.complete(
        system=SYSTEM_PROMPT,
        user=f"Parse this job description:\n\n{raw_text}",
        response_model=ParsedJD,
    )
    result.raw_text = raw_text
    return result
