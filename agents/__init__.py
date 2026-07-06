# agents/__init__.py
# Exports the ADK agent factories and a ready-to-use `root_agent` instance.
#
# `root_agent` follows the ADK CLI convention (used by `adk web`, `adk run`,
# and `agents-cli playground`) of discovering an agent package via a
# module-level `root_agent` symbol. Building it here is cheap — it only
# constructs the in-memory Agent/AgentTool object graph, it does not make
# any network calls.

from agents.research_agent import create_research_agent, run_research_agent
from agents.lead_scorer import create_lead_scorer_agent, run_lead_scorer
from agents.email_drafter import create_email_drafter_agent, run_email_drafter
from agents.crm_logger import create_crm_logger_agent, run_crm_logger
from agents.orchestrator import create_orchestrator_agent, run_orchestrator, APP_NAME

root_agent = create_orchestrator_agent()

__all__ = [
    "create_research_agent",
    "create_lead_scorer_agent",
    "create_email_drafter_agent",
    "create_crm_logger_agent",
    "create_orchestrator_agent",
    "root_agent",
    "run_research_agent",
    "run_lead_scorer",
    "run_email_drafter",
    "run_crm_logger",
    "run_orchestrator",
    "APP_NAME",
]
