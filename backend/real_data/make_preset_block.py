"""
make_preset_block.py
--------------------
Prints a ready-to-paste entry for the frontend's preset list (frontend/app.js -> SCENARIOS), built from
data/real_markets.json, so adding the next real dataset = run this, paste the output, done.

It lands in the "Real data" category of the preset dropdown (category: "real").
Paste the printed entry inside `const SCENARIOS = { ... }` in frontend/app.js, after the existing real presets.

    python real_data/make_preset_block.py --id up_bihar_mar2026 \
        --label "Bihar + UP mandis, Mar 2026" \
        --blurb "REAL: ... SYNTHETIC: ..." --fleet-multiplier 2

Same farmer/fleet generation as load_real_scenario.py (same seed => same farmers). Farmers and fleet are
SYNTHETIC; say so in the blurb, and say which parts are real and from which source/window.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # backend/
from logistics_lib_v2 import haversine  # noqa: E402
from load_real_scenario import make_farmers_and_fleet, select_markets  # noqa: E402
from common import REAL_MARKETS_JSON  # noqa: E402


def _d(d):
    return "{ " + ", ".join(f"{k}: {v}" for k, v in d.items()) + " }"


def render(data, preset_id, label, blurb, anchor, n_farmers, seed, max_markets, fleet_multiplier):
    chosen = select_markets(data["markets"], anchor, max_markets)
    if not chosen:
        sys.exit("No usable markets in the JSON.")
    farmers, comp = make_farmers_and_fleet(chosen, anchor, n_farmers, seed, fleet_multiplier)
    if not farmers:
        sys.exit("No synthetic farmer grows a crop that the chosen markets quote.")
    q = lambda s: json.dumps(s)   # noqa: E731  (JS-compatible string literal)
    out = [f"  {preset_id}: {{", '    category: "real",', f"    label: {q(label)},", f"    blurb: {q(blurb)},", "    farmers: ["]
    for f in farmers:
        out.append(f'      {{ lat: {round(f.lat, 5)}, lng: {round(f.lng, 5)}, crop: "{f.crop}", qty_kg: {round(f.qty_kg, 1)}, '
                   f"ready_hr: {round(f.ready_hr, 2)}, deadline_hr: {round(f.deadline_hr, 2)} }},")
    out += ["    ],", "    vehicles: ["]
    out += [f'      {{ type_name: "{t}", count: {n} }},' for t, n in comp.items() if n]
    out += ["    ],", "    markets: ["]
    for m in chosen:
        d = haversine(anchor[0], anchor[1], m["lat"], m["lng"])
        ph = [f'{c} {m["capacity_kg"][c] / 1000:g} t on {m["capacity_top_share"][c]:.0%} of days'
              for c in m["capacity_kg"] if m.get("capacity_is_placeholder", {}).get(c)]
        note = (" | capacity looks like a reporting default: " + "; ".join(ph)) if ph else ""
        out.append(f'      {{ lat: {round(m["lat"], 5)}, lng: {round(m["lng"], 5)}, price: {_d(m["price"])}, '
                   f'capacity_kg: {_d({k: round(v) for k, v in m["capacity_kg"].items()})} }}, '
                   f'// {m["name"].replace(" Apmc", "")} ({m["district"]}), {d:.0f} km from farmers{note}')
    out += ["    ],", "  },"]
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--id", required=True, help="JS key, e.g. bihar_mar2026 (letters/digits/underscore)")
    ap.add_argument("--label", required=True, help="text shown in the dropdown")
    ap.add_argument("--blurb", required=True, help="description under the dropdown; state what is real vs synthetic")
    ap.add_argument("--json", default=str(REAL_MARKETS_JSON))
    ap.add_argument("--anchor", default="25.60,84.90")
    ap.add_argument("--n-farmers", type=int, default=120)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--max-markets", type=int, default=8)
    ap.add_argument("--fleet-multiplier", type=int, default=2)
    ap.add_argument("--out", default=None, help="write to this file instead of stdout")
    args = ap.parse_args(argv)
    if not args.id.replace("_", "").isalnum() or args.id[0].isdigit():
        sys.exit("--id must be a valid JS identifier (letters, digits, underscore; not starting with a digit).")
    data = json.loads(Path(args.json).read_text())
    anchor = tuple(float(x) for x in args.anchor.split(","))
    text = render(data, args.id, args.label, args.blurb, anchor, args.n_farmers, args.seed, args.max_markets,
                  args.fleet_multiplier)
    if args.out:
        Path(args.out).write_text(text + "\n")
        print("wrote", args.out)
    else:
        print(text)


if __name__ == "__main__":
    main()
