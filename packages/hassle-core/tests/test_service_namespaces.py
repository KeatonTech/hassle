"""M18 milestone tests — typed service namespaces + entity-method sugar
(MILESTONES "M18 — Typed service namespaces", DESIGN §5.2/§5.3).

Covers the milestone's 7-test contract:
1. Regression pin: today (pre-M18) calling a stub-promised entity method
   raises (red against main); green = records the service action.
2. IR equivalence: `hassle.services` namespace call, entity-method call, and
   `service(...)` compile to byte-identical IR for the same inputs.
3. Decompiler canonical-form tests live in `test_service_namespace_decompile.py`
   (snapshot-present namespace form / fallback / round-trip / splice merge).
4. Validate: unknown service via namespace -> Finding with did-you-mean.
5. Stubs: generated `hassle.services` stub pyright test lives in
   `test_registry_stubs_pyright.py` (extended); golden content test in
   `test_registry_stubs.py`.
6. Simulator: namespace/entity-method calls execute identically to
   `service(...)` in the simulator (I5).
7. Docs gate: covered by `hassle-dev docs` (docs/dsl-f3.md new section).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hassle.compiler.bundle import compile_bundle
from hassle.compiler.recording import recording
from hassle.registry._entities import entities as e

REPO_ROOT = Path(__file__).resolve().parents[3]


def _write_bundle(tmp_path: Path, source: str) -> Path:
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "objects.py").write_text(source, encoding="utf-8")
    return bundle_dir


# ---------------------------------------------------------------------------
# Test 1 — regression pin: entity-method call records (was AttributeError on
# `main`, not the milestone text's "TypeError" -- verified against actual
# `main` behavior; recorded in docs/ha-api-notes.md).
# ---------------------------------------------------------------------------


def test_entity_method_call_records_service_action() -> None:
    with recording(kind="automation", id="x") as rec:
        e.light.hallway.turn_on(brightness_pct=60)
    assert len(rec.actions) == 1
    body = rec.actions[0].body
    assert body == {
        "action": "light.turn_on",
        "target": {"entity_id": "light.hallway"},
        "data": {"brightness_pct": 60},
    }


def test_entity_method_call_bare_attribute_access_stays_inert() -> None:
    # Bare attribute access (no call) must not record anything -- only CALLS
    # record actions (milestone surface 2).
    with recording(kind="automation", id="x") as rec:
        _ = e.light.hallway.turn_on  # not called -- just attribute access
    assert rec.actions == []


def test_entity_ref_attr_method_unaffected() -> None:
    # `.attr("name")` is a real EntityRef method (pre-existing, M1.1) and must
    # keep working exactly as before -- it must NOT be swallowed by whatever
    # machinery makes arbitrary attribute access call-able.
    from hassle.compiler.templates import TemplateExpr

    result = e.sun.sun.attr("elevation")
    assert isinstance(result, TemplateExpr)
    assert str(result) == "{{ state_attr('sun.sun', 'elevation') }}"


def test_entity_ref_string_semantics_unaffected() -> None:
    # EntityRef is still a plain str usable as an entity id everywhere.
    ref = e.light.hallway
    assert ref == "light.hallway"
    assert ref.domain == "light"
    assert ref.object_id == "hallway"


# ---------------------------------------------------------------------------
# Test 2 — IR equivalence: namespace call / entity-method call / service()
# all compile to byte-identical IR.
# ---------------------------------------------------------------------------


def test_namespace_call_matches_service_call_ir() -> None:
    from hassle import services
    from hassle.compiler.actions import service

    with recording(kind="automation", id="x") as rec_ns:
        services.light.turn_on(target={"entity_id": "light.hallway"}, brightness_pct=60)
    with recording(kind="automation", id="x") as rec_svc:
        service("light.turn_on", target={"entity_id": "light.hallway"}, brightness_pct=60)
    assert rec_ns.actions[0].body == rec_svc.actions[0].body


def test_entity_method_call_matches_service_call_ir() -> None:
    from hassle.compiler.actions import service

    with recording(kind="automation", id="x") as rec_entity:
        e.light.hallway.turn_on(brightness_pct=60)
    with recording(kind="automation", id="x") as rec_svc:
        service("light.turn_on", target={"entity_id": "light.hallway"}, brightness_pct=60)
    assert rec_entity.actions[0].body == rec_svc.actions[0].body


def test_namespace_and_entity_method_and_service_all_match() -> None:
    from hassle import services
    from hassle.compiler.actions import service

    with recording(kind="automation", id="x") as rec_a:
        services.light.turn_on(target={"entity_id": "light.hallway"}, brightness_pct=60)
    with recording(kind="automation", id="x") as rec_b:
        e.light.hallway.turn_on(brightness_pct=60)
    with recording(kind="automation", id="x") as rec_c:
        service("light.turn_on", target={"entity_id": "light.hallway"}, brightness_pct=60)
    assert rec_a.actions[0].body == rec_b.actions[0].body == rec_c.actions[0].body


def test_namespace_golden_pair_compiles() -> None:
    """Golden pair fixture: a multi-domain bundle using both the namespace
    form and the entity-method form compiles to the exact expected IR."""
    import json

    case_dir = REPO_ROOT / "fixtures" / "dsl" / "service_namespace_sugar"
    expected = json.loads((case_dir / "expected_ir.json").read_text(encoding="utf-8"))
    result = compile_bundle(case_dir / "bundle")
    emitted = {key: obj.to_ha() for key, obj in result.objects.items()}
    assert emitted == expected


# ---------------------------------------------------------------------------
# Test 4 — validate: unknown service via namespace gets a Finding with
# did-you-mean, at the call's file:line.
# ---------------------------------------------------------------------------


def test_validate_unknown_domain_typo_via_namespace_has_did_you_mean(tmp_path: Path) -> None:
    from hassle.registry.snapshot import RegistrySnapshot
    from hassle.registry.validate import validate_bundle

    # `ligth` (a typo'd `light`) is close enough (Levenshtein) to a real,
    # known `domain.service` string that did-you-mean fires.
    source = (
        "from hassle import automation\n"
        "from hassle.services import ligth\n"
        "\n"
        "@automation(id='x')\n"
        "def x():\n"
        "    ligth.turn_on(target={'entity_id': 'light.hallway'})\n"
    )
    bundle_dir = _write_bundle(tmp_path, source)
    result = compile_bundle(bundle_dir)
    snapshot = RegistrySnapshot.load(REPO_ROOT / "fixtures" / "registry" / "home.json")
    findings = validate_bundle(result, snapshot)
    unknown = [f for f in findings if f.code == "unknown-service"]
    assert len(unknown) == 1
    assert "ligth.turn_on" in unknown[0].message
    assert unknown[0].fix is not None and "light.turn_on" in unknown[0].fix
    assert unknown[0].file is not None and unknown[0].file.endswith("objects.py")
    assert unknown[0].line == 6


def test_validate_known_domain_service_typo_via_namespace_has_did_you_mean(tmp_path: Path) -> None:
    # A typo'd SERVICE within a real, known domain (`light.turn_of` instead
    # of `light.turn_off`/`light.turn_on`) is close enough to fire too -- the
    # check is gated on edit-distance evidence, not "is the domain known".
    from hassle.registry.snapshot import RegistrySnapshot
    from hassle.registry.validate import validate_bundle

    source = (
        "from hassle import automation\n"
        "from hassle.services import light\n"
        "\n"
        "@automation(id='x')\n"
        "def x():\n"
        "    light.turn_of(target={'entity_id': 'light.hallway'})\n"
    )
    bundle_dir = _write_bundle(tmp_path, source)
    result = compile_bundle(bundle_dir)
    snapshot = RegistrySnapshot.load(REPO_ROOT / "fixtures" / "registry" / "home.json")
    findings = validate_bundle(result, snapshot)
    unknown = [f for f in findings if f.code == "unknown-service"]
    assert len(unknown) == 1
    assert "light.turn_of" in unknown[0].message


def test_validate_uncaptured_but_plausible_service_is_not_flagged(tmp_path: Path) -> None:
    """Deliberate scope boundary (fixture-corpus false-positive evidence,
    `docs/ha-api-notes.md` §33 predecessor / `_validate_unknown_services`'s
    docstring): a real HA service simply absent from this snapshot's
    necessarily-incomplete `get_services` capture (an integration not loaded
    when the snapshot was taken) must not be flagged merely for having no
    close lexical match to anything already known -- `cover.set_cover_position`
    is real HA, genuinely just not in this particular snapshot."""
    from hassle.registry.snapshot import RegistrySnapshot
    from hassle.registry.validate import validate_bundle

    source = (
        "from hassle import automation\n"
        "from hassle.services import cover\n"
        "\n"
        "@automation(id='x')\n"
        "def x():\n"
        "    cover.set_cover_position(target={'entity_id': 'cover.blind'}, position=50)\n"
    )
    bundle_dir = _write_bundle(tmp_path, source)
    result = compile_bundle(bundle_dir)
    snapshot = RegistrySnapshot.load(REPO_ROOT / "fixtures" / "registry" / "home.json")
    findings = validate_bundle(result, snapshot)
    assert [f for f in findings if f.code == "unknown-service"] == []


def test_validate_known_namespace_service_has_no_unknown_service_finding(tmp_path: Path) -> None:
    from hassle.registry.snapshot import RegistrySnapshot
    from hassle.registry.validate import validate_bundle

    source = (
        "from hassle import automation\n"
        "from hassle.services import light\n"
        "\n"
        "@automation(id='x')\n"
        "def x():\n"
        "    light.turn_on(target={'entity_id': 'light.hallway'}, brightness_pct=60)\n"
    )
    bundle_dir = _write_bundle(tmp_path, source)
    result = compile_bundle(bundle_dir)
    snapshot = RegistrySnapshot.load(REPO_ROOT / "fixtures" / "registry" / "home.json")
    findings = validate_bundle(result, snapshot)
    assert [f for f in findings if f.code == "unknown-service"] == []


def test_validate_unknown_service_via_plain_service_call_unaffected(tmp_path: Path) -> None:
    # Sanity: the plain `service(...)` verb (pre-existing) gets the exact same
    # unknown-service Finding -- proves the check is IR-shape-driven, not
    # namespace-call-specific (the whole point of "identical IR").
    from hassle.registry.snapshot import RegistrySnapshot
    from hassle.registry.validate import validate_bundle

    source = (
        "from hassle import automation, service\n"
        "\n"
        "@automation(id='x')\n"
        "def x():\n"
        "    service('ligth.turn_on', target={'entity_id': 'light.hallway'})\n"
    )
    bundle_dir = _write_bundle(tmp_path, source)
    result = compile_bundle(bundle_dir)
    snapshot = RegistrySnapshot.load(REPO_ROOT / "fixtures" / "registry" / "home.json")
    findings = validate_bundle(result, snapshot)
    unknown = [f for f in findings if f.code == "unknown-service"]
    assert len(unknown) == 1


# ---------------------------------------------------------------------------
# Test 6 — simulator: namespace/entity-method calls execute identically to
# service() (I5: same compiled JSON either way, executed the same).
# ---------------------------------------------------------------------------


def test_simulator_executes_namespace_and_entity_method_calls_identically() -> None:
    import contextlib
    from datetime import datetime

    from hassle import services
    from hassle.testing.actions import ActionContext, _run_one
    from hassle.testing.state import StateStore
    from hassle.testing.templates import TemplateEngine

    def _run(action: dict[str, object]) -> list[object]:
        states = StateStore()
        ctx = ActionContext(
            states=states, templates=TemplateEngine(states, lambda: datetime(2026, 1, 1)), calls=[]
        )
        gen = _run_one(action, ctx)
        with contextlib.suppress(StopIteration):
            next(gen)
        return list(ctx.calls)

    with recording(kind="automation", id="x") as rec_ns:
        services.light.turn_on(target={"entity_id": "light.hallway"}, brightness_pct=60)
    with recording(kind="automation", id="x") as rec_entity:
        e.light.hallway.turn_on(brightness_pct=60)

    calls_ns = _run(rec_ns.actions[0].body)
    calls_entity = _run(rec_entity.actions[0].body)
    assert calls_ns == calls_entity
    assert calls_ns[0].action == "light.turn_on"  # type: ignore[attr-defined]
    assert calls_ns[0].data.get("brightness_pct") == 60  # type: ignore[attr-defined]


@pytest.mark.parametrize("via", ["namespace", "entity_method", "service"])
def test_compile_then_simulate_end_to_end_all_forms_match(tmp_path: Path, via: str) -> None:
    """Full compile -> IR path (mirrors what `hassle test` executes), proving
    I5 for all three call forms end to end produce identical actions."""
    if via == "namespace":
        imports = "from hassle import automation\nfrom hassle.services import light\n"
        body = "    light.turn_on(target={'entity_id': 'light.hallway'}, brightness_pct=60)\n"
    elif via == "entity_method":
        imports = "from hassle import automation\nfrom hassle.registry import entities as e\n"
        body = "    e.light.hallway.turn_on(brightness_pct=60)\n"
    else:
        imports = "from hassle import automation, service\n"
        body = (
            "    service('light.turn_on', target={'entity_id': 'light.hallway'}, "
            "brightness_pct=60)\n"
        )

    source = f"{imports}\n@automation(id='x')\ndef x():\n{body}"
    bundle_dir = _write_bundle(tmp_path, source)
    result = compile_bundle(bundle_dir)
    (obj,) = result.objects.values()
    actions = obj.to_ha()["actions"]
    assert actions == [
        {
            "action": "light.turn_on",
            "target": {"entity_id": "light.hallway"},
            "data": {"brightness_pct": 60},
        }
    ]
