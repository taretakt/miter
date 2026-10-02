"""Engine tests — determinism, verdicts, variations, ghost-car interfaces."""

import json
import subprocess
import sys

from miter.engine import MiterEngine
from miter.model import Evaluation
from miter.parser import parse

SPEC = """
EVALUATION route_feasibility
SUBJECT route
INPUTS depot_capacity driver_hours

CRITERION depot_within_capacity
    FIELD depot_capacity <= 0.95

CRITERION driver_within_hours
    FIELD driver_hours <= 14.0

VARIATION peak_volume
    ADJUST depot_capacity SCALE 1.2

INTERFACE merge_onto_expressway
    FROM collector TO expressway
    MATCH velocity TO lane_velocity
    TOLERANCE 0.10
    BUDGET 20m
    TIME t
END
"""


def make_engine() -> MiterEngine:
    return MiterEngine(parse(SPEC))


def test_clean_route_passes():
    rows = [
        {"depot_capacity": 0.75, "driver_hours": 11.5, "velocity": 98.0,
         "lane_velocity": 100.0, "t": 600}
    ]
    report = make_engine().evaluate_all(rows)
    assert report["summary"] == {"rows": 1, "FAIL": 0, "PASS": 1}
    row = report["results"][0]
    assert row["verdict"] == "PASS"
    assert row["criteria"]["depot_within_capacity"]["status"] == "PASS"
    assert row["criteria"]["driver_within_hours"]["status"] == "PASS"
    assert row["interfaces"]["merge_onto_expressway"]["status"] == "MATCHED"


def test_over_capacity_fails():
    rows = [{"depot_capacity": 0.97, "driver_hours": 13.2, "velocity": 105.0,
             "lane_velocity": 100.0, "t": 900}]
    report = make_engine().evaluate_all(rows)
    assert report["summary"]["FAIL"] == 1
    row = report["results"][0]
    assert row["criteria"]["depot_within_capacity"]["status"] == "FAIL"
    assert row["verdict"] == "FAIL"


def test_driver_hours_fail():
    rows = [{"depot_capacity": 0.88, "driver_hours": 15.1, "velocity": 96.0,
             "lane_velocity": 100.0, "t": 600}]
    report = make_engine().evaluate_all(rows)
    assert report["results"][0]["criteria"]["driver_within_hours"]["status"] == "FAIL"
    assert report["results"][0]["verdict"] == "FAIL"


def test_interface_velocity_mismatch():
    rows = [{"depot_capacity": 0.8, "driver_hours": 10.0, "velocity": 120.0,
             "lane_velocity": 100.0, "t": 600}]
    row = make_engine().evaluate_row(rows[0])
    assert row["interfaces"]["merge_onto_expressway"]["status"] == "MISMATCHED"
    assert row["verdict"] == "FAIL"


def test_interface_over_budget():
    rows = [{"depot_capacity": 0.8, "driver_hours": 10.0, "velocity": 100.0,
             "lane_velocity": 100.0, "t": 1500}]
    row = make_engine().evaluate_row(rows[0])
    iface = row["interfaces"]["merge_onto_expressway"]
    assert iface["status"] == "MISMATCHED"
    assert iface["budget"] == "OVER"


def test_variation_turns_pass_into_fail():
    rows = [{"depot_capacity": 0.9, "driver_hours": 11.0, "velocity": 100.0,
             "lane_velocity": 100.0, "t": 600}]
    row = make_engine().evaluate_row(rows[0])
    # base passes...
    assert row["criteria"]["depot_within_capacity"]["status"] == "PASS"
    peak = row["variations"]["peak_volume"]
    # 0.9 * 1.2 = 1.08 > 0.95 -> fails under peak
    assert peak["criteria"]["depot_within_capacity"]["status"] == "FAIL"
    # ...but a variation failure fails the row (edge conditions must hold)
    assert row["verdict"] == "FAIL"


def test_missing_fields_are_na():
    rows = [{"depot_capacity": 0.8}]
    row = make_engine().evaluate_row(rows[0])
    assert row["criteria"]["driver_within_hours"]["status"] == "NA"
    assert row["interfaces"]["merge_onto_expressway"]["status"] == "NA"


def test_to_json_is_deterministic():
    rows = [
        {"depot_capacity": 0.75, "driver_hours": 11.5, "velocity": 98.0,
         "lane_velocity": 100.0, "t": 600},
        {"depot_capacity": 0.97, "driver_hours": 13.2, "velocity": 105.0,
         "lane_velocity": 100.0, "t": 900},
    ]
    engine = make_engine()
    a = engine.to_json(rows)
    b = engine.to_json(rows)
    assert a == b
    # and the parsed structure is stable across json round-trips
    assert json.loads(a) == json.loads(b)


def test_nested_field_paths():
    spec = """
EVALUATION trip_check
SUBJECT trip
CRITERION within_window
    FIELD trip.duration <= 12.0
END
"""
    engine = MiterEngine(parse(spec))
    row = engine.evaluate_row({"trip": {"duration": 9.5}})
    assert row["criteria"]["within_window"]["status"] == "PASS"
    row2 = engine.evaluate_row({"trip": {}})
    assert row2["criteria"]["within_window"]["status"] == "NA"


def test_cli_run_roundtrip():
    """The CLI is the public surface; make sure it exits non-zero on failures."""
    import os
    import tempfile

    spec_path = os.path.join(tempfile.mkdtemp(), "spec.mtr")
    data_path = os.path.join(tempfile.mkdtemp(), "rows.json")
    with open(spec_path, "w") as f:
        f.write(SPEC)
    with open(data_path, "w") as f:
        json.dump([
            {"depot_capacity": 0.75, "driver_hours": 11.5, "velocity": 98.0,
             "lane_velocity": 100.0, "t": 600}
        ], f)

    ok = subprocess.run(
        [sys.executable, "-m", "miter.cli", "run", spec_path, "--data", data_path],
        capture_output=True, text=True,
    )
    assert ok.returncode == 0, ok.stderr

    with open(data_path, "w") as f:
        json.dump([
            {"depot_capacity": 0.97, "driver_hours": 13.2, "velocity": 105.0,
             "lane_velocity": 100.0, "t": 900}
        ], f)
    bad = subprocess.run(
        [sys.executable, "-m", "miter.cli", "run", spec_path, "--data", data_path],
        capture_output=True, text=True,
    )
    assert bad.returncode == 1, bad.stdout