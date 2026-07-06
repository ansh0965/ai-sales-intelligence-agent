# web_search.py
# Reusable web search tool — can be called by any agent
# Wraps Serper API (Google Search) with error handling,
# rate limiting protection, and input sanitization

import os
import sys
import requests
import time
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv(override=True)

SERPER_API_KEY = os.getenv("SERPER_API_KEY")
SERPER_URL = "https://google.serper.dev/search"

# Rate limiting — max requests per minute
MAX_REQUESTS_PER_MINUTE = 10
_request_times = []


def _check_rate_limit():
    """
    Simple rate limiter — prevents API abuse.
    Tracks request timestamps and enforces max requests per minute.
    """
    global _request_times
    
    now = time.time()
    
    # Remove requests older than 60 seconds
    _request_times = [t for t in _request_times if now - t < 60]
    
    # Check if we are over the limit
    if len(_request_times) >= MAX_REQUESTS_PER_MINUTE:
        wait_time = 60 - (now - _request_times[0])
        if wait_time > 0:
            # stderr keeps this log out of the MCP stdio protocol channel.
            print(f"   [wait] Rate limit reached - waiting {wait_time:.1f}s", file=sys.stderr)
            time.sleep(wait_time)
    
    # Record this request
    _request_times.append(now)


def search_company(company_name: str, search_type: str = "overview") -> list:
    """
    Searches for company information using Serper API.
    
    Args:
        company_name: Name of the company to search
        search_type: Type of search — overview, news, funding, tech
        
    Returns:
        list: List of search results with title, snippet, link
    """
    
    # Security: validate inputs
    if not company_name or not isinstance(company_name, str):
        raise ValueError("Invalid company name")
    
    # Sanitize company name
    safe_name = "".join(
        c for c in company_name
        if c.isalnum() or c in (' ', '-', '.')
    ).strip()
    
    if len(safe_name) < 2:
        raise ValueError("Company name too short or invalid")
    
    # Build query based on search type
    query_map = {
        "overview": f"{safe_name} company overview about",
        "news": f"{safe_name} latest news {datetime.now().year}",
        "funding": f"{safe_name} funding raised investors valuation",
        "tech": f"{safe_name} technology stack engineering blog"
    }
    
    query = query_map.get(search_type, f"{safe_name} company")
    
    return _execute_search(query)


def search_custom(query: str) -> list:
    """
    Executes a custom search query.
    
    Args:
        query: Custom search query string
        
    Returns:
        list: List of search results
    """
    
    # Security: validate and sanitize query
    if not query or not isinstance(query, str):
        raise ValueError("Invalid search query")
    
    # Limit query length to prevent abuse
    if len(query) > 200:
        query = query[:200]
    
    return _execute_search(query)


def _execute_search(query: str) -> list:
    """
    Internal function that executes the actual Serper API call.
    
    Args:
        query: Sanitized search query
        
    Returns:
        list: Parsed search results
    """
    
    # Validate API key
    if not SERPER_API_KEY:
        raise ValueError("SERPER_API_KEY not configured in environment")
    
    # Apply rate limiting
    _check_rate_limit()
    
    headers = {
        "X-API-KEY": SERPER_API_KEY,
        "Content-Type": "application/json"
    }
    
    payload = {
        "q": query,
        "num": 5,
        "gl": "us",  # Geographic location
        "hl": "en"   # Language
    }
    
    try:
        response = requests.post(
            SERPER_URL,
            headers=headers,
            json=payload,
            timeout=10  # 10 second timeout
        )
        
        # Check response status
        if response.status_code == 401:
            raise ValueError("Invalid Serper API key")
        elif response.status_code == 429:
            raise Exception("Serper API rate limit exceeded")
        elif response.status_code != 200:
            raise Exception(f"Serper API error: {response.status_code}")
        
        data = response.json()
        
        # Parse and return results
        results = []
        for item in data.get("organic", []):
            results.append({
                "title": item.get("title", "").strip(),
                "snippet": item.get("snippet", "").strip(),
                "link": item.get("link", "").strip()
            })
        
        # Also include knowledge graph if available
        knowledge_graph = data.get("knowledgeGraph", {})
        if knowledge_graph:
            results.insert(0, {
                "title": knowledge_graph.get("title", ""),
                "snippet": knowledge_graph.get("description", ""),
                "link": knowledge_graph.get("website", ""),
                "source": "knowledge_graph"
            })
        
        return results
        
    except requests.Timeout:
        raise Exception("Search request timed out after 10 seconds")
    except requests.ConnectionError:
        raise Exception("Network connection error during search")


def get_company_news(company_name: str, days: int = 30) -> list:
    """
    Gets recent news about a company.
    
    Args:
        company_name: Company to search news for
        days: How many days back to search (default 30)
        
    Returns:
        list: Recent news results
    """
    
    safe_name = "".join(
        c for c in company_name
        if c.isalnum() or c in (' ', '-', '.')
    ).strip()
    
    query = f"{safe_name} news announcement {datetime.now().year}"
    return _execute_search(query)


if __name__ == "__main__":
    # Quick test
    print("Testing web search tool...")
    
    results = search_company("Stripe", "overview")
    print(f"\n✅ Found {len(results)} results for Stripe overview")
    for r in results[:2]:
        print(f"  - {r['title']}")
    
    news = get_company_news("Stripe")
    print(f"\n✅ Found {len(news)} news results for Stripe")