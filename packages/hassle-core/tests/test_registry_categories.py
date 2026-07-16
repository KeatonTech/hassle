"""DESIGN §7.3 says placement should follow HA's UI category registry, but
that was never implemented -- pull always fell back to ``automations/misc.py``
/ ``scripts/misc.py`` (`bundle_ops.default_source_path`). This is the
registry-model half of the fix:

- `RegistrySnapshot` gains an additive `categories` field: `{scope: {category_id:
  name}}` (WS `config/category_registry/list` is called once per scope, e.g.
  `{"scope": "automation"}`; DESIGN §7.3, docs/ha-api-notes.md new §22).
- `EntityInfo` gains `unique_id` (== the automation/script/helper config id,
  docs/ha-api-notes.md §2 "id <-> unique_id") and a per-scope `categories` map
  (`{scope: category_id}`) already present on entity-registry rows but never
  parsed by the snapshot model.

Both additions are additive (`extra="allow"` + new fields with safe defaults)
so every pre-existing fixture/snapshot round-trips unchanged -- no frozen
interface breaks.
"""

from __future__ import annotations

from pathlib import Path

from hassle.registry.snapshot import EntityInfo, RegistrySnapshot


def test_entity_info_parses_unique_id_and_categories() -> None:
    entity = EntityInfo.model_validate(
        {
            "entity_id": "automation.hall_light_on_motion",
            "unique_id": "hall_light_on_motion",
            "categories": {"automation": "lighting"},
            "domain": "automation",
        }
    )
    assert entity.unique_id == "hall_light_on_motion"
    assert entity.categories == {"automation": "lighting"}


def test_entity_info_categories_default_empty() -> None:
    entity = EntityInfo.model_validate({"entity_id": "light.hallway"})
    assert entity.categories == {}
    assert entity.unique_id is None


def test_registry_snapshot_parses_categories_by_scope() -> None:
    snapshot = RegistrySnapshot.model_validate(
        {
            "categories": {
                "automation": {"lighting": "Lighting", "security": "Security"},
                "script": {"chores": "Chores"},
            }
        }
    )
    assert snapshot.categories["automation"]["lighting"] == "Lighting"
    assert snapshot.categories["script"]["chores"] == "Chores"


def test_registry_snapshot_categories_default_empty() -> None:
    snapshot = RegistrySnapshot()
    assert snapshot.categories == {}


def test_registry_snapshot_category_name_lookup_helper() -> None:
    snapshot = RegistrySnapshot.model_validate(
        {
            "categories": {"automation": {"lighting": "Lighting"}},
            "entities": [
                {
                    "entity_id": "automation.hall_light_on_motion",
                    "unique_id": "hall_light_on_motion",
                    "domain": "automation",
                    "categories": {"automation": "lighting"},
                }
            ],
        }
    )
    entry = snapshot.entity_by_unique_id("automation", "hall_light_on_motion")
    assert entry is not None
    assert snapshot.category_name_for_entity("automation", entry) == "Lighting"


def test_registry_snapshot_entity_by_unique_id_returns_none_when_absent() -> None:
    snapshot = RegistrySnapshot()
    assert snapshot.entity_by_unique_id("automation", "nope") is None


def test_registry_snapshot_existing_fixture_still_loads() -> None:
    # No `categories` key present at all (pre-existing fixture shape) -> must
    # still parse with the new field defaulting to empty, not erroring.
    fixture = Path(__file__).resolve().parents[3] / "fixtures" / "registry" / "home.json"
    snapshot = RegistrySnapshot.load(fixture)
    assert snapshot.categories == {}
