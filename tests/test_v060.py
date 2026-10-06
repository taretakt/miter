"""v0.6.0 — the compiler catches up.

The deterministic NL compiler now emits real windowed and aggregate specs,
instead of warming about them:

  "no more than two missed deliveries in thirty days"
    -> CRITERION ... FIELD missed_deliveries <= 0  WITHIN 30d  LIMIT 2  TIME t

  "average coverage must be at least 90 percent"
    -> CRITERION ... FIELD SUM/AVG(coverage) >= 0.9

Pragmatics kept honest:
- predicates are drafts: SEVERITY warn + a NOTE naming what must be edited
  (window length, LIMIT, or the predicate polarity) -- the compiler guesses
  the encoding, never the data.
- months approximate to 30d, years to 365d, stated in a NOTE.
- the windowed NOTICE is retired for the compilable form and kept for the
  rest (rolling, consecutive).
"""

from miter.compiler import compile_text
from miter.parser import MiterError, parse


# ---------- windowed phrasings ----------

def test_no_more_than_in_days_compiles_to_window():
    res = compile_text("no more than two missed deliveries in thirty days")
    assert res.valid
    spec = res.spec_text
    assert "FIELD missed_deliveries <= 0" in spec
    assert "WITHIN" in spec
    assert "LIMIT 2" in spec
    ev = parse(spec)
    c = ev.criteria[0]
    assert c.within_s == 30 * 86400
    assert c.limit == 2
    assert c.severity == "warn"
    # windowed NOTICE is gone for the compilable form
    assert not any("window" in n.lower() for n in ev.notices)
    assert not any("window" in n.lower() for n in res.notes)


def test_at_most_in_weeks_compiles():
    res = compile_text("at most five late arrivals in any two weeks")
    assert res.valid
    ev = parse(res.spec_text)
    c = ev.criteria[0]
    assert c.limit == 5
    assert c.within_s == 14 * 86400


def test_window_without_duration_defaults_with_note():
    res = compile_text("no more than two missed deliveries")
    assert res.valid
    ev = parse(res.spec_text)
    c = ev.criteria[0]
    assert c.within_s == 7 * 86400  # documented default
    assert c.severity == "warn"
    assert any("window length" in n for n in ev.notices) or any(
        "edit WITHIN" in n for n in (c.note, *ev.notices)
    )


# ---------- aggregate phrasings ----------

def test_average_percent_compiles_to_avg():
    res = compile_text("average coverage must be at least 90 percent")
    assert res.valid
    spec = res.spec_text
    assert "FIELD AVG(coverage) >= 0.9" in spec
    assert "INPUTS coverage" in spec  # clean inputs list, no wrapped junk


def test_sum_compiles():
    res = compile_text("sum of load must not exceed 1000")
    assert res.valid
    assert "FIELD SUM(load) <= 1000" in res.spec_text


def test_count_compiles():
    res = compile_text("count of failures must not exceed five")
    assert res.valid
    ev = parse(res.spec_text)
    assert ev.criteria[0].agg == "count"


def test_min_max_compile():
    a = compile_text("minimum temperature must stay above -40")
    assert "FIELD MIN(temperature) > -40" in a.spec_text
    b = compile_text("maximum load must be under 20 tons")
    assert "FIELD MAX(load) < 20" in b.spec_text


def test_aggregate_no_junk_criteria():
    """The aggregate phrase must not leak a plain-field junk criterion."""
    res = compile_text("average coverage must be at least 90 percent")
    ev = parse(res.spec_text)
    assert len(ev.criteria) == 1
    assert ev.criteria[0].agg == "avg"


# ---------- NOTICE discipline ----------

def test_rolling_still_notices():
    res = compile_text("rolling 30-day average of handle time must stay under 5")
    assert res.valid
    ev = parse(res.spec_text)
    assert any("not supported" in n.lower() for n in ev.notices)
    assert "WITHIN" not in res.spec_text


def test_clean_phrase_still_clean():
    res = compile_text("check that driver hours stay under 14")
    assert res.valid
    assert len(res.notes) == 0


def test_compile_deterministic():
    for phrase in [
        "no more than two missed deliveries in thirty days",
        "average coverage must be at least 90 percent",
        "sum of load must not exceed 1000",
    ]:
        a = compile_text(phrase).spec_text
        b = compile_text(phrase).spec_text
        assert a == b