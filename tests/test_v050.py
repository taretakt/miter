"""v0.5.0 — the window clause (rolling-limit semantics).

    CRITERION missed_stops
        FIELD stops >= 1
        WITHIN 7d
        TIME event_t
        LIMIT 2

Every criterion is still a per-row check. WITHIN adds a dataset-level rule:
count the rows where this criterion FAILs inside ANY window of the given
length; if any window count exceeds LIMIT, the windowed rule fails.

- Deterministic: events are time-sorted (stable, ties broken by input order),
  windows are [t, t + duration] including both ends, count includes the anchor.
- A row with a missing/non-numeric time makes the window unenumerable, so the
  windowed rule returns NA (cannot be evaluated honestly at all).
- Rows where the criterion is NA (missing field) never count toward the window.
- LIMIT defaults to 0 (no failures allowed in any window).
- Severity governs the dataset verdict, as everywhere: an error-severity rule
  with a violated window FAILs the whole evaluation; warn reports only.
"""

import json

import pytest

from miter.engine import MiterEngine
from miter.parser import MiterError, parse

SPEC = """
EVALUATION delivery_monitor
SUBJECT stop
INPUTS ok event_t

CRITERION stop_ok
    FIELD ok >= 1
    SEVERITY error
CRITERION burst_rule
    FIELD ok >= 1
    WITHIN 7d
    TIME event_t
    LIMIT 2
    SEVERITY error
END
"""


def _rows(counts):
    """days-delta list -> rows at day * 86400, ok=0 (fail) or 1 (pass)."""
    return [{"ok": 1 if c == "pass" else 0, "event_t": int(d * 86400)} for d, c in counts]


# ---------- parser ----------

def test_window_directives_parse():
    ev = parse(SPEC)
    burst = [c for c in ev.criteria if c.id == "burst_rule"][0]
    assert burst.within_s == 7 * 86400
    assert burst.time_field == "event_t"
    assert burst.limit == 2


def test_limit_requires_within():
    with pytest.raises(MiterError):
        parse(
            "EVALUATION e\n"
            "CRITERION c\n"
            "    FIELD ok >= 1\n"
            "    LIMIT 2\n"
            "END\n"
        )


def test_window_affects_hash():
    a = parse(SPEC)
    plain = SPEC.replace("    WITHIN 7d\n    TIME event_t\n    LIMIT 2\n", "")
    b = parse(plain)
    assert a.spec_hash() != b.spec_hash()


# ---------- engine ----------

def test_window_burst_violates_limit():
    # 3 fails within a 7-day span when only 2 are allowed
    rows = _rows([(0, "fail"), (1, "fail"), (2, "fail"), (40, "pass")])
    report = MiterEngine(parse(SPEC)).evaluate_all(rows)
    w = {x["id"]: x for x in report["windows"]}["burst_rule"]
    assert w["status"] == "FAIL"
    assert report["verdict"] == "FAIL"


def test_window_within_limit_passes():
    rows = _rows([(0, "fail"), (1, "fail"), (10, "fail"), (40, "pass")])
    report = MiterEngine(parse(SPEC)).evaluate_all(rows)
    w = {x["id"]: x for x in report["windows"]}["burst_rule"]
    assert w["status"] == "PASS"
    assert report["verdict"] == "PASS"


def test_window_exact_limit_ok():
    # 2 fails exactly at the boundary of a single 7d window
    rows = _rows([(0, "fail"), (7, "fail"), (30, "pass")])
    report = MiterEngine(parse(SPEC)).evaluate_all(rows)
    w = {x["id"]: x for x in report["windows"]}["burst_rule"]
    assert w["count"] == 2
    assert w["status"] == "PASS"


def test_window_missing_time_is_na():
    rows = [{"ok": 0}, {"ok": 0}]
    report = MiterEngine(parse(SPEC)).evaluate_all(rows)
    w = {x["id"]: x for x in report["windows"]}["burst_rule"]
    assert w["status"] == "NA"


def test_window_na_rows_do_not_count():
    # second row: ok missing -> criterion NA on that row, never a FAIL
    rows = [
        {"ok": 0, "event_t": 0},
        {"event_t": 86400},
    ]
    report = MiterEngine(parse(SPEC)).evaluate_all(rows)
    w = {x["id"]: x for x in report["windows"]}["burst_rule"]
    assert w["status"] == "PASS"
    assert w["count"] == 1


def test_window_deterministic():
    engine = MiterEngine(parse(SPEC))
    rows = _rows([(0, "fail"), (1, "fail"), (2, "fail"), (40, "pass")])
    assert engine.to_json(rows) == engine.to_json(rows)


def test_window_prefix_and_report_shape():
    # a convention: windows section only exists when a WITHIN rule is present
    plain = SPEC.replace("    WITHIN 7d\n    TIME event_t\n    LIMIT 2\n", "")
    report = MiterEngine(parse(plain)).evaluate_all(_rows([(0, "fail")]))
    assert "windows" not in report


def test_window_default_limit_zero():
    # WITHIN without LIMIT means: no failures allowed in any window
    spec = """
EVALUATION e
SUBJECT s
CRITERION c
    FIELD ok >= 1
    WITHIN 7d
    TIME event_t
END
"""
    rows = _rows([(0, "fail"), (40, "pass")])
    report = MiterEngine(parse(spec)).evaluate_all(rows)
    w = report["windows"][0]
    assert w["limit"] == 0
    assert w["status"] == "FAIL"