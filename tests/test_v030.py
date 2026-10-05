"""v0.3.0 — categorical equality.

`FIELD tag == "urgent"` compares exact strings (== and != only, no ordering).
Still byte-deterministic: string comparison is exact. Missing field -> N/A.
The compiler's closed phrasings now cover "tagged/classified/labeled as X"
and "status/type must be X" — these no longer need a NOTICE.
"""

import json

import pytest

from miter.compiler import compile_text
from miter.engine import MiterEngine
from miter.parser import MiterError, parse

CAT_SPEC = """
EVALUATION triage
SUBJECT ticket
INPUTS tag
CRITERION is_urgent
    FIELD tag == "urgent"
    SEVERITY error
CRITERION not_paid
    FIELD status != "paid"
    SEVERITY warn
END
"""


# ---------- parser ----------

def test_string_equality_parses():
    ev = parse(CAT_SPEC)
    assert ev.criteria[0].threshold_str == "urgent"
    assert ev.criteria[0].op == "=="
    assert ev.criteria[1].threshold_str == "paid"
    assert ev.criteria[1].op == "!="


def test_string_value_ops_restricted():
    with pytest.raises(MiterError):
        parse(
            "EVALUATION e\n"
            "CRITERION c\n"
            "    FIELD tag < \"urgent\"\n"
            "END\n"
        )


def test_string_equality_affects_spec_hash():
    a = parse("EVALUATION e\nCRITERION c\n    FIELD tag == \"urgent\"\nEND\n")
    b = parse("EVALUATION e\nCRITERION c\n    FIELD tag == \"normal\"\nEND\n")
    assert a.spec_hash() != b.spec_hash()


# ---------- engine ----------

def test_string_match_passes():
    rows = [{"tag": "urgent"}]
    row = MiterEngine(parse(CAT_SPEC)).evaluate_row(rows[0])
    assert row["criteria"]["is_urgent"]["status"] == "PASS"
    assert row["verdict"] == "PASS"


def test_string_mismatch_fails():
    row = MiterEngine(parse(CAT_SPEC)).evaluate_row({"tag": "normal"})
    assert row["criteria"]["is_urgent"]["status"] == "FAIL"
    assert row["verdict"] == "FAIL"


def test_string_missing_is_na():
    row = MiterEngine(parse(CAT_SPEC)).evaluate_row({})
    assert row["criteria"]["is_urgent"]["status"] == "NA"


def test_string_ne_is_mismatch_too():
    # status != "paid": a "paid" row is the mismatch for !=
    spec = "EVALUATION e\nCRITERION c\n    FIELD status != \"paid\"\nEND\n"
    row = MiterEngine(parse(spec)).evaluate_row({"status": "paid"})
    assert row["criteria"]["c"]["status"] == "FAIL"
    row2 = MiterEngine(parse(spec)).evaluate_row({"status": "open"})
    assert row2["criteria"]["c"]["status"] == "PASS"


def test_numeric_looking_string_value():
    spec = "EVALUATION e\nCRITERION c\n    FIELD code == \"42\"\nEND\n"
    engine = MiterEngine(parse(spec))
    assert engine.evaluate_row({"code": "42"})["criteria"]["c"]["status"] == "PASS"
    assert engine.evaluate_row({"code": 42})["criteria"]["c"]["status"] == "PASS"


def test_string_report_shape():
    report = MiterEngine(parse(CAT_SPEC)).evaluate_all([{"tag": "urgent", "status": "open"}])
    c = report["results"][0]["criteria"]["is_urgent"]
    assert c["value"] == "urgent"
    assert c["threshold"] == "urgent"


def test_determinism_with_strings():
    spec = "EVALUATION e\nCRITERION c\n    FIELD tag == \"urgent\"\nEND\n"
    engine = MiterEngine(parse(spec))
    a = engine.to_json([{"tag": "urgent"}, {"tag": "normal"}])
    b = engine.to_json([{"tag": "urgent"}, {"tag": "normal"}])
    assert a == b


# ---------- compiler ----------

def test_compile_tagged_as_categorical():
    res = compile_text("shipments tagged as hazardous must be reviewed")
    assert res.valid
    spec = res.spec_text
    assert 'FIELD shipments == "hazardous"' in spec
    assert not any("categorical" in n.lower() for n in res.notes)


def test_compile_status_must_be_categorical():
    res = compile_text("status must be paid")
    assert res.valid
    assert 'FIELD status == "paid"' in res.spec_text


def test_clean_phrase_still_no_notice():
    res = compile_text("check that driver hours stay under 14")
    assert res.valid
    assert parse(res.spec_text).notices == []


def test_clean_phrase_no_categorical_noise():
    """The categorical rule must not fire on ordinary numeric phrases."""
    res = compile_text("depot utilization must not exceed 95 percent")
    assert '"' not in res.spec_text
    assert parse(res.spec_text).notices == []