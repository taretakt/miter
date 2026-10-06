"""v0.2 — aggregate criteria and compiler NOTICE semantics.

Aggregates: dataset-level criteria (AVG/SUM/MIN/MAX/COUNT) that keep
byte-determinism and extend the verdict to the whole row set.
Notices: the compiler's honesty rule, extended — when a sentence contains
structure the deterministic core cannot express, the output spec carries a
NOTICE naming the lost structure instead of silently degrading it.
"""

import json

import pytest

from miter.compiler import compile_text
from miter.engine import MiterEngine
from miter.parser import MiterError, parse

AGG_SPEC = """
EVALUATION batch_qc
SUBJECT lot
INPUTS classification_rate

CRITERION coverage_ok
    FIELD AVG(classification_rate) >= 0.9
    SEVERITY error

CRITERION min_rate_ok
    FIELD MIN(classification_rate) >= 0.5
    SEVERITY error
END
"""


def _rows():
    return [
        {"classification_rate": 0.93},
        {"classification_rate": 0.95},
        {"classification_rate": 0.88},
    ]


# ---------- parser ----------

def test_aggregate_criterion_parses():
    ev = parse(AGG_SPEC)
    assert ev.criteria[0].agg == "avg"
    assert ev.criteria[1].agg == "min"
    assert ev.criteria[0].field == "classification_rate"
    assert ev.criteria[0].op == ">="
    assert ev.criteria[0].threshold == 0.9


def test_unknown_aggregate_function_rejected():
    with pytest.raises(MiterError):
        parse(
            "EVALUATION e\n"
            "CRITERION c\n"
            "    FIELD MEDIAN(coverage) >= 0.5\n"
            "END\n"
        )


def test_count_star_parses():
    ev = parse(
        "EVALUATION e\n"
        "CRITERION rows_ok\n"
        "    FIELD COUNT(*) >= 3\n"
        "END\n"
    )
    assert ev.criteria[0].agg == "count"
    assert ev.criteria[0].field == "*"


def test_notice_directive_parses():
    ev = parse("EVALUATION e\nNOTICE windowed semantics unsupported\nEND\n")
    assert ev.notices == ["windowed semantics unsupported"]


def test_notice_affects_spec_hash():
    a = parse("EVALUATION e\nNOTICE x\nEND\n")
    b = parse("EVALUATION e\nNOTICE y\nEND\n")
    assert a.spec_hash() != b.spec_hash()


# ---------- engine ----------

def test_aggregate_average_pass():
    report = MiterEngine(parse(AGG_SPEC)).evaluate_all(_rows())
    aggs = {a["id"]: a for a in report["aggregates"]}
    assert aggs["coverage_ok"]["status"] == "PASS"
    assert abs(aggs["coverage_ok"]["value"] - (0.93 + 0.95 + 0.88) / 3) < 1e-9
    assert report["verdict"] == "PASS"


def test_aggregate_fail_flips_overall_verdict():
    rows = [{"classification_rate": 0.85}, {"classification_rate": 0.50}]
    report = MiterEngine(parse(AGG_SPEC)).evaluate_all(rows)
    aggs = {a["id"]: a for a in report["aggregates"]}
    assert aggs["coverage_ok"]["status"] == "FAIL"   # avg 0.675 < 0.9
    assert aggs["min_rate_ok"]["status"] == "PASS"   # min 0.50 >= 0.5 (inclusive)
    assert report["verdict"] == "FAIL"               # coverage_ok alone flips it


def test_aggregate_na_when_no_values():
    spec = (
        "EVALUATION e\n"
        "CRITERION avg_ok\n"
        "    FIELD AVG(coverage) >= 0.5\n"
        "END\n"
    )
    report = MiterEngine(parse(spec)).evaluate_all([{"other": 1}])
    aggs = {a["id"]: a for a in report["aggregates"]}
    assert aggs["avg_ok"]["status"] == "NA"
    assert report["verdict"] == "PASS"


def test_count_operators():
    spec = (
        "EVALUATION e\n"
        "CRITERION all_rows\n"
        "    FIELD COUNT(*) >= 3\n"
        "CRITERION present\n"
        "    FIELD COUNT(coverage) >= 2\n"
        "END\n"
    )
    rows = [
        {"coverage": 0.9},
        {"coverage": 0.8},
        {"other": 1},
    ]
    report = MiterEngine(parse(spec)).evaluate_all(rows)
    aggs = {a["id"]: a for a in report["aggregates"]}
    assert aggs["all_rows"]["status"] == "PASS"
    assert aggs["present"]["status"] == "PASS"  # 2 non-null
    assert report["verdict"] == "PASS"


def test_aggregate_determinism_and_report_shape():
    spec = (
        "EVALUATION e\n"
        "CRITERION sum_ok\n"
        "    FIELD SUM(x) <= 10.0\n"
        "END\n"
    )
    rows = [{"x": 1.0}, {"x": 2.0}, {"x": 3.0}]
    a = MiterEngine(parse(spec)).evaluate_all(rows)
    b = MiterEngine(parse(spec)).evaluate_all(rows)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    aggs = {x["id"]: x for x in a["aggregates"]}
    assert aggs["sum_ok"]["value"] == 6.0


def test_row_evaluation_untouched_by_aggregates():
    """Aggregates must not change per-row verdicts or the summary."""
    report = MiterEngine(parse(AGG_SPEC)).evaluate_all(_rows())
    assert report["summary"] == {"rows": 3, "FAIL": 0, "PASS": 3}
    for row in report["results"]:
        assert row["verdict"] == "PASS"


# ---------- compiler notices ----------

def test_temporal_phrase_now_compiles():
    """v0.6: the windowed phrasing compiles to a real WITHIN rule (no NOTICE)."""
    res = compile_text("no more than two missed deliveries in thirty days")
    assert res.valid
    ev = parse(res.spec_text)
    assert ev.criteria[0].within_s == 30 * 86400
    assert not any("not supported" in n.lower() for n in ev.notices)


def test_conditional_phrase_gets_notice():
    res = compile_text("if driver hours exceed 14 then flag the trip")
    assert res.valid
    ev = parse(res.spec_text)
    assert any("conditional" in n.lower() for n in ev.notices)


def test_clean_phrase_gets_no_notice():
    res = compile_text("check that driver hours stay under 14")
    assert res.valid
    ev = parse(res.spec_text)
    assert ev.notices == []