"""`hassle.blueprints` is CORE, not a testing module (blueprints-design §1).

Stage 1 makes a blueprint file a managed object, so the *validator*
(`hassle.registry.validate`, §6) and the *backend* (`FakeBackend.
blueprint_substitute`, §2/§7) both have to parse and expand blueprints --
and neither may import from `hassle.testing`, which sits beside them in the
layering rather than below (`test_package_layering.py`). The loader/expander
therefore moves to `hassle.blueprints`, with `hassle.testing.blueprints`
kept as a pure re-export so every existing importer (bundles' own tests
included) keeps working: the frozen surfaces are additive-only
(CONTRIBUTING R5).

The per-domain generalization of `BLUEPRINT_SUBDIR` (§1: "`<domain>` is HA's
blueprint domain (`automation`, `script`)"; the constant "currently pins
`automation`") is pinned here too -- additive, so the old
zero-argument/`automation` behaviour is byte-identical.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import hassle.blueprints as core_blueprints
import hassle.testing.blueprints as testing_blueprints

#: Everything the simulator-era module exported and every importer may keep
#: importing from EITHER path.
_PROMOTED_NAMES = (
    "BLUEPRINT_SUBDIR",
    "Blueprint",
    "BlueprintError",
    "BlueprintInput",
    "InvalidBlueprintError",
    "MissingBlueprintInputError",
    "blueprint_display_path",
    "blueprint_file",
    "expand_blueprint",
    "load_blueprint",
)


@pytest.mark.parametrize("name", _PROMOTED_NAMES)
def test_core_module_exports_every_promoted_name(name: str) -> None:
    assert hasattr(core_blueprints, name), f"hassle.blueprints is missing {name!r}"


@pytest.mark.parametrize("name", _PROMOTED_NAMES)
def test_testing_module_re_exports_the_same_objects(name: str) -> None:
    """Not merely "a name of the same spelling" -- the SAME object, so an
    `except hassle.testing.blueprints.MissingBlueprintInputError` in an
    existing bundle still catches what core raises."""
    assert getattr(testing_blueprints, name) is getattr(core_blueprints, name)


def test_core_module_does_not_live_under_testing() -> None:
    """The validator must not import a testing module (§1)."""
    assert core_blueprints.__name__ == "hassle.blueprints"
    assert ".testing." not in (core_blueprints.__file__ or "")


# --- §1: BLUEPRINT_SUBDIR generalized per-domain (additive) ----------------


def test_blueprint_subdir_still_pins_automation() -> None:
    """The existing constant keeps its exact value: every current caller
    (the simulator's `expand_blueprint`, bundles' own layout) is unaffected."""
    assert core_blueprints.BLUEPRINT_SUBDIR == ("blueprints", "automation")


def test_blueprint_subdir_for_domain() -> None:
    assert core_blueprints.blueprint_subdir("automation") == ("blueprints", "automation")
    assert core_blueprints.blueprint_subdir("script") == ("blueprints", "script")


def test_blueprint_domains_are_has_two() -> None:
    """`<domain>` is HA's blueprint domain -- `automation` or `script` (§1)."""
    assert core_blueprints.BLUEPRINT_DOMAINS == ("automation", "script")


def test_blueprint_file_defaults_to_automation(tmp_path: Path) -> None:
    assert core_blueprints.blueprint_file(tmp_path, "local/x.yaml") == (
        tmp_path / "blueprints" / "automation" / "local" / "x.yaml"
    )


def test_blueprint_file_honors_domain(tmp_path: Path) -> None:
    assert core_blueprints.blueprint_file(tmp_path, "local/x.yaml", domain="script") == (
        tmp_path / "blueprints" / "script" / "local" / "x.yaml"
    )


def test_blueprint_display_path_honors_domain() -> None:
    assert core_blueprints.blueprint_display_path("local/x.yaml") == (
        "blueprints/automation/local/x.yaml"
    )
    assert core_blueprints.blueprint_display_path("local/x.yaml", domain="script") == (
        "blueprints/script/local/x.yaml"
    )
