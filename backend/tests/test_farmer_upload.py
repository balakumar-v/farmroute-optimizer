"""Farmer-list upload: validation is all-or-nothing and tells the user exactly which row and column is wrong."""
import io
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from farmer_upload import parse_farmers

HEADER = "lat,lng,crop,qty_kg,ready_hr,deadline_hr,needs_refrigeration\n"
GOOD = "25.3,84.8,Tomato,400,6,30,\n25.4,85.0,onion,900,4,40,no\n"


def _csv(body, header=HEADER):
    return parse_farmers("farmers.csv", (header + body).encode())


def test_valid_csv_is_parsed_and_crop_case_is_forgiven():
    farmers, errors = _csv(GOOD)
    assert not errors and [f.crop for f in farmers] == ["tomato", "onion"]
    assert farmers[0].needs_refrigeration is None and farmers[1].needs_refrigeration is False


def test_headers_are_normalised_and_blank_lines_skipped():
    farmers, errors = _csv("\n25.3,84.8,onion,400,6,30\n\n", header="Lat, LNG ,Crop,Qty KG,Ready Hr,Deadline Hr\n")
    assert not errors and len(farmers) == 1


def test_valid_xlsx_is_parsed():
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["lat", "lng", "crop", "qty_kg", "ready_hr", "deadline_hr"])
    ws.append([25.3, 84.8, "potato", 500, 6, 30])
    buf = io.BytesIO()
    wb.save(buf)
    farmers, errors = parse_farmers("list.xlsx", buf.getvalue())
    assert not errors and farmers[0].qty_kg == 500


@pytest.mark.parametrize("row, column, fragment", [
    ("25.3,84.8,banana,400,6,30,", "crop", "crop must be one of"),
    ("25.3,84.8,onion,-5,6,30,", "qty_kg", "greater than 0"),
    ("25.3,84.8,onion,nan,6,30,", "qty_kg", "finite"),
    ("25.3,84.8,onion,400,30,30,", "deadline_hr", "later than ready_hr"),
    ("95,84.8,onion,400,6,30,", "lat", "between -90 and 90"),
    ("25.3,84.8,onion,abc,6,30,", "qty_kg", ""),
    ("25.3,84.8,onion,,6,30,", "qty_kg", "required"),
    ("25.3,84.8,onion,400,6,30,maybe", "needs_refrigeration", "yes/no"),
])
def test_each_kind_of_bad_row_is_reported_with_row_and_column(row, column, fragment):
    farmers, errors = _csv(GOOD + row + "\n")
    assert any(e["row"] == 4 and e["column"] == column and fragment in e["message"] for e in errors), errors


def test_every_error_is_reported_not_just_the_first():
    _, errors = _csv("25.3,84.8,banana,400,6,30,\n25.3,84.8,onion,-1,6,30,\n")
    assert {e["row"] for e in errors} == {2, 3}


@pytest.mark.parametrize("name, content, fragment", [
    ("f.csv", b"", "empty"),
    ("f.csv", b"lat,lng,crop\n1,2,onion\n", "Missing required column"),
    ("f.csv", HEADER.encode(), "no farmers"),
    ("f.txt", b"x", ".csv or .xlsx"),
    ("f.csv", b"\xff\xfe\x00bad", "UTF-8"),
    ("f.xlsx", b"not a workbook", "Could not read"),
])
def test_file_level_problems_are_reported_at_row_zero(name, content, fragment):
    farmers, errors = parse_farmers(name, content)
    assert not farmers and errors[0]["row"] == 0 and fragment in errors[0]["message"]


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="needs DATABASE_URL (a Postgres)")
def test_upload_endpoint_stores_all_or_nothing():
    from fastapi.testclient import TestClient
    import main
    with TestClient(main.app) as c:
        c.post("/reset")
        up = lambda body, **kw: c.post("/farmers/upload", files={"file": ("f.csv", (HEADER + body).encode())}, **kw)  # noqa: E731
        bad = up(GOOD + "25,84,banana,1,1,2,\n")
        assert bad.status_code == 422 and bad.json()["detail"]["errors"][0]["row"] == 4
        assert c.get("/farmers").json() == []                                       # nothing stored
        assert up(GOOD, params={"dry_run": True}).json() == {"farmers": 2, "stored": False}
        assert c.get("/farmers").json() == []                                       # dry run stores nothing
        assert up(GOOD).json() == {"farmers": 2, "stored": True}
        stored = c.get("/farmers").json()
        assert [f["crop"] for f in stored] == ["tomato", "onion"]
        assert stored[0]["needs_refrigeration"] is True                             # derived from the crop table
        assert stored[1]["needs_refrigeration"] is False
