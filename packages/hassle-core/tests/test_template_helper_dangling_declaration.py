"""M13 reviewer finding B1 (PR #8) -- dangling `state=`-omitted template-helper
declaration guard.

A `template_number`/`template_sensor`/`template_binary_sensor`/`template_select`
call that omits `state=` (the M13 decorator-form signal) but is never applied
as a decorator over a function builds and registers NOTHING. On the pre-M13
call form the same bare call registered a (degenerate, `state=None`) object;
after M13 added decorator detection this became a silent no-op -- a behavior
regression AND an I6 hazard: if the helper already exists in HA, its
declaration vanishing from the compiled set schedules a DELETE of the live
object on the next plan/push. `template_number`/`template_select` are
accidentally protected already (the write-target guard,
`MissingTemplateHelperWriteTargetError`, fires first since they have no
`state=` write-target-adjacent field either) -- `template_sensor`/
`template_binary_sensor` (read-only, no write-target requirement) are the
exposed domains this guard closes.

`hassle.compiler.bundle.compile_registered`'s compile-end sweep
(`check_no_dangling_template_helper_declarations`) is the sweep site -- it
runs for BOTH `compile_bundle` (whole-bundle loader) and any direct
`compile_registered` caller, so golden error-case fixtures
(`fixtures/dsl/template_sensor_dangling_declaration/`) exercise it exactly
like every other compile-time DSL error.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hassle import template_binary_sensor, template_sensor
from hassle.compiler import DanglingTemplateHelperDeclarationError
from hassle.compiler.bundle import compile_bundle
from hassle.compiler.registry import fresh
from hassle.compiler.template_helpers import reset_declared_template_helpers
from hassle_dev.snapshots import check_snapshot, normalize_error

FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "dsl"
    / "template_sensor_dangling_declaration"
    / "bundle"
)


SNAP_DIR = Path(__file__).resolve().parent / "snapshots" / "errors"


def _check_snapshot(name: str, actual: str) -> None:
    check_snapshot(SNAP_DIR, name, actual)


def _normalize(msg: str) -> str:
    return normalize_error(msg, mask_lines_for=Path(__file__).name)


@pytest.fixture(autouse=True)
def _reset():
    reset_declared_template_helpers()
    fresh()
    yield
    reset_declared_template_helpers()


# ---------------------------------------------------------------------------
# (a) unit test for the dangling case, per read-only domain (sensor/
# binary_sensor -- the two domains with no write-target guard already
# catching this).
# ---------------------------------------------------------------------------


def test_dangling_template_sensor_declaration_raises_at_compile_end() -> None:
    from hassle.compiler.bundle import compile_registered
    from hassle.compiler.registry import current_registry

    template_sensor(name="Ghost Sensor")  # no state=, never decorated
    with pytest.raises(DanglingTemplateHelperDeclarationError) as excinfo:
        compile_registered(list(current_registry().objects), list(current_registry().prebuilt))
    msg = str(excinfo.value)
    assert "template_sensor" in msg
    assert "never used as a decorator" in msg


def test_dangling_template_binary_sensor_declaration_raises_at_compile_end() -> None:
    from hassle.compiler.registry import current_registry

    template_binary_sensor(name="Ghost Binary Sensor")  # no state=, never decorated
    from hassle.compiler.bundle import compile_registered

    with pytest.raises(DanglingTemplateHelperDeclarationError) as excinfo:
        compile_registered(list(current_registry().objects), list(current_registry().prebuilt))
    msg = str(excinfo.value)
    assert "template_binary_sensor" in msg
    assert "never used as a decorator" in msg


def test_dangling_declaration_error_names_file_and_line() -> None:
    from hassle.compiler.bundle import compile_registered
    from hassle.compiler.registry import current_registry

    template_sensor(name="Ghost Sensor")
    with pytest.raises(DanglingTemplateHelperDeclarationError) as excinfo:
        compile_registered(list(current_registry().objects), list(current_registry().prebuilt))
    msg = str(excinfo.value)
    assert "test_template_helper_dangling_declaration.py" in msg
    assert "Fix:" in msg


def test_dangling_declaration_error_message_snapshot() -> None:
    from hassle.compiler.bundle import compile_registered
    from hassle.compiler.registry import current_registry

    template_sensor(name="Ghost Sensor")
    with pytest.raises(DanglingTemplateHelperDeclarationError) as excinfo:
        compile_registered(list(current_registry().objects), list(current_registry().prebuilt))
    _check_snapshot("template_helper_dangling_declaration", _normalize(str(excinfo.value)))


def test_properly_decorated_declaration_never_dangles() -> None:
    """Sanity companion: a properly-applied decorator is consumed and never
    trips the sweep."""
    from hassle import expr
    from hassle.compiler.bundle import compile_registered
    from hassle.compiler.registry import current_registry
    from hassle.registry import entities as e

    @template_sensor(name="Real Sensor")
    def real_sensor():
        return expr(e.sensor.a)

    result = compile_registered(list(current_registry().objects), list(current_registry().prebuilt))
    assert "template_sensor:real_sensor" in result.objects


def test_call_form_with_state_never_dangles() -> None:
    """Sanity companion: the ordinary call form (`state=` given) never trips
    the sweep either -- only a `state=`-omitted, never-decorated call does."""
    from hassle.compiler.bundle import compile_registered
    from hassle.compiler.registry import current_registry

    template_sensor(name="Direct Sensor", state="{{ 1 }}")
    result = compile_registered(list(current_registry().objects), list(current_registry().prebuilt))
    assert "template_sensor:direct_sensor" in result.objects


# ---------------------------------------------------------------------------
# (b) golden error-case fixture:
# fixtures/dsl/template_sensor_dangling_declaration/ -- exercised generically
# by test_dsl_golden_pairs.py::test_dsl_error_case (error_cases()).
# ---------------------------------------------------------------------------


def test_golden_fixture_compiles_via_compile_bundle_and_raises() -> None:
    with pytest.raises(DanglingTemplateHelperDeclarationError) as excinfo:
        compile_bundle(FIXTURE)
    msg = str(excinfo.value)
    assert "helpers.py:13" in _normalize(msg) or "helpers.py:13" in msg


# ---------------------------------------------------------------------------
# (c) regression test: the ON-MAIN behavior for a state-less call (silently
# registering a degenerate object for template_sensor/template_binary_sensor,
# or -- pre-M13 -- being unreachable for template_number/template_select
# since a plain call always had `state=` as a real kwarg) is now an ERROR for
# BOTH the "never decorated" call-form omission mistake. This is the new
# contract: omitting `state=` without either supplying it OR decorating a
# function is always wrong, not silently accepted.
# ---------------------------------------------------------------------------


def test_state_less_never_decorated_call_no_longer_silently_registers(tmp_path: Path) -> None:
    """Direct regression pin for the reviewer's B1 report: this exact
    snippet used to compile clean (with the object silently absent from the
    compiled set on this branch, or present-but-degenerate on main) -- it
    must now raise, for every read-only template-helper domain."""
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "ghost.py").write_text(
        'from hassle import template_sensor\n\ntemplate_sensor(name="Ghost Sensor")\n',
        encoding="utf-8",
    )
    with pytest.raises(DanglingTemplateHelperDeclarationError):
        compile_bundle(bundle_dir)


def test_state_less_never_decorated_binary_sensor_no_longer_silently_registers(
    tmp_path: Path,
) -> None:
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "ghost.py").write_text(
        "from hassle import template_binary_sensor\n\n"
        'template_binary_sensor(name="Ghost Binary Sensor")\n',
        encoding="utf-8",
    )
    with pytest.raises(DanglingTemplateHelperDeclarationError):
        compile_bundle(bundle_dir)
