# seed_history_from_crm.py
# One-off utility: rebuilds ui/history_cache.json from rows already logged
# to the Google Sheets CRM, so the UI's history dropdown has entries without
# re-running the pipeline (i.e. without spending any Gemini/Serper quota).
#
# The sheet contains two row layouts (an older 16-column logger and the
# current 12-column one appended under the same 16-column header), so rows
# are parsed positionally with layout detection instead of by header name.
# For each company the richest row wins (most non-empty fields), ties going
# to the newer row. Entries written by a real pipeline run are never
# overwritten here.
#
# Usage (from the project root):
#   python scripts/seed_history_from_crm.py

import json
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from tools.sheets_logger import get_authenticated_client

load_dotenv(override=True)

CACHE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "ui",
    "history_cache.json",
)


def _intlike(value) -> bool:
    try:
        int(str(value).strip())
        return True
    except ValueError:
        return False


def _split_list(value) -> list:
    return [s.strip() for s in str(value).split(",") if s.strip()]


def parse_row(cells: list) -> dict | None:
    """Detects which logger version wrote the row and maps it to the
    pipeline-result shape the UI renders. Returns None if unparseable."""
    cells = list(cells) + [""] * 16

    if _intlike(cells[7]):
        # Legacy 16-column layout: Timestamp, Company Name, Industry,
        # Description, Employee Count, Revenue, Funding, Lead Score,
        # Lead Grade, Recommended Action, Top Signals, Pain Points,
        # Email Subject, Email Body, Estimated Reply Rate, Errors
        return {
            "company": cells[1],
            "research": {
                "company_name": cells[1],
                "industry": cells[2],
                "description": cells[3],
                "employee_count": cells[4],
                "revenue": cells[5],
                "funding": cells[6],
                "pain_points": _split_list(cells[11]),
            },
            "lead_score": {
                "score": int(cells[7]),
                "grade": cells[8],
                "recommended_action": cells[9],
                "top_signals": _split_list(cells[10]),
            },
            "email_draft": {
                "subject": cells[12],
                "body": cells[13],
                "estimated_reply_rate": cells[14],
            },
            "errors": [],
            "crm_logged": True,
            "seeded_from_crm": True,
        }

    if _intlike(cells[5]):
        # Current 12-column layout: Timestamp, Company, Industry,
        # Employee Count, Funding, Lead Score, Lead Grade, Action,
        # Top Signals, Email Subject, Reply Rate, Errors
        return {
            "company": cells[1],
            "research": {
                "company_name": cells[1],
                "industry": cells[2],
                "employee_count": cells[3],
                "funding": cells[4],
            },
            "lead_score": {
                "score": int(cells[5]),
                "grade": cells[6],
                "recommended_action": cells[7],
                "top_signals": _split_list(cells[8]),
            },
            "email_draft": {
                "subject": cells[9],
                "estimated_reply_rate": cells[10],
            },
            "errors": [],
            "crm_logged": True,
            "seeded_from_crm": True,
        }

    return None


def _richness(result: dict) -> int:
    """Counts non-empty leaf values so the fullest row per company wins."""
    count = 0
    for section in ("research", "lead_score", "email_draft"):
        for value in result.get(section, {}).values():
            if value not in ("", None, []):
                count += 1
    return count


def main() -> None:
    sheet_id = os.getenv("GOOGLE_SHEETS_ID")
    if not sheet_id:
        sys.exit("GOOGLE_SHEETS_ID is not set in .env")

    client = get_authenticated_client()
    worksheet = client.open_by_key(sheet_id).worksheet("Sales Intelligence")
    rows = worksheet.get_all_values()[1:]  # skip header row

    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            cache = json.load(f)
    except (OSError, ValueError):
        cache = {}

    best: dict[str, dict] = {}
    for cells in rows:
        result = parse_row(cells)
        if not result:
            continue
        company = str(result["company"]).strip()
        if not company:
            continue
        # >= so a newer row of equal richness replaces an older one
        if company not in best or _richness(result) >= _richness(best[company]):
            best[company] = result

    seeded = []
    for company, result in best.items():
        existing = cache.get(company)
        if existing and not existing.get("seeded_from_crm"):
            continue  # keep the richer full-pipeline entry
        cache[company] = result
        seeded.append(f"{company} (score {result['lead_score']['score']}, {_richness(result)} fields)")

    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

    print(f"Seeded {len(seeded)} companies into {CACHE_PATH}:")
    for line in seeded:
        print(f"  - {line}")


if __name__ == "__main__":
    main()
