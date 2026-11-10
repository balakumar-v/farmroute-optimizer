"""'My trader pays less than expected, I want to join the pooling': what the LLM may say, how it is checked, and that
one farmer's trader quote prices only that farmer. No database needed (the DB-backed flow shares the change-request
tables and is covered by test_change_requests.py when DATABASE_URL is set)."""
import copy
import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import advisor
import change_requests as cr
import chat_llm
import ilo_v3 as V
import main
from baselines_v3 import FarmgatePrices
from logistics_lib_v2 import generate_scenario_v2

DOOR = {"qty_kg": 400.0, "ready_hr": 6.0, "deadline_hr": 16.0, "active": True, "trader_quote_per_kg": None,
        "pool_status": "farmgate", "expected_per_kg": 16.0}


def _join(q):
    return cr.ChangeParse(pool_join=cr.PoolJoin(quote_per_kg=q))


# ---------------------------------------------------------------- what the LLM may send
@pytest.mark.parametrize("raw", [
    '{"pool_join":{"quote_per_kg":0}}',                                   # a price must be positive
    '{"pool_join":{"quote_per_kg":-3}}',
    '{"pool_join":{"quote_per_kg":NaN}}',
    '{"pool_join":{"quote_per_kg":"cheap"}}',
    '{"pool_join":{"quote_per_kg":12,"farmer_id":3}}',                    # extra key
    '{"pool_join":{}}',                                                   # the quote is required
    '{"pool_join":{"quote_per_kg":12},"participation":"rejoin"}',         # never mixed
    '{"pool_join":{"quote_per_kg":12},"changes":[{"field":"qty_kg","mode":"set","value":5}]}',
])
def test_malformed_pool_join_is_rejected(raw):
    with pytest.raises(ValidationError):
        cr.ChangeParse.model_validate_json(raw)


def test_the_form_fallback_can_send_a_pool_join():
    assert cr.ChatIn(structured={"pool_join": {"quote_per_kg": 12}}).structured.pool_join.quote_per_kg == 12


def test_the_model_reply_for_a_low_trader_offer_parses(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setenv("OPENROUTER_MODEL", "m")
    reply = {"choices": [{"message": {"content": json.dumps({"changes": [], "participation": None,
                                                              "pool_join": {"quote_per_kg": 12}, "clarify": None})},
                          "finish_reason": "stop"}]}
    monkeypatch.setattr(chat_llm, "_post", lambda payload: reply)
    out = chat_llm.parse_message("my trader gives only 12 rupees a kilo, put me in the pool", DOOR)
    assert out.pool_join.quote_per_kg == 12 and not out.changes


def test_the_prompt_tells_the_model_about_pool_join_and_one_kg_prices():
    assert "pool_join" in chat_llm.SYSTEM and "ONE kg" in chat_llm.SYSTEM


# ---------------------------------------------------------------- resolving against the farmer's card
def test_a_lower_offer_from_a_doorstep_farmer_resolves_to_that_farmers_quote_only():
    got = cr.resolve(_join(12.345), DOOR)
    assert got == {"trader_quote_per_kg": round(12.345, 2)}
    assert set(got) == {"trader_quote_per_kg"}                    # no quantity, time or participation is touched
    assert set(got) <= set(cr.COLUMNS)


@pytest.mark.parametrize("patch,code", [
    ({"pool_status": "hauled"}, "already_hauled"),
    ({"pool_status": "unserved"}, "waiting_truck"),
    ({"pool_status": None}, "no_card"),
    ({"active": False}, "inactive"),
    ({"trader_quote_per_kg": 12.0}, "same"),
])
def test_pool_join_refusals(patch, code):
    with pytest.raises(cr.ChangeError) as e:
        cr.resolve(_join(12.0), {**DOOR, **patch})
    assert e.value.code == code


@pytest.mark.parametrize("q", [16.0, 20.0])
def test_an_offer_not_below_the_expected_price_is_not_a_reason_to_pool(q):
    with pytest.raises(cr.ChangeError) as e:
        cr.resolve(_join(q), DOOR)
    assert e.value.code == "not_lower" and e.value.params == {"quote": q, "expected": 16.0}


def test_an_absurd_price_is_refused(monkeypatch):
    monkeypatch.setenv("CHANGE_MAX_QUOTE_PER_KG", "50")
    with pytest.raises(cr.ChangeError) as e:
        cr.resolve(_join(60), {**DOOR, "expected_per_kg": None})
    assert e.value.code == "quote_range"


def test_the_confirm_card_shows_expected_and_offered_price():
    line, = cr.change_lines(DOOR, {"trader_quote_per_kg": 12.0})
    assert (line["field"], line["from"], line["to"]) == ("trader_quote_per_kg", "16", "12")
    assert "12" in cr.summary(DOOR, {"trader_quote_per_kg": 12.0})


def test_two_quote_requests_clash_but_a_quote_and_a_quantity_change_do_not():
    assert cr._clash({"trader_quote_per_kg"}, {"trader_quote_per_kg"})
    assert not cr._clash({"trader_quote_per_kg"}, {"qty_kg"})


def test_with_card_adds_status_and_expected_price_without_touching_the_row():
    cur = {"qty_kg": 1.0, "ready_hr": 1.0, "deadline_hr": 2.0, "active": True, "trader_quote_per_kg": None}
    out = cr.with_card(cur, {"status": "farmgate", "doorstep_per_kg": 15.5})
    assert out["pool_status"] == "farmgate" and out["expected_per_kg"] == 15.5 and "pool_status" not in cur
    assert cr.with_card(None, {"status": "x"}) is None
    assert "pool_status" not in cr.with_card(cur, None)


# ---------------------------------------------------------------- one farmer's quote prices only that farmer
def _scenario(seed=1, n=40):
    return generate_scenario_v2(n_farmers=n, n_markets=3, seed=seed)


def test_no_quotes_means_the_default_price_path_is_untouched():
    _, _, markets = _scenario()
    assert main.farmer_prices(markets, None) is None and main.farmer_prices(markets, {}) is None


def test_a_quote_changes_that_farmers_price_and_nobody_elses():
    farmers, _, markets = _scenario()
    base = FarmgatePrices(markets)
    target = farmers[0]
    prices = main.farmer_prices(markets, {target.id: 3.0})
    assert prices.per_kg(target) == 3.0
    for f in farmers[1:]:
        assert prices.per_kg(f) == pytest.approx(base.per_kg(f))


def test_a_stored_quote_prices_the_card_and_quote_check_for_that_farmer_only():
    farmers, fleet, markets = _scenario(seed=2)
    snap = {"markets": [{"id": m.id, "lat": m.lat, "lng": m.lng, "price": m.price, "capacity_kg": m.capacity_kg}
                        for m in markets]}
    plain = advisor._prices(snap, 0.20)
    quoted = advisor._prices({**snap, "trader_quotes": {str(farmers[0].id): 4.5}}, 0.20)
    obj = lambda f: advisor._as_obj(f.__dict__)
    assert quoted.per_kg(obj(farmers[0])) == 4.5
    assert all(quoted.per_kg(obj(f)) == pytest.approx(plain.per_kg(obj(f))) for f in farmers[1:])


def test_a_low_quote_puts_a_doorstep_farmer_on_a_truck_and_an_unchanged_price_does_not():
    farmers, fleet, markets = _scenario(seed=1, n=40)
    hauled = lambda res: {i for r in res if r["vehicle_id"] is not None for i in r["farmer_ids"]}
    res0 = V.run_ilo_v3(farmers, copy.deepcopy(fleet), markets)
    door = [i for r in res0 if r["vehicle_id"] is None and r.get("sold_at_farmgate") for i in r["farmer_ids"]]
    assert door, "the scenario must contain a farmer the planner leaves at the doorstep"
    f = next(x for x in farmers if x.id == door[0])
    assert f.id not in hauled(res0)
    # the farmer's own trader offers almost nothing: the planner now hauls this farmer
    low = main.farmer_prices(markets, {f.id: 0.5})
    assert f.id in hauled(V.run_ilo_v3(farmers, copy.deepcopy(fleet), markets, prices=low))
    # a "quote" equal to the assumed price is no news: same farmer stays at the doorstep
    same = main.farmer_prices(markets, {f.id: FarmgatePrices(markets).per_kg(f)})
    assert f.id not in hauled(V.run_ilo_v3(farmers, copy.deepcopy(fleet), markets, prices=same))
