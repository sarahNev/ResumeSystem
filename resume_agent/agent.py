import os

from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_response import LlmResponse

from .callbacks import log_model_usage_callback, save_pipeline_log_callback
from .prompts import (
    CRITIC_INSTRUCTION,
    FINAL_WRITER_INSTRUCTION,
    JD_ANALYZER_INSTRUCTION,
    RETRIEVER_INSTRUCTION,
    RESUME_WRITER_INSTRUCTION,
)
from .schemas import JDRequirements, ResumePipelineOutput, SelectedContent
from .tools import load_all_excel_data, save_resume_as_pdf

# ---------------------------------------------------------------------------
# Model config
# MODEL     — fast/cheap model for simple steps (Flash)
# MODEL_PRO — best model for reasoning-heavy steps (Pro)
# ---------------------------------------------------------------------------

MODEL     = os.getenv("RESUME_MODEL",       os.getenv("MODEL",      "gemini-2.5-flash"))
MODEL_PRO = os.getenv("RESUME_DRAFT_MODEL", os.getenv("MODEL_PRO",  "gemini-2.5-pro"))

# ---------------------------------------------------------------------------
# Session state injection helpers
# ADK does NOT automatically inject session state into the model context.
# These callbacks prepend state values into the first user message before
# the LLM call so the model can actually read them.
#
# make_inject_callback accepts a `required` flag. When True, a missing or
# empty state key raises RuntimeError so the pipeline fails loudly rather
# than silently passing an empty context to the model and hallucinating.
# ---------------------------------------------------------------------------

def make_inject_callback(state_key: str, label: str, *, required: bool = True):
    """
    Factory — returns a before_model_callback that injects a session state
    value into the top of the model's first user message.

    Args:
        state_key: Key to look up in callback_context.state.
        label:     Human-readable section header wrapped around the injected text.
        required:  If True (default), raise RuntimeError when the key is missing
                   or empty. Set to False only for truly optional context.
    """
    def _callback(callback_context: CallbackContext, llm_request) -> None:
        state = callback_context.state
        data  = state.get(state_key)

        if not data:
            msg = f"[inject:{state_key}] State key '{state_key}' is empty or missing."
            if required:
                raise RuntimeError(msg)
            else:
                print(f"{msg} Skipping injection (key is optional).")
                return

        data_str = data if isinstance(data, str) else str(data)
        print(f"[inject:{state_key}] Injecting {len(data_str)} chars into prompt")

        if llm_request.contents:
            first = llm_request.contents[0]
            if hasattr(first, "parts") and first.parts:
                original            = first.parts[0].text or ""
                first.parts[0].text = (
                    f"=== {label} ===\n{data_str}\n=== END {label} ===\n\n"
                    + original
                )
    return _callback


# One inject callback per piece of context downstream agents need.
# All are required=True (default) — a missing key always means a pipeline bug.
inject_excel    = make_inject_callback("raw_excel_data",   "CANDIDATE EXCEL DATA")
inject_selected = make_inject_callback("selected_content", "SELECTED CONTENT")
inject_draft    = make_inject_callback("draft_resume",     "DRAFT RESUME")
inject_critique = make_inject_callback("critique",         "CRITIQUE")
inject_jd       = make_inject_callback("jd_requirements",  "JD REQUIREMENTS")


def inject_retriever_context(callback_context: CallbackContext, llm_request) -> None:
    """
    Retriever needs raw Excel AND jd_requirements to do selection.
    Without the JD it has nothing to compare against and will hallucinate.
    """
    inject_jd(callback_context, llm_request)
    inject_excel(callback_context, llm_request)


def inject_all_writer_context(callback_context: CallbackContext, llm_request) -> None:
    """
    Writer needs jd_requirements + selected_content + raw Excel for personal info.
    selected_content has skills/projects but personal_info lives only in raw Excel.
    """
    inject_excel(callback_context, llm_request)
    inject_jd(callback_context, llm_request)
    inject_selected(callback_context, llm_request)


def inject_critic_context(callback_context: CallbackContext, llm_request) -> None:
    """
    Critic needs jd_requirements + selected_content + draft_resume.
    No raw Excel needed — personal info is already in the draft.
    """
    inject_jd(callback_context, llm_request)
    inject_selected(callback_context, llm_request)
    inject_draft(callback_context, llm_request)


def inject_all_final_writer_context(callback_context: CallbackContext, llm_request) -> None:
    """
    Final writer needs jd_requirements + selected_content + draft_resume + critique.
    No raw Excel — personal info already in draft, don't modify it anyway.
    """
    inject_jd(callback_context, llm_request)
    inject_selected(callback_context, llm_request)
    inject_draft(callback_context, llm_request)
    inject_critique(callback_context, llm_request)


# ---------------------------------------------------------------------------
# Excel loader callback
# Runs before the retriever agent — loads the workbook directly into session
# state via plain Python. No LLM call, no tokens, guaranteed accuracy.
# ---------------------------------------------------------------------------

def load_excel_before_retriever(callback_context: CallbackContext) -> None:
    """Load Excel data into session state before the retriever LLM call."""
    state = callback_context.state

    # Skip if already loaded (e.g. retry scenario).
    if state.get("raw_excel_data"):
        print("[load_excel] Already loaded, skipping.")
        return

    try:
        data = load_all_excel_data()
        state["raw_excel_data"] = data
        print(f"[load_excel] Loaded {len(data)} chars from workbook")
    except Exception as e:
        # Re-raise with a clear message so the pipeline fails loudly.
        raise RuntimeError(
            f"[load_excel] Failed to load Excel workbook — pipeline cannot continue. "
            f"Original error: {e}"
        ) from e


# ---------------------------------------------------------------------------
# PDF saver callback
# Runs after the final writer agent — saves PDF directly via plain Python.
# No LLM call, no tokens, no risk of malformed function call errors.
#
# Accepts both dict (ADK serialises output_schema results as dicts) and
# ResumePipelineOutput objects. Extracts a clean ResumeBundle via
# to_resume_bundle() so skill_gaps are never written to the PDF.
# ---------------------------------------------------------------------------

def save_pdf_after_final_writer(callback_context: CallbackContext) -> None:
    """Save the final resume as PDF after final_writer_agent completes."""
    state           = callback_context.state
    final_resume    = state.get("final_resume")
    jd_requirements = state.get("jd_requirements")

    if not final_resume:
        print("[save_pdf] ERROR: final_resume not found in state")
        return
    if not jd_requirements:
        print("[save_pdf] ERROR: jd_requirements not found in state")
        return

    # Resolve job title robustly regardless of whether state holds a dict or object.
    if isinstance(jd_requirements, dict):
        job_title = jd_requirements.get("role", "role")
    elif hasattr(jd_requirements, "role"):
        job_title = jd_requirements.role
    else:
        job_title = "role"
    job_title = job_title.replace(",", "").strip()

    # Strip pipeline-internal fields (skill_gaps) before handing off to the PDF tool.
    if isinstance(final_resume, ResumePipelineOutput):
        resume_for_pdf = final_resume.to_resume_bundle()
    elif isinstance(final_resume, dict):
        # ADK may serialise the output_schema result as a plain dict.
        # Pop skill_gaps so it never reaches the PDF renderer.
        resume_for_pdf = {k: v for k, v in final_resume.items() if k != "skill_gaps"}
    else:
        resume_for_pdf = final_resume

    try:
        path = save_resume_as_pdf(resume_bundle=resume_for_pdf, job_title=job_title)
        state["pdf_path"] = path
        print(f"[save_pdf] Saved → {path}")
    except Exception as e:
        print(f"[save_pdf] ERROR: {e}")
        raise


# ---------------------------------------------------------------------------
# Step 1 — JD Analyzer
# Parses the job description into structured requirements.
# Fast, simple extraction — Flash is fine.
# ---------------------------------------------------------------------------

jd_analyzer_agent = LlmAgent(
    name="jd_analyzer_agent",
    model=MODEL,
    description="Parses the job description and extracts structured requirements.",
    instruction=JD_ANALYZER_INSTRUCTION,
    output_schema=JDRequirements,
    output_key="jd_requirements",
    after_model_callback=log_model_usage_callback,
)

# ---------------------------------------------------------------------------
# Step 2 — Retriever
# Excel is loaded via before_agent_callback (no LLM cost).
# Pro model then reasons over both Excel data AND jd_requirements to select
# the best content. FIX: was inject_excel (missing JD context) — now uses
# inject_retriever_context so the model can actually score against the JD.
# ---------------------------------------------------------------------------

retriever_agent = LlmAgent(
    name="retriever_agent",
    model=MODEL_PRO,
    description="Selects the most relevant skills, projects, and experience for the JD.",
    instruction=RETRIEVER_INSTRUCTION,
    output_schema=SelectedContent,
    output_key="selected_content",
    before_agent_callback=load_excel_before_retriever,   # loads Excel (no LLM)
    before_model_callback=inject_retriever_context,      # injects Excel + JD into prompt
    after_model_callback=log_model_usage_callback,
)

# ---------------------------------------------------------------------------
# Step 3 — Resume Writer
# Drafts the resume from selected content + JD requirements.
# Flash is sufficient — Pro already did the hard selection reasoning.
# ---------------------------------------------------------------------------

resume_writer_agent = LlmAgent(
    name="resume_writer_agent",
    model=MODEL,
    description="Writes the first draft of the tailored resume.",
    instruction=RESUME_WRITER_INSTRUCTION,
    output_schema=ResumePipelineOutput,
    output_key="draft_resume",
    before_model_callback=inject_all_writer_context,
    after_model_callback=log_model_usage_callback,
)

# ---------------------------------------------------------------------------
# Step 4 — Critic
# Reviews the draft against the JD for ATS coverage and bullet quality.
# ---------------------------------------------------------------------------

critic_agent = LlmAgent(
    name="critic_agent",
    model=MODEL,
    description="Critiques the resume draft for ATS coverage and quality.",
    instruction=CRITIC_INSTRUCTION,
    output_key="critique",
    before_model_callback=inject_critic_context,
    after_model_callback=log_model_usage_callback,
)

# ---------------------------------------------------------------------------
# Step 5 — Final Writer
# Revises the draft using critique. Saves PDF + debug log via after_agent_callbacks.
# Pro model — this is the last high-stakes reasoning step.
# ---------------------------------------------------------------------------

final_writer_agent = LlmAgent(
    name="final_writer_agent",
    model=MODEL_PRO,
    description="Revises the resume using critique feedback into a final polished resume.",
    instruction=FINAL_WRITER_INSTRUCTION,
    output_schema=ResumePipelineOutput,
    output_key="final_resume",
    before_model_callback=inject_all_final_writer_context,
    after_model_callback=log_model_usage_callback,
    # after_agent_callback chains: PDF saved first, then debug log written.
    after_agent_callback=[save_pdf_after_final_writer, save_pipeline_log_callback],
)

# ---------------------------------------------------------------------------
# Root agent — sequential pipeline, no routing layer
# ---------------------------------------------------------------------------

root_agent = SequentialAgent(
    name="root_agent",
    description="Resume customization pipeline. Paste a job description to begin.",
    sub_agents=[
        jd_analyzer_agent,
        retriever_agent,
        resume_writer_agent,
        critic_agent,
        final_writer_agent,
    ],
)