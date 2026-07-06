# research_agent.py
# Research Agent — a real Google ADK LlmAgent.
#
# ADK ARCHITECTURE NOTES
# -----------------------------------------------------------------------
# - `Agent` is the public alias for `google.adk.agents.LlmAgent`. This is a
#   model-driven agent: instead of a Python function calling steps in a
#   fixed order, the LLM itself decides when to call its tools based on the
#   `instruction` prompt.
# - `tools=[research_company_web, search_web_query]` — plain functions from
#   skills/search_skill.py. ADK has no "@tool" decorator in 2.3.0; passing a
#   typed, docstringed function directly is the documented pattern, and ADK
#   wraps it as a FunctionTool automatically.
# - `output_schema=ResearchOutput` forces the agent's FINAL message to be
#   valid JSON matching this Pydantic schema. ADK 2.3.0 supports combining
#   `output_schema` with `tools`: tools stay available during the agent's
#   reasoning loop, and the schema is enforced only on the last message.
# - `output_key="research_data"` writes that final structured dict into
#   `session.state["research_data"]`. When this agent is invoked through an
#   `AgentTool` (see orchestrator.py), ADK automatically forwards this state
#   write back to the PARENT session, so every downstream agent
#   (lead scorer, email drafter, CRM logger) can read it without the
#   orchestrator manually re-typing the research JSON into each tool call.
# - `create_research_agent()` is a factory, not a module-level singleton.
#   ADK agent instances can only be attached to one parent at a time, so a
#   fresh instance is built on demand for the orchestrator's AgentTool and
#   for standalone/backward-compatible use.

import os
import json
import asyncio
from dotenv import load_dotenv
from pydantic import BaseModel

from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from skills.search_skill import research_company_web, search_web_query
from agents.rate_limiter import throttle_model_call

load_dotenv(override=True)

# Model is read from the environment so it can be swapped without code
# changes; defaults to the model specified for this project.
from agents.model_factory import build_model


class ResearchOutput(BaseModel):
    """Structured company intelligence report produced by the research agent."""

    company_name: str
    industry: str
    description: str
    founded: str
    headquarters: str
    employee_count: str
    revenue: str
    funding: str
    recent_news: list[str]
    key_products: list[str]
    tech_stack: list[str]
    pain_points: list[str]
    growth_signals: list[str]


RESEARCH_AGENT_INSTRUCTION = """
You are a B2B sales research analyst.

The user message contains the name of a company to research. You MUST:

1. Call the `research_company_web` tool with the company name to gather raw
   web search snippets (overview, funding, tech stack, recent news).
2. If any field below is still unclear after that, call `search_web_query`
   with a more specific follow-up query. Do not call it more than twice.
3. Analyze all snippets and produce your FINAL answer as a JSON object
   matching the required output schema exactly.

Rules:
- Use "Unknown" for any single-string field you cannot confidently determine
  from the search results — never invent facts.
- recent_news, key_products, tech_stack, pain_points, and growth_signals
  must be lists of short strings (use an empty list if nothing was found).
- Do not include any text outside the final structured JSON response.
- Even if the search results are sparse, unclear, or the searches failed,
  you MUST still reply with the JSON object (filling "Unknown" and empty
  lists) — NEVER reply with an apology, a question, or any plain text.
"""


def create_research_agent() -> Agent:
    """Factory that builds a fresh Research Agent instance."""
    return Agent(
        name="research_agent",
        model=build_model(),
        description=(
            "Researches a company on the web and returns structured company "
            "intelligence: industry, funding, recent news, pain points, and "
            "growth signals."
        ),
        instruction=RESEARCH_AGENT_INSTRUCTION,
        tools=[research_company_web, search_web_query],
        output_schema=ResearchOutput,
        output_key="research_data",
        before_model_callback=throttle_model_call,
    )


# -----------------------------------------------------------------------
# Backward-compatible synchronous wrapper.
#
# mcp/mcp_server.py (a separate competition deliverable, left unmodified per
# project requirements) imports `run_research_agent(company_name) -> dict`
# as a plain function. This wrapper preserves that exact interface while
# running the real ADK agent underneath, using a throwaway Runner +
# InMemorySessionService, so the MCP server keeps working unchanged.
# -----------------------------------------------------------------------


def run_research_agent(company_name: str) -> dict:
    """Runs the research agent for one company and returns its structured
    result. Synchronous wrapper around the async ADK Runner.

    Args:
        company_name: Name of the company to research.

    Returns:
        dict: Structured company intelligence report (see ResearchOutput).
    """
    return asyncio.run(_run_research_agent_async(company_name))


async def _run_research_agent_async(company_name: str) -> dict:
    app_name = "research_agent_app"
    user_id = "standalone_user"

    session_service = InMemorySessionService()
    runner = Runner(
        agent=create_research_agent(),
        app_name=app_name,
        session_service=session_service,
    )

    session = await session_service.create_session(app_name=app_name, user_id=user_id)

    async for _event in runner.run_async(
        user_id=user_id,
        session_id=session.id,
        new_message=types.Content(
            role="user", parts=[types.Part.from_text(text=company_name)]
        ),
    ):
        pass  # We only need the final session state, populated via output_key.

    session = await session_service.get_session(
        app_name=app_name, user_id=user_id, session_id=session.id
    )
    data = session.state.get("research_data")
    if not data:
        raise RuntimeError("Research agent returned no structured result")
    return data


if __name__ == "__main__":
    # Quick standalone test (requires GEMINI_API_KEY and SERPER_API_KEY).
    result = run_research_agent("Stripe")
    print("\nResearch Result:")
    print(json.dumps(result, indent=2))
