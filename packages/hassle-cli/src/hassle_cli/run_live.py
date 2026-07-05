"""`hassle run --live` (DESIGN §10.4): compile + validate one automation, push
it as a shadow automation, trigger it, stream its trace, then clean up --
always, on success or failure.

Split for testability (MILESTONES M7 test 5: the ONE live test lives in
`tests/integration/test_run_live.py`, env-gated like the M6 suite; everything
here that doesn't require a real HA connection is unit-tested against
`FakeBackend` in `tests/test_run_command.py`):

- `shadow_automation_id` / `build_shadow_config` -- pure, deterministic (R8).
- `trigger_payload` -- the `skip_condition: false`-by-default payload (HA's
  own default is `true`; DESIGN §10.4 point 2/docs/ha-api-notes.md §10.6).
- `run_shadow_session` -- the create -> trigger -> get-trace -> delete
  orchestration against the `Backend` protocol (`create`/`delete` only, so it
  runs unchanged against `FakeBackend`), with `trigger_fn`/`get_trace_fn`
  injected so the real HA-only bits (an actual `automation.trigger` service
  call + `trace/get`) can be faked in unit tests and provided for real by the
  `run` command against `DirectBackend`.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Protocol

from hassle.ir.canonical import canonical_json


def shadow_automation_id(object_key: str) -> str:
    """Deterministic shadow id (R8): same object key -> same shadow id, so a
    crashed run's leftover shadow is recognizable/idempotent-ish across runs."""
    digest = hashlib.sha256(object_key.encode("utf-8")).hexdigest()[:16]
    return f"hassle_shadow_{digest}"


SHADOW_ID_PREFIX = "hassle_shadow_"


def build_shadow_config(object_key: str, body: dict[str, Any]) -> dict[str, Any]:
    """The automation body to push as a shadow: same triggers/conditions/
    actions, but `initial_state: off` (DESIGN §10.4 point 1: "its triggers
    never fire on their own") and a shadow-prefixed id."""
    shadow_id = shadow_automation_id(object_key)
    shadow = dict(body)
    shadow["id"] = shadow_id
    shadow["initial_state"] = False
    return shadow


def trigger_payload(
    *, skip_conditions: bool, variables: dict[str, Any] | None = None
) -> dict[str, Any]:
    """The `automation.trigger` service-call payload.

    HA's own default for `skip_condition` is `true` (conditions skipped); a
    live run should behave like a *real* trigger, so Hassle always sends an
    explicit value: `false` unless `--skip-conditions` was passed (DESIGN
    §10.4 point 2, docs/ha-api-notes.md §10.6).
    """
    payload: dict[str, Any] = {"skip_condition": bool(skip_conditions)}
    if variables:
        payload["variables"] = variables
    return payload


class TriggerFn(Protocol):
    def __call__(self, shadow_id: str, **payload: Any) -> None: ...


class GetTraceFn(Protocol):
    def __call__(self, shadow_id: str) -> dict[str, Any]: ...


@dataclass
class LiveRunResult:
    shadow_id: str
    trace: dict[str, Any] | None


def run_shadow_session(
    backend: Any,
    object_key: str,
    body: dict[str, Any],
    *,
    trigger_fn: TriggerFn,
    get_trace_fn: GetTraceFn,
    skip_conditions: bool = False,
    variables: dict[str, Any] | None = None,
) -> LiveRunResult:
    """Create the shadow, trigger + fetch its trace, then delete the shadow --
    on success *and* on any exception during trigger/trace (cleanup always
    runs; MILESTONES M7 test 5's "also on failure" requirement)."""
    kind = object_key.partition(":")[0]
    shadow_config = build_shadow_config(object_key, body)
    shadow_id = shadow_config["id"]
    backend.create(kind, shadow_config)
    try:
        payload = trigger_payload(skip_conditions=skip_conditions, variables=variables)
        trigger_fn(shadow_id, **payload)
        trace = stream_trace(get_trace_fn, shadow_id)
        return LiveRunResult(shadow_id=shadow_id, trace=trace)
    finally:
        backend.delete(kind, shadow_id)


def stream_trace(get_trace_fn: GetTraceFn, shadow_id: str) -> dict[str, Any]:
    """Thin seam so tests can monkeypatch `hassle_cli.run_live.stream_trace`
    to inject a trace-stream failure (MILESTONES M7 test 5)."""
    return get_trace_fn(shadow_id)


def canonical_shadow_json(config: dict[str, Any]) -> str:
    return canonical_json(config)
