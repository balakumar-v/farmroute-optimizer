"""Shared constants/helpers for the real-data pipeline."""
from pathlib import Path

HERE = Path(__file__).parent
DATA = HERE / "data"
RAW_DIR = DATA / "raw"
COORDS_CSV = DATA / "mandi_coords.csv"
OVERRIDES_CSV = DATA / "mandi_coords_overrides.csv"
REAL_MARKETS_JSON = DATA / "real_markets.json"

# project crop key -> (Agmarknet commodity id, commodity group id).
# IDs read from the SDK's bundled filters.json (Agmarknet 2.0 lookup tables):
# group 6 = Vegetables, group 5 = Fruits. "Wild Spinach" (id 545) is a
# different commodity and is deliberately NOT mapped to "spinach".
CROPS = {
    "tomato":      (65, 6),
    "onion":       (23, 6),
    "potato":      (24, 6),
    "cauliflower": (31, 6),
    "mango":       (20, 5),
    "spinach":     (290, 6),
}
# Agmarknet commodity name (lower-case) -> project crop key
COMMODITY_TO_CROP = {
    "tomato": "tomato", "onion": "onion", "potato": "potato",
    "cauliflower": "cauliflower", "mango": "mango", "spinach": "spinach",
}

# Rough bounding boxes (min_lat, min_lng, max_lat, max_lng), used ONLY as a
# sanity filter on geocoder hits (reject a hit that lands in another state).
STATE_BBOX = {
    "Bihar":         (24.2, 83.3, 27.6, 88.3),
    "Jharkhand":     (21.9, 83.3, 25.4, 87.9),
    "Uttar Pradesh": (23.8, 77.0, 30.5, 84.7),
    "West Bengal":   (21.5, 85.8, 27.3, 89.9),
}
