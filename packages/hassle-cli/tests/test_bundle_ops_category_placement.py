"""MILESTONES M15 work item B: category-first bundle layout, root-level and
cross-kind (docs/ha-api-notes.md §31.6). `default_source_path` places an
object at root-level ``<slug(category_name)>.py`` derived from its OWN
scope's category (`automation`/`script` scopes for those two kinds, the
shared `"helpers"` scope for all 13 helper kinds -- §31.2) -- retiring the
M11/M12-era per-kind-tree shape (``automations/<slug>.py`` /
``scripts/<slug>.py``, helpers never actually reaching a category-shaped
file at all).

Placement mapping mechanics (registry-aware):
  object key -> its entity-registry entry (match on `unique_id == identity`,
    domain-filtered by the object's OWN kind)
    -> that entry's `categories[scope]` (scope from `kind`'s OWN
       category-registry scope: `"automation"`/`"script"`/`"helpers"`)
    -> the category registry's name for that id
    -> root-level `<slug(category_name)>.py`
  else (no entry, or entry uncategorized) -> the shared root-level `misc.py`.

Same category NAME across different scopes lands every object in the SAME
root-level file (a mixed-kind category file, MILESTONES M15's headline
scenario) -- covered by `test_same_slug_across_scopes_shares_one_file` below.
"""

from __future__ import annotations

from hassle.registry.snapshot import RegistrySnapshot
from hassle_cli.bundle_ops import default_source_path


def _snapshot(**overrides) -> RegistrySnapshot:
    data = {
        "categories": {
            "automation": {"lighting": "Lighting", "sec_urity": "Security & Safety"},
            "script": {"chores": "Chores"},
            "helpers": {"hvac_helpers": "HVAC"},
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
            {
                "entity_id": "input_boolean.guest_mode",
                "unique_id": "guest_mode",
                "domain": "input_boolean",
                "categories": {},
            },
            {
                "entity_id": "input_number.tank_level",
                "unique_id": "tank_level",
                "domain": "input_number",
                "categories": {"helpers": "hvac_helpers"},
            },
        ],
    }
    data.update(overrides)
    return RegistrySnapshot.model_validate(data)


def test_categorized_automation_places_under_root_level_slug() -> None:
    path = default_source_path("automation:hall_light_on_motion", registry=_snapshot())
    assert path == "lighting.py"


def test_category_name_with_punctuation_is_slugified() -> None:
    snapshot = _snapshot()
    # Give hall_light_on_motion the "Security & Safety" category instead.
    snapshot.entities[0].categories = {"automation": "sec_urity"}
    path = default_source_path("automation:hall_light_on_motion", registry=snapshot)
    assert path == "security_safety.py"


def test_categorized_script_places_under_root_level_slug() -> None:
    path = default_source_path("script:movie_time", registry=_snapshot())
    assert path == "chores.py"


def test_categorized_helper_places_under_root_level_slug() -> None:
    # MILESTONES M15 work item B: helpers now get real category-shaped
    # placement too (the shared "helpers" scope, §31.2/§31.6) -- no longer
    # hardcoded to the flat helpers/misc.py fallback.
    path = default_source_path("input_number:tank_level", registry=_snapshot())
    assert path == "hvac.py"


def test_uncategorized_entity_falls_back_to_misc() -> None:
    path = default_source_path("automation:morning_lights", registry=_snapshot())
    assert path == "misc.py"


def test_uncategorized_helper_falls_back_to_misc() -> None:
    path = default_source_path("input_boolean:guest_mode", registry=_snapshot())
    assert path == "misc.py"


def test_unknown_identity_falls_back_to_misc() -> None:
    # No entity-registry entry has this unique_id at all.
    path = default_source_path("automation:totally_unseen", registry=_snapshot())
    assert path == "misc.py"


def test_no_registry_argument_still_falls_back_to_misc() -> None:
    # Existing (pre-feature) call sites that never pass a registry keep working.
    assert default_source_path("automation:hall_light_on_motion") == "misc.py"


def test_empty_registry_snapshot_behaves_like_no_registry() -> None:
    path = default_source_path("automation:hall_light_on_motion", registry=RegistrySnapshot())
    assert path == "misc.py"


def test_same_slug_across_scopes_shares_one_file() -> None:
    """MILESTONES M15 headline scenario: an automation, a script, and a
    helper each carry a category that slugifies to "hvac" in their OWN scope
    -- all three independently resolve to the SAME root-level `hvac.py`, with
    no cross-scope coordination needed (each call only ever looks at its own
    object's own scope)."""
    snapshot = _snapshot(
        categories={
            "automation": {"cat_hvac": "HVAC"},
            "script": {"cat_hvac_script": "HVAC"},
            "helpers": {"hvac_helpers": "HVAC"},
        }
    )
    snapshot.entities[0].categories = {"automation": "cat_hvac"}
    snapshot.entities[2].categories = {"script": "cat_hvac_script"}
    assert default_source_path("automation:hall_light_on_motion", registry=snapshot) == "hvac.py"
    assert default_source_path("script:movie_time", registry=snapshot) == "hvac.py"
    assert default_source_path("input_number:tank_level", registry=snapshot) == "hvac.py"
