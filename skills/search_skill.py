# search_skill.py
# Reusable ADK tool skill — web search for company intelligence.
#
# ADK ARCHITECTURE NOTE:
# google.adk.tools has no "@tool" decorator in ADK 2.3.0 — the documented
# pattern is to write a plain, type-hinted Python function with a clear
# docstring and pass the function reference directly in an agent's
# `tools=[...]` list. ADK inspects the signature/docstring at agent build
# time and auto-wraps it as a `FunctionTool`.
#
# Tool function rules enforced here (per ADK conventions):
#   - Every parameter has a type hint and NO default value (LLM must always
#     supply it explicitly).
#   - Every function returns a JSON-serializable dict, including a "status"
#     key, so the calling LLM agent can branch on success/failure without a
#     raised exception aborting the whole turn.
#
# This module wraps tools/web_search.py (kept unmodified) rather than
# duplicating its Serper API / rate-limiting / sanitization logic.

from tools.web_search import search_company, get_company_news, search_custom


def research_company_web(company_name: str) -> dict:
    """Runs a broad set of web searches about a company (overview, funding,
    tech stack, recent news) and returns the raw, deduplicated search
    snippets for analysis.

    Args:
        company_name: The name of the company to research.

    Returns:
        dict with 'status' ('success' or 'error'), and on success a
        'results' list of {title, snippet, link} search results.
    """
    try:
        overview = search_company(company_name, "overview")
        funding = search_company(company_name, "funding")
        tech = search_company(company_name, "tech")
        news = get_company_news(company_name)

        combined = overview + funding + tech + news

        # De-duplicate by link since the same page often surfaces across
        # multiple query variants.
        seen_links = set()
        deduped = []
        for item in combined:
            link = item.get("link", "")
            if link and link in seen_links:
                continue
            if link:
                seen_links.add(link)
            deduped.append(item)

        return {
            "status": "success",
            "company_name": company_name,
            "result_count": len(deduped),
            "results": deduped,
        }
    except Exception as e:
        return {"status": "error", "error_message": str(e)}


def search_web_query(query: str) -> dict:
    """Runs a single custom web search query. Use this for a specific
    follow-up question that the broad research_company_web search did not
    already answer.

    Args:
        query: The search query text.

    Returns:
        dict with 'status' ('success' or 'error'), and on success a
        'results' list of {title, snippet, link} search results.
    """
    try:
        results = search_custom(query)
        return {"status": "success", "query": query, "results": results}
    except Exception as e:
        return {"status": "error", "error_message": str(e)}
