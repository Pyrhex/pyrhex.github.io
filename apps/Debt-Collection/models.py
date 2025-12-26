"""SQLite data access helpers for the debt tracking app."""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional

from flask import current_app, g


def get_db() -> sqlite3.Connection:
    """Return a cached DB connection for the current request context."""
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(e: Optional[BaseException] = None) -> None:
    """Close the connection at request teardown."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    """Create required tables when they do not exist."""
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE,
            password_hash TEXT
        );

        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            person_name TEXT NOT NULL,
            transaction_name TEXT NOT NULL,
            amount REAL NOT NULL,
            payment_method TEXT NOT NULL,
            date TEXT NOT NULL,
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            person_name TEXT NOT NULL,
            amount REAL NOT NULL,
            payment_method TEXT NOT NULL,
            date TEXT NOT NULL,
            notes TEXT
        );
        """
    )
    db.commit()


def init_app(app) -> None:
    """Register teardown handlers and ensure database exists."""
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()


def add_transaction(payload: Dict[str, Any]) -> int:
    db = get_db()
    cursor = db.execute(
        """
        INSERT INTO transactions (
            person_name, transaction_name, amount, payment_method, date, notes
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            payload["person_name"],
            payload["transaction_name"],
            payload["amount"],
            payload["payment_method"],
            payload["date"],
            payload.get("notes"),
        ),
    )
    db.commit()
    return cursor.lastrowid


def add_payment(payload: Dict[str, Any]) -> int:
    db = get_db()
    cursor = db.execute(
        """
        INSERT INTO payments (
            person_name, amount, payment_method, date, notes
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            payload["person_name"],
            payload["amount"],
            payload["payment_method"],
            payload["date"],
            payload.get("notes"),
        ),
    )
    db.commit()
    return cursor.lastrowid


def delete_transaction(entry_id: int) -> bool:
    db = get_db()
    cursor = db.execute("DELETE FROM transactions WHERE id = ?", (entry_id,))
    db.commit()
    return cursor.rowcount > 0


def delete_payment(entry_id: int) -> bool:
    db = get_db()
    cursor = db.execute("DELETE FROM payments WHERE id = ?", (entry_id,))
    db.commit()
    return cursor.rowcount > 0


def get_records_for_person(person_name: str) -> List[Dict[str, Any]]:
    db = get_db()
    rows = db.execute(
        """
        SELECT id, person_name, transaction_name AS description, amount,
               payment_method, date, notes, 'transaction' AS type
        FROM transactions
        WHERE person_name = ?
        UNION ALL
        SELECT id, person_name, COALESCE(notes, 'Payment') AS description,
               amount, payment_method, date, notes, 'payment' AS type
        FROM payments
        WHERE person_name = ?
        ORDER BY date
        """,
        (person_name, person_name),
    ).fetchall()

    formatted: List[Dict[str, Any]] = []
    for row in rows:
        amount = float(row["amount"])
        signed_amount = amount if row["type"] == "payment" else -amount
        formatted.append(
            {
                "id": row["id"],
                "person_name": row["person_name"],
                "type": row["type"],
                "description": row["description"],
                "amount": signed_amount,
                "payment_method": row["payment_method"],
                "date": row["date"],
                "notes": row["notes"],
            }
        )
    return formatted


def get_balance(person_name: Optional[str] = None) -> float:
    db = get_db()
    params: List[Any] = []
    where_clause = ""
    if person_name:
        where_clause = "WHERE person_name = ?"
        params.append(person_name)

    total_transactions = db.execute(
        f"SELECT COALESCE(SUM(amount), 0) FROM transactions {where_clause}",
        params,
    ).fetchone()[0]

    total_payments = db.execute(
        f"SELECT COALESCE(SUM(amount), 0) FROM payments {where_clause}",
        params,
    ).fetchone()[0]

    return float(total_transactions or 0) - float(total_payments or 0)
