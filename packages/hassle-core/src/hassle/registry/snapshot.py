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
