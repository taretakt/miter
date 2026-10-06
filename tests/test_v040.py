"""v0.4.0 — two-leg interfaces.

A handoff between two subjects:
    INTERFACE trailer_handoff
        FROM leg_a TO leg_b
        MATCH trailer_weight TO capacity
        JOIN shipment_id
        TOLERANCE 0.10

Rows are paired by equal JOIN value (1:1). Each side evaluates its own
match against the other's lane field. Determinism preserved: pairing is a
pure function of the row set, iteration follows input order.

Pairing semantics:
- 1 join value -> both rows NA (no counterpart)
- 2 join values -> each checks the other
- >2            -> all MISMATCHED (non-unique join key)
- missing join key on a row -> NA (missing join key)

Two-leg interfaces are dataset-level (like aggregates): evaluate_row alone
yields NA with reason 'two-leg interface', and they are NOT evaluated under
variations (documented asymmetry).
"""

import json

import pytest

from miter.engine import MiterEngine
from miter.parser import MiterError, parse

SPEC = """
EVALUATION handoff
SUBJECT leg
INPUTS shipment_id trailer_weight capacity

INTERFACE trailer_handoff
    FROM leg_a TO leg_b
    MATCH trailer_weight TO capacity
    JOIN shipment_id
    TOLERANCE 0.10
END
"""


def _rows():
    return [
        {"shipment_id": "S-1", "trailer_weight": 1000.0, "capacity": 1050.0},
        {"shipment_id": "S-1", "trailer_weight": 1000.0, "capacity": 1050.0},
    ]


# ---------- parser ----------

def test_two_leg_parses():
    ev = parse(SPEC)
    iface = ev.interfaces[0]
    assert iface.join == "shipment_id"
    assert iface.match_field == "trailer_weight"
    assert iface.lane_field == "capacity"


def test_join_affects_hash():
    a = parse(SPEC)
    no_join = SPEC.replace("    JOIN shipment_id\n", "")
    b = parse(no_join)
    assert a.spec_hash() != b.spec_hash()


# ---------- engine ----------

def test_paired_rows_matched_both_sides():
    report = MiterEngine(parse(SPEC)).evaluate_all(_rows())
    rows = report["results"]
    assert rows[0]["interfaces"]["trailer_handoff"]["status"] == "MATCHED"
    assert rows[1]["interfaces"]["trailer_handoff"]["status"] == "MATCHED"
    assert report["summary"] == {"rows": 2, "FAIL": 0, "PASS": 2}


def test_mismatched_pair_fails_both_rows():
    rows = [
        {"shipment_id": "S-1", "trailer_weight": 1000.0, "capacity": 700.0},
        {"shipment_id": "S-1", "trailer_weight": 1000.0, "capacity": 700.0},
    ]
    report = MiterEngine(parse(SPEC)).evaluate_all(rows)
    assert report["results"][0]["interfaces"]["trailer_handoff"]["status"] == "MISMATCHED"
    assert report["results"][0]["verdict"] == "FAIL"
    assert report["results"][1]["verdict"] == "FAIL"


def test_unpaired_key_is_na():
    rows = [{"shipment_id": "S-1", "trailer_weight": 1000.0, "capacity": 1100.0}]
    report = MiterEngine(parse(SPEC)).evaluate_all(rows)
    entry = report["results"][0]["interfaces"]["trailer_handoff"]
    assert entry["status"] == "NA"
    assert entry["reason"] == "no counterpart"
    assert report["summary"]["PASS"] == 1  # NA never fails a row


def test_non_unique_join_key_fails():
    rows = [
        {"shipment_id": "S-1", "trailer_weight": 1000.0, "capacity": 1100.0},
        {"shipment_id": "S-1", "trailer_weight": 1000.0, "capacity": 1100.0},
        {"shipment_id": "S-1", "trailer_weight": 1000.0, "capacity": 1100.0},
    ]
    report = MiterEngine(parse(SPEC)).evaluate_all(rows)
    for r in report["results"]:
        assert r["interfaces"]["trailer_handoff"]["status"] == "MISMATCHED"
        assert "non-unique" in r["interfaces"]["trailer_handoff"]["reason"]
        assert r["verdict"] == "FAIL"


def test_missing_join_key_is_na():
    rows = [{"trailer_weight": 1000.0, "capacity": 1100.0}]
    entry = MiterEngine(parse(SPEC)).evaluate_all(rows)["results"][0]["interfaces"]["trailer_handoff"]
    assert entry["status"] == "NA"
    assert entry["reason"] == "missing join key"


def test_evaluate_row_defers_two_leg():
    row = MiterEngine(parse(SPEC)).evaluate_row(_rows()[0])
    entry = row["interfaces"]["trailer_handoff"]
    assert entry["status"] == "NA"
    assert "two-leg" in entry["reason"]


def test_two_leg_deterministic():
    engine = MiterEngine(parse(SPEC))
    a = engine.to_json(_rows())
    b = engine.to_json(_rows())
    assert a == b


def test_budget_still_applies_on_entity_side():
    spec = """
EVALUATION handoff
SUBJECT leg
INPUTS shipment_id trailer_weight capacity

INTERFACE trailer_handoff
    FROM leg_a TO leg_b
    MATCH trailer_weight TO capacity
    JOIN shipment_id
    TOLERANCE 0.10
    BUDGET 15m
    TIME handoff_t
END
"""
    rows = [
        {"shipment_id": "S-1", "trailer_weight": 1000.0, "capacity": 1100.0, "handoff_t": 600},
        {"shipment_id": "S-1", "trailer_weight": 1000.0, "capacity": 1100.0, "handoff_t": 1200},
    ]
    report = MiterEngine(parse(spec)).evaluate_all(rows)
    r0 = report["results"][0]["interfaces"]["trailer_handoff"]
    r1 = report["results"][1]["interfaces"]["trailer_handoff"]
    assert r0["budget"] == "OK"
    assert r1["budget"] == "OVER"
    assert r1["status"] == "MISMATCHED"


def test_within_row_interfaces_untouched():
    """A JOIN-less interface must behave exactly as before."""
    spec = """
EVALUATION merge_check
SUBJECT route
CRITERION c
    FIELD v <= 10.0
INTERFACE merge
    FROM collector TO expressway
    MATCH v TO lane_v
    TOLERANCE 0.10
END
"""
    rows = [{"v": 8.0, "lane_v": 8.1}]
    report = MiterEngine(parse(spec)).evaluate_all(rows)
    assert report["results"][0]["interfaces"]["merge"]["status"] == "MATCHED"
    assert report["results"][0]["interfaces"]["merge"].get("join") is None