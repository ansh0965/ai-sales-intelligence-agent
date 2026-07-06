# email_skill.py
# Reusable ADK tool skill — final email packaging and validation.
#
# ADK ARCHITECTURE NOTE:
# Writing persuasive, personalized copy is a creative task the LLM should
# own. What this tool owns is the deterministic bookkeeping the model tends
# to get wrong if asked to "self-report" it in the same JSON blob — exact
# word count and the under-150-words rule check. The agent's instruction
# tells it to draft the copy itself, then call this tool with the drafted
# pieces to get the final packaged, validated record.


def package_email_draft(
    subject: str,
    body: str,
    opening_hook: str,
    pain_point_addressed: str,
    cta: str,
    estimated_reply_rate: str,
) -> dict:
    """Packages a drafted cold outreach email into a final structured
    record, computing an exact word count. Call this AFTER you have written
    the subject, body, opening hook, pain point, and CTA yourself.

    Args:
        subject: The email subject line.
        body: The full email body text, with line breaks written as \\n.
        opening_hook: The specific fact referenced in the opening line.
        pain_point_addressed: The pain point targeted by the email.
        cta: The call-to-action used in the email.
        estimated_reply_rate: Predicted reply likelihood — High, Medium, or Low.

    Returns:
        dict with 'status', the packaged email fields, and a computed
        'word_count' plus 'within_length_limit' (<= 150 words) flag.
    """
    try:
        word_count = len(body.split())
        return {
            "status": "success",
            "subject": subject,
            "body": body,
            "opening_hook": opening_hook,
            "pain_point_addressed": pain_point_addressed,
            "cta": cta,
            "estimated_reply_rate": estimated_reply_rate,
            "word_count": word_count,
            "within_length_limit": word_count <= 150,
        }
    except AttributeError as e:
        return {"status": "error", "error_message": str(e)}
