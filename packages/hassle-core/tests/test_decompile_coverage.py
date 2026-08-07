"""DSL-coverage metric: >= 90% of fixture objects decompile with zero
``raw_*`` nodes; the report lists the exceptions as a tracked,
machine-readable artifact.

``analyze_coverage`` walks the *decompiled* form (not the JSON) so it counts
what actually ended up as ``raw_trigger``/``raw_condition``/``raw_action``/
``raw_automation`` (or, for dashboards, ``raw_card``/``raw_section``/
``raw_view``/``raw_dashboard``, docs/internals/dashboards-design.md §5.5/§6.2)
in the generated source, per object.

**Dashboards are folded into the 90% gate** (docs/internals/dashboards-design.md
§6.2): with all 47 built-in card builders merged (DB3) and the registry-driven
decompiler emitter handling the varargs-rows and single-dict-child container
conventions those builders use, the corpus-wide fraction holds >= 90% with
dashboards included -- see ``test_dashboard_coverage_is_reported`` for the
per-kind breakdown and the exact, individually-justified exceptions that
remain (backstop proofs, not bugs: a `custom:` card, the strategy dashboard,
a legacy bare-string badge, and one card whose stored shape genuinely can't
be reproduced through its typed builder without breaking byte-exact
round-trip -- each documented at its own assertion below).
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


def _dashboard_objects() -> dict[str, object]:
    return {key: obj for key, obj in _objects().items() if key.startswith("dashboard:")}


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


def test_dashboard_coverage_is_reported() -> None:
    """Dashboards get their own reported percentage (docs/internals/
    dashboards-design.md §6.2). With DB3's 47 card builders merged, only 4
    of the 12 corpus fixtures still carry a `raw_*` node -- each individually
    justified (backstop proofs, not bugs):

    - ``dashboard:custom-cards`` -- two genuine `custom:`-prefixed cards
      (no stable schema Hassle could model generically);
    - ``dashboard:auto-generated`` -- the strategy dashboard (no `views` at
      all, `@raw_dashboard` is the only lossless shape);
    - ``dashboard:badges-showcase`` -- a view with a legacy bare-string
      badge entry (`badge()` has no shape that reproduces one, ha-api-notes
      §39);
    - ``dashboard:entity-filter-demo`` -- a presentation card stored as a
      bare ``{"type": "glance"}`` with NO ``entities:`` key at all;
      ``c.glance()`` ALWAYS materializes ``entities: []`` even for zero rows
      (verified: compiling ``c.glance()`` produces
      ``{"type": "glance", "entities": []}``, never the bare dict), so using
      the typed builder here would silently ADD a key the original never
      had -- raw_card is the only byte-exact choice, the same
      always-materialized-key rule that already governs every varargs-rows
      family.

    Every exception is self-describing (a real justification string, never
    a bare count).
    """
    dashboards = _dashboard_objects()
    assert len(dashboards) >= 10
    report = analyze_coverage(dashboards)
    assert report.total_objects == len(dashboards)
    exception_keys = {e.object_key for e in report.exceptions}
    assert exception_keys == {
        "dashboard:custom-cards",
        "dashboard:auto-generated",
        "dashboard:badges-showcase",
        "dashboard:entity-filter-demo",
    }
    for exc in report.exceptions:
        assert exc.justifications
        for justification in exc.justifications:
            assert justification.strip()


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
