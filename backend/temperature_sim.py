"""Simulated DHT22 room-temperature feed for the demo.

In the real build an ESP32 reads a DHT22 (range -40..80 C, +/-0.5 C, 0.1 C resolution) beside the produce. For the demo
there is no hardware, so this module imitates what that sensor would plausibly report in a room: a slow mean-reverting
wander between 20 and 30 C plus a little sensor noise, quantised to 0.1 C. One new reading is drawn per plan compute.
Nothing here is a measurement.
"""
import random
import threading

SENSOR = "DHT22"
ROOM_MIN_C, ROOM_MAX_C, ROOM_MID_C = 27.0, 30.0, 29.0
MIN_MOVE_C = 0.8          # a new reading always moves at least this much, so the change is visible in a demo

_lock = threading.Lock()
_last = None
_rng = random.Random()


def seed(value):
    """Tests only: make the sequence reproducible and forget the last reading."""
    global _last
    with _lock:
        _rng.seed(value)
        _last = None


def next_reading():
    """-> {"temp_c", "previous_temp_c", "sensor", "simulated"}; the sensor value is the room wander + DHT22 noise."""
    global _last
    with _lock:
        prev = _last
        if prev is None:
            base = _rng.uniform(ROOM_MIN_C + 1.5, ROOM_MAX_C - 1.5)
        else:
            for _ in range(50):
                step = _rng.gauss(0.15 * (ROOM_MID_C - prev), 1.8)      # gentle pull back toward 25 C
                cand = min(ROOM_MAX_C, max(ROOM_MIN_C, prev + step))
                if abs(cand - prev) >= MIN_MOVE_C:
                    break
            else:   # clamped against a wall every time: step away from it
                cand = prev + (MIN_MOVE_C if prev - ROOM_MIN_C < ROOM_MAX_C - prev else -MIN_MOVE_C)
            base = cand
        _last = base
        reading = round(min(ROOM_MAX_C, max(ROOM_MIN_C, base + _rng.gauss(0, 0.15))), 1)
        return {"temp_c": reading, "previous_temp_c": None if prev is None else round(prev, 1),
                "sensor": SENSOR, "simulated": True}


def describe(reading, pools, fleet):
    """The plan's temperature block: the reading, how it scales spoilage, and the same trips re-rated across room temps.

    `pools` = the recommended plan's pools, `fleet` = [{id, refrigerated}] (spot-hired trucks carry `vehicle_spec`).
    Re-rating keeps the trips fixed and rescales only the unrefrigerated trips' spoilage by factor(T)/factor(now); it
    ignores the 60% loss cap (never reached at room temperature on these trip lengths) and does not re-plan.
    """
    from logistics_lib_v2 import AMBIENT_REF_C, SPOIL_Q10, ambient_spoil_factor
    t = reading["temp_c"]
    refrig_by_id = {v["id"]: bool(v["refrigerated"]) for v in fleet}

    def refrigerated(p):
        spec = p.get("vehicle_spec")
        if spec is not None:
            return bool(spec.get("refrigerated"))
        return refrig_by_id.get(p.get("vehicle_id"), False)

    hauled = [p for p in pools if p.get("vehicle_id") is not None and not p.get("sold_at_farmgate") and not p.get("withheld")]
    warm = sum(p.get("spoilage_loss_kg", 0.0) for p in hauled if not refrigerated(p))
    cold = sum(p.get("spoilage_loss_kg", 0.0) for p in hauled if refrigerated(p))
    now = ambient_spoil_factor(t)
    temps = [20.0, 22.0, 24.0, 26.0, 28.0, 30.0]
    curve = [{"temp_c": x, "spoilage_kg": warm * ambient_spoil_factor(x) / now + cold} for x in temps]
    return {
        "sensor": reading["sensor"], "simulated": True, "temp_c": t, "previous_temp_c": reading["previous_temp_c"],
        "reference_c": AMBIENT_REF_C, "q10": SPOIL_Q10, "rate_factor": now,
        "unrefrigerated_trips": sum(1 for p in hauled if not refrigerated(p)),
        "refrigerated_trips": sum(1 for p in hauled if refrigerated(p)),
        "unrefrigerated_spoilage_kg": float(warm), "refrigerated_spoilage_kg": float(cold),
        "at_reference_spoilage_kg": float(warm / now + cold),
        "curve": [{"temp_c": c["temp_c"], "spoilage_kg": float(c["spoilage_kg"])} for c in curve],
    }
