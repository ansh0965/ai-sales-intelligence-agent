# orchestrator.py
# Root Orchestrator Agent — a real Google ADK LlmAgent.
#
# ADK ARCHITECTURE NOTES
# -----------------------------------------------------------------------
# - This is the ROOT agent of the multi-agent system. It is a genuine
#   LlmAgent — the LLM itself decides which tool to call and when, guided
#   by ORCHESTRATOR_INSTRUCTION, rather than a Python function calling
#   sub-steps in a hardcoded sequence.
# - Sub-agents are wrapped in `google.adk.tools.agent_tool.AgentTool`. This
#   is the "agent-as-a-tool" pattern: the orchestrator STAYS in control of
#   the conversation and explicitly decides to call each specialist agent,
#   as opposed to `sub_agents=[...]` delegation, where control transfers
#   away permanently. AgentTool is what the project spec calls for
#   ("uses AgentTool to delegate to sub-agents").
# - STATE SHARING (the key mechanic that makes this pipeline work without
#   manually re-typing giant JSON blobs into every tool call): when the
#   orchestrator calls an AgentTool,
#     1. ADK copies the orchestrator's CURRENT session.state into a fresh,
#        ephemeral session for the sub-agent.
#     2. The sub-agent runs (with its own tools, its own reasoning loop).
#     3. Its `output_key` write (e.g. "research_data") becomes a
#        `state_delta`, which ADK copies back into the orchestrator's
#        session automatically.
#   So by the time the orchestrator calls `lead_scorer_agent`,
#   `session.state["research_data"]` (written by `research_agent`) is
#   already there for `lead_scorer_agent`'s instruction to read via its own
#   `{research_data}` placeholder — no orchestrator-side plumbing required.
# - `after_agent_callback=_remember_company` implements simple session
#   memory: every company processed is appended to a user-scoped state list
#   (`state["user:researched_companies"]`), fulfilling the requirement that
#   the agent remembers previously researched companies within a session.

import os
import asyncio
from dotenv import load_dotenv

from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import AgentTool
from google.genai import types

from agents.research_agent import create_research_agent
from agents.lead_scorer import create_lead_scorer_agent
from agents.email_drafter import create_email_drafter_agent
from agents.crm_logger import create_crm_logger_agent
from agents.rate_limiter import throttle_model_call

load_dotenv(override=True)

from agents.model_factory import build_model

# Shared app name used by main.py's Runner too — kept as a single constant
# so both modules always target the same logical "app".
APP_NAME = "ai_sales_intelligence_agent"

ORCHESTRATOR_INSTRUCTION = """
You are the orchestrator of an AI sales intelligence pipeline. The user
message is the name of a company. Run these steps IN ORDER, using exactly
one tool call per step:

1. Call `research_agent` with request equal to the company name.
2. Call `lead_scorer_agent` with request asking it to score the lead using
   the research already gathered.
3. Call `email_drafter_agent` with request asking it to draft a
   personalized cold outreach email using the research and score already
   gathered.
4. Call `crm_logger_agent` with request asking it to log everything
   gathered so far to the CRM.

The data each tool needs (research, lead score, email draft) is already
shared with it through session state — you do NOT need to copy JSON between
tool calls yourself, just call each tool in order.

After all four tools have run, reply with a short, friendly plain-text
summary for the user: the company name, the lead score and grade, a one-line
teaser of the email's opening hook, and whether CRM logging succeeded. Do
not repeat the full JSON from each step.

If any step returns an error, stop, explain what failed in plain text, and
do not attempt the remaining steps.
"""


async def _remember_company(callback_context: CallbackContext) -> None:
    """after_agent_callback — session memory of previously researched companies.

    Appends the just-researched company name to a user-scoped state list so
    later turns in the same session can recall which companies have already
    been processed.
    """
    research_data = callback_context.state.get("research_data") or {}
    company = research_data.get("company_name")
    if not company:
        return

    researched = callback_context.state.get("user:researched_companies", [])
    if company not in researched:
        callback_context.state["user:researched_companies"] = researched + [company]


def create_orchestrator_agent() -> Agent:
    """Factory that builds a fresh root orchestrator LlmAgent, wiring up all
    four sub-agents as AgentTools."""
    return Agent(
        name="sales_intelligence_orchestrator",
        model=build_model(),
        description=(
            "Coordinates research, lead scoring, email drafting, and CRM "
            "logging for a company."
        ),
        instruction=ORCHESTRATOR_INSTRUCTION,
        tools=[
            AgentTool(create_research_agent()),
            AgentTool(create_lead_scorer_agent()),
            AgentTool(create_email_drafter_agent()),
            AgentTool(create_crm_logger_agent()),
        ],
        after_agent_callback=_remember_company,
        before_model_callback=throttle_model_call,
    )


# -----------------------------------------------------------------------
# Backward-compatible synchronous wrapper — see research_agent.py for why
# this exists. mcp/mcp_server.py imports `run_orchestrator(company_name)`.
# -----------------------------------------------------------------------


def run_orchestrator(company_name: str) -> dict:
    """Runs the full ADK pipeline for one company and returns a structured
    result. Synchronous wrapper around the async ADK Runner — each call gets
    its own fresh session (no cross-call memory); see main.py for the
    session-reusing version used by the UI.

    Args:
        company_name: Name of the company to research end-to-end.

    Returns:
        dict: {company, research, lead_score, email_draft, crm_logged,
               summary, errors}
    """
    return asyncio.run(_run_orchestrator_async(company_name))


async def _run_orchestrator_async(company_name: str) -> dict:
    app_name = APP_NAME
    user_id = "standalone_user"

    session_service = InMemorySessionService()
    runner = Runner(
        agent=create_orchestrator_agent(),
        app_name=app_name,
        session_service=session_service,
    )

    session = await session_service.create_session(app_name=app_name, user_id=user_id)

    final_text = ""
    errors = []
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session.id,
        new_message=types.Content(
            role="user", parts=[types.Part.from_text(text=company_name)]
        ),
    ):
        if event.error_message:
            errors.append(event.error_message)
        if event.is_final_response() and event.content and event.content.parts:
            text = "".join(
                p.text or "" for p in event.content.parts if getattr(p, "text", None)
            )
            if text:
                final_text = text

    session = await session_service.get_session(
        app_name=app_name, user_id=user_id, session_id=session.id
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
    }


if __name__ == "__main__":
    # Quick standalone test (requires GEMINI_API_KEY and SERPER_API_KEY;
    # GOOGLE_SHEETS_ID is optional — CRM logging is skipped gracefully
    # without it).
    test_result = run_orchestrator("Stripe")
    print("\nFinal Result:")
    print(f"Company: {test_result['company']}")
    print(f"Lead Score: {test_result['lead_score']}")
    print(f"CRM Logged: {test_result['crm_logged']}")
    print(f"Summary: {test_result['summary']}")
