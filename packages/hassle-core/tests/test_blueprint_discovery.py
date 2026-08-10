"""`compile_bundle` discovers blueprint files as objects (blueprints-design §1).

A blueprint is the one managed object with no DSL declaration in stage 1: its
source of truth is the bundle FILE at ``blueprints/<domain>/<path>``, so
discovery is a filesystem scan rather than a decorator registration. That scan
is what makes the file plannable, pushable and orderable like everything else —
instead of YAML on the side that a human must remember to upload first (§0).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hassle.blueprints import InvalidBlueprintError
from hassle.compiler import compile_bundle
from hassle.ir.models import BlueprintConfig

MINIMAL = """\
blueprint:
  name: Minimal
  domain: automation
  input:
    switch_entity:
triggers:
  - trigger: state
    entity_id: !input switch_entity
actions: []
"""


def _bundle(tmp_path: Path, files: dict[str, str], *, dsl: str = "") -> Path:
    root = tmp_path / "bundle"
    root.mkdir(exist_ok=True)
    (root / "misc.py").write_text(dsl, encoding="utf-8")
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


def test_a_blueprint_file_becomes_an_object(tmp_path: Path) -> None:
    root = _bundle(tmp_path, {"blueprints/automation/local/room.yaml": MINIMAL})
    result = compile_bundle(root)
    assert "blueprint:automation/local/room.yaml" in result.objects
    obj = result.objects["blueprint:automation/local/room.yaml"]
    assert isinstance(obj, BlueprintConfig)
    assert obj.to_ha()["source"] == MINIMAL


def test_nested_paths_keep_their_full_use_blueprint_path(tmp_path: Path) -> None:
    """The key's `<path>` must be the string an instance writes in
    `use_blueprint`, so a nested directory is part of it."""
    root = _bundle(tmp_path, {"blueprints/automation/a/b/c.yaml": MINIMAL})
    assert "blueprint:automation/a/b/c.yaml" in compile_bundle(root).objects


def test_script_domain_is_discovered_too(tmp_path: Path) -> None:
    """§1: `<domain>` is HA's blueprint domain -- `automation` OR `script`."""
    root = _bundle(tmp_path, {"blueprints/script/local/s.yaml": MINIMAL})
    assert "blueprint:script/local/s.yaml" in compile_bundle(root).objects


def test_yml_extension_is_discovered(tmp_path: Path) -> None:
    root = _bundle(tmp_path, {"blueprints/automation/local/room.yml": MINIMAL})
    assert "blueprint:automation/local/room.yml" in compile_bundle(root).objects


def test_non_yaml_files_are_ignored(tmp_path: Path) -> None:
    """A README beside the blueprints is not a blueprint."""
    root = _bundle(
        tmp_path,
        {
            "blueprints/automation/README.md": "# notes\n",
            "blueprints/automation/local/room.yaml": MINIMAL,
        },
    )
    assert set(compile_bundle(root).objects) == {"blueprint:automation/local/room.yaml"}


def test_unknown_domain_directories_are_ignored(tmp_path: Path) -> None:
    """HA ships exactly two blueprint domains. Anything else under
    `blueprints/` is somebody's own directory, not a blueprint tree to guess
    at."""
    root = _bundle(tmp_path, {"blueprints/notes/scratch.yaml": MINIMAL})
    assert compile_bundle(root).objects == {}


def test_no_blueprints_directory_is_fine(tmp_path: Path) -> None:
    assert compile_bundle(_bundle(tmp_path, {})).objects == {}


def test_discovery_is_deterministic(tmp_path: Path) -> None:
    """R8: compiled output must be byte-stable across runs."""
    root = _bundle(
        tmp_path,
        {
            "blueprints/automation/b.yaml": MINIMAL,
            "blueprints/automation/a.yaml": MINIMAL,
            "blueprints/script/z.yaml": MINIMAL,
        },
    )
    first = list(compile_bundle(root).objects)
    for _ in range(3):
        assert list(compile_bundle(root).objects) == first
    assert first == [
        "blueprint:automation/a.yaml",
        "blueprint:automation/b.yaml",
        "blueprint:script/z.yaml",
    ]


def test_symlinked_blueprint_is_skipped(tmp_path: Path) -> None:
    """The same sandbox rule the module walk and `expand_blueprint` apply: a
    bundle never reads through a symlink out of itself (DESIGN §14)."""
    outside = tmp_path / "outside.yaml"
    outside.write_text(MINIMAL, encoding="utf-8")
    root = _bundle(tmp_path, {})
    (root / "blueprints" / "automation").mkdir(parents=True)
    (root / "blueprints" / "automation" / "linked.yaml").symlink_to(outside)
    assert compile_bundle(root).objects == {}


def test_a_malformed_blueprint_fails_the_compile_loudly(tmp_path: Path) -> None:
    """Not skipped: a file under `blueprints/<domain>/` is a blueprint the
    bundle means to manage, and HA would reject it. Failing at compile time is
    the whole point of §0's third failure mode (an opaque HTTP 400 forty
    minutes into a push)."""
    root = _bundle(tmp_path, {"blueprints/automation/broken.yaml": "just a string\n"})
    with pytest.raises(InvalidBlueprintError) as excinfo:
        compile_bundle(root)
    assert "blueprints/automation/broken.yaml" in str(excinfo.value)


def test_blueprint_objects_coexist_with_their_instances(tmp_path: Path) -> None:
    dsl = (
        "from hassle import blueprint_automation\n"
        "blueprint_automation(\n"
        '    id="kitchen_switch",\n'
        '    use_blueprint="local/room.yaml",\n'
        '    inputs={"switch_entity": "event.kitchen"},\n'
        ")\n"
    )
    root = _bundle(tmp_path, {"blueprints/automation/local/room.yaml": MINIMAL}, dsl=dsl)
    keys = set(compile_bundle(root).objects)
    assert keys == {"blueprint:automation/local/room.yaml", "automation:kitchen_switch"}


def test_the_instance_payload_is_unchanged_by_the_blueprint_object(tmp_path: Path) -> None:
    """The instance still compiles to exactly `use_blueprint` -- discovering
    the file must not inline or expand anything into the pushed automation."""
    dsl = (
        "from hassle import blueprint_automation\n"
        "blueprint_automation(\n"
        '    id="kitchen_switch",\n'
        '    use_blueprint="local/room.yaml",\n'
        '    inputs={"switch_entity": "event.kitchen"},\n'
        ")\n"
    )
    root = _bundle(tmp_path, {"blueprints/automation/local/room.yaml": MINIMAL}, dsl=dsl)
    body = compile_bundle(root).objects["automation:kitchen_switch"].to_ha()
    assert body == {
        "id": "kitchen_switch",
        "use_blueprint": {"path": "local/room.yaml", "input": {"switch_entity": "event.kitchen"}},
    }
