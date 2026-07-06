# crm_logger.py
# CRM Logger Agent — a real Google ADK LlmAgent.
#
# ADK ARCHITECTURE NOTES
# -----------------------------------------------------------------------
# - Instruction references `{research_data}`, `{lead_score_data}`, and
#   `{email_draft_data}` — all three ADK state placeholders, populated by
#   the three prior agents' `output_key` writes and forwarded automatically
#   by AgentTool when this agent runs under the orchestrator.
# - `tools=[log_to_crm]` performs the actual Google Sheets write — the LLM's
#   job is only to extract the right flat values out of the three state
#   blobs above and call the tool; see skills/crm_skill.py for why the tool
#   takes flat arguments instead of nested dicts.
# - `output_schema=CrmLogOutput` + `output_key="crm_log_data"` mirror the
#   other agents. `crm_log_data["logged"]` is what main.py reads to report
#   `crm_logged` in the final pipeline result.

import os
import json
import asyncio
from dotenv import load_dotenv
from pydantic import BaseModel

from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from skills.crm_skill import log_to_crm
from agents.rate_limiter import throttle_model_call

load_dotenv(override=True)

from agents.model_factory import build_model


class CrmLogOutput(BaseModel):
    """Structured result of the CRM logging attempt."""

    status: str
    logged: bool
    message: str


CRM_LOGGER_INSTRUCTION = """
You are a CRM data-entry agent. Your job is to log the completed sales
intelligence record for a company to the Google Sheets CRM.

COMPANY RESEARCH DATA (from session state):
{research_data}

LEAD SCORE DATA (from session state):
{lead_score_data}

EMAIL DRAFT DATA (from session state):
{email_draft_data}

Steps:
1. Extract: company_name, industry, employee_count, funding (from the
   research data); lead_score, lead_grade (the "grade" field),
   recommended_action, and top_signals (join the list into a single
   comma-separated string) (from the lead score data); email_subject (the
   "subject" field) and estimated_reply_rate (from the email draft data).
2. Call the `log_to_crm` tool with exactly those extracted values.
3. Reply with the FINAL JSON object matching the required output schema
   exactly: "status" and "logged" copied from the tool's response, and a
   short one-line "message" describing the outcome (e.g. "Logged to Google
   Sheets", "Skipped — Google Sheets not configured", or the tool's error).
"""


def create_crm_logger_agent() -> Agent:
    """Factory that builds a fresh CRM Logger Agent instance."""
    return Agent(
        name="crm_logger_agent",
        model=build_model(),
        description=(
            "Logs the completed research, lead score, and email draft for "
            "a company to the Google Sheets CRM."
        ),
        instruction=CRM_LOGGER_INSTRUCTION,
        tools=[log_to_crm],
        output_schema=CrmLogOutput,
        output_key="crm_log_data",
        generate_content_config=types.GenerateContentConfig(temperature=0.1),
        before_model_callback=throttle_model_call,
    )


# -----------------------------------------------------------------------
# Backward-compatible synchronous wrapper — see research_agent.py for why
# this exists. Kept for standalone testing / parity with the original
# plain-function interface (mcp/mcp_server.py does not import this one
# directly — it only calls run_orchestrator, which uses this agent
# internally).
# -----------------------------------------------------------------------


def run_crm_logger(pipeline_result: dict) -> dict:
    """Runs the CRM logger agent for a completed pipeline result.

    Args:
        pipeline_result: dict containing "company", "research", "lead_score",
            and "email_draft" keys, as produced by the orchestrator.

    Returns:
        dict: {status, logged, message} (see CrmLogOutput).
    """
    if not pipeline_result:
        raise ValueError("pipeline_result must be provided")

    company_name = pipeline_result.get("company", "Unknown")
    research_data = pipeline_result.get("research") or {}
    lead_score_data = pipeline_result.get("lead_score") or {}
    email_draft_data = pipeline_result.get("email_draft") or {}

    return asyncio.run(
        _run_crm_logger_async(company_name, research_data, lead_score_data, email_draft_data)
    )


async def _run_crm_logger_async(
    company_name: str,
    research_data: dict,
    lead_score_data: dict,
    email_draft_data: dict,
) -> dict:
    app_name = "crm_logger_app"
    user_id = "standalone_user"

    session_service = InMemorySessionService()
    runner = Runner(
        agent=create_crm_logger_agent(),
        app_name=app_name,
        session_service=session_service,
    )

    session = await session_service.create_session(
        app_name=app_name,
        user_id=user_id,
        state={
            "research_data": research_data,
            "lead_score_data": lead_score_data,
            "email_draft_data": email_draft_data,
        },
    )

    async for _event in runner.run_async(
        user_id=user_id,
        session_id=session.id,
        new_message=types.Content(
            role="user",
            parts=[types.Part.from_text(text=f"Log {company_name} to the CRM.")],
        ),
    ):
        pass

    session = await session_service.get_session(
        app_name=app_name, user_id=user_id, session_id=session.id
    )
    data = session.state.get("crm_log_data")
    if not data:
        raise RuntimeError("CRM logger agent returned no structured result")
    return data


if __name__ == "__main__":
    # Quick standalone test with mock data.
    mock_result = {
        "company": "Stripe",
        "research": {
            "company_name": "Stripe",
            "industry": "Fintech",
            "employee_count": "8000+",
            "funding": "$2.2B raised",
        },
        "lead_score": {
            "score": 87,
            "grade": "A",
            "recommended_action": "Prioritize",
            "top_signals": ["Recent AI launch", "Series I funded"],
        },
        "email_draft": {
            "subject": "Your AI expansion — quick thought",
            "estimated_reply_rate": "High",
        },
    }

    result = run_crm_logger(mock_result)
    print(f"\nCRM Logger Result: {result}")
