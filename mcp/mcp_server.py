# mcp_server.py
# MCP (Model Context Protocol) Server
# Exposes agent tools as MCP-compatible endpoints
# This allows external AI systems to call our agent tools
# MCP is a key judging requirement for this competition
#
# CONCURRENCY NOTE: the agent wrappers (run_research_agent, run_orchestrator,
# etc.) are synchronous and each call asyncio.run() internally. They must NOT
# be called directly from call_tool(), which already runs inside this
# server's own event loop — asyncio.run() would raise "cannot be called from
# a running event loop". Every tool call is therefore dispatched with
# asyncio.to_thread(), giving the wrapper a fresh thread with no running
# loop, and keeping the server loop responsive while the pipeline runs.
#
# STDIO NOTE: under stdio transport, STDOUT is the JSON-RPC protocol channel.
# Any print() to stdout corrupts the stream, so all human-facing logging in
# this process goes to stderr (see main()).

import os
import json
import asyncio
from typing import Any
from dotenv import load_dotenv

# MCP SDK imports
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Tool,
    TextContent,
    CallToolResult,
    ListToolsResult
)

# Import our agent tools
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.web_search import search_company, get_company_news, search_custom
from agents.research_agent import run_research_agent
from agents.lead_scorer import run_lead_scorer
from agents.email_drafter import run_email_drafter
from agents.orchestrator import run_orchestrator

# Load environment variables
load_dotenv(override=True)

# Initialize MCP server
app = Server("ai-sales-intelligence")


@app.list_tools()
async def list_tools() -> ListToolsResult:
    """
    Lists all available tools exposed by this MCP server.
    These tools can be called by any MCP-compatible AI agent.
    """
    
    return ListToolsResult(
        tools=[
            Tool(
                name="research_company",
                description=(
                    "Research a company using web search and AI analysis. "
                    "Returns structured intelligence including industry, "
                    "funding, recent news, pain points and growth signals."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "company_name": {
                            "type": "string",
                            "description": "Name of the company to research"
                        }
                    },
                    "required": ["company_name"]
                }
            ),
            
            Tool(
                name="score_lead",
                description=(
                    "Score a sales lead from 1-100 based on company research. "
                    "Returns score, grade (A/B/C/D), breakdown, and "
                    "recommended sales action."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "company_name": {
                            "type": "string",
                            "description": "Name of the company"
                        },
                        "research_data": {
                            "type": "object",
                            "description": "Research data from research_company tool"
                        }
                    },
                    "required": ["company_name", "research_data"]
                }
            ),
            
            Tool(
                name="draft_email",
                description=(
                    "Draft a personalized cold outreach email for a company. "
                    "Uses research and lead score to craft a highly relevant, "
                    "human-sounding email with subject line and body."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "company_name": {
                            "type": "string",
                            "description": "Name of the company"
                        },
                        "research_data": {
                            "type": "object",
                            "description": "Research data from research_company tool"
                        },
                        "lead_score": {
                            "type": "object",
                            "description": "Lead score from score_lead tool"
                        }
                    },
                    "required": ["company_name", "research_data", "lead_score"]
                }
            ),
            
            Tool(
                name="run_full_pipeline",
                description=(
                    "Runs the complete sales intelligence pipeline for a company. "
                    "Researches, scores, drafts email and logs to CRM — "
                    "all in one call. Returns complete intelligence report."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "company_name": {
                            "type": "string",
                            "description": "Name of the company to process"
                        }
                    },
                    "required": ["company_name"]
                }
            ),
            
            Tool(
                name="search_web",
                description=(
                    "Search the web for any query using Google Search. "
                    "Returns top 5 results with titles, snippets and links."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query to execute"
                        }
                    },
                    "required": ["query"]
                }
            )
        ]
    )


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> CallToolResult:
    """
    Handles tool calls from MCP clients.
    Routes each tool call to the appropriate agent function.
    
    Args:
        name: Name of the tool to call
        arguments: Tool arguments from the MCP client
        
    Returns:
        CallToolResult: Tool execution result
    """
    
    try:
        # Security: validate tool name
        allowed_tools = [
            "research_company",
            "score_lead", 
            "draft_email",
            "run_full_pipeline",
            "search_web"
        ]
        
        if name not in allowed_tools:
            return CallToolResult(
                content=[TextContent(
                    type="text",
                    text=json.dumps({
                        "error": f"Unknown tool: {name}",
                        "allowed_tools": allowed_tools
                    })
                )],
                isError=True
            )
        
        # Security: validate arguments is a dict
        if not isinstance(arguments, dict):
            return CallToolResult(
                content=[TextContent(
                    type="text",
                    text=json.dumps({"error": "Arguments must be a dictionary"})
                )],
                isError=True
            )
        
        # Route to correct tool
        if name == "research_company":
            company_name = arguments.get("company_name", "").strip()
            if not company_name:
                raise ValueError("company_name is required")
            
            result = await asyncio.to_thread(run_research_agent, company_name)
            
        elif name == "score_lead":
            company_name = arguments.get("company_name", "").strip()
            research_data = arguments.get("research_data", {})
            
            if not company_name:
                raise ValueError("company_name is required")
            if not research_data:
                raise ValueError("research_data is required")
            
            result = await asyncio.to_thread(run_lead_scorer, company_name, research_data)
            
        elif name == "draft_email":
            company_name = arguments.get("company_name", "").strip()
            research_data = arguments.get("research_data", {})
            lead_score = arguments.get("lead_score", {})
            
            if not company_name:
                raise ValueError("company_name is required")
            
            result = await asyncio.to_thread(
                run_email_drafter,
                company_name,
                research_data,
                lead_score,
            )
            
        elif name == "run_full_pipeline":
            company_name = arguments.get("company_name", "").strip()
            if not company_name:
                raise ValueError("company_name is required")
            
            result = await asyncio.to_thread(run_orchestrator, company_name)
            
        elif name == "search_web":
            query = arguments.get("query", "").strip()
            if not query:
                raise ValueError("query is required")
            
            result = await asyncio.to_thread(search_custom, query)
        
        # Return successful result
        return CallToolResult(
            content=[TextContent(
                type="text",
                text=json.dumps(result, indent=2)
            )],
            isError=False
        )
        
    except ValueError as e:
        # Input validation errors
        return CallToolResult(
            content=[TextContent(
                type="text",
                text=json.dumps({"error": f"Validation error: {str(e)}"})
            )],
            isError=True
        )
        
    except Exception as e:
        # Unexpected errors
        return CallToolResult(
            content=[TextContent(
                type="text",
                text=json.dumps({
                    "error": f"Tool execution failed: {str(e)}",
                    "tool": name
                })
            )],
            isError=True
        )


async def main():
    """
    Main entry point for the MCP server.
    Runs the server using stdio transport.
    """
    # stderr, never stdout — stdout is the MCP protocol channel (see header).
    print("AI Sales Intelligence MCP Server starting...", file=sys.stderr)
    print("Available tools: research_company, score_lead, "
          "draft_email, run_full_pipeline, search_web", file=sys.stderr)
    
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())