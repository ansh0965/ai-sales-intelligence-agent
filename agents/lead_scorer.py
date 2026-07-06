# lead_scorer.py
# Lead Scorer Agent — a real Google ADK LlmAgent.
#
# ADK ARCHITECTURE NOTES
# -----------------------------------------------------------------------
# - The instruction references `{research_data}` — ADK's dynamic state
#   injection: at model-call time, ADK substitutes this placeholder with
#   `session.state["research_data"]`. When this agent runs as an AgentTool
#   under the orchestrator, that state key was already populated by
#   research_agent's `output_key` and copied into this agent's ephemeral
#   session automatically (see AgentTool's state-forwarding behavior,
#   documented in orchestrator.py). No manual re-plumbing of the research
#   JSON is required.
# - `tools=[calculate_lead_score]` gives the model a deterministic
#   calculator for the parts LLMs are unreliable at (summing/clamping
#   integers, applying grade thresholds) — see skills/score_skill.py.
# - `output_schema=LeadScoreOutput` + `output_key="lead_score_data"` mirror
#   the pattern in research_agent.py.

import os
import json
import asyncio
from dotenv import load_dotenv
from pydantic import BaseModel

from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from skills.score_skill import calculate_lead_score
from agents.rate_limiter import throttle_model_call

load_dotenv(override=True)

from agents.model_factory import build_model


class LeadScoreOutput(BaseModel):
    """Structured lead score produced by the lead scorer agent."""

    score: int
    grade: str
    growth_score: int
    funding_score: int
    activity_score: int
    pain_points_score: int
    reasoning: str
    top_signals: list[str]
    risk_factors: list[str]
    recommended_action: str


LEAD_SCORER_INSTRUCTION = """
You are an expert B2B sales lead scoring analyst.

COMPANY RESEARCH DATA (from session state):
{research_data}

Score this lead against 4 categories, 0-25 points each:
1. GROWTH & SIZE — company growth signals, headcount, hiring momentum.
2. FUNDING & REVENUE — recent funding raised, revenue health.
3. RECENT ACTIVITY — product launches, news momentum, market presence.
4. PAIN POINTS ALIGNMENT — do their pain points suggest they need an AI
   sales intelligence tool right now?

Steps:
1. Estimate each of the 4 sub-scores yourself (integers 0-25) based on the
   research data above.
2. Call the `calculate_lead_score` tool with your 4 sub-scores to get the
   validated total score, letter grade, and recommended action. Never skip
   this call and never invent the final score/grade yourself.
3. Reply with the FINAL JSON object matching the required output schema
   exactly: use the score/grade/recommended_action returned by the tool,
   plus your own "reasoning" (2-3 sentences), "top_signals" (the 3 strongest
   signals you found), and "risk_factors" (list of concerns, empty list if
   none).
"""


def create_lead_scorer_agent() -> Agent:
    """Factory that builds a fresh Lead Scorer Agent instance."""
    return Agent(
        name="lead_scorer_agent",
        model=build_model(),
        description=(
            "Scores a sales lead from 1-100 with a letter grade and "
            "recommended sales action, based on company research."
        ),
        instruction=LEAD_SCORER_INSTRUCTION,
        tools=[calculate_lead_score],
        output_schema=LeadScoreOutput,
        output_key="lead_score_data",
        before_model_callback=throttle_model_call,
    )


# -----------------------------------------------------------------------
# Backward-compatible synchronous wrapper — see research_agent.py for why
# this exists. mcp/mcp_server.py imports
# `run_lead_scorer(company_name, research_data) -> dict`.
# -----------------------------------------------------------------------


def run_lead_scorer(company_name: str, research_data: dict) -> dict:
    """Runs the lead scorer agent and returns its structured result.

    Args:
        company_name: Name of the company (used only in the trigger message).
        research_data: Structured research data from research_agent.

    Returns:
        dict: Lead score with breakdown and reasoning (see LeadScoreOutput).
    """
    if not research_data or not isinstance(research_data, dict):
        raise ValueError("research_data must be a non-empty dict")
    return asyncio.run(_run_lead_scorer_async(company_name, research_data))


async def _run_lead_scorer_async(company_name: str, research_data: dict) -> dict:
    app_name = "lead_scorer_app"
    user_id = "standalone_user"

    session_service = InMemorySessionService()
    runner = Runner(
        agent=create_lead_scorer_agent(),
        app_name=app_name,
        session_service=session_service,
    )

    # Pre-seed state with the research data this agent's instruction expects
    # to find at session.state["research_data"] — mirrors what the
    # orchestrator's AgentTool would forward automatically in the real
    # pipeline.
    session = await session_service.create_session(
        app_name=app_name, user_id=user_id, state={"research_data": research_data}
    )

    async for _event in runner.run_async(
        user_id=user_id,
        session_id=session.id,
        new_message=types.Content(
            role="user",
            parts=[types.Part.from_text(text=f"Score the lead for {company_name}.")],
        ),
    ):
        pass

    session = await session_service.get_session(
        app_name=app_name, user_id=user_id, session_id=session.id
    )
    data = session.state.get("lead_score_data")
    if not data:
        raise RuntimeError("Lead scorer agent returned no structured result")
    return data


if __name__ == "__main__":
    # Quick standalone test with mock research data.
    mock_research = {
        "company_name": "Stripe",
        "industry": "Fintech / Payments",
        "description": "Stripe is a technology company that builds economic infrastructure for the internet.",
        "founded": "2010",
        "headquarters": "San Francisco, CA",
        "employee_count": "8000+",
        "revenue": "$14 billion valuation",
        "funding": "$2.2 billion raised",
        "recent_news": ["Launched Stripe AI", "Expanded to 50 new countries", "New enterprise partnerships"],
        "key_products": ["Stripe Payments", "Stripe Connect", "Stripe Atlas"],
        "tech_stack": ["Python", "Ruby", "AWS"],
        "pain_points": ["Scaling payment infrastructure", "International expansion complexity"],
        "growth_signals": ["Rapid international expansion", "New AI product line", "Enterprise focus"],
    }

    result = run_lead_scorer("Stripe", mock_research)
    print("\nLead Score Result:")
    print(json.dumps(result, indent=2))
