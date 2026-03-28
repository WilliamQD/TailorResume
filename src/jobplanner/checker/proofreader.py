"""Proofread extracted resume text using an LLM."""

from __future__ import annotations

from dataclasses import dataclass, field

from jobplanner.llm.base import LLMClient

PROOFREAD_SYSTEM = """\
You are a resume proofreader. Review the extracted text from a PDF resume
and check for:

1. Illegible or garbled characters (encoding artifacts, broken ligatures)
2. Grammar and spelling errors
3. Inconsistent formatting (date formats, bullet style, capitalization)
4. Overly long bullets (should be 1-2 lines)
5. Passive voice overuse
6. Vague statements that could be more specific

Return your findings as a numbered list. If the resume looks clean, say
"No issues found." Be concise — one line per issue.
"""


@dataclass
class ProofreadResult:
    issues: list[str] = field(default_factory=list)
    raw_response: str = ""

    @property
    def clean(self) -> bool:
        return len(self.issues) == 0 or (
            len(self.issues) == 1 and "no issues" in self.issues[0].lower()
        )


def proofread(client: LLMClient, extracted_text: str) -> ProofreadResult:
    """Proofread the extracted resume text."""
    response = client.complete_text(
        system=PROOFREAD_SYSTEM,
        user=f"Proofread this resume text extracted from a PDF:\n\n{extracted_text}",
    )

    lines = [line.strip() for line in response.strip().split("\n") if line.strip()]
    return ProofreadResult(issues=lines, raw_response=response)
