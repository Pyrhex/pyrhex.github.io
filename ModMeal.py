#!/usr/bin/env python3
import argparse
import datetime
import re
from pathlib import Path

import pandas as pd
import pytz

from flask import Flask, request, render_template, redirect, url_for
import tempfile
import os

VAN_TZ = pytz.timezone("America/Vancouver")

# Seniority (most senior first)
SENIORITY_ORDER = [
    "Cindy", "KC", "Ryan", "Emilyn", "Christian", "Troy", "Brian", "Tristan", "Jordan", "Abdi"
]
SENIORITY_RANK = {name.lower(): i for i, name in enumerate(SENIORITY_ORDER)}

# Optional: restrict to the roster you use
KNOWN_NAMES = [
    "Brian", "Abdi*", "Emilyn*", "Ryan*", "Jordan", "Cindy*", "KC",
    "Christian*", "Troy*", "Tristan*", "Ian", "Sara", "Terry"
]

TIME_RANGE_PATTERN = re.compile(
    r"^\d{1,2}(:\d{2})?(AM|PM)\s*-\s*\d{1,2}(:\d{2})?(AM|PM)$", re.IGNORECASE
)
SKIP_VALUES = {"-", "OFF", "N/A", "AM ONLY"}
SKIP_KEYWORDS = ["REQ", "NO"]


def remove_end_star(name: str) -> str:
    return name[:-1] if isinstance(name, str) and name.endswith("*") else name


def normalize_name(s: str) -> str:
    if s is None:
        return ""
    return remove_end_star(str(s).strip()).lower()


def convert_to_24_hour(time_str: str):
    time_str = time_str.strip()
    period = time_str[-2:].upper()
    time_part = time_str[:-2].strip()
    if ":" in time_part:
        hour, minute = map(int, time_part.split(":"))
    else:
        hour, minute = int(time_part), 0
    if period == "PM" and hour != 12:
        hour += 12
    elif period == "AM" and hour == 12:
        hour = 0
    return hour, minute


def parse_time_range(time_str: str):
    if not isinstance(time_str, str):
        return None
    time_str = time_str.strip().upper()
    try:
        start_str, end_str = [s.strip() for s in time_str.split("-")]
        sh, sm = convert_to_24_hour(start_str)
        eh, em = convert_to_24_hour(end_str)
        return sh, sm, eh, em
    except Exception:
        return None


def interval_for_date(date_dt: datetime.datetime, tr: str):
    parsed = parse_time_range(tr)
    if not parsed:
        return None
    sh, sm, eh, em = parsed
    start_dt = date_dt.replace(hour=sh, minute=sm, second=0, microsecond=0)
    end_dt = date_dt.replace(hour=eh, minute=em, second=0, microsecond=0)
    if end_dt <= start_dt:
        end_dt = date_dt.replace(hour=23, minute=59, second=59, microsecond=0)
    return VAN_TZ.localize(start_dt), VAN_TZ.localize(end_dt)


def rank(name: str) -> int:
    return SENIORITY_RANK.get(remove_end_star(name).lower(), 10_000)


def build_shifts(xls_path: Path, restrict_to_known=True):
    """
    Returns dict[date -> list[(name, start_dt, end_dt)]]
    """
    sched = pd.read_excel(xls_path, engine="openpyxl", skiprows=2)
    sched = sched.iloc[:, 3:].dropna(axis=1, how="all")      # schedule columns
    sched = sched.iloc[1:].reset_index(drop=True)              # drop first data row
    sched.columns = ["Name"] + sched.columns[1:].tolist()

    shifts_by_day = {}
    targets = KNOWN_NAMES if restrict_to_known else sched["Name"].dropna().astype(str).tolist()

    for person in targets:
        row = sched[sched["Name"].apply(normalize_name) == normalize_name(person)]
        if row.empty:
            continue
        row_vals = list(row.values[0])[1:]
        for day, val in zip(sched.columns[1:], row_vals):
            val_str = str(val).strip()
            up = val_str.upper()
            if (
                not val_str
                or up in SKIP_VALUES
                or any(kw in up for kw in SKIP_KEYWORDS)
                or not TIME_RANGE_PATTERN.match(up)
            ):
                continue
            date_obj = pd.to_datetime(day, errors="coerce")
            if pd.isna(date_obj):
                continue
            iv = interval_for_date(date_obj.to_pydatetime(), up)
            if not iv:
                continue
            sdt, edt = iv
            shifts_by_day.setdefault(sdt.date(), []).append((person, sdt, edt))

    return shifts_by_day

def compute_jojo_days(xls_path: Path):
    """
    Scan the entire sheet (including Managers section) for a row named 'Jojo' (ignoring a trailing '*').
    Return a set of datetime.date objects for which Jojo is marked as working by any non-empty cell
    that is not in SKIP_VALUES.
    """
    sched = pd.read_excel(xls_path, engine="openpyxl", skiprows=2)
    # Align column slicing with build_shifts: schedule starts at col index 3
    sched = sched.iloc[:, 3:].dropna(axis=1, how="all")
    # Keep header row handling consistent with build_shifts
    sched = sched.iloc[1:].reset_index(drop=True)
    sched.columns = ["Name"] + sched.columns[1:].tolist()

    jojo_days = set()
    if "Name" not in sched.columns:
        return jojo_days

    # Find Jojo rows anywhere in the sheet
    jojo_rows = sched[sched["Name"].apply(normalize_name) == "jojo"]
    if jojo_rows.empty:
        return jojo_days

    date_cols = sched.columns[1:]
    for _, row in jojo_rows.iterrows():
        for day_col in date_cols:
            val = row[day_col]
            if pd.isna(val):
                continue
            val_str = str(val).strip()
            # treat any non-empty value not in SKIP_VALUES as "working"
            if val_str and val_str.upper() not in SKIP_VALUES:
                # day_col should already be a datetime-like label from the processed header
                day_dt = pd.to_datetime(day_col, errors="coerce")
                if not pd.isna(day_dt):
                    jojo_days.add(day_dt.date())
    return jojo_days

def manager_at(point_dt, all_entries):
    """Return most-senior active manager at a specific datetime, or None if nobody active."""
    active = [n for (n, s, e) in all_entries if s <= point_dt < e]
    if not active:
        return None
    return remove_end_star(min(active, key=rank))


def compute_day_managers_fixed_windows(shifts_by_day, jojo_days):
    """
    For each calendar day, select managers for three fixed windows in this order:
      1) 10pm–2am  (we anchor at 23:00 of the same day)
      2) 6am–2pm   (anchor at 10:00)
      3) 2pm–10pm  (anchor at 18:00)
    Returns dict[date -> [night, open, close]]
    """
    # Flatten all entries across days so we can look across midnight
    all_entries = []
    day_keys = set()
    for day, entries in shifts_by_day.items():
        day_keys.add(day)
        all_entries.extend(entries)
    # Ensure we also include any days that only appear because of overnight coverage
    # (Using existing keys is typically sufficient because entries include concrete datetimes.)

    out = {}
    for day in sorted(day_keys):
        # Build anchor datetimes for that day in local tz
        base = datetime.datetime.combine(day, datetime.time(0, 0))
        base = VAN_TZ.localize(base)
        t_night = base.replace(hour=23, minute=0)   # represents 10pm–2am shift
        t_open  = base.replace(hour=10, minute=0)   # inside 6am–2pm
        t_close = base.replace(hour=18, minute=0)   # inside 2pm–10pm

        m1 = manager_at(t_night, all_entries)
        m2 = manager_at(t_open,  all_entries)
        m3 = manager_at(t_close, all_entries)

        # Jojo AM override based on Managers section scan
        if day in jojo_days:
            m2 = "Jojo"

        out[day] = [m for m in [m1, m2, m3] if m]
    return out


def compute_day_managers(shifts_by_day, min_block_minutes=45, max_names_per_day=3):
    """
    For each day:
      - build contiguous blocks
      - assign most-senior active person per block
      - merge away tiny transition blocks (< min_block_minutes)
      - keep at most 3 managers by total coverage, preserving first-appearance order
    Returns: dict[date -> [Manager1, Manager2, Manager3]]
    """
    from collections import defaultdict
    def mins(a, b):
        return int((b - a).total_seconds() // 60)

    out = {}
    for day, entries in sorted(shifts_by_day.items()):
        # 1) boundaries and raw blocks
        boundaries = sorted({t for _, s, e in entries for t in (s, e)})
        blocks = []  # (start, end, manager)
        for i in range(len(boundaries) - 1):
            seg_start, seg_end = boundaries[i], boundaries[i + 1]
            active = [n for (n, s, e) in entries if s < seg_end and e > seg_start]
            if not active:
                continue
            mgr = min(active, key=rank)  # most-senior
            blocks.append((seg_start, seg_end, remove_end_star(mgr)))

        if not blocks:
            out[day] = []
            continue

        # 2) merge consecutive same-manager blocks
        merged = []
        for s, e, m in blocks:
            if not merged:
                merged.append((s, e, m))
            else:
                ps, pe, pm = merged[-1]
                if pm == m and s <= pe:
                    merged[-1] = (ps, max(pe, e), pm)
                else:
                    merged.append((s, e, m))

        # 3) drop/absorb tiny transition blocks shorter than threshold
        cleaned = []
        i = 0
        while i < len(merged):
            s, e, m = merged[i]
            if mins(s, e) >= min_block_minutes:
                cleaned.append((s, e, m))
                i += 1
            else:
                # absorb into longer neighbor when possible
                left_len = mins(*merged[i-1][:2]) if i > 0 else -1
                right_len = mins(*merged[i+1][:2]) if i < len(merged)-1 else -1
                if left_len >= right_len and cleaned:
                    ls, le, lm = cleaned[-1]
                    cleaned[-1] = (ls, max(le, e), lm)
                elif i < len(merged)-1:
                    rs, re, rm = merged[i+1]
                    merged[i+1] = (min(s, rs), re, rm)
                # skip tiny block
                i += 1

        if not cleaned:
            out[day] = []
            continue

        # 4) compute coverage per manager
        coverage = defaultdict(int)
        for s, e, m in cleaned:
            coverage[m] += mins(s, e)

        # 5) pick managers by coverage (top N), but print in first-appearance order
        top = {m for m, _ in sorted(coverage.items(), key=lambda kv: kv[1], reverse=True)[:max_names_per_day]}

        ordered = []
        seen = set()
        for _, _, m in cleaned:
            if m in top and m not in seen:
                ordered.append(m)
                seen.add(m)

        out[day] = ordered[:max_names_per_day]

    return out



app = Flask(__name__)

def _process_excel_to_rows(temp_xlsx_path: Path):
    shifts = build_shifts(temp_xlsx_path, restrict_to_known=True)
    jojo_days = compute_jojo_days(temp_xlsx_path)
    day_to_managers = compute_day_managers_fixed_windows(shifts, jojo_days)
    rows = []
    for day, mgrs in sorted(day_to_managers.items()):
        date_str = day.strftime("%Y-%m-%d")
        rows.append((date_str, ", ".join(mgrs)))
    return rows

@app.get("/")
def index():
    return render_template("manager_meals.html", rows=None, error=None)

@app.post("/upload")
def upload():
    f = request.files.get("file")
    if not f or f.filename == "":
        return render_template("manager_meals.html", rows=None, error="Please choose an .xlsx file.")
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            f.save(tmp.name)
            tmp_path = Path(tmp.name)
        rows = _process_excel_to_rows(tmp_path)
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        return render_template("manager_meals.html", rows=rows, error=None)
    except Exception as e:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        return render_template("manager_meals.html", rows=None, error=f"Error processing file: {e}")

# if __name__ == "__main__":
#     parser = argparse.ArgumentParser(description="Manager Meal List — Web by default; CLI if file provided")
#     parser.add_argument("--web", action="store_true", help="Force run as a Flask website (http://127.0.0.1:5000)")
#     parser.add_argument("excel", type=Path, nargs="?", help="Path to weekly schedule.xlsx (CLI mode)")
#     parser.add_argument("--all-names", action="store_true",
#                         help="CLI mode: Use all names from sheet instead of restricting to KNOWN_NAMES")
#     args = parser.parse_args()

#     # Default behavior: if no excel file is provided, run the web app
#     if args.web or not args.excel:
#         app.run(host="127.0.0.1", port=5000, debug=True)
#     else:
#         shifts = build_shifts(args.excel, restrict_to_known=not args.all_names)
#         jojo_days = compute_jojo_days(args.excel)
#         day_to_managers = compute_day_managers_fixed_windows(shifts, jojo_days)
#         for day, mgrs in sorted(day_to_managers.items()):
#             date_str = day.strftime("%Y-%m-%d")
#             print(f"{date_str}: {', '.join(mgrs)}")