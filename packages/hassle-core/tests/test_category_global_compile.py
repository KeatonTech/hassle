"""Reading the module-level `CATEGORY` global at compile time (DESIGN §7.3's
placement, reversed).

`hassle.compiler.bundle.compile_bundle` reads `CATEGORY` off each imported
bundle module's namespace (when present) and records it on `CompileResult`,
keyed by the module's bundle-relative source path -- a sidecar map alongside
the existing per-object span bookkeeping, never touching the frozen IR
schema or plan/apply models.

Covers:
- `CATEGORY` present and a `str` -> recorded with its value and (when
  obtainable) the assignment's source span.
- No `CATEGORY` at all -> the file simply has no entry (the "humanize_slug
  fallback" path -- nothing for a downstream consumer to find).
- `CATEGORY` present but NOT a `str` (e.g. an int) -> a compile-time
  `CompileError` (what/where/fix, snapshot-tested), never silently
  coerced or ignored.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hassle.compiler.bundle import compile_bundle
from hassle.compiler.errors import CompileError
from hassle_dev.snapshots import check_snapshot, normalize_error

SNAP_DIR = Path(__file__).resolve().parent / "snapshots" / "errors"


def _check_snapshot(name: str, actual: str) -> None:
    check_snapshot(SNAP_DIR, name, actual)


def _normalize(msg: str) -> str:
    return normalize_error(msg, mask_lines_for=Path(__file__).name)


def _write_bundle(tmp_path: Path, filename: str, code: str) -> Path:
    # Category-shaped files are root-level (`<slug>.py`), not under a
    # per-kind tree (`automations/<slug>.py`).
    bundle = tmp_path / "bundle"
    bundle.mkdir(exist_ok=True)
    (bundle / filename).write_text(code, encoding="utf-8")
    return bundle


def test_category_global_recorded_with_value(tmp_path: Path) -> None:
    bundle = _write_bundle(
        tmp_path,
        "automatic_hvac.py",
        """
from hassle import automation, service, state, when

CATEGORY = "Automatic HVAC"


@automation(id="auto_hvac_1", alias="Keep temp steady")
def auto_hvac_1():
    when(state("binary_sensor.hall_motion").to("on"))
    service("climate.turn_on", target={"entity_id": "climate.living_room"})
""",
    )
    result = compile_bundle(bundle)
    entry = result.category_global_for("automatic_hvac.py")
    assert entry is not None
    assert entry.value == "Automatic HVAC"


def test_category_global_span_points_at_assignment(tmp_path: Path) -> None:
    bundle = _write_bundle(
        tmp_path,
        "automatic_hvac.py",
        """
from hassle import automation, service, state, when

CATEGORY = "Automatic HVAC"


@automation(id="auto_hvac_1", alias="Keep temp steady")
def auto_hvac_1():
    when(state("binary_sensor.hall_motion").to("on"))
    service("climate.turn_on", target={"entity_id": "climate.living_room"})
""",
    )
    result = compile_bundle(bundle)
    entry = result.category_global_for("automatic_hvac.py")
    assert entry is not None
    assert entry.span is not None
    assert entry.span.file.endswith("automatic_hvac.py")
    assert entry.span.line == 4  # the `CATEGORY = "Automatic HVAC"` line


def test_no_category_global_means_no_entry(tmp_path: Path) -> None:
    bundle = _write_bundle(
        tmp_path,
        "misc.py",
        """
from hassle import automation, service, state, when


@automation(id="auto_1", alias="Whatever")
def auto_1():
    when(state("binary_sensor.hall_motion").to("on"))
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
    )
    result = compile_bundle(bundle)
    assert result.category_global_for("misc.py") is None


def test_non_str_category_global_is_a_compile_error(tmp_path: Path) -> None:
    bundle = _write_bundle(
        tmp_path,
        "automatic_hvac.py",
        """
from hassle import automation, service, state, when

CATEGORY = 42


@automation(id="auto_hvac_1", alias="Keep temp steady")
def auto_hvac_1():
    when(state("binary_sensor.hall_motion").to("on"))
    service("climate.turn_on", target={"entity_id": "climate.living_room"})
""",
    )
    with pytest.raises(CompileError) as excinfo:
        compile_bundle(bundle)
    _check_snapshot("category_global_not_str", _normalize(str(excinfo.value)))


def test_category_global_survives_bundle_with_multiple_files(tmp_path: Path) -> None:
    """A CATEGORY global in one file must not leak into another file's entry
    (sidecar map is keyed per source path, not a single process-wide value)."""
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "hvac.py").write_text(
        """
from hassle import automation, service, state, when

CATEGORY = "Automatic HVAC"


@automation(id="auto_hvac_1", alias="Keep temp steady")
def auto_hvac_1():
    when(state("binary_sensor.hall_motion").to("on"))
    service("climate.turn_on", target={"entity_id": "climate.living_room"})
""",
        encoding="utf-8",
    )
    (bundle / "misc.py").write_text(
        """
from hassle import automation, service, state, when


@automation(id="auto_misc_1", alias="Whatever")
def auto_misc_1():
    when(state("binary_sensor.hall_motion").to("on"))
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
        encoding="utf-8",
    )
    result = compile_bundle(bundle)
    hvac_entry = result.category_global_for("hvac.py")
    assert hvac_entry is not None
    assert hvac_entry.value == "Automatic HVAC"
    assert result.category_global_for("misc.py") is None
