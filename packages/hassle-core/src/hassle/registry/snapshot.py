"""The M3 registry snapshot model (DESIGN §9.2).

Loads the CLI's committed `.hassle/registry.json` shape (mirrored offline by
`fixtures/registry/home.json` in tests) — entities, areas, labels, floors,
devices, service schemas (`get_services`), and the enumerated purpose-trigger/
condition vocabulary. Pure data + lookup helpers; no network (this module only
ever reads a local JSON file).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict


class EntityInfo(BaseModel):
    model_config = ConfigDict(extra="allow")

    entity_id: str
    name: str | None = None
    original_name: str | None = None
    area_id: str | None = None
    device_id: str | None = None
    labels: list[str] = []
    domain: str | None = None
    platform: str | None = None
    # `unique_id` == the automation/script/helper config `id` (docs/ha-api-notes.md
    # §2 "id <-> unique_id" -- confirmed on a real WS `config/entity_registry/list`
    # capture). Used to look up an object's entity-registry entry from its object
    # key identity (pull placement, DESIGN §7.3).
    unique_id: str | None = None
    # Per-scope UI category assignment: `{"automation": "lighting"}` (DESIGN
    # §7.3; docs/ha-api-notes.md §5 confirms the `categories` key is already
    # present on real entity-registry rows -- just never parsed by this model
    # before).
    categories: dict[str, str] = {}


class AreaInfo(BaseModel):
    model_config = ConfigDict(extra="allow")

    area_id: str
    name: str | None = None


class LabelInfo(BaseModel):
    model_config = ConfigDict(extra="allow")

    label_id: str
    name: str | None = None


class FloorInfo(BaseModel):
    model_config = ConfigDict(extra="allow")

    floor_id: str
    name: str | None = None
    level: int | None = None
    icon: str | None = None
    aliases: list[str] = []


class DeviceInfo(BaseModel):
    model_config = ConfigDict(extra="allow")

    device_id: str
    name: str | None = None
    # HA's device-registry user override (ux/stub-device-names): when the
    # user renames a device in the UI, HA writes `name_by_user` and leaves
    # `name` as the integration-reported name -- `name_by_user` wins whenever
    # both are set (mirrors HA's own `Device.name_by_user or Device.name`
    # composition, e.g. `homeassistant.helpers.device_registry`).
    name_by_user: str | None = None
    area_id: str | None = None


class ServiceField(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str | None = None
    description: str | None = None
    example: Any = None
    required: bool = False


class ServiceDef(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str | None = None
    description: str | None = None
    fields: dict[str, ServiceField] = {}


class PurposeVocabulary(BaseModel):
    model_config = ConfigDict(extra="allow")

    triggers: list[str] = []
    conditions: list[str] = []


class RegistrySnapshot(BaseModel):
    """The full offline snapshot the M3 validator/stub-generator consume."""

    model_config = ConfigDict(extra="allow")

    entities: list[EntityInfo] = []
    areas: list[AreaInfo] = []
    labels: list[LabelInfo] = []
    floors: list[FloorInfo] = []
    devices: list[DeviceInfo] = []
    services: dict[str, dict[str, ServiceDef]] = {}
    purpose_vocabulary: PurposeVocabulary = PurposeVocabulary()
    # UI category registry, per scope (DESIGN §7.3): `{"automation": {"lighting":
    # "Lighting"}, "script": {"chores": "Chores"}}`. Additive -- absent entirely
    # from every pre-existing fixture/committed snapshot, which parse to `{}`.
    categories: dict[str, dict[str, str]] = {}

    @classmethod
    def load(cls, path: str | Path) -> RegistrySnapshot:
        """Load a registry snapshot from a JSON file (no network)."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.model_validate(data)

    def entity_ids(self) -> set[str]:
        return {e.entity_id for e in self.entities}

    def area_ids(self) -> set[str]:
        return {a.area_id for a in self.areas}

    def label_ids(self) -> set[str]:
        return {label.label_id for label in self.labels}

    def floor_ids(self) -> set[str]:
        return {f.floor_id for f in self.floors}

    def device_ids(self) -> set[str]:
        return {d.device_id for d in self.devices}

    def service_def(self, domain: str, service: str) -> ServiceDef | None:
        return self.services.get(domain, {}).get(service)

    def entity_by_unique_id(self, scope: str, unique_id: str) -> EntityInfo | None:
        """Find the entity-registry entry whose `unique_id` matches (and whose
        domain matches `scope`, when known) -- the id<->unique_id anchor
        (docs/ha-api-notes.md §2) that lets pull placement map an object key's
        identity back to its registry row."""
        for entity in self.entities:
            if entity.unique_id == unique_id and (entity.domain is None or entity.domain == scope):
                return entity
        return None

    def category_name_for_entity(self, scope: str, entity: EntityInfo) -> str | None:
        """The UI category *name* (not id) assigned to `entity` within `scope`,
        or None if uncategorized / the category id is unknown to this snapshot."""
        category_id = entity.categories.get(scope)
        if category_id is None:
            return None
        return self.categories.get(scope, {}).get(category_id)
