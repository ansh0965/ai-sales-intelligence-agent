# model_factory.py
# Single place where every agent's Gemini model object is built.
#
# Wraps the env-selected model name in ADK's `Gemini` class with
# retry_options, so transient 429/5xx responses — especially 503 "model is
# experiencing high demand" spikes on flash-tier models — are retried with
# exponential backoff at the HTTP layer instead of killing the pipeline.
# A full pipeline run fires ~14 model calls; without retries, one flaky
# call out of 14 aborts the entire run.

import os
from dotenv import load_dotenv

from google.adk.models.google_llm import Gemini
from google.genai import types

load_dotenv(override=True)

MODEL_NAME = os.getenv("ADK_MODEL", "gemini-2.5-flash")

_RETRY = types.HttpRetryOptions(
    attempts=6,
    initial_delay=2,
    max_delay=30,
    exp_base=2,
    jitter=0.5,
    http_status_codes=[408, 429, 500, 502, 503, 504],
)


def build_model() -> Gemini:
    """Fresh retry-wrapped Gemini model instance, shared by all agents."""
    return Gemini(model=MODEL_NAME, retry_options=_RETRY)
