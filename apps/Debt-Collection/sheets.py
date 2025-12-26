"""Google Sheets sync helpers."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict

from flask import current_app

try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
except Exception:  # pragma: no cover - optional dependency during local dev
    service_account = None  # type: ignore
    build = None  # type: ignore

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

def _get_credentials(credentials_path: str):
    if not service_account:
        raise RuntimeError("google-api-python-client is not installed")
    return service_account.Credentials.from_service_account_file(
        credentials_path, scopes=SCOPES
    )


def append_ledger_row(entry: Dict[str, Any]) -> None:
    """Append the provided entry to the configured Google Sheet."""
    sheet_id = current_app.config.get("GOOGLE_SHEET_ID")
    credentials_file = current_app.config.get("GOOGLE_SERVICE_ACCOUNT_FILE")

    if not sheet_id or not credentials_file:
        current_app.logger.info("Google Sheets not configured; skipping sync")
        return

    if not os.path.exists(credentials_file):
        current_app.logger.warning("Service account file %s not found", credentials_file)
        return

    try:
        credentials = _get_credentials(credentials_file)
        service = build("sheets", "v4", credentials=credentials)
        entry_type = (entry.get("type") or "").lower()
        if entry_type == "transaction":
            values = [
                [
                    entry["date"],
                    entry.get("description", ""),
                    entry["amount"],
                    entry.get("payment_method", ""),
                ]
            ]
            target_range = "Transactions!A:D"
        elif entry_type == "payment":
            values = [
                [
                    entry["date"],
                    entry["amount"],
                    entry.get("payment_method", ""),
                ]
            ]
            target_range = "Payments!A:C"
        else:
            values = [
                [
                    entry["date"],
                    entry.get("description", ""),
                    entry["amount"],
                    entry.get("payment_method", ""),
                ]
            ]
            target_range = "Sheet1!A:D"
        body = {"values": values}
        service.spreadsheets().values().append(
            spreadsheetId=sheet_id,
            range=target_range,
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body=body,
        ).execute()
    except Exception as exc:  # pragma: no cover - network/credentials errors
        logging.getLogger(__name__).exception("Failed to append to Google Sheets: %s", exc)
