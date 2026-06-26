"""
Callbacks for the resume agent pipeline.
"""

import json
from pathlib import Path

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_response import LlmResponse


def log_model_usage_callback(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> LlmResponse | None:
    """Logs token usage for each agent step to help track costs."""
    agent_name = callback_context.agent_name
    usage = getattr(llm_response, "usage_metadata", None)

    if usage:
        # Use 0 (not "?") so logs can be parsed and summed programmatically.
        input_tokens  = getattr(usage, "prompt_token_count",     0)
        output_tokens = getattr(usage, "candidates_token_count", 0)
        print(f"[{agent_name}] tokens — input: {input_tokens}, output: {output_tokens}")
    else:
        print(f"[{agent_name}] completed (no usage metadata)")

    return None  # Don't modify the response


def save_pipeline_log_callback(
    callback_context: CallbackContext,
) -> None:
    """
    After the final_writer_agent completes, saves a JSON debug log of the full
    pipeline output (jd_requirements + final_resume).

    Wired as an after_agent_callback on final_writer_agent alongside
    save_pdf_after_final_writer; ADK chains multiple after_agent_callbacks in
    registration order, so PDF is saved first, then this log is written.
    """
    state           = callback_context.state
    final_resume    = state.get("final_resume")
    jd_requirements = state.get("jd_requirements")

    if not final_resume or not jd_requirements:
        print("[pipeline_log] Skipping — final_resume or jd_requirements missing in state.")
        return

    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    log = {
        "jd_requirements": (
            jd_requirements if isinstance(jd_requirements, dict) else str(jd_requirements)
        ),
        "final_resume": (
            final_resume if isinstance(final_resume, dict) else str(final_resume)
        ),
    }

    log_path = output_dir / "pipeline_log.json"
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2)

    print(f"[pipeline_log] Saved → {log_path}")