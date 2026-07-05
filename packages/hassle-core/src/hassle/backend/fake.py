"""`FakeBackend` — in-memory `Backend` for M5 (DESIGN §8, docs/ha-api-notes.md §11).

Seed data is hand-written Python modeled on the real capture shapes in
docs/ha-api-captures/ (not parsed at runtime — provenance noted per record
below), covering automations, scripts, and all nine storage-collection helper
domains (rest-ws-core.json records: `automation_create`/`automation_read_normalized`
for automations, `script_create`/`script_read_normalized` for scripts,
`helper_*_full_cycle` for the nine helper domains).

Two behaviors mirror real HA exactly (docs/ha-api-notes.md §10.1, §11):

- **Normalization on write.** `create`/`update` run the input through
  `hassle.ir.normalize_ha` before storing — legacy singular `trigger/condition/
  action` + `service:` becomes plural `triggers/conditions/actions` + `action:`,
  exactly like HA's real POST-then-GET round-trip
  (docs/ha-api-captures/normalize-post-get-pair.json). Without this, the plan
  engine would show spurious `update`s for every already-plural object.
- **Helper identity derivation.** A helper's `id` (if not supplied) is a slug
  of its `name` — real HA slugifies `name` into the storage-collection item id
  (docs/ha-api-notes.md §4: `"H bool"` -> `"h_bool"`). Real HA addresses
  update/delete via a `{domain}_id` payload key (quirk #1); `FakeBackend`
  reproduces this as an internal storage-organization detail even though the
  `Backend` Protocol's `update`/`delete` signatures are domain-shape-agnostic.
"""

from __future__ import annotations

from typing import Any

from hassle.ir.canonical import sha256_hash
from hassle.ir.keys import HELPER_DOMAINS, OBJECT_KINDS
from hassle.ir.keys import slugify as _slugify
from hassle.ir.normalize import normalize_ha


class FakeBackend:
    """In-memory `Backend` (structurally satisfies `hassle.backend.Backend`)."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, dict[str, Any]]] = {kind: {} for kind in OBJECT_KINDS}
        self._writes = 0

    # -- Backend protocol -------------------------------------------------

    def fetch_registry_snapshot(self):  # additive test/registry surface, not part of F2
        """Minimal registry snapshot (settable via `self.registry_snapshot`).

        Mirrors DirectBackend's non-protocol registry surface so CLI flows that
        refresh `.hassle/registry.json` on pull are exercisable offline.
        """
        from hassle.registry.snapshot import RegistrySnapshot

        snapshot = getattr(self, "registry_snapshot", None)
        return snapshot if snapshot is not None else RegistrySnapshot()

    def list_remote(self, kind: str) -> dict[str, dict[str, Any]]:
        self._require_kind(kind)
        return {identity: dict(config) for identity, config in self._store[kind].items()}

    def create(self, kind: str, config: dict[str, Any]) -> str:
        self._require_kind(kind)
        # normalize_ha only special-cases kind == "automation" (outer-key
        # pluralization); every other kind gets the same service:->action:
        # recursive rewrite, so passing `kind` straight through is correct.
        normalized = normalize_ha(config, kind=kind)
        identity = self._derive_identity(kind, normalized)
        normalized = {**normalized, "id": identity} if kind in HELPER_DOMAINS else normalized
        self._store[kind][identity] = normalized
        self._writes += 1
        return identity

    def update(self, kind: str, identity: str, config: dict[str, Any]) -> None:
        self._require_kind(kind)
        normalized = normalize_ha(config, kind=kind)
        if kind in HELPER_DOMAINS:
            normalized = {**normalized, "id": identity}
        self._store[kind][identity] = normalized
        self._writes += 1

    def delete(self, kind: str, identity: str) -> None:
        self._require_kind(kind)
        self._store[kind].pop(identity, None)
        self._writes += 1

    # -- test-only helpers --------------------------------------------------

    def writes_since_reset(self) -> int:
        return self._writes

    def reset_write_tracking(self) -> None:
        self._writes = 0

    def snapshot(self, kind: str) -> dict[str, dict[str, Any]]:
        """A deep-ish copy of the current store for a kind (for rollback tests)."""
        return {identity: dict(config) for identity, config in self._store[kind].items()}

    def restore(self, kind: str, snapshot: dict[str, dict[str, Any]]) -> None:
        self._store[kind] = {identity: dict(config) for identity, config in snapshot.items()}

    def hash_of(self, kind: str, identity: str) -> str | None:
        config = self._store[kind].get(identity)
        return None if config is None else sha256_hash(config)

    @classmethod
    def with_seed_data(cls) -> FakeBackend:
        """A FakeBackend pre-populated with realistic starting state, modeled on
        docs/ha-api-captures/rest-ws-core.json (automations, scripts, one item
        per helper domain)."""
        backend = cls()

        # rest-ws-core.json records "automation_create" / "automation_read_normalized"
        backend.create(
            "automation",
            {
                "id": "hassle_auto_demo",
                "alias": "Hassle Demo Automation",
                "description": "created by M0.V harness",
                "mode": "single",
                "trigger": [
                    {"platform": "state", "entity_id": "input_boolean.hassle_flag_2", "to": "on"}
                ],
                "condition": [],
                "action": [
                    {
                        "service": "input_boolean.turn_off",
                        "target": {"entity_id": "input_boolean.hassle_flag_2"},
                    }
                ],
            },
        )

        # rest-ws-core.json records "script_create" / "script_read_normalized"
        backend.create(
            "script",
            {
                "alias": "Hassle Demo Script",
                "mode": "single",
                "sequence": [
                    {
                        "service": "input_boolean.toggle",
                        "target": {"entity_id": "input_boolean.hassle_flag_2"},
                    }
                ],
            },
        )
        # Give the script a stable, known identity for seed consumers/tests.
        scripts = backend._store["script"]
        ((identity, config),) = list(scripts.items())
        del scripts[identity]
        scripts["hassle_script_demo"] = config

        # rest-ws-core.json "helper_input_boolean_full_cycle"
        backend.create(
            "input_boolean", {"id": "hassle_flag", "name": "Hassle Flag", "icon": "mdi:flag"}
        )
        # rest-ws-core.json "helper_input_number_full_cycle"
        backend.create(
            "input_number",
            {"id": "h_num", "name": "H num", "min": 0, "max": 100, "step": 1, "mode": "slider"},
        )
        # rest-ws-core.json "helper_input_select_full_cycle"
        backend.create("input_select", {"id": "h_sel", "name": "H sel", "options": ["a", "b", "c"]})
        # rest-ws-core.json "helper_input_text_full_cycle"
        backend.create("input_text", {"id": "h_text", "name": "H text", "min": 0, "max": 100})
        # rest-ws-core.json "helper_input_datetime_full_cycle"
        backend.create(
            "input_datetime", {"id": "h_dt", "name": "H dt", "has_date": True, "has_time": True}
        )
        # rest-ws-core.json "helper_input_button_full_cycle"
        backend.create("input_button", {"id": "h_btn", "name": "H btn"})
        # rest-ws-core.json "helper_counter_full_cycle"
        backend.create(
            "counter",
            {
                "id": "h_counter",
                "name": "H counter",
                "initial": 0,
                "step": 1,
                "minimum": 0,
                "maximum": 10,
            },
        )
        # rest-ws-core.json "helper_timer_full_cycle"
        backend.create("timer", {"id": "h_timer", "name": "H timer", "duration": "00:01:00"})
        # rest-ws-core.json "helper_schedule_full_cycle"
        backend.create(
            "schedule",
            {
                "id": "h_schedule",
                "name": "H schedule",
                "monday": [{"from": "08:00:00", "to": "17:00:00"}],
            },
        )

        backend.reset_write_tracking()
        return backend

    # -- internal ------------------------------------------------------------

    def _require_kind(self, kind: str) -> None:
        if kind not in OBJECT_KINDS:
            raise ValueError(
                f"unknown object kind {kind!r} (expected one of {sorted(OBJECT_KINDS)})"
            )

    def _derive_identity(self, kind: str, normalized: dict[str, Any]) -> str:
        if kind == "automation":
            return str(normalized.get("id") or _slugify(str(normalized.get("alias", "automation"))))
        if kind == "script":
            # Scripts are keyed by an extrinsic object_id HA doesn't invent from
            # the body; callers of FakeBackend.create for scripts should supply
            # one via config["id"] (mirroring the CLI layer choosing the object_id
            # before POSTing to /api/config/script/config/{object_id}).
            return str(normalized.get("id") or _slugify(str(normalized.get("alias", "script"))))
        if kind in HELPER_DOMAINS:
            supplied = normalized.get("id")
            if supplied:
                return str(supplied)
            return _slugify(str(normalized.get("name", kind)))
        raise ValueError(f"unknown object kind {kind!r}")
