# main.py
# Entry point for the AI Sales Intelligence Agent.
#
# ADK ARCHITECTURE NOTES
# -----------------------------------------------------------------------
# - This module owns the single process-wide `Runner` + `InMemorySessionService`
#   + session id that the Gradio UI (and any other caller) should share. ADK's
#   InMemorySessionService keeps all session state in a plain Python dict in
#   the process — reusing the SAME session across calls is what gives the
#   orchestrator's `after_agent_callback` memory of previously researched
#   companies (`state["user:researched_companies"]`) for the life of the
#   process. A fresh session id would reset that memory.
# - `run_pipeline(company_name)` is the synchronous entry point requested by
#   the project spec — it wraps the async ADK Runner with `asyncio.run`.
# - `stream_pipeline(company_name)` is the async-generator counterpart used
#   by ui/app.py to show agent reasoning steps (tool calls / tool responses)
#   in real time as ADK events arrive, rather than waiting for the whole
#   pipeline to finish.
# - Security: `_validate_company_name` is the single input-sanitization
#   boundary for every entry point in this module (CLI, UI, and — via the
#   agents' own backward-compatible wrappers — the MCP server).

import os
import json
import asyncio
from dotenv import load_dotenv

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from agents.orchestrator import create_orchestrator_agent, APP_NAME

load_dotenv(override=True)

_DEFAULT_USER_ID = "default_user"

# Process-wide singletons — lazily created on first use so importing this
# module never triggers agent construction or network calls by itself.
_session_service = InMemorySessionService()
_runner: Runner | None = None
_root_agent_name: str | None = None
_session_id: str | None = None


def _validate_company_name(company_name: str) -> str:
    """Input-sanitization boundary shared by every entry point below.

    Args:
        company_name: Raw company name from a user or caller.

    Returns:
        str: Trimmed, length-bounded company name.

    Raises:
        ValueError: If the input is empty, not a string, or out of bounds.
    """
    if not company_name or not isinstance(company_name, str):
        raise ValueError("company_name must be a non-empty string")

    cleaned = company_name.strip()
    if len(cleaned) < 2:
        raise ValueError("company_name is too short")
    if len(cleaned) > 100:
        cleaned = cleaned[:100]

    return cleaned


def _get_runner() -> Runner:
    """Lazily builds the single shared Runner for this process."""
    global _runner, _root_agent_name
    if _runner is None:
        root_agent = create_orchestrator_agent()
        _root_agent_name = root_agent.name
        _runner = Runner(agent=root_agent, app_name=APP_NAME, session_service=_session_service)
    return _runner


async def _ensure_session() -> str:
    """Lazily creates the single shared session for this process, so agent
    memory (researched companies) persists across multiple run_pipeline calls."""
    global _session_id
    if _session_id is None:
        session = await _session_service.create_session(
            app_name=APP_NAME, user_id=_DEFAULT_USER_ID
        )
        _session_id = session.id
    return _session_id


async def _read_result(company_name: str, final_text: str, errors: list) -> dict:
    session = await _session_service.get_session(
        app_name=APP_NAME, user_id=_DEFAULT_USER_ID, session_id=_session_id
    )
    crm_result = session.state.get("crm_log_data") or {}

    return {
        "company": company_name,
        "research": session.state.get("research_data"),
        "lead_score": session.state.get("lead_score_data"),
        "email_draft": session.state.get("email_draft_data"),
        "crm_logged": bool(crm_result.get("logged")),
        "summary": final_text,
        "errors": errors,
        "researched_companies": session.state.get("user:researched_companies", []),
    }


async def run_pipeline_async(company_name: str) -> dict:
    """Runs the full ADK multi-agent pipeline for one company.

    Args:
        company_name: Name of the company to research end-to-end.

    Returns:
        dict: {company, research, lead_score, email_draft, crm_logged,
               summary, errors, researched_companies}
    """
    company_name = _validate_company_name(company_name)
    runner = _get_runner()
    session_id = await _ensure_session()

    final_text = ""
    errors = []
    async for event in runner.run_async(
        user_id=_DEFAULT_USER_ID,
        session_id=session_id,
        new_message=types.Content(role="user", parts=[types.Part.from_text(text=company_name)]),
    ):
        if event.error_message:
            errors.append(event.error_message)
        if event.is_final_response() and event.content and event.content.parts:
            text = "".join(
                p.text or "" for p in event.content.parts if getattr(p, "text", None)
            )
            if text:
                final_text = text

    return await _read_result(company_name, final_text, errors)


def run_pipeline(company_name: str) -> dict:
    """Synchronous entry point — wraps the async ADK pipeline with asyncio.run.

    Args:
        company_name: Name of the company to research end-to-end.

    Returns:
        dict: Structured pipeline result (see run_pipeline_async).
    """
    return asyncio.run(run_pipeline_async(company_name))


async def stream_pipeline(company_name: str):
    """Async generator used by the Gradio UI to stream agent reasoning steps
    in real time.

    Yields:
        dict: {"type": "step", "text": str} for each tool call / tool
              response / error observed on the orchestrator's event stream,
              followed by exactly one {"type": "result", "data": dict} with
              the final structured pipeline result.
    """
    company_name = _validate_company_name(company_name)
    runner = _get_runner()
    session_id = await _ensure_session()

    final_text = ""
    errors = []
    async for event in runner.run_async(
        user_id=_DEFAULT_USER_ID,
        session_id=session_id,
        new_message=types.Content(role="user", parts=[types.Part.from_text(text=company_name)]),
    ):
        for call in event.get_function_calls() or []:
            yield {"type": "step", "text": f"🔧 Calling `{call.name}`..."}

        for response in event.get_function_responses() or []:
            yield {"type": "step", "text": f"✅ `{response.name}` responded"}

        if event.error_message:
            errors.append(event.error_message)
            yield {"type": "step", "text": f"⚠️ Error: {event.error_message}"}

        if (
            event.is_final_response()
            and event.author == _root_agent_name
            and event.content
            and event.content.parts
        ):
            text = "".join(
                p.text or "" for p in event.content.parts if getattr(p, "text", None)
            )
            if text:
                final_text = text
                yield {"type": "step", "text": f"💬 {event.author}: {text}"}

    result = await _read_result(company_name, final_text, errors)
    yield {"type": "result", "data": result}


if __name__ == "__main__":
    result = run_pipeline("Stripe")
    print(json.dumps(result, indent=2, default=str))
