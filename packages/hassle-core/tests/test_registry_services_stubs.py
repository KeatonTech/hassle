"""M18 milestone test 5 — the `hassle.services` stub generator.

Generated alongside the entities stub (same write path, `hassle stubs` and
`hassle pull`'s auto-refresh both emit it): per-domain classes, typed kwargs
from `snapshot.services`, reusing `_service_method`'s field typing. Golden-
tests the generated content against `fixtures/registry/home.json`.
"""

from __future__ import annotations

import ast
import os
import subprocess
from pathlib import Path

import pytest

from hassle.registry.snapshot import RegistrySnapshot
from hassle.registry.stubs import generate_services_stub

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE = REPO_ROOT / "fixtures" / "registry" / "home.json"
GOLDEN = Path(__file__).resolve().parent / "snapshots" / "stubs" / "services.pyi"


@pytest.fixture(scope="module")
def snapshot() -> RegistrySnapshot:
    return RegistrySnapshot.load(FIXTURE)


def _check_golden(actual: str) -> None:
    if os.environ.get("HASSLE_UPDATE_SNAPSHOTS"):
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(actual, encoding="utf-8")
    assert GOLDEN.is_file(), f"missing golden {GOLDEN}; set HASSLE_UPDATE_SNAPSHOTS=1 to write it"
    assert actual == GOLDEN.read_text(encoding="utf-8")


def test_services_stub_golden_matches(snapshot: RegistrySnapshot) -> None:
    actual = generate_services_stub(snapshot)
    _check_golden(actual)


def test_services_stub_contains_domain_module_attr(snapshot: RegistrySnapshot) -> None:
    stub = generate_services_stub(snapshot)
    assert "light: " in stub or "light:" in stub


def test_services_stub_contains_typed_service_method(snapshot: RegistrySnapshot) -> None:
    stub = generate_services_stub(snapshot)
    assert "def turn_on(" in stub
    assert "brightness_pct" in stub


def test_services_stub_service_functions_accept_target(snapshot: RegistrySnapshot) -> None:
    """Regression test (task #28, annotation-truth pass): every generated
    ``@staticmethod`` service function must accept a ``target=`` parameter --
    the decompiler's own canonical namespace-form output
    (``light.turn_on(target=e.light.hallway, ...)``, MILESTONES M18) was a
    hard `reportCallIssue` ("No parameter named 'target'") in a real
    decompiled bundle before this, since the underlying
    ``hassle.compiler.actions.service`` call this delegates to always accepts
    ``target=``."""
    stub = generate_services_stub(snapshot)
    # Round 2 widened the annotation to the _TargetArg alias (purpose-target
    # helpers) -- the contract here is only that target= exists on every
    # generated function.
    assert "target: _TargetArg = ..." in stub
    assert "from collections.abc import Sequence" in stub


def test_services_stub_module_getattr_present(snapshot: RegistrySnapshot) -> None:
    """The module-level `__getattr__` PEP 562 fallback must ALSO be typed (so
    an unlisted/future domain doesn't become a hard pyright error) -- matches
    the entities stub's own `_EntitiesRegistry.__getattr__` fallback pattern."""
    stub = generate_services_stub(snapshot)
    assert "def __getattr__(" in stub


def test_services_stub_module_getattr_suppresses_incomplete_stub(
    snapshot: RegistrySnapshot,
) -> None:
    """N1 (reviewer non-blocking note): a bare module-level ``def
    __getattr__`` trips pyright's ``reportIncompleteStub`` ("obscures type
    errors for module") -- unlike the entities stub, `hassle.services` is a
    REAL module at runtime (not a variable holding an instance), so the
    class-indirection trick the entities stub uses for ITS `__getattr__`
    doesn't apply here without breaking the direct `from hassle.services
    import light` import shape. Explicitly suppressed with a targeted
    `# pyright: ignore[reportIncompleteStub]` instead (verified end-to-end by
    the pyright integration test, which escalates the rule to `error` and
    asserts zero)."""
    stub = generate_services_stub(snapshot)
    getattr_lines = [line for line in stub.splitlines() if line.startswith("def __getattr__(")]
    assert len(getattr_lines) == 1
    assert "# pyright: ignore[reportIncompleteStub]" in getattr_lines[0]


def test_services_stub_is_valid_python(snapshot: RegistrySnapshot) -> None:
    stub = generate_services_stub(snapshot)
    ast.parse(stub)


def test_services_stub_is_ruff_format_clean(snapshot: RegistrySnapshot, tmp_path: Path) -> None:
    stub = generate_services_stub(snapshot)
    stub_path = tmp_path / "services.pyi"
    stub_path.write_text(stub, encoding="utf-8")
    proc = subprocess.run(
        ["ruff", "format", "--check", str(stub_path)],
        capture_output=True,
        text=True,
    )
    if proc.returncode == 127 or "not found" in (proc.stderr or "").lower():
        pytest.skip("ruff not available in this environment")
    assert proc.returncode == 0, f"ruff format --check failed:\n{proc.stdout}\n{proc.stderr}"


def test_service_functions_accept_envelope_kwargs(snapshot: RegistrySnapshot) -> None:
    """Owner field report (BrandtCamp prettify pass): every decompiled call
    carries `metadata={}` and response services use `response_variable=` --
    universal envelope kwargs, not snapshot fields. Both stub forms must
    accept them or every real bundle turns red with reportCallIssue."""
    from hassle.registry.stubs import generate_entities_stub

    for stub in (generate_services_stub(snapshot), generate_entities_stub(snapshot)):
        assert "metadata: dict[str, Any] = ..." in stub
        assert "response_variable: str = ..." in stub


def test_envelope_kwarg_skipped_when_field_claims_the_name() -> None:
    """A per-service field literally named `enabled` (legal as an HA data
    key) must not produce a duplicate parameter -- the field wins and the
    generated stub stays syntactically valid."""
    from hassle.registry.snapshot import ServiceDef, ServiceField
    from hassle.registry.stubs import _envelope_params, _service_function

    service = ServiceDef(
        name="Exotic",
        description="",
        fields={"enabled": ServiceField(type="boolean", selector={"boolean": {}})},
    )
    assert not any(p.startswith("enabled:") for p in _envelope_params(service))
    rendered = "\n".join(_service_function("exotic", service))
    assert rendered.count("enabled:") == 1
    assert "metadata: dict[str, Any] = ..." in rendered


def test_keyword_field_names_are_skipped() -> None:
    """HA really ships a `calendar.create_event` field literally named `in`
    (owner field report, round 2): a Python keyword can never be passed as a
    kwarg, and emitting it makes the whole generated .pyi a syntax error."""
    import ast

    from hassle.registry.snapshot import ServiceDef, ServiceField
    from hassle.registry.stubs import _service_function, _service_method

    service = ServiceDef(
        name="Create event",
        description="",
        fields={
            "in": ServiceField(type="string", selector={"text": {}}),
            "summary": ServiceField(type="string", selector={"text": {}}),
        },
    )
    for rendered in (
        "\n".join(_service_function("create_event", service)),
        "\n".join(_service_method("create_event", service)),
    ):
        assert "in:" not in rendered
        assert "summary: str" in rendered
        ast.parse(rendered.replace("@staticmethod\n", "").strip())


def test_entity_classes_expose_attr(snapshot: RegistrySnapshot) -> None:
    """`e.cover.x.attr("current_position")` is real DSL surface
    (EntityRef.attr, M16) -- the stub classes must declare it or every use
    is a reportAttributeAccessIssue (owner field report, round 2)."""
    from hassle.registry.stubs import generate_entities_stub

    assert "def attr(self, attribute: str) -> Any: ..." in generate_entities_stub(snapshot)


def test_namespace_target_accepts_purpose_targets(snapshot: RegistrySnapshot) -> None:
    """`light.turn_on(target=area("kitchen"))` is canonical decompiler output
    -- the namespace stubs' target= must accept the public target helpers'
    return types (AreaTarget/FloorTarget/LabelTarget/DeviceIdTarget), not
    just str/sequence/dict (owner field report, round 2)."""
    stub = generate_services_stub(snapshot)
    assert "from hassle.compiler.purpose import" in stub
    assert (
        "type _SingleTarget = str | AreaTarget | DeviceIdTarget | FloorTarget | LabelTarget" in stub
    )
    assert "type _TargetArg = _SingleTarget | Sequence[_SingleTarget] | dict[str, Any]" in stub
    assert "target: _TargetArg = ..." in stub
    assert "target: str | Sequence[str]" not in stub


def test_entity_method_shadowing_str_gets_targeted_ignore() -> None:
    """Entity classes subclass str (task #28 annotation-truth), so a service
    named after a str method (media_player.join, owner field report round 3)
    is an incompatible override -- suppressed per-method, never file-wide."""
    from hassle.registry.snapshot import ServiceDef, ServiceField
    from hassle.registry.stubs import _service_method

    join = ServiceDef(
        name="Join",
        description="",
        fields={"group_members": ServiceField(type="string", selector={"text": {}})},
    )
    rendered = _service_method("join", join)
    # pyright reports the override error on the `def` line -- an ignore
    # anywhere else (e.g. the wrapped form's closing paren line, round 3's
    # bug) suppresses nothing.
    assert rendered[0].rstrip().endswith(
        "# pyright: ignore[reportIncompatibleMethodOverride]"
    ), rendered[0]
    rendered = "\n".join(rendered)
    plain = "\n".join(_service_method("turn_on", join))
    assert "pyright: ignore" not in plain
