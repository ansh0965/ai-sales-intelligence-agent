# AI Sales Intelligence Agent — Kaggle Capstone Writeup

> **Draft for the Kaggle submission (~2,500 words). Before submitting: fill in
> the three placeholder links, personalize the Antigravity paragraph with what
> you actually did, and read it once end-to-end so it sounds like you.**

**GitHub:** *(link)* · **Live demo:** *(Hugging Face Space link)* · **Video:** *(YouTube link)*

---

## The problem: sales research doesn't scale

Ask any sales development representative what eats their day and you will get
the same answer: research. Before a single cold email goes out, someone has to
read the target company's recent news, figure out whether it is growing or
shrinking, guess at its pain points, decide whether it is even worth
contacting, and then write outreach that doesn't sound like the two hundred
other templates in the prospect's inbox. Industry surveys consistently put
this at two to three hours per qualified lead. It is skilled work — but it is
also repetitive, structured, and largely assembled from public information,
which makes it an almost perfect target for an agentic system.

The AI Sales Intelligence Agent compresses that entire workflow into one
input. You type a company name. About a minute later you have a structured
research report built from live web search, a defensible 1–100 lead score
with reasoning and risk factors, a personalized cold email whose tone adapts
to how hot the lead is, and a new row in a Google Sheets CRM. The system is
built on the Google Agent Development Kit (ADK) with Gemini 2.5 Flash,
exposes itself to the wider agent ecosystem through a Model Context Protocol
(MCP) server, and runs live on Hugging Face Spaces.

This writeup covers the architecture, the specific ADK mechanics that make it
work, and the engineering decisions — including the unglamorous ones like
rate limiting and event-loop management — that turned a demo into something
robust.

## What the system demonstrates

Of the competition's capability list, this project demonstrates five:

1. **A multi-agent system built with ADK** — one orchestrator and four
   specialist `LlmAgent`s, in code.
2. **An MCP server** — five tools exposed over the official MCP Python SDK,
   in code.
3. **Agent skills** — a reusable, typed tool library shared by the agents, in
   code.
4. **Security features** — input validation, sanitization, secret hygiene,
   dual rate limiting, and MCP hardening, in code.
5. **Deployability** — a live Hugging Face Space, shown in the video, along
   with the **Antigravity** development workflow.

## Architecture: five agents, one shared memory

The system is a hierarchy with a single root: `sales_intelligence_orchestrator`,
a genuine ADK `LlmAgent`. It is worth stressing what that means, because it is
the difference between an agent system and a Python script with LLM calls in
it: the orchestrator's control flow lives in its instruction prompt, not in
code. The model itself decides to invoke the research agent, then the scorer,
then the drafter, then the CRM logger, and the model itself writes the final
plain-language summary for the user. If a step fails, the model explains what
failed and stops — behavior specified in natural language, not `try/except`
choreography.

The four specialists are each real `LlmAgent`s too, with their own tools,
reasoning loops, and — critically — their own structured output contracts:

- **Research Agent** — calls a `research_company_web` tool that fans out four
  Serper (Google Search) queries — overview, funding, tech stack, news —
  deduplicates results by URL, and returns raw snippets. The agent may issue
  up to two follow-up searches if fields are still unclear, then must emit
  JSON matching a thirteen-field Pydantic `ResearchOutput` schema. The
  instruction explicitly requires `"Unknown"` for anything not supported by
  the search results — an anti-hallucination rule that matters more in sales
  than in most domains, because a fabricated "fact" in a cold email is
  instantly disqualifying.
- **Lead Scorer** — reads the research and estimates four 0–25 sub-scores
  (growth, funding, recent activity, pain-point alignment). It is *required*
  to call a deterministic `calculate_lead_score` tool to clamp, sum, and
  grade those estimates. The judgment is the LLM's; the arithmetic never is.
- **Email Drafter** — runs at temperature 0.7, the only agent allowed real
  creative latitude. Its instruction encodes actual sales craft: reference
  exactly one specific recent fact, address exactly one pain point, one
  low-friction call to action, under 150 words, tone selected by lead grade —
  bold for an A, casual for a D. A `package_email_draft` tool computes the
  exact word count, because language models are famously bad at counting
  their own words.
- **CRM Logger** — extracts ten flat fields from the accumulated state and
  calls a `log_to_crm` tool that writes to Google Sheets. It runs at
  temperature 0.1; data entry is not the place for creativity.

### The mechanic that makes it work: session state as a data bus

The most important architectural decision is how data moves between agents,
because the naive approach — the orchestrator copying JSON blobs from one
tool call into the next — is both token-expensive and error-prone.

ADK offers two composition patterns. With `sub_agents`, control *transfers*
to the sub-agent and doesn't come back. I used the second pattern: each
specialist is wrapped in an `AgentTool`, so to the orchestrator every agent
looks like a callable tool, and the orchestrator remains in control
throughout. When an `AgentTool` is invoked, ADK copies the parent's session
state into an ephemeral session for the sub-agent, runs it, and copies its
state writes back.

Combined with two other ADK features, this becomes a zero-plumbing data bus.
Each agent declares an `output_key` — the research agent's validated JSON is
written to `session.state["research_data"]` automatically. And each
downstream agent's instruction contains placeholders like `{research_data}`,
which ADK substitutes from session state at model-call time. So research
flows to the scorer, research and score flow to the drafter, and everything
flows to the CRM logger, without the orchestrator shuttling a single byte.
The orchestrator's instruction says, in effect, "call these four tools in
order; the data is already shared" — and it is.

Two callbacks complete the picture. An `after_agent_callback` on the
orchestrator appends each processed company to a user-scoped state list,
giving the system session memory ("which companies have I already
researched?") that the UI surfaces as an instant-reload history. And a
`before_model_callback` on *every* agent implements global rate limiting,
which deserves its own section.

## The unglamorous engineering: quota, event loops, and stdio

**Rate limiting across five agents.** All five agents share one Gemini API
key, and a single pipeline run fires a dozen-plus model calls in quick
succession — one per agent turn plus a round trip for every tool call. On
the free tier that reliably produced `429 RESOURCE_EXHAUSTED` mid-pipeline.
The fix is a process-wide token-bucket throttle registered as a
`before_model_callback` on every agent: a shared deque of call timestamps,
and a sleep that delays the next model call just long enough to stay under
`GEMINI_MAX_CALLS_PER_MINUTE`. Because it hooks the model-call layer itself,
it covers every agent and every retry, not just the happy path. On a paid
tier the ceiling is raised via environment variable and the throttle becomes
a cheap safety net.

One subtlety: the throttle originally guarded its deque with an
`asyncio.Lock`, which binds itself to the first event loop that acquires it.
This process legitimately runs *multiple* event loops over its lifetime —
the Gradio UI's loop, plus a fresh `asyncio.run` loop for each CLI or MCP
invocation — so the lock was replaced with a `threading.Lock` held only for
microseconds of bookkeeping, with the actual waiting done in
`await asyncio.sleep` outside the lock. Loop-agnostic and thread-safe.

**MCP and the event-loop boundary.** The MCP server's `call_tool` handler is
async and runs inside the server's own event loop, while the agent pipeline
wrappers are synchronous functions that own their own loops via
`asyncio.run`. Calling one directly from the other raises `asyncio.run()
cannot be called from a running event loop`. Every tool invocation is
therefore dispatched with `await asyncio.to_thread(...)`: the wrapper gets a
fresh thread with no running loop, and the server's loop stays responsive.

**Stdio discipline.** Under MCP's stdio transport, stdout *is* the JSON-RPC
channel. Any stray `print()` corrupts the protocol — and emoji in those
prints can crash outright on Windows, where piped stdout defaults to cp1252.
All human-facing logging in the server process goes to stderr in plain
ASCII. These are exactly the bugs that don't show up in a notebook and do
show up the moment a real MCP client connects; finding and fixing them was a
lesson in why "exposes an MCP server" and "works with an MCP client" are
different claims.

## The MCP server: the pipeline as infrastructure

`mcp/mcp_server.py` exposes five tools over the official MCP Python SDK:
`research_company`, `score_lead`, `draft_email`, `run_full_pipeline`, and
`search_web`. Granular tools matter: an external agent can compose *parts*
of the pipeline — research five companies, score them all, and only draft
emails for the A-grades — rather than being forced through the full
pipeline every time.

This reframes the project. The Gradio UI is one client. Claude Desktop can
be another; so can any MCP-capable framework. The multi-agent system stops
being an app and becomes infrastructure — which is, I'd argue, where the
agent ecosystem is heading: specialized agent systems exposing themselves as
tools to other agents. The server hardens its surface with an explicit tool
allowlist, argument type validation, and structured error results instead of
raw tracebacks.

## Agent skills: the reusable tool layer

The `skills/` package is the system's reusable capability library — plain,
typed Python functions that ADK auto-wraps as `FunctionTool`s. They follow
three conventions throughout: every parameter is type-hinted with no
defaults (the LLM must supply everything explicitly), every function returns
a JSON-serializable dict with a `status` key (so an agent can read an error
and adapt, instead of an exception killing its turn), and every docstring is
written for an LLM reader, because the docstring *is* the tool's interface.

The design principle across the four skills is a strict division of labor:
**LLMs judge and write; deterministic code counts and validates.** The
scorer's grade thresholds, the email's word count, the CRM write — none of
that is entrusted to a model. One less obvious example: `log_to_crm` takes
ten *flat* arguments rather than one nested dict, because models fill flat,
named parameters extracted from context far more reliably than they
re-serialize nested JSON exactly.

## Security

Security here is layered rather than performative. A single input-validation
boundary (`main._validate_company_name`) covers every entry point — UI, CLI,
and MCP — checking type, emptiness, and length bounds. The web-search tool
independently strips search inputs down to alphanumerics plus basic
punctuation and length-caps custom queries before they reach the Serper API.
No secret appears anywhere in code: keys live in `.env` (gitignored, with a
documented `.env.example`), the Sheets service account stays in a gitignored
credentials file, and the deployed Space injects the same variables as
platform secrets. Rate limiting exists at two independent layers (the global
Gemini throttle and a separate Serper limiter). The UI HTML-escapes every
model- or web-derived value it renders — research snippets come from the
open web and are treated as untrusted. And the research agent's
"say-Unknown-don't-invent" rule is a content-level guard: in an outbound
email, a hallucination is not just wrong, it is reputational damage.

## The interface: showing the agents think

The Gradio 6 front end streams the ADK Runner's event stream into a live
"Agent Activity" panel — every tool call and tool response appears as it
happens, so you can watch the orchestrator delegate in real time rather than
staring at a spinner. It matters for trust (users see *why* the score is
what it is), and it makes the multi-agent architecture legible to a
non-technical audience in a way no diagram can. Results land in three tabs —
research report, a visual score card with per-criterion bars, and the email
with a copy-ready text box — plus a session history dropdown backed by the
agent's own memory, and a downloadable Markdown report.

## Development with Antigravity

*(Personalize this paragraph with what you actually did before submitting.)*
The project was developed and tested in Antigravity, Google's agentic IDE.
Its agent was most useful at the debugging edges of this project — tracing
ADK's event stream to get the streaming UI right, and exercising the MCP
server the way an external client would — while the built-in browser preview
closed the loop on UI iterations without leaving the editor. The video
includes a segment of this workflow.

## Results and honest limitations

On test companies (Stripe, Notion, Figma, OpenAI, HubSpot), the pipeline
completes in roughly one to two minutes on free-tier rate limits — the bulk
of it throttle wait, not compute — and much faster on Tier 1. Research
quality tracks the company's web footprint: rich and specific for
well-covered companies, sparse (but honestly marked "Unknown") for obscure
ones. Emails reliably reference one verifiable recent fact and land under
150 words.

Limitations worth naming: lead scoring reflects a generic B2B ideal-customer
profile rather than a configurable one; `InMemorySessionService` means
session memory dies with the process (ADK's database-backed session service
is the natural upgrade); research inherits any inaccuracies in search
snippets even when it avoids invention; and cost per lead, while low, is not
zero — batch scoring thousands of leads would want caching and cheaper
models for the research pass.

The extensions are mostly configuration, not architecture: an ICP-aware
scorer, an email-sending agent with human approval, real CRM integrations
(HubSpot and Salesforce both speak MCP now), and parallel batch processing —
ADK's `ParallelAgent` slots directly into the existing orchestrator pattern.

## Closing

The interesting part of this project was never any single agent — Gemini can
research a company in one prompt if you ask nicely. It was the composition:
five specialized agents with structured contracts, sharing state through a
mechanism none of them has to think about, throttled globally, validated at
every boundary, and exposed to the outside world through a protocol that
makes the whole system a tool in someone else's toolbox. That composition is
what turns "an LLM demo" into "a system" — and it is what I would build on.

---
*Word count: ~2,450. Links to fill: GitHub repo, HF Space, YouTube video.*
