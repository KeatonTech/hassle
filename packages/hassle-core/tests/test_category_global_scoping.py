"""M12 -- CATEGORY capture must be SCOPED to category-shaped files only
(reviewer finding, PR #7 BLOCKED: empirically reproduced regression against
main).

`_import_bundle_modules` originally used a bare `hasattr(module, "CATEGORY")`
with no path-shape filter at all -- so ANY bundle file with a module-level
name `CATEGORY` (previously an unremarkable, ordinary Python identifier in
user code -- `lib/constants.py`, `helpers/enums.py`, a nested
`automations/sub/x.py`, ...) was captured and acted on:

- A non-category-shaped file's `CATEGORY` that doesn't slugify to ANYTHING
  meaningful (there is no file stem to compare against outside
  `automations/<stem>.py` / `scripts/<stem>.py`) still produced a spurious
  `category-slug-mismatch` Finding.
- A non-category-shaped file's `CATEGORY` that is a non-`str` (e.g. an
  unrelated `CATEGORY = 5` enum value) still raised
  `InvalidCategoryGlobalError` -- the ENTIRE bundle failed to compile, even
  though that file has nothing to do with HA UI categories at all.

Both were a regression against bundles that were green on `main` (the name
`CATEGORY` was unremarkable before this milestone). The fix: only interpret
`CATEGORY` for a file matching `hassle.ir.keys.category_shaped_stem`'s
`automations/<stem>.py` / `scripts/<stem>.py` shape (stem != "misc", no
deeper nesting) -- checked AT CAPTURE TIME, so the non-str guard itself only
ever fires for a category-shaped file too.

Every combination below (mismatched str / non-str CATEGORY, in a
non-category file that isn't nested under a recognized tree at all, the
`misc.py` fallback, and a nested `automations/sub/x.py`) must produce
NEITHER a Finding NOR a compile error -- `CATEGORY` in any of these files is
just an ordinary, ignored Python name, exactly as it always was on `main`.
"""

from __future__ import annotations

from pathlib import Path

from hassle.compiler.bundle import compile_bundle
from hassle.registry.snapshot import RegistrySnapshot
from hassle.registry.validate import validate_bundle

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE = REPO_ROOT / "fixtures" / "registry" / "home.json"

_AUTOMATION_BODY = """
from hassle import automation, service, state, when


@automation(id="auto_1", alias="Whatever")
def auto_1():
    when(state("binary_sensor.hall_motion").to("on"))
    service("light.turn_on", target={"entity_id": "light.hallway"})
"""


def _write_bundle(tmp_path: Path, rel_path: str, category_line: str) -> Path:
    """A bundle whose ONLY automation lives at `automations/misc.py` (so the
    bundle always compiles regardless of `rel_path`'s own shape), plus a
    second file at `rel_path` containing `category_line` followed by nothing
    else meaningful -- isolating the CATEGORY-scoping question from whether
    the file itself declares any automation/script at all (it need not; a
    plain `lib`/`helpers` support module never does)."""
    bundle = tmp_path / "bundle"
    bundle.mkdir(exist_ok=True)
    (bundle / "automations").mkdir(exist_ok=True)
    (bundle / "automations" / "misc.py").write_text(_AUTOMATION_BODY, encoding="utf-8")

    target = bundle / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"{category_line}\n", encoding="utf-8")
    return bundle


# -- (a) mismatched CATEGORY str, in each non-category-shaped location ------


def test_mismatched_str_category_in_lib_file_is_ignored(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path, "lib/constants.py", 'CATEGORY = "Heating"')
    result = compile_bundle(bundle)  # must not raise
    snapshot = RegistrySnapshot.load(FIXTURE)
    findings = validate_bundle(result, snapshot)
    assert not [f for f in findings if f.code == "category-slug-mismatch"], findings
    assert result.category_global_for("lib/constants.py") is None


def test_mismatched_str_category_in_misc_file_is_ignored(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "automations").mkdir()
    (bundle / "automations" / "misc.py").write_text(
        f'CATEGORY = "Totally Unrelated Name"\n{_AUTOMATION_BODY}', encoding="utf-8"
    )
    result = compile_bundle(bundle)  # must not raise
    snapshot = RegistrySnapshot.load(FIXTURE)
    findings = validate_bundle(result, snapshot)
    assert not [f for f in findings if f.code == "category-slug-mismatch"], findings
    assert result.category_global_for("automations/misc.py") is None


def test_mismatched_str_category_in_nested_automations_file_is_ignored(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path, "automations/sub/x.py", 'CATEGORY = "Nested Nonsense"')
    result = compile_bundle(bundle)  # must not raise
    snapshot = RegistrySnapshot.load(FIXTURE)
    findings = validate_bundle(result, snapshot)
    assert not [f for f in findings if f.code == "category-slug-mismatch"], findings
    assert result.category_global_for("automations/sub/x.py") is None


# -- (b) non-str CATEGORY, in each non-category-shaped location -------------


def test_non_str_category_in_lib_file_does_not_error(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path, "lib/enums.py", "CATEGORY = 5")
    result = compile_bundle(bundle)  # must NOT raise InvalidCategoryGlobalError
    assert "automation:auto_1" in result.objects
    assert result.category_global_for("lib/enums.py") is None


def test_non_str_category_in_misc_file_does_not_error(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "automations").mkdir()
    (bundle / "automations" / "misc.py").write_text(
        f"CATEGORY = 5\n{_AUTOMATION_BODY}", encoding="utf-8"
    )
    result = compile_bundle(bundle)  # must NOT raise InvalidCategoryGlobalError
    assert "automation:auto_1" in result.objects
    assert result.category_global_for("automations/misc.py") is None


def test_non_str_category_in_nested_automations_file_does_not_error(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path, "automations/sub/x.py", "CATEGORY = 5")
    result = compile_bundle(bundle)  # must NOT raise InvalidCategoryGlobalError
    assert "automation:auto_1" in result.objects
    assert result.category_global_for("automations/sub/x.py") is None
