from pydantic import BaseModel, Field
from typing import Optional


class JDRequirements(BaseModel):
    role: str = Field(description="Job title / role name")
    company: Optional[str] = Field(default=None, description="Company name if mentioned")
    must_have_skills: list[str] = Field(description="Non-negotiable skills from the JD")
    nice_to_have_skills: list[str] = Field(description="Preferred but not required skills")
    relevant_keywords: list[str] = Field(description="ATS keywords to include in the resume")
    relevant_domains: list[str] = Field(description="Domain areas the job focuses on")


class CourseEntry(BaseModel):
    code: str
    name: str
    relevance_reason: str


# ---------------------------------------------------------------------------
# RetrievedProject — used by the retriever agent (SelectedContent).
# Carries relevance metadata that informs project selection.
# ---------------------------------------------------------------------------

class RetrievedProject(BaseModel):
    title: str
    description: str
    skills: list[str]
    relevance_reason: str


class SelectedContent(BaseModel):
    matched_skills: list[str] = Field(
        description="Flat list of candidate skills that match the JD — no categories"
    )
    all_skills: list[str] = Field(
        description="Full flat list of all technical skills from the Excel sheet"
    )
    unmatched_required_skills: list[str] = Field(
        description="JD must-haves not found in candidate skills"
    )
    relevant_projects: list[RetrievedProject] = Field(
        description="Top 4 projects scored by JD relevance, most relevant first"
    )
    selection_rationale: str = Field(
        description="Brief explanation of scoring and selection decisions"
    )


# ---------------------------------------------------------------------------
# Resume structure — mirrors the candidate's actual resume format.
# ---------------------------------------------------------------------------

class PersonalInfo(BaseModel):
    name: str
    email: str
    phone: str
    location: str
    linkedin: Optional[str] = None


class EducationEntry(BaseModel):
    school: str = Field(description="e.g. Colorado School of Mines, Golden, CO")
    degree: str = Field(description="e.g. Masters of Engineering in Data Science")
    gpa: Optional[str] = None
    date: Optional[str] = None  # e.g. "May 2026"


class ExperienceEntry(BaseModel):
    role: str = Field(description="Job title")
    company: str = Field(description="Company name and location")
    date_range: str = Field(description="e.g. May 2024 – June 2024")
    bullets: list[str]


# ---------------------------------------------------------------------------
# ResumeProject — used inside ResumeBundle for the rendered resume.
# No relevance metadata; only what appears on the printed page.
# ---------------------------------------------------------------------------

class ResumeProject(BaseModel):
    title: str
    bullets: list[str]


class SkillCategory(BaseModel):
    category: str  # e.g. "Data Science", "Programming Languages"
    skills: str    # comma-separated skills in that category


# ---------------------------------------------------------------------------
# ResumeBundle — clean representation of what goes on the printed resume.
# No pipeline-internal fields here; those live in ResumePipelineOutput below.
# save_resume_as_pdf accepts a ResumeBundle and will never leak internal data.
# ---------------------------------------------------------------------------

class ResumeBundle(BaseModel):
    personal_info: PersonalInfo
    education: list[EducationEntry]
    work_experience: list[ExperienceEntry] = Field(
        description="Paid work experience entries, most recent first"
    )
    projects: list[ResumeProject] = Field(
        description="Project experience entries, most relevant first, max 4"
    )
    technical_skills: list[SkillCategory] = Field(
        description="Skills grouped by category, max 4 categories, max 6 skills each"
    )


# ---------------------------------------------------------------------------
# ResumePipelineOutput — wraps ResumeBundle with pipeline-internal metadata.
# Used as the output_schema for writer agents so skill_gaps are captured.
# The PDF saver receives a ResumeBundle (via .model_dump exclusion) so that
# skill_gaps never appear in the output file.
# ---------------------------------------------------------------------------

class ResumePipelineOutput(ResumeBundle):
    skill_gaps: list[str] = Field(
        description=(
            "Pipeline-internal: JD must-haves absent from the candidate's data. "
            "Excluded from PDF output — never rendered on the resume."
        )
    )

    def to_resume_bundle(self) -> ResumeBundle:
        """Return a pure ResumeBundle, dropping all pipeline-internal fields."""
        return ResumeBundle(
            personal_info=self.personal_info,
            education=self.education,
            work_experience=self.work_experience,
            projects=self.projects,
            technical_skills=self.technical_skills,
        )