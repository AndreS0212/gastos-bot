"""
Google Sheets sync module for GastosBot.
Syncs transactions to a Google Sheet automatically.
"""

import os
import json
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

_client = None
_sheet = None

def _get_client():
    global _client
    if _client:
        return _client

    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")
    creds_file = os.environ.get("GOOGLE_CREDENTIALS_FILE", "")

    if creds_json:
        try:
            info = json.loads(creds_json)
            creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        except json.JSONDecodeError as e:
            print(f"Error parsing GOOGLE_CREDENTIALS_JSON: {e}")
            print(f"First 100 chars of JSON: {creds_json[:100]}")
            print("Make sure the JSON uses double quotes, not single quotes.")
            print("Example format: {\"type\": \"service_account\", \"project_id\": \"...\", ...}")
            return None
    elif creds_file and os.path.exists(creds_file):
        creds = Credentials.from_service_account_file(creds_file, scopes=SCOPES)
    else:
        return None

    _client = gspread.authorize(creds)
    return _client


def _get_sheet():
    global _sheet
    if _sheet:
        return _sheet

    client = _get_client()
    if not client:
        print("❌ Could not get Google Sheets client")
        return None

    sheet_id = os.environ.get("GOOGLE_SHEETS_ID", "")
    if not sheet_id:
        print("❌ GOOGLE_SHEETS_ID not configured")
        return None

    try:
        print(f"📊 Opening spreadsheet with ID: {sheet_id}")
        spreadsheet = client.open_by_key(sheet_id)
        # Try to get "Registro" sheet, or first sheet
        try:
            _sheet = spreadsheet.worksheet("Registro")
            print("✅ Found 'Registro' worksheet")
        except gspread.exceptions.WorksheetNotFound:
            _sheet = spreadsheet.sheet1
            print("✅ Using first worksheet")
        return _sheet
    except Exception as e:
        print(f"❌ Google Sheets error: {e}")
        return None


def is_enabled():
    return bool(os.environ.get("GOOGLE_SHEETS_ID")) and bool(
        os.environ.get("GOOGLE_CREDENTIALS_JSON") or os.environ.get("GOOGLE_CREDENTIALS_FILE")
    )


def setup_sheet_headers():
    """Create headers in the sheet if empty."""
    sheet = _get_sheet()
    if not sheet:
        return False

    try:
        first_cell = sheet.acell("A1").value
        if not first_cell:
            headers = ["Fecha", "Tipo", "Categoría", "Descripción", "Monto", "Método de Pago", "Hora"]
            sheet.update("A1:G1", [headers])
            # Format header row
            sheet.format("A1:G1", {
                "backgroundColor": {"red": 0.106, "green": 0.165, "blue": 0.29},
                "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
                "horizontalAlignment": "CENTER"
            })
        return True
    except Exception as e:
        print(f"❌ Sheet setup error: {e}")
        return False


def sync_transaction(tx_type, category, amount, description="", payment_method="Efectivo"):
    """Append a transaction row to Google Sheet."""
    print(f"📝 Attempting to sync transaction: {tx_type}, {category}, {amount}")
    sheet = _get_sheet()
    if not sheet:
        print("❌ Could not get sheet object")
        return False

    try:
        now = datetime.now()
        row = [
            now.strftime("%d/%m/%Y"),
            "Gasto" if tx_type == "gasto" else "Ingreso",
            category,
            description or "",
            amount,
            payment_method,
            now.strftime("%H:%M"),
        ]
        sheet.append_row(row, value_input_option="USER_ENTERED")
        print(f"✅ Transaction synced to Google Sheets: {row}")
        return True
    except Exception as e:
        print(f"❌ Sync error: {e}")
        # Reset sheet cache in case of auth issues
        global _sheet
        _sheet = None
        return False


def sync_delete_last():
    """Delete the last row from the sheet."""
    sheet = _get_sheet()
    if not sheet:
        return False

    try:
        all_rows = sheet.get_all_values()
        if len(all_rows) > 1:  # More than just headers
            sheet.delete_rows(len(all_rows))
        return True
    except Exception as e:
        print(f"❌ Delete sync error: {e}")
        return False


def get_row_count():
    """Get number of data rows."""
    sheet = _get_sheet()
    if not sheet:
        return 0
    try:
        return len(sheet.get_all_values()) - 1  # Minus header
    except:
        return 0
