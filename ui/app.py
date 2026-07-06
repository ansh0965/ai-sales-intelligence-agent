# app.py
# Gradio UI for AI Sales Intelligence Agent
# This is the main interface judges will interact with
# Clean, professional UI that showcases all agent capabilities
#
# ADK ARCHITECTURE NOTE:
# The UI no longer talks to agents/orchestrator.py directly — it goes
# through main.py's `stream_pipeline`, an async generator that surfaces the
# ADK Runner's event stream (tool calls, tool responses, the orchestrator's
# final message) as they happen, so the "Agent Activity" panel updates live
# instead of only showing a result after the whole pipeline finishes.
#
# UI NOTE: history and the downloadable report are kept in a gr.State dict
# of {company_name: raw_result} — separate from ADK's own session state
# (which only remembers company *names*, not full results). The dict is
# mirrored to ui/history_cache.json after every successful run and reloaded
# on every page load, so previously researched companies survive app
# restarts without re-running the pipeline (or re-spending API quota).

import os
import re
import sys
import html
import json
import tempfile
import gradio as gr
from dotenv import load_dotenv

# Add parent directory to path so `main` and `agents` are importable when
# this file is run directly (e.g. `python ui/app.py`).
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import stream_pipeline

# Load environment variables
load_dotenv(override=True)

esc = html.escape

GRADE_COLORS = {
    "A": ("#166534", "#dcfce7"),
    "B": ("#1d4ed8", "#dbeafe"),
    "C": ("#92400e", "#fef3c7"),
    "D": ("#991b1b", "#fee2e2"),
}

STATUS_KINDS = {
    "idle": ("#eef2ff", "#3730a3"),
    "running": ("#fffbeb", "#92400e"),
    "success": ("#f0fdf4", "#166534"),
    "error": ("#fef2f2", "#991b1b"),
    "history": ("#f5f3ff", "#5b21b6"),
}

HEADER_HTML = """
<div class="header-banner">
  <h1>🤖 AI Sales Intelligence Agent</h1>
  <p>Multi-agent research &rarr; lead scoring &rarr; personalized outreach, powered by Google ADK + Gemini 2.5</p>
  <div class="badges">
    <span class="badge">🔗 Google ADK</span>
    <span class="badge">✨ Gemini 2.5</span>
    <span class="badge">🏆 Kaggle Capstone 2026</span>
  </div>
</div>
"""

CUSTOM_CSS = """
.gradio-container { max-width: 1150px !important; margin: 0 auto !important; }

.header-banner {
  background: linear-gradient(135deg, #4338ca 0%, #7c3aed 60%, #a855f7 100%);
  border-radius: 16px;
  padding: 28px 32px;
  color: white;
  text-align: center;
  margin-bottom: 8px;
  box-shadow: 0 10px 30px rgba(76, 29, 149, 0.25);
}
.header-banner h1 { margin: 0 0 6px 0; font-size: 1.9rem; }
.header-banner p { margin: 0 0 12px 0; opacity: 0.92; }
.header-banner .badges { display: flex; justify-content: center; gap: 8px; flex-wrap: wrap; }
.header-banner .badge {
  background: rgba(255,255,255,0.18);
  border: 1px solid rgba(255,255,255,0.35);
  border-radius: 999px;
  padding: 4px 12px;
  font-size: 0.78rem;
  font-weight: 600;
}

.status-banner { border-radius: 10px; padding: 12px 16px; font-weight: 600; font-size: 0.95rem; }

.empty-state { color: #94a3b8; font-style: italic; }

.score-card { padding: 4px 6px; }
.score-top { display: flex; align-items: center; gap: 18px; margin-bottom: 14px; }
.grade-badge {
  flex: 0 0 auto;
  width: 64px; height: 64px;
  border-radius: 50%;
  border: 3px solid;
  display: flex; align-items: center; justify-content: center;
  font-size: 1.8rem; font-weight: 800;
}
.score-number { font-size: 2rem; font-weight: 800; line-height: 1; }
.score-max { font-size: 1rem; font-weight: 500; color: #64748b; }
.score-action { font-size: 0.95rem; color: #475569; margin-top: 4px; }

.score-track { background: #e2e8f0; border-radius: 999px; overflow: hidden; height: 14px; margin-bottom: 18px; }
.score-fill { height: 100%; border-radius: 999px; }

.subscore-row { display: grid; grid-template-columns: 160px 1fr 56px; align-items: center; gap: 10px; margin-bottom: 8px; }
.subscore-label { font-size: 0.85rem; color: #334155; }
.subscore-track { background: #e2e8f0; border-radius: 999px; overflow: hidden; height: 10px; }
.subscore-fill { height: 100%; border-radius: 999px; background: #6366f1; }
.subscore-value { font-size: 0.8rem; color: #64748b; text-align: right; }

.score-section { margin-top: 16px; }
.score-section h4 { margin: 0 0 6px 0; font-size: 0.8rem; color: #334155; text-transform: uppercase; letter-spacing: 0.04em; }
.score-section p { margin: 0; color: #1e293b; }

.pill-list { display: flex; flex-wrap: wrap; gap: 6px; }
.pill { display: inline-block; padding: 3px 10px; border-radius: 999px; font-size: 0.8rem; font-weight: 600; }
.pill-good { background: #dcfce7; color: #166534; }
.pill-risk { background: #fee2e2; color: #991b1b; }
"""

THEME = gr.themes.Soft(primary_hue="indigo", secondary_hue="violet", neutral_hue="slate")


def status_banner(text: str, kind: str = "idle") -> str:
    bg, fg = STATUS_KINDS.get(kind, STATUS_KINDS["idle"])
    return f'<div class="status-banner" style="background:{bg};color:{fg};">{text}</div>'


def format_research(research: dict) -> str:
    """Formats research data into readable markdown."""
    if not research:
        return "Research results will appear here..."

    return f"""
## 🏢 {research.get('company_name', 'Unknown')}

**Industry:** {research.get('industry', 'Unknown')}
**Founded:** {research.get('founded', 'Unknown')}
**Headquarters:** {research.get('headquarters', 'Unknown')}
**Employees:** {research.get('employee_count', 'Unknown')}
**Revenue:** {research.get('revenue', 'Unknown')}
**Funding:** {research.get('funding', 'Unknown')}

**Description:**
{research.get('description', 'No description available.')}

**Recent News:**
{chr(10).join(f"• {news}" for news in research.get('recent_news', []))}

**Key Products:**
{chr(10).join(f"• {p}" for p in research.get('key_products', []))}

**Pain Points:**
{chr(10).join(f"• {p}" for p in research.get('pain_points', []))}

**Growth Signals:**
{chr(10).join(f"• {s}" for s in research.get('growth_signals', []))}
"""


def format_lead_score_html(score: dict) -> str:
    """Renders the lead score as a styled HTML card (grade badge, score bar,
    per-criterion breakdown bars, signal/risk pills)."""
    if not score:
        return '<div class="empty-state">Lead score will appear here once the pipeline runs...</div>'

    grade = score.get("grade", "N/A")
    score_val = score.get("score", 0) or 0
    fg, bg = GRADE_COLORS.get(grade, ("#334155", "#e2e8f0"))

    def subscore(label: str, value, emoji: str) -> str:
        value = value or 0
        pct = max(0, min(100, int(value / 25 * 100)))
        return f"""
        <div class="subscore-row">
          <div class="subscore-label">{emoji} {esc(label)}</div>
          <div class="subscore-track"><div class="subscore-fill" style="width:{pct}%;"></div></div>
          <div class="subscore-value">{esc(str(value))}/25</div>
        </div>"""

    signals = "".join(f'<span class="pill pill-good">✓ {esc(s)}</span>' for s in score.get("top_signals", []))
    risks = "".join(f'<span class="pill pill-risk">⚠ {esc(r)}</span>' for r in score.get("risk_factors", []))

    return f"""
    <div class="score-card">
      <div class="score-top">
        <div class="grade-badge" style="color:{fg};background:{bg};border-color:{fg};">{esc(str(grade))}</div>
        <div class="score-top-text">
          <div class="score-number">{esc(str(score_val))}<span class="score-max">/100</span></div>
          <div class="score-action">{esc(score.get('recommended_action', 'N/A'))}</div>
        </div>
      </div>
      <div class="score-track"><div class="score-fill" style="width:{score_val}%;background:{fg};"></div></div>
      <div class="subscore-list">
        {subscore("Growth & Size", score.get("growth_score"), "📈")}
        {subscore("Funding & Revenue", score.get("funding_score"), "💰")}
        {subscore("Recent Activity", score.get("activity_score"), "🗞️")}
        {subscore("Pain Point Fit", score.get("pain_points_score"), "🎯")}
      </div>
      <div class="score-section">
        <h4>Reasoning</h4>
        <p>{esc(score.get('reasoning', 'No reasoning available.'))}</p>
      </div>
      <div class="score-section">
        <h4>Top Signals</h4>
        <div class="pill-list">{signals or '<span class="empty-state">None found.</span>'}</div>
      </div>
      <div class="score-section">
        <h4>Risk Factors</h4>
        <div class="pill-list">{risks or '<span class="empty-state">None found.</span>'}</div>
      </div>
    </div>"""


def format_lead_score_markdown(score: dict) -> str:
    """Plain-markdown lead score summary, used only in the downloadable report."""
    if not score:
        return "No score data available."

    grade = score.get("grade", "N/A")
    score_val = score.get("score", 0)
    filled = int(score_val / 10)
    bar = "█" * filled + "░" * (10 - filled)

    return f"""
## Lead Score: {score_val}/100 — Grade {grade}

**Score Bar:** [{bar}] {score_val}%

**Recommended Action:** {score.get('recommended_action', 'N/A')}

**Score Breakdown:**
- Growth & Size: {score.get('growth_score', 0)}/25
- Funding & Revenue: {score.get('funding_score', 0)}/25
- Recent Activity: {score.get('activity_score', 0)}/25
- Pain Points Alignment: {score.get('pain_points_score', 0)}/25

**Reasoning:**
{score.get('reasoning', 'No reasoning available.')}

**Top Signals:**
{chr(10).join(f"• {s}" for s in score.get('top_signals', []))}

**Risk Factors:**
{chr(10).join(f"• {r}" for r in score.get('risk_factors', []))}
"""


def format_email_meta(email: dict) -> str:
    """Formats email metadata (everything but the body) into markdown."""
    if not email:
        return "Email draft will appear here..."

    return f"""
## ✉️ Personalized Cold Email

**Subject:** {email.get('subject', 'N/A')}

**Estimated Reply Rate:** {email.get('estimated_reply_rate', 'N/A')} &nbsp;|&nbsp; **Word Count:** {email.get('word_count', 'N/A')}

**Opening Hook:** {email.get('opening_hook', 'N/A')}
**Pain Point Addressed:** {email.get('pain_point_addressed', 'N/A')}
**CTA:** {email.get('cta', 'N/A')}
"""


def email_body_text(email: dict) -> str:
    """Plain text for the copy-to-clipboard textbox: subject + body."""
    if not email:
        return ""
    subject = email.get("subject", "")
    body = (email.get("body", "") or "").replace("\\n", "\n")
    return f"Subject: {subject}\n\n{body}" if subject else body


def build_report_markdown(company: str, result: dict) -> str:
    """Builds the full downloadable markdown report for one company."""
    parts = [
        f"# Sales Intelligence Report — {company}",
        format_research(result.get("research")),
        "---",
        format_lead_score_markdown(result.get("lead_score")),
        "---",
        "## Email Draft",
        email_body_text(result.get("email_draft")) or "No email draft available.",
    ]
    return "\n\n".join(parts)


def history_choices(history: dict) -> list:
    """Most-recently-researched company first."""
    return list(reversed(history.keys()))


# ---------------------------------------------------------------------------
# History persistence — survives app restarts and page refreshes.
# ---------------------------------------------------------------------------
HISTORY_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "history_cache.json"
)


def _load_history_cache() -> dict:
    try:
        with open(HISTORY_CACHE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_history_cache(history: dict) -> None:
    # A disk hiccup must never kill a pipeline run — warn and move on.
    try:
        with open(HISTORY_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except (OSError, TypeError) as e:
        print(f"[warn] Could not save history cache: {e}", file=sys.stderr)


def init_history():
    """Runs on every page load: rehydrates the history dict (and the
    dropdown choices) from the on-disk cache. value=None is explicit so
    Gradio doesn't auto-select the first choice — that would fire the
    dropdown's change event and load a report onto a fresh page."""
    history = _load_history_cache()
    return history, gr.update(choices=history_choices(history), value=None)


# 10 no-op updates — appended after the streamed activity log to fill the
# remaining outputs of the 11-component `run_outputs` list.
NO_CHANGE_10 = tuple(gr.update() for _ in range(10))


def _validation_error(message: str, history: dict):
    return (
        [{"role": "assistant", "content": message}],
        gr.update(), gr.update(), gr.update(), gr.update(),
        status_banner(esc(message), "error"),
        gr.update(), gr.update(), gr.update(), gr.update(),
        history,
    )


async def run_pipeline_ui(company_name: str, history: dict):
    """
    Main function called by Gradio UI.
    Streams the ADK Runner's events live into the "Agent Activity" chat log
    while the pipeline runs, then fills in the Research / Lead Score / Email
    tabs once the orchestrator's structured result is ready. Also caches the
    raw result in `history` (a gr.State dict) so it can be reloaded instantly
    later, and unlocks the report download button.

    Args:
        company_name: Company name entered by user.
        history: {company_name: raw_result} cache from previous runs this session.

    Yields:
        tuple: (activity_log, research_md, score_html, email_meta_md,
                email_body, status_html, run_button_update,
                download_button_update, history_dropdown_update,
                current_company, history)
    """
    if not company_name or not company_name.strip():
        yield _validation_error("⚠️ Please enter a company name.", history)
        return

    company_name = company_name.strip()

    if len(company_name) < 2:
        yield _validation_error("⚠️ Company name too short.", history)
        return

    if len(company_name) > 100:
        yield _validation_error("⚠️ Company name too long (max 100 characters).", history)
        return

    activity_log = [
        {"role": "assistant", "content": f"🔍 Starting sales intelligence pipeline for **{company_name}**..."}
    ]
    yield (
        activity_log,
        "⏳ Waiting for research to complete...",
        format_lead_score_html(None),
        "⏳ Waiting for email draft to complete...",
        "",
        status_banner(f"Running pipeline for <b style='color:inherit;'>{esc(company_name)}</b>…", "running"),
        gr.update(interactive=False),
        gr.update(interactive=False),
        gr.update(),
        company_name,
        history,
    )

    try:
        result = None
        async for update in stream_pipeline(company_name):
            if update["type"] == "step":
                activity_log.append({"role": "assistant", "content": update["text"]})
                yield (activity_log,) + NO_CHANGE_10
            else:
                result = update["data"]

        research_output = format_research(result.get("research"))
        score_output = format_lead_score_html(result.get("lead_score"))
        email_output = format_email_meta(result.get("email_draft"))
        email_body = email_body_text(result.get("email_draft"))

        errors = result.get("errors", [])
        crm_logged = result.get("crm_logged", False)
        lead_score = result.get("lead_score") or {}
        score = lead_score.get("score", "N/A")
        grade = lead_score.get("grade", "N/A")

        if errors:
            status = status_banner(
                "Completed with " + str(len(errors)) + " warning(s): " + "; ".join(esc(e) for e in errors),
                "error",
            )
        else:
            status = status_banner(
                f"Pipeline complete for <b style='color:inherit;'>{esc(company_name)}</b> — Lead Score {esc(str(score))}/100 "
                f"(Grade {esc(str(grade))}) &middot; CRM {'logged ✅' if crm_logged else 'skipped (no Sheet ID)'}",
                "success",
            )

        activity_log.append({"role": "assistant", "content": "🎯 Pipeline complete."})

        history = dict(history)
        history.pop(company_name, None)
        history[company_name] = result
        _save_history_cache(history)

        yield (
            activity_log,
            research_output,
            score_output,
            email_output,
            email_body,
            status,
            gr.update(interactive=True),
            gr.update(interactive=True, value=None),
            gr.update(choices=history_choices(history), value=company_name),
            company_name,
            history,
        )

    except Exception as e:
        error_msg = f"❌ Pipeline failed: {esc(str(e))}"
        activity_log.append({"role": "assistant", "content": error_msg})
        yield (
            activity_log,
            gr.update(), gr.update(), gr.update(), gr.update(),
            status_banner(error_msg, "error"),
            gr.update(interactive=True),
            gr.update(interactive=False),
            gr.update(),
            gr.update(),
            history,
        )


def load_from_history(company: str, history: dict):
    """Reloads a cached report into the tabs without re-running the pipeline."""
    if not company or company not in history:
        return gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update()

    result = history[company]
    status = status_banner(f"📂 Loaded cached report for <b style='color:inherit;'>{esc(company)}</b> — no re-run needed.", "history")
    return (
        format_research(result.get("research")),
        format_lead_score_html(result.get("lead_score")),
        format_email_meta(result.get("email_draft")),
        email_body_text(result.get("email_draft")),
        status,
        gr.update(interactive=True, value=None),
        company,
    )


def export_report(company: str, history: dict):
    """Writes the currently-loaded company's report to a temp .md file for download."""
    if not company or company not in history:
        return gr.update()

    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", company).strip("_") or "company"
    path = os.path.join(tempfile.gettempdir(), f"sales_report_{safe_name}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(build_report_markdown(company, history[company]))
    return path


def clear_all(history: dict):
    """Resets the input form and outputs without touching the session history cache."""
    return (
        "",
        [],
        "Research results will appear here...",
        format_lead_score_html(None),
        "Email draft will appear here...",
        "",
        status_banner("👆 Enter a company name and click Run Pipeline", "idle"),
        gr.update(value=None),
        gr.update(interactive=False, value=None),
        "",
    )


# Build Gradio UI
with gr.Blocks(title="AI Sales Intelligence Agent") as demo:

    history_state = gr.State({})
    current_company_state = gr.State("")

    gr.HTML(HEADER_HTML)

    # Input row
    with gr.Row():
        company_input = gr.Textbox(
            label="Company Name",
            placeholder="e.g. Stripe, OpenAI, Notion, Figma...",
            scale=4,
        )
        run_button = gr.Button("🚀 Run Pipeline", variant="primary", scale=1)
        clear_button = gr.Button("🔄 Clear", variant="secondary", scale=1)

    # History + export row
    with gr.Row():
        history_dropdown = gr.Dropdown(
            label="📜 Previously researched (select to reload instantly)",
            choices=[],
            value=None,
            interactive=True,
            scale=4,
        )
        download_button = gr.DownloadButton("⬇️ Download Report", scale=1, interactive=False)

    # Status bar
    status_output = gr.HTML(value=status_banner("👆 Enter a company name and click Run Pipeline", "idle"))

    # Live agent activity log — shows tool calls / tool responses as the
    # ADK orchestrator emits them in real time.
    with gr.Accordion("🧠 Agent Activity (live)", open=True):
        activity_output = gr.Chatbot(
            label="Agent Steps",
            height=220,
        )

    # Output tabs
    with gr.Tabs():
        with gr.Tab("🔍 Research"):
            research_output = gr.Markdown(
                value="Research results will appear here..."
            )

        with gr.Tab("📊 Lead Score"):
            score_output = gr.HTML(
                value=format_lead_score_html(None)
            )

        with gr.Tab("✉️ Email Draft"):
            email_output = gr.Markdown(
                value="Email draft will appear here..."
            )
            email_body_box = gr.Textbox(
                label="📋 Ready-to-send email (click the copy icon)",
                lines=12,
                interactive=False,
                buttons=["copy"],
            )

    # Examples
    gr.Examples(
        examples=[
            ["Stripe"],
            ["OpenAI"],
            ["Notion"],
            ["Figma"],
            ["HubSpot"]
        ],
        inputs=company_input,
        label="Try these examples"
    )

    # Footer
    gr.Markdown("""
    ---
    **How it works (Google ADK multi-agent architecture):**
    1. 🧠 **Orchestrator Agent** — root LlmAgent that delegates to specialists via `AgentTool`
    2. 🔍 **Research Agent** — searches the web for company intelligence
    3. 📊 **Lead Scorer Agent** — scores the lead 1-100 with reasoning
    4. ✉️ **Email Drafter Agent** — writes a personalized cold email
    5. 🗂️ **CRM Logger Agent** — logs everything to Google Sheets

    Each agent shares data through ADK session state — no manual JSON plumbing.
    Built with Google ADK 2.3.0 • MCP Server • Gemini 2.5 • Gradio
    """)

    run_outputs = [
        activity_output,
        research_output,
        score_output,
        email_output,
        email_body_box,
        status_output,
        run_button,
        download_button,
        history_dropdown,
        current_company_state,
        history_state,
    ]

    # Wire up the button
    run_button.click(
        fn=run_pipeline_ui,
        inputs=[company_input, history_state],
        outputs=run_outputs,
    )

    # Also trigger on Enter key
    company_input.submit(
        fn=run_pipeline_ui,
        inputs=[company_input, history_state],
        outputs=run_outputs,
    )

    history_dropdown.change(
        fn=load_from_history,
        inputs=[history_dropdown, history_state],
        outputs=[
            research_output,
            score_output,
            email_output,
            email_body_box,
            status_output,
            download_button,
            current_company_state,
        ],
    )

    download_button.click(
        fn=export_report,
        inputs=[current_company_state, history_state],
        outputs=[download_button],
    )

    # Rehydrate history from disk on every page load / refresh.
    demo.load(
        fn=init_history,
        outputs=[history_state, history_dropdown],
    )

    clear_button.click(
        fn=clear_all,
        inputs=[history_state],
        outputs=[
            company_input,
            activity_output,
            research_output,
            score_output,
            email_output,
            email_body_box,
            status_output,
            history_dropdown,
            download_button,
            current_company_state,
        ],
    )


if __name__ == "__main__":
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        show_error=True,
        theme=THEME,
        css=CUSTOM_CSS,
    )
