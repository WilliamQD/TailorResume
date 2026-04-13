"""Pydantic models for the experience bank (data/experience.yaml)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Leaf models
# ---------------------------------------------------------------------------

class Bullet(BaseModel):
    """A factual description of work done, used as source material for synthesis."""

    description: str = Field(..., description="Factual account of what was done, how, and why")
    tech_stack: list[str] = Field(default_factory=list, description="Specific technologies used")
    skills: list[str] = Field(default_factory=list, description="Broader skills demonstrated")
    metrics: str = Field("", description="Quantifiable results (preserved verbatim)")
    context: str = Field("", description="Brief context for why this matters")


class InferredSkill(BaseModel):
    """A skill inferred from coursework or closely related experience."""

    name: str = Field(..., description="Skill name as it would appear on a resume")
    basis: str = Field(..., description="Coursework or experience that supports this inference")
    confidence: Literal["high", "moderate", "low"] = Field(
        "moderate", description="high = project work, moderate = coursework, low = tangential"
    )


class Education(BaseModel):
    institution: str
    school: str = ""
    degree: str
    location: str = ""
    dates: str
    gpa: str = ""
    coursework: list[str] = Field(default_factory=list)
    honors: list[str] = Field(default_factory=list)


class Experience(BaseModel):
    id: str = Field(..., description="Stable identifier for citation tracking")
    organization: str
    role: str
    location: str = ""
    dates: str
    tags: list[str] = Field(default_factory=list, description="Coarse categories for filtering")
    bullets: list[Bullet] = Field(default_factory=list)


class Project(BaseModel):
    id: str = Field(..., description="Stable identifier for citation tracking")
    name: str
    dates: str = ""
    url: str = ""
    tags: list[str] = Field(default_factory=list)
    anchor: bool = Field(False, description="Always include in tailored resume regardless of tag overlap")
    bullets: list[Bullet] = Field(default_factory=list)


class Skills(BaseModel):
    languages: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)


CandidateLevel = Literal["new_grad", "entry_level", "mid_level", "senior_ic"]


class Meta(BaseModel):
    name: str
    email: str = ""
    phone: str = ""
    linkedin: str = ""
    github: str = ""
    location: str = ""
    website: str = ""
    candidate_level: CandidateLevel = Field(
        default="new_grad",
        description="Drives section order on the rendered resume",
    )


# ---------------------------------------------------------------------------
# Root model
# ---------------------------------------------------------------------------

class ExperienceBank(BaseModel):
    """Root schema for data/experience.yaml -- the single source of truth."""

    meta: Meta
    education: list[Education] = Field(default_factory=list)
    experience: list[Experience] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    skills: Skills = Field(default_factory=Skills)
    inferred_skills: list[InferredSkill] = Field(default_factory=list)

    def get_experience(self, id: str) -> Experience | None:
        return next((e for e in self.experience if e.id == id), None)

    def get_project(self, id: str) -> Project | None:
        return next((p for p in self.projects if p.id == id), None)

    def all_skill_names(self) -> set[str]:
        """Return every skill mentioned anywhere in the bank (lowercased)."""
        names: set[str] = set()
        for s in self.skills.languages + self.skills.frameworks + self.skills.tools:
            names.add(s.lower())
        for entry in self.experience + self.projects:  # type: ignore[operator]
            for b in entry.bullets:
                names.update(s.lower() for s in b.skills)
                names.update(s.lower() for s in b.tech_stack)
        for inf in self.inferred_skills:
            names.add(inf.name.lower())
        return names


# ---------------------------------------------------------------------------
# Models for the AI tailoring output
# ---------------------------------------------------------------------------

RoleType = Literal[
    "swe", "ds", "mle", "de", "biostats", "analyst", "research", "finance", "other"
]


class ParsedJD(BaseModel):
    """Structured representation of a parsed job description."""

    title: str = ""
    company: str = ""
    role_type: RoleType = "other"
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    key_responsibilities: list[str] = Field(default_factory=list)
    qualifications: list[str] = Field(default_factory=list)
    industry: str = ""
    seniority: Literal["intern", "entry", "mid", "senior"] = "entry"
    raw_text: str = ""


class TailoredBullet(BaseModel):
    source_bullet_indices: list[int] = Field(
        ..., description="Indices of source bullets used to synthesize this output bullet"
    )
    text: str = Field(..., description="Synthesized bullet text for the resume")


class SelectedExperience(BaseModel):
    source_id: str = Field(..., description="Must match an id in experience bank")
    bullets: list[TailoredBullet] = Field(default_factory=list)


class SelectedProject(BaseModel):
    source_id: str = Field(..., description="Must match an id in experience bank")
    bullets: list[TailoredBullet] = Field(default_factory=list)


class SkillsSection(BaseModel):
    """Skills to display on the tailored resume."""
    line1_label: str = "Languages/Systems"
    line1: list[str] = Field(default_factory=list)
    line2_label: str = "Frameworks & Tools"
    line2: list[str] = Field(default_factory=list)
    line3_label: str = "ML/LLM & Data"
    line3: list[str] = Field(default_factory=list)


class SelectedCoursework(BaseModel):
    """Coursework to display per education entry."""
    institution: str = Field(..., description="Must match an institution in the bank")
    courses: list[str] = Field(default_factory=list, description="Selected courses (max 4 per school)")


class TailoredResume(BaseModel):
    """Output of the resume tailoring agent."""

    selected_experiences: list[SelectedExperience] = Field(default_factory=list)
    selected_projects: list[SelectedProject] = Field(default_factory=list)
    skills: SkillsSection = Field(default_factory=SkillsSection)
    selected_coursework: list[SelectedCoursework] = Field(
        default_factory=list,
        description="Coursework per education entry (max 4 per school, 8 total, no cross-school topic overlap)",
    )
