"""Parser tests — the the evaluation DSL DSL grammar."""

import pytest

from miter.model import Evaluation, Interface
from miter.parser import MiterError, parse

VALID = """
EVALUATION route_feasibility
SUBJECT route
INPUTS depot_capacity driver_hours

CRITERION depot_within_capacity
    FIELD depot_capacity <= 0.95
    SEVERITY error

CRITERION driver_within_hours
    FIELD driver_hours <= 14.0

VARIATION peak_volume
    ADJUST depot_capacity SCALE 1.2

INTERFACE merge_onto_expressway
    FROM collector TO expressway
    MATCH velocity TO lane_velocity
    TOLERANCE 0.10
    BUDGET 20m
END
"""


def test_parse_full_spec():
    ev = parse(VALID)
    assert isinstance(ev, Evaluation)
    assert ev.name == "route_feasibility"
    assert ev.subject == "route"
    assert ev.inputs == ["depot_capacity", "driver_hours"]
    assert len(ev.criteria) == 2
    assert len(ev.variations) == 1
    assert len(ev.interfaces) == 1
    assert ev.criteria[0].op == "<="
    assert ev.criteria[0].threshold == 0.95
    assert ev.criteria[0].severity == "error"
    assert ev.criteria[1].severity == "error"  # default


def test_parse_interface():
    ev = parse(VALID)
    iface = ev.interfaces[0]
    assert isinstance(iface, Interface)
    assert iface.lane_from == "collector"
    assert iface.lane_to == "expressway"
    assert iface.match_field == "velocity"
    assert iface.lane_field == "lane_velocity"
    assert iface.tolerance == 0.10
    assert iface.budget_s == 20 * 60


def test_duration_units():
    ev = parse(VALID)
    assert ev.interfaces[0].budget_s == 1200.0


def test_comments_are_stripped():
    ev = parse(VALID)
    assert ev.criteria[0].note == ""


def test_missing_evaluation_name():
    with pytest.raises(MiterError):
        parse("SUBJECT route\nEND")


def test_missing_end():
    with pytest.raises(MiterError):
        parse("EVALUATION x\nSUBJECT route")


def test_unknown_directive():
    with pytest.raises(MiterError):
        parse("""
EVALUATION x
CRITERION c
    FROBNICATE depot_capacity <= 0.9
END
""")


def test_criterion_requires_field():
    with pytest.raises(MiterError):
        parse("""
EVALUATION x
CRITERION c
    SEVERITY error
END
""")


def test_bad_operator():
    with pytest.raises(MiterError):
        parse("""
EVALUATION x
CRITERION c
    FIELD depot_capacity IS 0.9
END
""")


def test_spec_hash_is_stable():
    a = parse(VALID).spec_hash()
    b = parse(VALID).spec_hash()
    assert a == b
    assert len(a) == 16