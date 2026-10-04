"""
Offline tests. NOTE: every number in here is a SYNTHETIC FIXTURE built to
exercise the code paths -- none of it is real Agmarknet data.
The live API call itself can only be checked by running the scraper on a
machine with internet (use `scrape_agmarknet.py --probe`).
"""
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import build_real_markets as brm
import geocode_mandis as gm
import scrape_agmarknet as sa


# ---------- scraper: payload sent through the SDK ----------
def _fake_payload(rows):
    return {"data": {"records": [{"data": rows, "pagination": [
        {"current_page": 1, "total_pages": 1, "total_count": len(rows), "limit": 1000}]}],
        "columns": []}}


def test_scraper_payload_and_columns(monkeypatch):
    from agmarknet import Agmarknet
    from agmarknet.session import AgmarknetSession
    sent = []

    def fake_post(self, path, payload):
        sent.append((path, dict(payload)))
        return _fake_payload([{
            "arrival_date": "2026-09-10", "state_name": "Bihar", "district_name": "Patna",
            "market_name": "Patna APMC", "cmdt_name": "Onion", "variety_name": "Other",
            "min_price": 1500, "max_price": 2500, "model_price": 2000,
            "unit_name_price": "Rs./Quintal", "arrival_qty": 120, "unit_name_arrival": "Tonnes"}])
    monkeypatch.setattr(AgmarknetSession, "post_json", fake_post)
    api = Agmarknet(request_delay=0)
    df = sa.fetch_crop(api, "onion", ["Bihar"], date(2026, 9, 1), date(2026, 9, 30))
    assert len(df) == 1 and df.iloc[0]["crop"] == "onion"
    assert sa.EXPECTED_COLS <= set(df.columns)
    path, p = sent[0]
    assert "daily-price-arrival" in path
    assert str(p["commodity"]) in ("23", "[23]")
    assert "5" in str(p["state"])                       # Bihar = state id 5
    assert str(p["data_type"]) == "100006"              # "both" (price+arrival)
    assert str(p["from_date"]).startswith("2026-09-01") and str(p["to_date"]).startswith("2026-09-30")


# ---------- builder: units, dedupe, filters ----------
def test_unit_factors():
    assert brm.price_per_kg_factor("Rs./Quintal") == pytest.approx(0.01)
    assert brm.price_per_kg_factor("Rs./Kg") == 1.0
    assert brm.arrival_kg_factor("Tonnes") == 1000.0
    assert brm.arrival_kg_factor("Quintal") == 100.0
    assert brm.arrival_kg_factor("Bags") is None        # unknown -> must NOT be guessed


def _row(d, mkt, crop, variety, modal, arr, pu="Rs./Quintal", au="Tonnes", cmdt=None):
    return {"arrival_date": d, "state_name": "Bihar", "district_name": "Patna", "market_name": mkt,
            "cmdt_name": cmdt or crop.title(), "variety_name": variety, "model_price": modal,
            "unit_name_price": pu, "arrival_qty": arr, "unit_name_arrival": au}


COORDS = {("Bihar", "Patna", "Alpha"): (25.6, 85.1, "nominatim")}


def test_build_conversions_and_arrival_not_double_counted():
    rows = []
    for day in range(1, 8):                              # 7 days
        d = f"2026-09-{day:02d}"
        rows += [_row(d, "Alpha", "onion", "Red", 2000, 100),      # arrival repeated per variety
                 _row(d, "Alpha", "onion", "White", 2200, 100)]
    markets, dropped = brm.build(pd.DataFrame(rows), COORDS, min_days=5)
    m = markets[0]
    assert m["price"]["onion"] == pytest.approx(21.0)             # mean(2000,2200)/100
    assert m["capacity_kg"]["onion"] == pytest.approx(100_000.0)  # 100 t once, NOT 200 t
    assert m["n_days"]["onion"] == 7 and dropped == []


def test_build_filters():
    rows = []
    for day in range(1, 8):
        d = f"2026-09-{day:02d}"
        rows += [_row(d, "Alpha", "potato", "Red", 1500, 50),
                 _row(d, "Alpha", "tomato", "Hybrid", 3000, 20) if day <= 3 else {},   # only 3 days
                 _row(d, "NoCoords", "potato", "Red", 1500, 50),
                 _row(d, "Alpha", "wild", "x", 900, 5, cmdt="Wild Spinach"),            # must not map to spinach
                 _row(d, "Alpha", "onion", "Red", 2000, 10, au="Bags")]                # unknown unit
    rows = [r for r in rows if r]
    markets, dropped = brm.build(pd.DataFrame(rows), COORDS, min_days=5)
    a = markets[0]
    assert set(a["price"]) == {"potato"}                  # tomato <5 days, onion no valid arrival, wild spinach unmapped
    assert dropped == [("Bihar", "Patna", "NoCoords")]    # reported, never invented


def test_dates_parse_both_formats():
    s = pd.Series(["2026-09-10", "10-09-2026"])
    assert list(brm._dates(s).dt.day) == [10, 10]


# ---------- geocoder helpers ----------
def test_clean_name_and_queries():
    assert gm.clean_name("Patna (Musallahpur) APMC") == ("Patna", "Musallahpur")
    assert gm.clean_name("Aarah") == ("Arrah", None)
    qs = gm.build_queries("Patna (Musallahpur) APMC", "Patna", "Bihar")
    assert qs[0].startswith("Musallahpur") and "Patna, Bihar, India" in qs[1]


def test_bbox_rejects_other_state():
    assert gm.in_bbox(25.6, 85.1, "Bihar")
    assert not gm.in_bbox(28.6, 77.2, "Bihar")            # Delhi


# ---------- scraper: live filters, clamping, error reporting ----------
def _mock_server(monkeypatch, live_to="2026-09-29"):
    """Fake API: live filters whose 'both' range ends at live_to; report calls beyond it -> HTTP 400."""
    import copy
    import agmarknet
    from agmarknet.exceptions import AgmarknetAPIError
    from agmarknet.session import AgmarknetSession
    bundled = json.load(open(Path(agmarknet.__file__).parent / "filters.json"))
    live = copy.deepcopy(bundled)
    live["data"]["range_data"][0]["both"]["to_date"] = live_to
    calls = {"filters": 0, "report": []}

    def fake_get(self, path):
        assert path == sa.FILTERS_PATH
        calls["filters"] += 1
        return live

    def fake_post(self, path, payload):
        calls["report"].append(dict(payload))
        if payload["to_date"] > live_to:
            raise AgmarknetAPIError("AGMARKNET request failed: 400", status_code=400,
                                    url="x", response_text='{"message":"to_date out of range"}')
        return _fake_payload([{"arrival_date": payload["to_date"], "state_name": "Bihar", "district_name": "Patna",
                               "market_name": "Patna APMC", "cmdt_name": "Onion", "variety_name": "v",
                               "model_price": 2000, "unit_name_price": "Rs./Quintal",
                               "arrival_qty": 10, "unit_name_arrival": "Tonnes"}])
    monkeypatch.setattr(AgmarknetSession, "get_json", fake_get)
    monkeypatch.setattr(AgmarknetSession, "post_json", fake_post)
    return calls


def test_clamp_window_pure():
    from datetime import date as D
    live = (D(2025, 11, 7), D(2026, 9, 29))
    assert sa.clamp_window(D(2026, 9, 28), D(2026, 9, 30), live) == (D(2026, 9, 27), D(2026, 9, 29))
    assert sa.clamp_window(D(2026, 9, 1), D(2026, 9, 10), live) == (D(2026, 9, 1), D(2026, 9, 10))
    assert sa.clamp_window(D(2025, 10, 1), D(2025, 11, 20), live)[0] == D(2025, 11, 7)
    assert sa.clamp_window(D(2026, 9, 1), D(2026, 9, 5), None) == (D(2026, 9, 1), D(2026, 9, 5))


def test_probe_clamps_to_live_range_and_uses_live_filters(monkeypatch, tmp_path, capsys):
    calls = _mock_server(monkeypatch, live_to="2026-09-29")
    sa.main(["--probe", "--to", "2026-09-30", "--delay", "0"])
    out = capsys.readouterr().out
    assert calls["filters"] >= 1                         # live filters were fetched (use_cache=False)
    assert "clamped" in out and "2026-09-29" in out
    assert all(c["to_date"] <= "2026-09-29" for c in calls["report"])
    assert "price units" in out


def test_failure_prints_status_and_server_body(monkeypatch, capsys):
    from agmarknet.exceptions import AgmarknetAPIError
    from agmarknet.session import AgmarknetSession
    _mock_server(monkeypatch, live_to="2026-09-30")
    monkeypatch.setattr(AgmarknetSession, "post_json",
                        lambda self, p, payload: (_ for _ in ()).throw(
                            AgmarknetAPIError("AGMARKNET request failed: 400", status_code=400,
                                              url="u", response_text='{"message":"bad district id"}')))
    with pytest.raises(SystemExit):
        sa.main(["--probe", "--to", "2026-09-30", "--delay", "0"])
    err = capsys.readouterr().err
    assert "HTTP status: 400" in err and "bad district id" in err


def test_diagnose_runs_ladder(monkeypatch, capsys):
    _mock_server(monkeypatch, live_to="2026-09-29")
    sa.main(["--diagnose", "--to", "2026-09-30", "--delay", "0"])
    out = capsys.readouterr().out
    assert out.count("[OK  ]") == 4 and "live 'both' range" in out


# ---------- India Data Portal importer + dataset coordinates (SYNTHETIC fixture CSV) ----------
import import_idp_csv as idp


def _idp_csv(path):
    """Tiny file shaped like the portal's documented schema; values are made up."""
    hdr = ("report_date,state_name,state_code,district_name,district_code,market_center,market_code,latitude,longitude,"
           "commodity_type,commodity,variety,origin,arrivals_tonnes,arrivals_unit,min_price,max_price,modal_price,price_unit")
    rows = [hdr]
    for d in range(1, 8):
        for variety in ("Red", "White"):
            rows.append(f"2024-09-{d:02d},Bihar,10,Patna,100,Alpha,1,25.6,85.1,Vegetables,Onion,{variety},,40,Tonnes,1500,2500,2000,INR / quintals")
        rows.append(f"2024-09-{d:02d},Bihar,10,Patna,100,Beta,2,25.6,85.1,Vegetables,Onion,Red,,30,Tonnes,1500,2500,2100,INR / quintals")
        rows.append(f"2024-09-{d:02d},Bihar,10,Gaya,101,Gamma,3,0,0,Vegetables,Onion,Red,,20,Tonnes,1500,2500,1900,INR / quintals")
        rows.append(f"2024-09-{d:02d},Bihar,10,Gaya,101,Delta,4,28.6,77.2,Vegetables,Onion,Red,,20,Tonnes,1500,2500,1900,INR / quintals")  # Delhi coords
        rows.append(f"2024-09-{d:02d},Punjab,3,X,1,Zed,5,30.9,75.8,Vegetables,Onion,Red,,20,Tonnes,1,2,3,INR / quintals")
        rows.append(f"2024-09-{d:02d},Bihar,10,Patna,100,Alpha,1,25.6,85.1,Cereals,Wheat,Red,,20,Tonnes,1,2,3,INR / quintals")
    rows.append("2023-01-01,Bihar,10,Patna,100,Alpha,1,25.6,85.1,Vegetables,Onion,Red,,99,Tonnes,1,2,3,INR / quintals")
    path.write_text("\n".join(rows))


def test_importer_filters_and_builder_uses_dataset_coords(tmp_path, monkeypatch):
    src, raw = tmp_path / "idp.csv", tmp_path / "raw.csv"
    _idp_csv(src)
    idp.main([str(src), "--state", "Bihar", "--from", "2024-09-01", "--to", "2024-09-30",
              "--chunk", "5", "--out", str(raw)])              # chunk=5 exercises streaming
    df = pd.read_csv(raw)
    assert set(df["crop"]) == {"onion"}                        # wheat excluded
    assert set(df["state_name"]) == {"Bihar"}                  # Punjab excluded
    assert "2023-01-01" not in set(df["arrival_date"])         # outside window excluded
    markets, dropped = brm.build(df, {}, min_days=5)           # NO geocode cache: coords come from the dataset
    names = {m["name"]: m for m in markets}
    assert set(names) == {"Alpha", "Beta"}                     # Gamma (0,0) and Delta (outside Bihar) dropped, not mis-placed
    assert {d[2] for d in dropped} == {"Gamma", "Delta"}
    a = names["Alpha"]
    assert (a["lat"], a["lng"], a["geocode_source"]) == (25.6, 85.1, "dataset")
    assert a["price"]["onion"] == pytest.approx(20.0)          # mean(2000,2000)/100
    assert a["capacity_kg"]["onion"] == pytest.approx(40_000.0)  # 40 t once per day, not 80 t
    warns = brm.shared_coordinate_warnings(markets)
    assert len(warns) == 1 and "Alpha" in warns[0] and "Beta" in warns[0]   # same point -> flagged


def test_importer_reports_available_dates_when_window_empty(tmp_path, capsys):
    src = tmp_path / "idp.csv"
    _idp_csv(src)
    with pytest.raises(SystemExit):
        idp.main([str(src), "--state", "Bihar", "--from", "2030-01-01", "--to", "2030-01-31", "--out", str(tmp_path / "o.csv")])
    assert "file covers 2023-01-01 .. 2024-09-07" in capsys.readouterr().out


def test_importer_missing_columns_message(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("foo,bar\n1,2\n")
    with pytest.raises(SystemExit) as e:
        idp.main([str(bad), "--from", "2024-01-01", "--to", "2024-01-02"])
    assert "Headers found" in str(e.value)


def test_overrides_beat_dataset_coords(tmp_path):
    src, raw = tmp_path / "idp.csv", tmp_path / "raw.csv"
    _idp_csv(src)
    idp.main([str(src), "--from", "2024-09-01", "--to", "2024-09-30", "--out", str(raw)])
    coords = {("Bihar", "Patna", "Alpha"): (25.0, 85.0, "override")}
    m = {x["name"]: x for x in brm.build(pd.read_csv(raw), coords, 5)[0]}
    assert (m["Alpha"]["lat"], m["Alpha"]["geocode_source"]) == (25.0, "override")


def test_headers_seen_in_portal_preview_are_recognised():
    # Header ids visible in the dataset preview screenshot: date, state_name, state_code, district_name,
    # district_code, market_center_name, market_center_code (the rest are inferred spellings).
    cols = idp.resolve_columns(["date", "state_name", "state_code", "district_name", "district_code",
                                "market_center_name", "market_center_code", "commodity_name", "modal_price"])
    assert cols["date"] == "date" and cols["market"] == "market_center_name" and cols["commodity"] == "commodity_name"


def test_real_portal_header_format_with_parenthesised_ids():
    hdr = ["Date (date)", "State Name (state_name)", "District Name (district_name)",
           "Market Center Name (market_center_name)", "Latitude (latitude)", "Longitude (longitude)",
           "Commodity Name (commodity_name)", "Variety (variety)", "Arrival Quantity (arrival_quantity)",
           "Arrival Units (arrival_units)", "Modal Price (modal_price)", "Price Unit (price_unit)"]
    cols = idp.resolve_columns(hdr)
    assert cols["market"] == "Market Center Name (market_center_name)"
    assert cols["arrivals"] == "Arrival Quantity (arrival_quantity)"
    assert cols["arrivals_unit"] == "Arrival Units (arrival_units)"
    assert cols["lat"] == "Latitude (latitude)"


def test_geocoder_skips_markets_that_already_have_dataset_coords():
    df = pd.DataFrame([
        {"state_name": "Bihar", "district_name": "Muzaffarpur", "market_name": "Muzaffarpur Apmc",
         "latitude": "26.149694", "longitude": "85.39634"},
        {"state_name": "Bihar", "district_name": "Banka", "market_name": "Barahat Apmc", "latitude": "", "longitude": ""}])
    have = brm.embedded_coords(df)
    assert ("Bihar", "Muzaffarpur", "Muzaffarpur Apmc") in have and ("Bihar", "Banka", "Barahat Apmc") not in have


def test_loader_fleet_multiplier_scales_vehicles():
    import load_real_scenario as L
    mk = [{"price": {"potato": 11, "onion": 20}, "capacity_kg": {"potato": 1, "onion": 1}, "lat": 25.5, "lng": 84.7}]
    _, c1 = L.make_farmers_and_fleet(mk, (25.6, 84.9), 100, 0)
    _, c2 = L.make_farmers_and_fleet(mk, (25.6, 84.9), 100, 0, fleet_multiplier=2)
    assert sum(c2.values()) == 2 * sum(c1.values()) and set(c1) == set(c2)


def test_preset_block_is_valid_js_shape_and_deterministic():
    import make_preset_block as mpb
    data = {"markets": [{"name": "A Apmc", "district": "D", "lat": 25.5, "lng": 84.7,
                         "price": {"potato": 11.0, "onion": 20.0}, "capacity_kg": {"potato": 1330.4, "onion": 3000.0}}]}
    kw = dict(preset_id="x_real", label="L \"q\"", blurb="REAL: a. SYNTHETIC: b.", anchor=(25.6, 84.9),
              n_farmers=100, seed=0, max_markets=8, fleet_multiplier=2)
    a, b = mpb.render(data, **kw), mpb.render(data, **kw)
    assert a == b                                           # same seed => identical output
    assert a.startswith("  x_real: {") and 'category: "real",' in a and a.rstrip().endswith("},")
    assert 'label: "L \\"q\\""' in a                        # quotes escaped for JS
    assert "farmers: [" in a and "vehicles: [" in a and "markets: [" in a
    assert "capacity_kg: { potato: 1330, onion: 3000 }" in a   # capacities rounded to whole kg
