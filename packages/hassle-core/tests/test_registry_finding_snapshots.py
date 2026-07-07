"""M3 milestone test 6: error snapshots for the top 10 Finding types (R6).

Same pattern as `tests/test_compile_errors.py`: snapshot files under
`tests/snapshots/findings/`, normalized to strip absolute directory prefixes,
written by `HASSLE_UPDATE_SNAPSHOTS=1`.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from hassle.compiler.bundle import compile_bundle
from hassle.registry.snapshot import RegistrySnapshot
from hassle.registry.validate import validate_bundle

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE = REPO_ROOT / "fixtures" / "registry" / "home.json"
SNAP_DIR = Path(__file__).resolve().parent / "snapshots" / "findings"


@pytest.fixture(scope="module")
def snapshot() -> RegistrySnapshot:
    return RegistrySnapshot.load(FIXTURE)


def _check_snapshot(name: str, actual: str) -> None:
    path = SNAP_DIR / f"{name}.txt"
    if os.environ.get("HASSLE_UPDATE_SNAPSHOTS"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual + "\n", encoding="utf-8")
    assert path.is_file(), f"missing snapshot {path}; set HASSLE_UPDATE_SNAPSHOTS=1 to write it"
    assert actual == path.read_text(encoding="utf-8").rstrip("\n")


def _normalize(msg: str) -> str:
    return re.sub(r"(/[^\s:]+/)([^/\s:]+\.py)", r"\2", msg)


def _write_bundle(tmp_path: Path, code: str) -> Path:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "automation.py").write_text(code, encoding="utf-8")
    return bundle


def _find_one(tmp_path: Path, snapshot: RegistrySnapshot, code: str, dsl_code: str) -> str:
    bundle = _write_bundle(tmp_path, dsl_code)
    result = compile_bundle(bundle)
    findings = validate_bundle(result, snapshot)
    matches = [f for f in findings if f.code == code]
    assert matches, f"expected a {code!r} finding, got: {findings}"
    return _normalize(str(matches[0]))


def test_snapshot_unknown_entity(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    text = _find_one(
        tmp_path,
        snapshot,
        "unknown-entity",
        """
from hassle import automation, service

@automation(id="a", alias="A")
def a():
    service("light.turn_on", target={"entity_id": "light.halway"})
""",
    )
    _check_snapshot("unknown_entity", text)


def test_snapshot_unknown_area(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    text = _find_one(
        tmp_path,
        snapshot,
        "unknown-area",
        """
from hassle import automation, area, on, service, when

@automation(id="a", alias="A")
def a():
    when(on("motion.detected", target=area("not_a_real_area")))
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
    )
    _check_snapshot("unknown_area", text)


def test_snapshot_unknown_floor(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    text = _find_one(
        tmp_path,
        snapshot,
        "unknown-floor",
        """
from hassle import automation, floor, on, service, when

@automation(id="a", alias="A")
def a():
    when(on("motion.detected", target=floor("not_a_real_floor")))
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
    )
    _check_snapshot("unknown_floor", text)


def test_snapshot_unknown_label(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    text = _find_one(
        tmp_path,
        snapshot,
        "unknown-label",
        """
from hassle import automation, label, on, service, when

@automation(id="a", alias="A")
def a():
    when(on("motion.detected", target=label("not_a_real_label")))
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
    )
    _check_snapshot("unknown_label", text)


def test_snapshot_unknown_purpose_type(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    text = _find_one(
        tmp_path,
        snapshot,
        "unknown-purpose-type",
        """
from hassle import automation, on, service, when

@automation(id="a", alias="A")
def a():
    when(on("nonsense.made_up_type"))
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
    )
    _check_snapshot("unknown_purpose_type", text)


def test_snapshot_renamed_purpose_type(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    text = _find_one(
        tmp_path,
        snapshot,
        "renamed-purpose-type",
        """
from hassle import automation, on, service, when

@automation(id="a", alias="A")
def a():
    when(on("battery.low", target="sensor.wireless_device_battery"))
    service("notify.mobile_app_keaton", message="low battery")
""",
    )
    _check_snapshot("renamed_purpose_type", text)


def test_snapshot_undeclared_helper(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    text = _find_one(
        tmp_path,
        snapshot,
        "unknown-entity",
        """
from hassle import automation, service, state, when

@automation(id="a", alias="A")
def a():
    when(state("input_boolean.totally_undeclared").to("on"))
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
    )
    _check_snapshot("undeclared_helper", text)


def test_snapshot_unknown_service_param(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    text = _find_one(
        tmp_path,
        snapshot,
        "unknown-service-param",
        """
from hassle import automation, service

@automation(id="a", alias="A")
def a():
    service("light.turn_on", target={"entity_id": "light.hallway"}, bogus_param=1)
""",
    )
    _check_snapshot("unknown_service_param", text)


def test_snapshot_service_param_wrong_type(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    text = _find_one(
        tmp_path,
        snapshot,
        "service-param-wrong-type",
        """
from hassle import automation, service

@automation(id="a", alias="A")
def a():
    service(
        "light.turn_on",
        target={"entity_id": "light.hallway"},
        brightness_pct="not_a_number",
    )
""",
    )
    _check_snapshot("service_param_wrong_type", text)


def test_snapshot_service_param_missing_required(
    tmp_path: Path, snapshot: RegistrySnapshot
) -> None:
    text = _find_one(
        tmp_path,
        snapshot,
        "service-param-missing-required",
        """
from hassle import automation, service

@automation(id="a", alias="A")
def a():
    service("notify.notify", target={"entity_id": "light.hallway"}, title="hi")
""",
    )
    _check_snapshot("service_param_missing_required", text)


def test_snapshot_unknown_service(tmp_path: Path, snapshot: RegistrySnapshot) -> None:
    """MILESTONES M18 (N2, reviewer non-blocking note): the `unknown-service`
    Finding, snapshot-tested like every other Finding here (R6) rather than
    just substring-asserted in test_service_namespaces.py."""
    text = _find_one(
        tmp_path,
        snapshot,
        "unknown-service",
        """
from hassle import automation
from hassle.services import ligth

@automation(id="a", alias="A")
def a():
    ligth.turn_on(target={"entity_id": "light.hallway"})
""",
    )
    _check_snapshot("unknown_service", text)
