# skills/__init__.py
# Exports every reusable ADK tool function so agents can import them from
# `skills` directly (e.g. `from skills import research_company_web`).

from skills.search_skill import research_company_web, search_web_query
from skills.score_skill import calculate_lead_score
from skills.email_skill import package_email_draft
from skills.crm_skill import log_to_crm

__all__ = [
    "research_company_web",
    "search_web_query",
    "calculate_lead_score",
    "package_email_draft",
    "log_to_crm",
]
