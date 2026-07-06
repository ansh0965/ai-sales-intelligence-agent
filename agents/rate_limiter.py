# rate_limiter.py
# Shared throttle so every agent's Gemini calls stay under the per-minute
# quota, instead of bursting past it and crashing the pipeline.
#
# The orchestrator + its 4 sub-agents all share one Gemini API key and one
# per-minute quota (observed as low as 5 requests/minute on the free tier).
# A single pipeline run fires many more model calls than that in a few
# seconds (one per agent turn, plus tool-call round trips), so without this
# throttle the run reliably hits a 429 RESOURCE_EXHAUSTED partway through.
# On a paid tier, raise GEMINI_MAX_CALLS_PER_MINUTE in .env — the throttle
# then acts as a cheap safety net instead of a bottleneck.
#
# This is registered as `before_model_callback` on every agent (see
# orchestrator.py, research_agent.py, lead_scorer.py, email_drafter.py,
# crm_logger.py) so the limit is enforced globally across the whole
# pipeline, not per-agent.
#
# CONCURRENCY NOTE: the deque is guarded by a threading.Lock, NOT an
# asyncio.Lock. Callers run on several different event loops over the
# process lifetime (the Gradio UI's loop, plus a fresh asyncio.run loop per
# MCP tool call or CLI run), and an asyncio.Lock binds itself to the first
# loop that acquires it — the next loop would raise "bound to a different
# event loop". The threading.Lock is held only for microseconds of deque
# bookkeeping; the actual waiting happens in `await asyncio.sleep`, outside
# the lock, so no event loop is ever blocked.

import asyncio
import os
import threading
import time
from collections import deque

_MAX_CALLS_PER_MINUTE = int(os.getenv("GEMINI_MAX_CALLS_PER_MINUTE", "4"))
_WINDOW_SECONDS = 60.0

_call_times: deque[float] = deque()
_guard = threading.Lock()


async def throttle_model_call(callback_context, llm_request):
    """`before_model_callback` that sleeps just long enough to keep the
    combined call rate, across all agents, under the shared per-minute
    quota. Returning None tells ADK to proceed with the model call as
    normal."""
    while True:
        with _guard:
            now = time.monotonic()
            while _call_times and now - _call_times[0] > _WINDOW_SECONDS:
                _call_times.popleft()
            if len(_call_times) < _MAX_CALLS_PER_MINUTE:
                _call_times.append(now)
                return None
            wait = _WINDOW_SECONDS - (now - _call_times[0]) + 0.5
        await asyncio.sleep(wait)
