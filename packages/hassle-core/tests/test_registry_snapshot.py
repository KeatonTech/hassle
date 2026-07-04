"""M3: the registry snapshot model (DESIGN §9.2) — loads `fixtures/registry/home.json`
and exposes lookup surfaces the validator/stub-generator build on.

No network: this only ever reads the committed fixture file.
"""

from __future__ import annotations

from pathlib import Path

from hassle.registry.snapshot import RegistrySnapshot

FIXTURE = Path(__file__).resolve().parents[3] / "fixtures" / "registry" / "home.json"


def _load() -> RegistrySnapshot:
    return RegistrySnapshot.load(FIXTURE)


def test_snapshot_loads_and_counts_match_fixture() -> None:
    snap = _load()
    assert len(snap.entities) >= 155
    assert len(snap.areas) == 12
    assert len(snap.labels) == 5
    assert len(snap.floors) == 2
    assert len(snap.devices) >= 103


def test_snapshot_entity_ids_lookup() -> None:
    snap = _load()
    ids = snap.entity_ids()
    assert "light.hallway" in ids
    assert "sensor.3d_printer" in ids
    assert "light.nonexistent" not in ids


def test_snapshot_area_label_floor_device_ids() -> None:
    snap = _load()
    assert "hallway" in snap.area_ids()
    assert "security" in snap.label_ids()
    assert "upstairs" in snap.floor_ids()
    assert "device_light_1" in snap.device_ids()


def test_snapshot_services_schema() -> None:
    snap = _load()
    assert "light" in snap.services
    assert "turn_on" in snap.services["light"]
    field = snap.services["light"]["turn_on"].fields["brightness_pct"]
    assert field.type == "integer"


def test_snapshot_purpose_vocabulary() -> None:
    snap = _load()
    assert "motion.detected" in snap.purpose_vocabulary.triggers
    assert "climate.is_target_temperature" in snap.purpose_vocabulary.conditions
    # cross-vocabulary leakage must not happen: a trigger type is not a condition
    assert "motion.detected" not in snap.purpose_vocabulary.conditions


def test_snapshot_digit_leading_object_id_present() -> None:
    snap = _load()
    sensor = next(e for e in snap.entities if e.entity_id == "sensor.3d_printer")
    assert sensor.name == "3D Printer"
    assert sensor.device_id == "device_sensor_6"
