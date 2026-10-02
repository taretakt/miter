"""the compiler compiler tests — NL extraction, bounds, and round-trip validity."""

from miter.compiler import compile_text


def test_subject_and_criteria():
    r = compile_text("check that the route respects depot capacity and driver hours")
    assert r.valid
    assert "SUBJECT route" in r.spec_text
    assert "depot_capacity" in r.spec_text
    assert "driver_hours" in r.spec_text


def test_bounded_threshold_hours():
    r = compile_text("check that driver hours stay under 14 hours")
    assert r.valid
    assert "driver_hours < 14" in r.spec_text


def test_no_more_than_percent():
    r = compile_text("depot utilization must not exceed 95%")
    assert r.valid
    assert "depot_utilization <= 0.95" in r.spec_text


def test_exactly():
    r = compile_text("the batch size must be exactly 32")
    assert r.valid
    assert "batch_size == 32" in r.spec_text


def test_at_least():
    r = compile_text("equipment availability must be at least 99%")
    assert r.valid
    assert "equipment_availability >= 0.99" in r.spec_text


def test_unbounded_criterion_is_warn():
    r = compile_text("check that the route respects driver hours")
    assert r.valid
    assert "SEVERITY warn" in r.spec_text


def test_ghost_car_interface():
    r = compile_text("the truck must match the lane velocity within 10%")
    assert r.valid
    assert "INTERFACE iface_1" in r.spec_text
    assert "TOLERANCE 0.1" in r.spec_text
    assert "MATCH velocity TO lane_velocity" in r.spec_text


def test_merge_sync_fallback():
    r = compile_text("the vehicle must merge and sync with the expressway lane")
    assert r.valid


def test_compile_is_deterministic():
    a = compile_text("check that the route respects depot capacity and driver hours")
    b = compile_text("check that the route respects depot capacity and driver hours")
    assert a.spec_text == b.spec_text


def test_all_outputs_parse():
    samples = [
        "check that the route respects depot capacity and driver hours",
        "driver hours must stay under 14",
        "depot utilization must not exceed 95%",
        "the batch size must be exactly 32",
        "equipment availability must be at least 99%",
        "check that the route respects driver hours",
        "the truck must match the lane velocity within 10%",
        "the vehicle must merge and sync with the expressway lane",
        "validate that on-time percentage is over 98%",
        "verify temperature stays below 4 degrees",
        "test that throughput is at least 100 units per hour",
    ]
    for s in samples:
        r = compile_text(s)
        assert r.valid, f"failed to compile: {s!r}\n{r.spec_text}"