"""DSL-coverage metric: >= 90% of fixture objects decompile with zero
``raw_*`` nodes; the report lists the exceptions as a tracked,
machine-readable artifact.

``analyze_coverage`` walks the *decompiled* form (not the JSON) so it counts
what actually ended up as ``raw_trigger``/``raw_condition``/``raw_action``/
``raw_automation`` in the generated source, per object.
"""

from __future__ import annotations

from _corpus import Fixture, load_corpus

from hassle.decompiler import analyze_coverage
from hassle.ir import parse

CORPUS: list[Fixture] = load_corpus()


def _objects() -> dict[str, object]:
    objects: dict[str, object] = {}
    for fx in CORPUS:
        key_hint = fx.key_hint
        if fx.kind == "automation" and "id" not in fx.config:
            key_hint = fx.name
        obj = parse(fx.config, kind=fx.kind, key_hint=key_hint)
        objects[obj.object_key()] = obj  # type: ignore[attr-defined]
    return objects


def test_coverage_report_structure() -> None:
    report = analyze_coverage(_objects())
    assert report.total_objects == len(CORPUS)
    assert 0.0 <= report.clean_fraction <= 1.0
    # Every exception names the object key and its raw-node count.
    for exc in report.exceptions:
        assert exc.object_key
        assert exc.raw_node_count >= 1


def test_coverage_meets_90_percent_gate() -> None:
    report = analyze_coverage(_objects())
    assert report.clean_fraction >= 0.90, (
        f"DSL coverage {report.clean_fraction:.1%} is below the 90% gate; "
        f"raw_* exceptions: {[e.object_key for e in report.exceptions]}"
    )


def test_legacy_device_trigger_is_a_known_exception() -> None:
    # `device()` triggers/conditions have no stable cross-integration schema
    # (DESIGN §5.4: "device() (raw passthrough)") -- decompiling one is expected
    # to require a raw_* node, so it's a tracked, accepted exception, not a bug.
    report = analyze_coverage(_objects())
    exception_keys = {e.object_key for e in report.exceptions}
    device_trigger_keys = {
        key for key in _objects() if "device_trigger" in key or "condition_device" in key
    }
    # At least one device-shaped fixture is present and is (correctly) not clean.
    assert device_trigger_keys
    assert device_trigger_keys & exception_keys
