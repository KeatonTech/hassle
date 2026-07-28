"""Regression: the `run --live` integration test must arrange its own
preconditions, not inherit them.

`packages/hassle-cli/tests/integration/test_run_live.py::
test_run_live_creates_shadow_triggers_and_cleans_up` passed against a
pristine Home Assistant and failed when the integration suite was re-run
against the SAME instance (HA 2026.7.4): phase 1 asserts the trace reports
`failed_conditions`, which requires the automation's gating `input_boolean`
to be `"off"` -- and the test took that state for granted as "HA's own
default -- no service call needed to arrange this" (docs/internals/
ha-api-notes.md §4). It is not a default a test may rely on: an
`input_boolean` is a `RestoreEntity`, so a re-created helper whose
`entity_id` was used earlier in the instance's life comes back up in the
state the PREVIOUS run left it in -- `"on"`, set by phase 2. The condition
then PASSED, no `failed_conditions` appeared, and the test failed at its
first phase-1 assertion (docs/internals/ha-api-notes.md §29 addendum,
round 4).

These are unit tests (no network, R2): they drive the arrangement helper the
integration test now uses (`tests/integration/live_helpers.py`) against
stub backends that model the two live failure modes -- a restored `"on"`
state, and an entity that never shows up in `/api/states` at all. The helper
is loaded by path because `tests/integration/` is not an importable package
from here.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_HELPERS_PATH = Path(__file__).resolve().parent / "integration" / "live_helpers.py"


def _load_live_helpers() -> ModuleType:
    spec = importlib.util.spec_from_file_location("hassle_cli_live_helpers", _HELPERS_PATH)
    assert spec is not None and spec.loader is not None, _HELPERS_PATH
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


live_helpers = _load_live_helpers()


class StubHA:
    """The slice of `DirectBackend` the live arrangement helpers use.

    `restored` models HA's `RestoreEntity` behavior on a re-run: the state a
    freshly created helper comes up in, keyed by the `entity_id` it will be
    assigned. Anything not listed comes up at HA's fresh-instance default.
    """

    def __init__(
        self,
        *,
        restored: dict[str, str] | None = None,
        materialize: bool = True,
        obey_services: bool = True,
    ) -> None:
        self.restored = restored or {}
        self.materialize = materialize
        self.obey_services = obey_services
        self.entity_states: dict[str, str] = {}
        self.created: list[tuple[str, dict[str, Any]]] = []
        self.service_calls: list[tuple[str, str, dict[str, Any]]] = []

    # -- Backend slice ---------------------------------------------------
    def create(self, kind: str, config: dict[str, Any]) -> str:
        self.created.append((kind, config))
        object_id = str(config["name"]).lower().replace(" ", "_")
        entity_id = f"{kind}.{object_id}"
        if self.materialize:
            self.entity_states[entity_id] = self.restored.get(
                entity_id, "0" if kind == "counter" else "off"
            )
        return object_id

    def call_service(self, domain: str, service: str, **data: Any) -> None:
        self.service_calls.append((domain, service, data))
        if not self.obey_services:
            return
        entity_id = str(data["entity_id"])
        if entity_id not in self.entity_states:
            return  # HA silently no-ops a call at an entity that does not exist
        if service == "turn_on":
            self.entity_states[entity_id] = "on"
        elif service == "turn_off":
            self.entity_states[entity_id] = "off"

    def states(self) -> list[dict[str, Any]]:
        return [{"entity_id": eid, "state": st} for eid, st in self.entity_states.items()]


def test_arrange_input_boolean_overrides_a_restored_on_state() -> None:
    """The bug, reproduced: the gate helper comes up `"on"` (restored from a
    previous run against the same instance). Arranging it must not assume
    HA's fresh-instance default -- it must SET the state it needs and
    observe it, so phase 1's condition is unsatisfied on run 2 exactly as it
    is on run 1.
    """
    ha = StubHA(restored={"input_boolean.hassle_live_gate_flag": "on"})

    entity_id = live_helpers.arrange_input_boolean(ha, name="Hassle Live Gate Flag", state="off")

    assert entity_id == "input_boolean.hassle_live_gate_flag"
    assert ha.entity_states[entity_id] == "off"
    assert ("input_boolean", "turn_off", {"entity_id": entity_id}) in ha.service_calls


def test_arrange_input_boolean_on_is_symmetric() -> None:
    ha = StubHA(restored={"input_boolean.hassle_live_gate_flag": "off"})

    entity_id = live_helpers.arrange_input_boolean(ha, name="Hassle Live Gate Flag", state="on")

    assert ha.entity_states[entity_id] == "on"
    assert ("input_boolean", "turn_on", {"entity_id": entity_id}) in ha.service_calls


def test_arrange_input_boolean_fails_loudly_when_the_entity_never_appears() -> None:
    """The other half of the live report: `GET /api/states/input_boolean.…`
    answered "Entity not found" -- the created helper's entity was not in
    `/api/states` at all. That must fail here, naming the entity, rather
    than downstream as an unexplained condition result.
    """
    ha = StubHA(materialize=False)

    with pytest.raises(AssertionError) as excinfo:
        live_helpers.arrange_input_boolean(
            ha, name="Hassle Live Gate Flag", state="off", timeout=0.0
        )

    assert "input_boolean.hassle_live_gate_flag" in str(excinfo.value)
    assert "/api/states" in str(excinfo.value)


def test_arrange_input_boolean_fails_loudly_when_the_state_never_settles() -> None:
    """A `turn_off` that is accepted but never lands leaves the precondition
    unmet; the arrangement must say so instead of letting the phase-1
    assertions fail with an unrelated-looking message.
    """
    ha = StubHA(restored={"input_boolean.hassle_live_gate_flag": "on"}, obey_services=False)

    with pytest.raises(AssertionError) as excinfo:
        live_helpers.arrange_input_boolean(
            ha, name="Hassle Live Gate Flag", state="off", timeout=0.0
        )

    message = str(excinfo.value)
    assert "input_boolean.hassle_live_gate_flag" in message
    assert "'off'" in message and "'on'" in message


def test_await_state_returns_once_the_state_is_observed() -> None:
    ha = StubHA()
    ha.entity_states["input_boolean.gate"] = "on"

    assert live_helpers.await_state(ha, "input_boolean.gate", "on", timeout=0.0) == "on"


def test_await_entity_returns_the_observed_state_for_a_counter() -> None:
    """`counter` helpers are arranged by the same suite; the presence wait is
    kind-agnostic (the integration test reads the counter's value before and
    after each phase).
    """
    ha = StubHA()
    counter_object_id = ha.create("counter", {"name": "Hassle Live Run Counter"})

    observed = live_helpers.await_entity(ha, f"counter.{counter_object_id}", timeout=0.0)

    assert observed == "0"


def test_integration_test_no_longer_relies_on_the_creation_default() -> None:
    """Belt and braces: the comment that encoded the bad assumption ("HA's
    own default -- no service call needed to arrange this") must not come
    back, and phase 1 must arrange the gate through the helper.
    """
    source = (_HELPERS_PATH.parent / "test_run_live.py").read_text(encoding="utf-8")

    assert "no service call needed to arrange this" not in source
    assert "arrange_input_boolean" in source
