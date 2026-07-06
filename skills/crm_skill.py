# crm_skill.py
# Reusable ADK tool skill — CRM (Google Sheets) logging.
#
# ADK ARCHITECTURE NOTE:
# This tool takes flat, individually-typed arguments (not one nested dict)
# because LLMs reliably fill in flat function-call arguments extracted from
# text/state, but are far less reliable at re-serializing a large nested
# JSON object exactly as an argument value. Internally it reassembles the
# shape tools/sheets_logger.py expects and delegates all Sheets API work to
# that unmodified module.

from tools.sheets_logger import log_sales_intelligence


def log_to_crm(
    company_name: str,
    industry: str,
    employee_count: str,
    funding: str,
    lead_score: int,
    lead_grade: str,
    recommended_action: str,
    top_signals: str,
    email_subject: str,
    estimated_reply_rate: str,
) -> dict:
    """Logs a completed sales intelligence record for a company to the
    Google Sheets CRM. Call this as the final step, after research, lead
    scoring, and email drafting are all done.

    Args:
        company_name: Name of the company.
        industry: The company's industry.
        employee_count: Approximate employee count.
        funding: Total funding raised.
        lead_score: Numeric lead score from 1-100.
        lead_grade: Letter grade — A, B, C, or D.
        recommended_action: Recommended sales action.
        top_signals: Comma-separated top buying signals.
        email_subject: Subject line of the drafted outreach email.
        estimated_reply_rate: Predicted reply likelihood — High, Medium, or Low.

    Returns:
        dict with 'status' ('success', 'skipped', or 'error') and a
        'logged' boolean.
    """
    pipeline_result = {
        "company": company_name,
        "research": {
            "company_name": company_name,
            "industry": industry,
            "employee_count": employee_count,
            "funding": funding,
        },
        "lead_score": {
            "score": lead_score,
            "grade": lead_grade,
            "recommended_action": recommended_action,
            "top_signals": [s.strip() for s in top_signals.split(",") if s.strip()],
        },
        "email_draft": {
            "subject": email_subject,
            "estimated_reply_rate": estimated_reply_rate,
        },
        "errors": [],
    }

    try:
        logged = log_sales_intelligence(pipeline_result)
        return {"status": "success" if logged else "skipped", "logged": bool(logged)}
    except Exception as e:
        return {"status": "error", "logged": False, "error_message": str(e)}
