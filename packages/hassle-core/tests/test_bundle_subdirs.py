"""M7.1 — bundle subdirectory support (docs/ha-api-notes.md §17.9, DESIGN §6/§7.3).

`compile_bundle` must treat the bundle directory as a package tree: files under
`automations/`, `scripts/`, `helpers/`, `lib/`, or any other user directory are
importable as packages (``from helpers.modes import guest_mode``,
``from lib.notify import notify_adults``), matching DESIGN §5.3/§5.6's examples
verbatim. This file is the loader-mechanism test contract; the golden pair
lives at fixtures/dsl/tree_bundle/ (checked by test_dsl_golden_pairs.py, which
auto-discovers every fixtures/dsl/* case).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from hassle.compiler import compile_bundle
from hassle.compiler.errors import DuplicateObjectError

REPO_ROOT = Path(__file__).resolve().parents[3]
TREE_CASE = REPO_ROOT / "fixtures" / "dsl" / "tree_bundle" / "bundle"
DUP_CASE = REPO_ROOT / "fixtures" / "dsl" / "tree_bundle_duplicate_id" / "bundle"


def test_tree_bundle_compiles_nonempty() -> None:
    """The kitchen-sink tree fixture must NOT silently compile to nothing.

    This is the regression the §17.9 finding describes: before the loader
    recursed, a fully-nested bundle compiled to an empty ``CompileResult`` with
    no error at all.
    """
    result = compile_bundle(TREE_CASE)
    assert result.objects, "tree bundle compiled to zero objects -- loader did not recurse"
    assert set(result.objects) == {
        "automation:hall_light_on_motion",
        "automation:front_door_notify",
        "input_boolean:guest_mode",
        "script:movie_time",
    }


def test_cross_package_imports_resolve(tmp_path: Path) -> None:
    """`from helpers.modes import guest_mode` / `from lib.notify import
    notify_adults` (DESIGN §5.3/§5.6 verbatim) must work with no `__init__.py`
    anywhere in the tree -- PEP 420 namespace packages, since the bundle root
    is put on `sys.path` (decided + documented in docs/ha-api-notes.md §17.9).
    """
    bundle = tmp_path / "bundle"
    (bundle / "helpers").mkdir(parents=True)
    (bundle / "lib").mkdir(parents=True)
    (bundle / "automations").mkdir(parents=True)
    assert not (bundle / "helpers" / "__init__.py").exists()

    (bundle / "helpers" / "modes.py").write_text(
        "from hassle import input_boolean\n"
        'guest_mode = input_boolean(id="guest_mode", name="Guest Mode")\n',
        encoding="utf-8",
    )
    (bundle / "lib" / "notify.py").write_text(
        "from hassle import macro, service\n"
        "\n"
        "@macro\n"
        "def notify_adults(message: str):\n"
        '    service("notify.mobile_app", message=message)\n',
        encoding="utf-8",
    )
    (bundle / "automations" / "hallway.py").write_text(
        "from hassle import automation, state, when\n"
        "from helpers.modes import guest_mode\n"
        "from lib.notify import notify_adults\n"
        "\n"
        '@automation(id="hallway_test", alias="Hallway")\n'
        "def hallway_test():\n"
        '    when(state(guest_mode).to("off"))\n'
        '    notify_adults("hi")\n',
        encoding="utf-8",
    )

    result = compile_bundle(bundle)
    assert set(result.objects) == {"automation:hallway_test", "input_boolean:guest_mode"}
    obj = result.objects["automation:hallway_test"].to_ha()
    assert obj["actions"] == [{"action": "notify.mobile_app", "data": {"message": "hi"}}]


def test_flat_bundle_still_works(tmp_path: Path) -> None:
    """Flat bundles (every existing fixture) keep working unchanged -- no
    subdirectory required."""
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "automations.py").write_text(
        "from hassle import automation, service\n"
        '@automation(id="flat_one", alias="Flat")\n'
        "def flat_one():\n"
        '    service("light.turn_on", entity_id="light.a")\n',
        encoding="utf-8",
    )
    result = compile_bundle(bundle)
    assert set(result.objects) == {"automation:flat_one"}


@pytest.mark.parametrize(
    "skip_dir",
    ["tests", ".hassle", "stubs", ".git", ".vscode", "__pycache__"],
)
def test_reserved_and_dot_dirs_are_skipped(tmp_path: Path, skip_dir: str) -> None:
    """tests/, .hassle/, stubs/, any dot-dir, and __pycache__ are never
    imported as bundle packages -- a stray/invalid .py under one of them must
    not blow up compilation nor register a bogus object."""
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "automations.py").write_text(
        "from hassle import automation, service\n"
        '@automation(id="real_one", alias="Real")\n'
        "def real_one():\n"
        '    service("light.turn_on", entity_id="light.a")\n',
        encoding="utf-8",
    )
    reserved = bundle / skip_dir
    reserved.mkdir()
    # A syntactically-broken file: if the loader ever imported this, compile
    # would raise SyntaxError. Its presence proves the directory was skipped.
    (reserved / "broken.py").write_text("this is not ) valid python (((", encoding="utf-8")

    result = compile_bundle(bundle)
    assert set(result.objects) == {"automation:real_one"}


def test_duplicate_id_across_subdirectories_is_detected() -> None:
    """Duplicate-id detection spans the whole tree, not just one directory;
    the error names both relative paths."""
    with pytest.raises(DuplicateObjectError) as excinfo:
        compile_bundle(DUP_CASE)
    message = str(excinfo.value)
    assert "automations/hallway.py" in message
    assert "scripts/night_mode.py" in message


def test_source_spans_carry_relative_tree_paths() -> None:
    """A span from a nested file reads like `automations/hallway.py:12`, not a
    bare filename (flat bundles) or an unrelated absolute path."""
    result = compile_bundle(TREE_CASE)
    obj = result.objects["automation:hall_light_on_motion"]
    trig_spans = result.spans_for(obj, "triggers")
    assert len(trig_spans) == 1
    assert trig_spans[0].file.endswith("automations/hallway.py")
    assert trig_spans[0].line == 18


def test_sandboxed_import_cleans_up_package_modules() -> None:
    """Cleanup on exit must remove every module imported from the tree,
    INCLUDING the namespace packages themselves (`helpers`, `lib`,
    `automations`), so a second compile in the same process starts fresh
    (R8: no cross-compile bleed) and the bundle's package names never leak
    into later imports."""
    before = set(sys.modules)
    compile_bundle(TREE_CASE)
    after = set(sys.modules)
    leaked = after - before
    assert not leaked, f"modules leaked into sys.modules after compile: {sorted(leaked)}"


def test_repeated_compile_is_deterministic_with_tree_bundle() -> None:
    """Two independent compiles of the same tree bundle produce the same
    object set (R8), exercising the cleanup-then-reimport path twice."""
    first = compile_bundle(TREE_CASE)
    second = compile_bundle(TREE_CASE)
    assert set(first.objects) == set(second.objects)
    for key in first.objects:
        assert first.objects[key].to_ha() == second.objects[key].to_ha()
