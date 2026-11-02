"""
farmer_upload.py -- parse and validate a farmer list from a .csv or .xlsx file.

All-or-nothing: if any row is invalid the caller gets every error (row number, column, message) and nothing is
stored, so a half-imported list can never silently skew a plan. Row numbers are spreadsheet rows (header = 1).
"""
import csv
import io
import math
from typing import Tuple

from pydantic import ValidationError

from schemas import FarmerIn

REQUIRED = ["lat", "lng", "crop", "qty_kg", "ready_hr", "deadline_hr"]
OPTIONAL = ["needs_refrigeration"]
MAX_ROWS = 5000
MAX_BYTES = 2_000_000
_TRUE, _FALSE = {"true", "yes", "y", "1"}, {"false", "no", "n", "0"}


def _norm_header(h):
    return str(h or "").strip().lower().replace(" ", "_")


def _read_table(filename: str, data: bytes):
    name = (filename or "").lower()
    if len(data) > MAX_BYTES:
        raise ValueError(f"File is larger than {MAX_BYTES // 1_000_000} MB.")
    if name.endswith(".xlsx"):
        from openpyxl import load_workbook
        try:
            ws = load_workbook(io.BytesIO(data), read_only=True, data_only=True).active
        except Exception:
            raise ValueError("Could not read this as an .xlsx file.")
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
    elif name.endswith(".csv"):
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise ValueError("CSV must be UTF-8 encoded.")
        rows = list(csv.reader(io.StringIO(text)))
    else:
        raise ValueError("Upload a .csv or .xlsx file.")
    rows = [r for r in rows if any(str(c).strip() for c in r if c is not None)]   # drop blank lines
    if not rows:
        raise ValueError("The file is empty.")
    return rows


def parse_farmers(filename: str, data: bytes) -> Tuple[list, list]:
    """Returns (valid FarmerIn list, error list). Errors: {"row", "column", "message"}; row 0 = whole file/header.
    The list is only meant to be used when errors is empty."""
    try:
        rows = _read_table(filename, data)
    except ValueError as exc:
        return [], [{"row": 0, "column": None, "message": str(exc)}]
    header = [_norm_header(h) for h in rows[0]]
    missing = [c for c in REQUIRED if c not in header]
    if missing:
        return [], [{"row": 0, "column": ", ".join(missing),
                     "message": f"Missing required column(s). Expected: {', '.join(REQUIRED + OPTIONAL)}."}]
    body = rows[1:]
    if len(body) > MAX_ROWS:
        return [], [{"row": 0, "column": None, "message": f"More than {MAX_ROWS} farmers in one file."}]
    if not body:
        return [], [{"row": 0, "column": None, "message": "The file has a header but no farmers."}]

    farmers, errors = [], []
    for i, raw in enumerate(body, start=2):
        rec = {h: (str(v).strip() if v is not None else "") for h, v in zip(header, raw) if h in REQUIRED + OPTIONAL}
        rec["crop"] = rec.get("crop", "").lower()
        refrig = rec.pop("needs_refrigeration", "").lower()
        if refrig in _TRUE | _FALSE:
            rec["needs_refrigeration"] = refrig in _TRUE
        elif refrig:
            errors.append({"row": i, "column": "needs_refrigeration", "message": "Use yes/no (or true/false)."})
            continue
        try:
            f = FarmerIn(**rec)
        except ValidationError as exc:
            for e in exc.errors():
                col = str(e["loc"][0]) if e["loc"] else None
                msg = "required" if e["type"] == "missing" or rec.get(col) == "" else e["msg"].replace("Value error, ", "")
                errors.append({"row": i, "column": col, "message": msg})
            continue
        problems = [(c, "must be a finite number") for c in ("lat", "lng", "qty_kg", "ready_hr", "deadline_hr")
                    if not math.isfinite(getattr(f, c))]
        if problems:
            errors += [{"row": i, "column": c, "message": m} for c, m in problems]
            continue
        if not (-90 <= f.lat <= 90):
            problems.append(("lat", "must be between -90 and 90"))
        if not (-180 <= f.lng <= 180):
            problems.append(("lng", "must be between -180 and 180"))
        if f.qty_kg <= 0:
            problems.append(("qty_kg", "must be greater than 0"))
        if f.ready_hr < 0:
            problems.append(("ready_hr", "must be 0 or more"))
        if f.deadline_hr <= f.ready_hr:
            problems.append(("deadline_hr", "must be later than ready_hr"))
        if problems:
            errors += [{"row": i, "column": c, "message": m} for c, m in problems]
            continue
        farmers.append(f)
    return farmers, errors
