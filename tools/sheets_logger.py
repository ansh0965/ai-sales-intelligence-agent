# sheets_logger.py
# Reusable Google Sheets logging tool
# Can be called by any agent that needs to log data
# Handles authentication, sheet creation, and data writing

import os
import sys
import json
from datetime import datetime
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials

# Load environment variables
load_dotenv(override=True)

# Google Sheets API scopes needed
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]


def get_authenticated_client():
    """
    Returns an authenticated gspread client.
    Uses service account credentials from file path in .env
    
    Returns:
        gspread.Client: Authenticated client
    """
    
    # Security: load credentials path from env — never hardcode
    creds_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")
    
    if not os.path.exists(creds_path):
        raise FileNotFoundError(
            f"Credentials file not found: {creds_path}\n"
            "Download it from Google Cloud Console and set "
            "GOOGLE_CREDENTIALS_PATH in your .env file"
        )
    
    creds = Credentials.from_service_account_file(
        creds_path,
        scopes=SCOPES
    )
    
    return gspread.authorize(creds)


def get_or_create_worksheet(
    spreadsheet_id: str,
    sheet_name: str,
    headers: list
):
    """
    Gets existing worksheet or creates a new one with headers.
    
    Args:
        spreadsheet_id: Google Sheets ID from URL
        sheet_name: Name of the tab/worksheet
        headers: List of column headers
        
    Returns:
        gspread.Worksheet: The worksheet object
    """
    
    # Validate inputs
    if not spreadsheet_id:
        raise ValueError("spreadsheet_id is required")
    
    if not sheet_name:
        raise ValueError("sheet_name is required")
    
    client = get_authenticated_client()
    spreadsheet = client.open_by_key(spreadsheet_id)
    
    # Try to get existing worksheet
    # Logs go to stderr so they never pollute the MCP stdio protocol channel
    # when this tool runs inside the MCP server process.
    try:
        worksheet = spreadsheet.worksheet(sheet_name)
        print(f"   [ok] Found existing worksheet: {sheet_name}", file=sys.stderr)

    except gspread.WorksheetNotFound:
        # Create new worksheet
        worksheet = spreadsheet.add_worksheet(
            title=sheet_name,
            rows=1000,
            cols=len(headers) + 5
        )
        print(f"   [ok] Created new worksheet: {sheet_name}", file=sys.stderr)

        # Add headers to first row
        worksheet.append_row(headers)
        print(f"   [ok] Headers added: {len(headers)} columns", file=sys.stderr)
    
    return worksheet


def append_row(
    spreadsheet_id: str,
    sheet_name: str,
    data: dict,
    headers: list
):
    """
    Appends a single row of data to a Google Sheet.
    Maps dict keys to header columns automatically.
    
    Args:
        spreadsheet_id: Google Sheets ID
        sheet_name: Name of worksheet tab
        data: Dictionary of data to log
        headers: List of column headers (defines column order)
        
    Returns:
        bool: True if successful
    """
    
    # Validate inputs
    if not isinstance(data, dict):
        raise TypeError("data must be a dictionary")
    
    if not headers:
        raise ValueError("headers list cannot be empty")
    
    # Get or create worksheet
    worksheet = get_or_create_worksheet(
        spreadsheet_id,
        sheet_name,
        headers
    )
    
    # Build row in correct column order
    row = []
    for header in headers:
        value = data.get(header, "")
        
        # Convert lists and dicts to strings
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value)
        elif isinstance(value, dict):
            value = json.dumps(value)
        elif value is None:
            value = ""
        
        # Truncate very long strings
        value = str(value)
        if len(value) > 500:
            value = value[:497] + "..."
        
        row.append(value)
    
    # Append to sheet
    worksheet.append_row(row)
    
    return True


def log_sales_intelligence(pipeline_result: dict) -> bool:
    """
    High-level function specifically for logging sales intelligence results.
    Called by CRM logger agent.
    
    Args:
        pipeline_result: Complete orchestrator result dict
        
    Returns:
        bool: True if logged successfully
    """
    
    sheet_id = os.getenv("GOOGLE_SHEETS_ID")
    
    if not sheet_id:
        print("   [skip] GOOGLE_SHEETS_ID not set in .env - skipping log", file=sys.stderr)
        return False
    
    # Headers must match the existing "Sales Intelligence" worksheet's first
    # row exactly — rows are appended positionally, so a shorter/reordered
    # list silently lands values under the wrong columns.
    headers = [
        "Timestamp",
        "Company Name",
        "Industry",
        "Description",
        "Employee Count",
        "Revenue",
        "Funding",
        "Lead Score",
        "Lead Grade",
        "Recommended Action",
        "Top Signals",
        "Pain Points",
        "Email Subject",
        "Email Body",
        "Estimated Reply Rate",
        "Errors"
    ]

    # Extract and flatten data
    research = pipeline_result.get("research") or {}
    score = pipeline_result.get("lead_score") or {}
    email = pipeline_result.get("email_draft") or {}
    errors = pipeline_result.get("errors") or []

    data = {
        "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Company Name": research.get("company_name", pipeline_result.get("company", "")),
        "Industry": research.get("industry", ""),
        "Description": research.get("description", ""),
        "Employee Count": research.get("employee_count", ""),
        "Revenue": research.get("revenue", ""),
        "Funding": research.get("funding", ""),
        "Lead Score": score.get("score", ""),
        "Lead Grade": score.get("grade", ""),
        "Recommended Action": score.get("recommended_action", ""),
        "Top Signals": score.get("top_signals", []),
        "Pain Points": research.get("pain_points", []),
        "Email Subject": email.get("subject", ""),
        "Email Body": email.get("body", ""),
        "Estimated Reply Rate": email.get("estimated_reply_rate", ""),
        "Errors": errors
    }
    
    try:
        append_row(sheet_id, "Sales Intelligence", data, headers)
        print("   [ok] Logged to Google Sheets successfully", file=sys.stderr)
        return True

    except FileNotFoundError as e:
        print(f"   [warn] {str(e)}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"   [warn] Sheets logging failed: {str(e)}", file=sys.stderr)
        return False


if __name__ == "__main__":
    # Quick test
    print("Testing sheets logger...")
    print("Note: Requires valid credentials.json and GOOGLE_SHEETS_ID")
    
    mock_result = {
        "company": "Stripe",
        "research": {
            "company_name": "Stripe",
            "industry": "Fintech",
            "employee_count": "8000+",
            "funding": "$2.2B"
        },
        "lead_score": {
            "score": 87,
            "grade": "A",
            "recommended_action": "Prioritize",
            "top_signals": ["AI launch", "Series I"]
        },
        "email_draft": {
            "subject": "Your AI expansion",
            "estimated_reply_rate": "High"
        },
        "errors": []
    }
    
    result = log_sales_intelligence(mock_result)
    print(f"\n✅ Test result: {result}")