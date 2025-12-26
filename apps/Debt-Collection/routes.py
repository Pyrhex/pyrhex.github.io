"""HTTP routes and API handlers for the debt tracking dashboard."""

from __future__ import annotations

import functools
from datetime import datetime
from typing import Callable, Dict

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.wrappers import Response

from models import (
    add_payment,
    add_transaction,
    delete_payment,
    delete_transaction,
    get_balance,
    get_records_for_person,
)
from sheets import append_ledger_row

bp = Blueprint("main", __name__, template_folder="templates")


def _auth_enabled() -> bool:
    return bool(current_app.config.get("ADMIN_PASSWORD"))


def _is_authenticated() -> bool:
    return bool(session.get("authenticated"))


def _auth_guard(view: Callable) -> Callable:
    """Enforce the optional dashboard password for UI + API routes."""

    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not _auth_enabled() or _is_authenticated():
            return view(*args, **kwargs)

        if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
            return jsonify({"error": "Authentication required"}), 401

        login_url = url_for("main.login", next=request.path)
        return redirect(login_url)

    return wrapped


def _default_date(value: str | None) -> str:
    if not value:
        return datetime.utcnow().date().isoformat()
    return value


def _coerce_amount(raw: str | float | int | None) -> float:
    try:
        amount = float(raw)
    except (TypeError, ValueError):
        raise ValueError("Amount must be a number")
    if amount <= 0:
        raise ValueError("Amount must be positive")
    return round(amount, 2)


@bp.app_context_processor
def inject_flags():
    return {"auth_enabled": _auth_enabled()}


@bp.route("/")
@_auth_guard
def dashboard():
    person_name = current_app.config.get("PERSON_NAME", "Friend")
    balance = get_balance(person_name)
    return render_template(
        "index.html",
        person_name=person_name,
        initial_balance=balance,
    )


@bp.route("/login", methods=["GET", "POST"])
def login():
    if not _auth_enabled():
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        password = request.form.get("password", "")
        if password and password == current_app.config.get("ADMIN_PASSWORD"):
            session["authenticated"] = True
            flash("Welcome back!", "success")
            next_url = request.args.get("next") or url_for("main.dashboard")
            return redirect(next_url)
        flash("Incorrect password.", "error")

    return render_template("login.html")


@bp.route("/logout")
def logout():
    session.pop("authenticated", None)
    flash("Signed out.", "success")
    if _auth_enabled():
        return redirect(url_for("main.login"))
    return redirect(url_for("main.dashboard"))


def _build_transaction_payload(data: Dict[str, str]) -> Dict[str, str | float]:
    person_name = current_app.config.get("PERSON_NAME", "Friend")
    description = (data.get("transaction_name") or "").strip()
    if not description:
        abort(400, "Description is required.")
    method = (data.get("payment_method") or "").strip()
    if not method:
        abort(400, "Payment method is required.")
    normalized_method = method.title()
    if normalized_method not in {"Cash", "Card"}:
        abort(400, "Payment method must be Cash or Card.")
    try:
        amount = _coerce_amount(data.get("amount"))
    except ValueError as exc:
        abort(400, str(exc))

    payload: Dict[str, str | float] = {
        "person_name": person_name,
        "transaction_name": description,
        "amount": amount,
        "payment_method": normalized_method,
        "date": _default_date(data.get("date")),
        "notes": (data.get("notes") or "").strip() or None,
    }
    return payload


def _build_payment_payload(data: Dict[str, str]) -> Dict[str, str | float]:
    person_name = current_app.config.get("PERSON_NAME", "Friend")
    try:
        amount = _coerce_amount(data.get("amount"))
    except ValueError as exc:
        abort(400, str(exc))

    method = (data.get("payment_method") or "").strip()
    if not method:
        abort(400, "Payment method is required.")

    payload: Dict[str, str | float] = {
        "person_name": person_name,
        "amount": amount,
        "payment_method": method,
        "date": _default_date(data.get("date")),
        "notes": (data.get("notes") or "").strip() or None,
    }
    return payload


@bp.route("/api/transactions", methods=["POST"])
@_auth_guard
def api_add_transaction():
    data = request.get_json(silent=True) or {}
    payload = _build_transaction_payload(data)
    entry_id = add_transaction(payload)

    append_ledger_row(
        {
            "type": "transaction",
            "date": payload["date"],
            "description": payload["transaction_name"],
            "amount": payload["amount"],
            "payment_method": payload["payment_method"],
        }
    )

    return jsonify({"id": entry_id, "message": "Transaction recorded"}), 201


@bp.route("/api/payments", methods=["POST"])
@_auth_guard
def api_add_payment():
    data = request.get_json(silent=True) or {}
    payload = _build_payment_payload(data)
    entry_id = add_payment(payload)

    append_ledger_row(
        {
            "type": "payment",
            "date": payload["date"],
            "amount": payload["amount"],
            "payment_method": payload["payment_method"],
        }
    )

    return jsonify({"id": entry_id, "message": "Payment recorded"}), 201


@bp.route("/api/records", methods=["GET"])
@_auth_guard
def api_records():
    person_name = current_app.config.get("PERSON_NAME", "Friend")
    records = get_records_for_person(person_name)
    balance = get_balance(person_name)
    return jsonify({"records": records, "balance": balance})


@bp.route("/api/summary", methods=["GET"])
@_auth_guard
def api_summary():
    person_name = current_app.config.get("PERSON_NAME", "Friend")
    balance = get_balance(person_name)
    return jsonify({"balance": balance})


@bp.route("/api/records/<string:record_type>/<int:entry_id>", methods=["DELETE"])
@_auth_guard
def api_delete_record(record_type: str, entry_id: int):
    record_type = record_type.lower()
    if record_type == "transaction":
        success = delete_transaction(entry_id)
    elif record_type == "payment":
        success = delete_payment(entry_id)
    else:
        abort(400, "Record type must be 'transaction' or 'payment'.")

    if not success:
        abort(404, "Record not found.")

    return Response(status=204)
