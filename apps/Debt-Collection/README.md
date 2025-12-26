# Debt Tracker

A lightweight Flask + SQLite application that records money you spend on behalf of a single friend, logs their repayments, keeps the running total, and mirrors every entry to Google Sheets so the debtor can see a read-only ledger.

## Features

- Track transactions (debts) and payments independently
- Automatic running balance for the single configured person
- Minimal login (optional) secured via an environment password
- REST endpoints used by the dashboard (and available for automations)
- Google Sheets sync with running balance per row
- Simple responsive UI with live table + balance updates
- Delete mistaken entries directly from the dashboard

## Requirements

- Python 3.10+
- Google Cloud service account with access to the target Sheet
- SQLite (bundled with Python)

Install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuration

Copy `.env.example` to `.env` and update the values:

```
SECRET_KEY=super-secret-key
DATABASE_PATH=instance/debts.db
GOOGLE_SERVICE_ACCOUNT_FILE=/absolute/path/to/service-account.json
GOOGLE_SHEET_ID=google-sheet-id
ADMIN_PASSWORD=optional-dashboard-password
PERSON_NAME=YourFriendName
```

- `GOOGLE_SERVICE_ACCOUNT_FILE`: JSON file you download from Google Cloud for the service account. Share the Google Sheet with the service account email.
- `GOOGLE_SHEET_ID`: The ID found in the Sheet URL (`https://docs.google.com/spreadsheets/d/<SHEET_ID>/edit`).
- `ADMIN_PASSWORD`: When set, enables a simple session-based login. Leave empty to disable auth.
- `DATABASE_PATH`: Use the default (`instance/debts.db`) or point to another writable file.
- `PERSON_NAME`: The single individual (e.g., “Alex”) whose balance is being tracked. Every transaction/payment is tied to this name.

## Database Initialization

The app automatically ensures tables exist on startup. To manually bootstrap (optional):

```bash
flask --app app.py shell <<'PY'
from models import init_db
init_db()
PY
```

The schema is also available in `schema.sql`.

## Google Sheets Setup

1. Create a Google Cloud project and enable the **Google Sheets API**.
2. Create a service account and download its JSON key.
3. Share the target Google Sheet with the service account email (Viewer access is enough for appending rows).
4. Put the JSON path into `GOOGLE_SERVICE_ACCOUNT_FILE` and sheet ID into `GOOGLE_SHEET_ID`.

Each sync writes to separate tabs named **Transactions** and **Payments**. Create those sheets (or rename existing ones) in your Google Sheet.

- Transactions tab columns: Date, Description, Amount (recorded as negative in-app), Payment Method.
- Payments tab columns: Date, Amount (positive), Payment Method.

## Running the App

```bash
export $(grep -v '^#' .env | xargs)  # or use a dotenv loader
flask --app app.py run --debug
```

The dashboard lives at `http://127.0.0.1:5000/`.

## REST Endpoints

| Method | Endpoint | Description |
| --- | --- | --- |
| `POST` | `/api/transactions` | Add a new transaction you paid on behalf of the configured person |
| `POST` | `/api/payments` | Log a repayment |
| `GET` | `/api/records` | All records + current balance |
| `GET` | `/api/summary` | Current running balance only |
| `DELETE` | `/api/records/<transaction|payment>/<id>` | Remove an incorrect entry |

All POST payloads accept JSON matching the form fields (see `static/app.js` for an example). Responses return JSON messages and IDs. Requests require authentication if `ADMIN_PASSWORD` is set.

## Project Structure

```
app.py              # Flask factory + configuration loading
models.py           # SQLite helpers and queries
routes.py           # UI + API routes
sheets.py           # Google Sheets integration
templates/          # HTML templates
static/             # CSS + JavaScript
schema.sql          # Reference schema
```

## Deployment Notes

- Use `gunicorn 'app:create_app()'` or another WSGI server in production.
- Store service account credentials securely (e.g., as a secret file or secret manager).
- Require HTTPS and a strong `SECRET_KEY` if exposing publicly.
