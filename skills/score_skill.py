# score_skill.py
# Reusable ADK tool skill — deterministic lead score combination.
#
# ADK ARCHITECTURE NOTE:
# Scoring which SIGNALS matter (growth, funding, activity, pain points) is a
# reasoning task best left to the LLM, which reads the research data and
# estimates each 0-25 sub-score itself. What should NOT be left to the LLM is
# arithmetic and bounds-checking (clamping, integer coercion, grade
# thresholds) — LLMs are unreliable at exact math. This tool does that
# deterministic part; the agent's instruction tells it to call this tool
# with its own sub-score estimates and use the tool's validated output.


def calculate_lead_score(
    growth_score: int,
    funding_score: int,
    activity_score: int,
    pain_points_score: int,
) -> dict:
    """Combines four 0-25 point sub-scores into a validated total lead score
    (1-100), letter grade, and recommended sales action. Call this only
    AFTER estimating each sub-score yourself from the company research.

    Args:
        growth_score: Score 0-25 for company growth and size signals.
        funding_score: Score 0-25 for funding and revenue signals.
        activity_score: Score 0-25 for recent news and market momentum.
        pain_points_score: Score 0-25 for how well pain points align with
            our AI sales intelligence product.

    Returns:
        dict with 'status', validated 'score' (1-100), 'grade' (A/B/C/D),
        the clamped sub-scores, and 'recommended_action'.
    """
    try:
        raw = [growth_score, funding_score, activity_score, pain_points_score]
        clamped = [max(0, min(25, int(s))) for s in raw]
        total = max(1, min(100, sum(clamped)))

        if total >= 80:
            grade, action = "A", "Prioritize"
        elif total >= 60:
            grade, action = "B", "Nurture"
        elif total >= 40:
            grade, action = "C", "Nurture"
        else:
            grade, action = "D", "Low Priority"

        return {
            "status": "success",
            "score": total,
            "grade": grade,
            "growth_score": clamped[0],
            "funding_score": clamped[1],
            "activity_score": clamped[2],
            "pain_points_score": clamped[3],
            "recommended_action": action,
        }
    except (ValueError, TypeError) as e:
        return {"status": "error", "error_message": str(e)}
