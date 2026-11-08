"""Load a preset from frontend/legacy/app.js (default: the Bihar Dec 2025 - Feb 2026 one) into the library's objects, so
the backend benchmarks and tests can run on it without a browser or the API.

    from real_data.bihar_preset import load
    farmers, fleet, markets = load()                 # bihar_dec2025_feb2026
    farmers, fleet, markets = load("cold_chain")     # any key of SCENARIOS
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from logistics_lib_v2 import CROPS, Farmer, Market, make_fleet  # noqa: E402

APP_JS = Path(__file__).resolve().parent.parent.parent / "frontend" / "legacy" / "app.js"


def _js_to_py(block):
    block = re.sub(r"//[^\n]*", "", block)                                    # strip line comments
    block = re.sub(r"([{,]\s*)([A-Za-z_]\w*)\s*:", r'\1"\2":', block)         # quote keys
    block = re.sub(r",\s*([}\]])", r"\1", block)                              # trailing commas
    return json.loads(block)


def load(key="bihar_dec2025_feb2026"):
    seg = APP_JS.read_text()
    seg = seg[seg.index(f"  {key}: {{"):]

    def arr(name):
        k = seg.index("[", seg.index(name + ":"))
        depth = 0
        for p in range(k, len(seg)):
            depth += seg[p] == "["
            depth -= seg[p] == "]"
            if depth == 0:
                return _js_to_py(seg[k:p + 1])

    farmers = [Farmer(id=i, lat=d["lat"], lng=d["lng"], crop=d["crop"], qty_kg=d["qty_kg"], ready_hr=d["ready_hr"],
                      deadline_hr=d["deadline_hr"], needs_refrigeration=CROPS[d["crop"]]["needs_refrigeration"])
               for i, d in enumerate(arr("farmers"))]
    fleet = make_fleet({v["type_name"]: v["count"] for v in arr("vehicles")})
    markets = [Market(id=i, lat=d["lat"], lng=d["lng"], price=d["price"], capacity_kg=d["capacity_kg"])
               for i, d in enumerate(arr("markets"))]
    return farmers, fleet, markets


if __name__ == "__main__":
    f, v, m = load()
    print(len(f), "farmers", round(sum(x.qty_kg for x in f)), "kg;", len(v), "vehicles;", len(m), "markets")
