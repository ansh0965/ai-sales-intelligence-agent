# email_drafter.py
# Email Drafter Agent — a real Google ADK LlmAgent.
#
# ADK ARCHITECTURE NOTES
# -----------------------------------------------------------------------
# - Instruction references both `{research_data}` and `{lead_score_data}` —
#   both are ADK dynamic state placeholders, populated automatically from
#   session state (see research_agent.py / lead_scorer.py for how they got
#   there via `output_key` + AgentTool state forwarding).
# - `tools=[package_email_draft]` — the LLM writes the creative copy, then
#   calls this tool to get an exact word count and length-limit check
#   rather than "eyeballing" its own word count in the same JSON blob.
# - `output_schema=EmailDraftOutput` + `output_key="email_draft_data"`
#   mirror the pattern used by the other agents.

import os
import json
import asyncio
from dotenv import load_dotenv
from pydantic import BaseModel

from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from skills.email_skill import package_email_draft
from agents.rate_limiter import throttle_model_call

load_dotenv(override=True)

from agents.model_factory import build_model


class EmailDraftOutput(BaseModel):
    """Structured cold outreach email produced by the email drafter agent."""

    subject: str
    body: str
    opening_hook: str
    pain_point_addressed: str
    cta: str
    estimated_reply_rate: str
    word_count: int


EMAIL_DRAFTER_INSTRUCTION = """
You are an expert B2B sales copywriter. Your emails feel human, specific, and
never generic. NEVER use buzzwords like "synergy", "leverage", or "circle back".

COMPANY RESEARCH DATA (from session state):
{research_data}

LEAD SCORE DATA (from session state):
{lead_score_data}

Pick a tone based on the lead grade:
- A: confident and direct — they are a hot lead, be bold.
- B: warm and consultative — good fit, be helpful.
- C: curious and exploratory — keep it light, low pressure.
- D: brief and casual — don't over-invest.

Steps:
1. Write a subject line — specific and curiosity-driven, never generic.
2. Write an opening line referencing ONE specific fact from recent_news or
   growth_signals.
3. Identify ONE specific pain point from pain_points and how an AI sales
   intelligence tool addresses it.
4. Add one clear, low-friction call to action (e.g. a 15 minute call).
5. Keep the body under 150 words total and sign off warmly. Use \\n for
   line breaks inside the body string.
6. Call the `package_email_draft` tool with your subject, body,
   opening_hook, pain_point_addressed, cta, and your own estimated
   estimated_reply_rate (High/Medium/Low).
7. Reply with the FINAL JSON object matching the required output schema
   exactly, using the word_count returned by the tool.
"""


def create_email_drafter_agent() -> Agent:
    """Factory that builds a fresh Email Drafter Agent instance."""
    return Agent(
        name="email_drafter_agent",
        model=build_model(),
        description=(
            "Drafts a personalized, human-sounding cold outreach email "
            "based on company research and lead score."
        ),
        instruction=EMAIL_DRAFTER_INSTRUCTION,
        tools=[package_email_draft],
        output_schema=EmailDraftOutput,
        output_key="email_draft_data",
        generate_content_config=types.GenerateContentConfig(temperature=0.7),
        before_model_callback=throttle_model_call,
    )


# -----------------------------------------------------------------------
# Backward-compatible synchronous wrapper — see research_agent.py for why
# this exists. mcp/mcp_server.py imports
# `run_email_drafter(company_name, research_data, lead_score) -> dict`.
# -----------------------------------------------------------------------


def run_email_drafter(company_name: str, research_data: dict, lead_score: dict) -> dict:
    """Runs the email drafter agent and returns its structured result.

    Args:
        company_name: Name of the company (used only in the trigger message).
        research_data: Structured research data from research_agent.
        lead_score: Structured lead score from lead_scorer.

    Returns:
        dict: Email draft with subject, body, and metadata (see EmailDraftOutput).
    """
    if not research_data:
        raise ValueError("research_data must be provided")
    if not lead_score:
        raise ValueError("lead_score must be provided")
    return asyncio.run(_run_email_drafter_async(company_name, research_data, lead_score))


async def _run_email_drafter_async(
    company_name: str, research_data: dict, lead_score: dict
) -> dict:
    app_name = "email_drafter_app"
    user_id = "standalone_user"

    session_service = InMemorySessionService()
    runner = Runner(
        agent=create_email_drafter_agent(),
        app_name=app_name,
        session_service=session_service,
    )

    session = await session_service.create_session(
        app_name=app_name,
        user_id=user_id,
        state={"research_data": research_data, "lead_score_data": lead_score},
    )

    async for _event in runner.run_async(
        user_id=user_id,
        session_id=session.id,
        new_message=types.Content(
            role="user",
            parts=[types.Part.from_text(text=f"Draft the outreach email for {company_name}.")],
        ),
    ):
        pass

    session = await session_service.get_session(
        app_name=app_name, user_id=user_id, session_id=session.id
    )
    data = session.state.get("email_draft_data")
    if not data:
        raise RuntimeError("Email drafter agent returned no structured result")
    return data


if __name__ == "__main__":
    # Quick standalone test with mock data.
    mock_research = {
        "company_name": "Stripe",
        "industry": "Fintech",
        "description": "Stripe builds payment infrastructure for the internet.",
        "recent_news": ["Launched Stripe AI", "Expanded to 50 countries"],
        "pain_points": ["Scaling sales team internationally", "Enterprise deal complexity"],
        "growth_signals": ["Rapid expansion", "New AI products", "Enterprise focus"],
        "funding": "$2.2 billion raised",
        "employee_count": "8000+",
    }

    mock_score = {
        "score": 87,
        "grade": "A",
        "reasoning": "Strong growth signals and recent funding make this a hot lead.",
        "top_signals": ["Recent AI launch", "International expansion", "Series I funded"],
        "recommended_action": "Prioritize",
    }

    result = run_email_drafter("Stripe", mock_research, mock_score)
    print("\nEmail Draft Result:")
    print(json.dumps(result, indent=2))
