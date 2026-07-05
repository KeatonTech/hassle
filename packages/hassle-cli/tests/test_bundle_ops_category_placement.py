"""UX feedback (owner, post-first-real-pull): DESIGN §7.3's placement default
("one file per HA category/label if set, else automations/misc.py") was never
implemented -- `default_source_path` always fell back to the flat misc.py,
ignoring HA's UI category registry entirely.

Placement mapping mechanics (new, registry-aware):
  object key -> its entity-registry entry (match on `unique_id == identity`)
    -> that entry's `categories[scope]` (scope == "automation"/"script")
    -> the category registry's name for that id
    -> `automations/<slug(category_name)>.py` (scripts: `scripts/<slug>.py`)
  else (no entry, or entry uncategorized) -> the existing misc.py fallback.

Helpers: same idea, but helpers have no "automation"/"script" scope in HA's
category registry (DESIGN §7.3 mentions labels/domain default for helpers) --
covered here by falling back straight to `helpers/misc.py` (no category
registry scope exists for helper domains), which is exactly today's behavior,
so no separate helper-category test is needed beyond confirming the fallback
still fires when a registry snapshot IS supplied.
"""

from __future__ import annotations

from hassle.registry.snapshot import RegistrySnapshot
from hassle_cli.bundle_ops import default_source_path


def _snapshot(**overrides) -> RegistrySnapshot:
    data = {
        "categories": {
            "automation": {"lighting": "Lighting", "sec_urity": "Security & Safety"},
            "script": {"chores": "Chores"},
        },
        "entities": [
            {
                "entity_id": "automation.hall_light_on_motion",
                "unique_id": "hall_light_on_motion",
                "domain": "automation",
                "categories": {"automation": "lighting"},
            },
            {
                "entity_id": "automation.morning_lights",
                "unique_id": "morning_lights",
                "domain": "automation",
                "categories": {},  # entity exists, but uncategorized
            },
            {
                "entity_id": "script.movie_time",
                "unique_id": "movie_time",
                "domain": "script",
                "categories": {"script": "chores"},
            },
        ],
    }
    data.update(overrides)
    return RegistrySnapshot.model_validate(data)


def test_categorized_automation_places_under_slugified_category_name() -> None:
    path = default_source_path("automation:hall_light_on_motion", registry=_snapshot())
    assert path == "automations/lighting.py"


def test_category_name_with_punctuation_is_slugified() -> None:
    snapshot = _snapshot()
    # Give hall_light_on_motion the "Security & Safety" category instead.
    snapshot.entities[0].categories = {"automation": "sec_urity"}
    path = default_source_path("automation:hall_light_on_motion", registry=snapshot)
    assert path == "automations/security_safety.py"


def test_categorized_script_places_under_scripts_slug() -> None:
    path = default_source_path("script:movie_time", registry=_snapshot())
    assert path == "scripts/chores.py"


def test_uncategorized_entity_falls_back_to_misc() -> None:
    path = default_source_path("automation:morning_lights", registry=_snapshot())
    assert path == "automations/misc.py"


def test_unknown_identity_falls_back_to_misc() -> None:
    # No entity-registry entry has this unique_id at all.
    path = default_source_path("automation:totally_unseen", registry=_snapshot())
    assert path == "automations/misc.py"


def test_no_registry_argument_still_falls_back_to_misc() -> None:
    # Existing (pre-feature) call sites that never pass a registry keep working.
    assert default_source_path("automation:hall_light_on_motion") == "automations/misc.py"


def test_helper_placement_ignores_categories_falls_back_to_misc() -> None:
    # Helpers have no automation/script category scope; registry-aware
    # placement must not change their existing behavior.
    path = default_source_path("input_boolean:guest_mode", registry=_snapshot())
    assert path == "helpers/misc.py"


def test_empty_registry_snapshot_behaves_like_no_registry() -> None:
    path = default_source_path("automation:hall_light_on_motion", registry=RegistrySnapshot())
    assert path == "automations/misc.py"
