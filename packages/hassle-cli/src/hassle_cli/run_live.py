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
import time
from dataclasses import dataclass
from typing import Any, Protocol

from hassle.ir.canonical import canonical_json

# Bounded polling for the trace-persistence race (docs/ha-api-notes.md §27):
# HA's `trace/list` can return empty for a short window after
# `automation.trigger` while the trace is asynchronously persisted -- the
# same class of async-settling race as the config-REST reload wait
# (`DirectBackend._await_config_entity`, docs/ha-api-notes.md §17.7). This is
# live-transport I/O, not core compiler/simulator logic, so R8's "no
# wall-clock" does not apply; the bound keeps a slow/never-settling trace
# from hanging the CLI forever.
DEFAULT_TRACE_POLL_TIMEOUT = 5.0
DEFAULT_TRACE_POLL_INTERVAL = 0.25


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
    poll_timeout: float = DEFAULT_TRACE_POLL_TIMEOUT,
    poll_interval: float = DEFAULT_TRACE_POLL_INTERVAL,
    sleep_fn: Any = time.sleep,
    monotonic_fn: Any = time.monotonic,
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
        trace = stream_trace(
            get_trace_fn,
            shadow_id,
            poll_timeout=poll_timeout,
            poll_interval=poll_interval,
            sleep_fn=sleep_fn,
            monotonic_fn=monotonic_fn,
        )
        return LiveRunResult(shadow_id=shadow_id, trace=trace)
    finally:
        backend.delete(kind, shadow_id)


def stream_trace(
    get_trace_fn: GetTraceFn,
    shadow_id: str,
    *,
    poll_timeout: float = DEFAULT_TRACE_POLL_TIMEOUT,
    poll_interval: float = DEFAULT_TRACE_POLL_INTERVAL,
    sleep_fn: Any = time.sleep,
    monotonic_fn: Any = time.monotonic,
) -> dict[str, Any]:
    """Fetch `shadow_id`'s trace, polling `get_trace_fn` for up to
    `poll_timeout` seconds if it starts out empty.

    `get_trace_fn` returning `{}` means "no trace yet" (see
    `hassle_cli.commands.run_live_command.get_trace_fn`: `trace/list` racing
    HA's async trace persistence right after `automation.trigger`, docs/
    ha-api-notes.md §27). Bare-`{}` used to be returned straight through and
    silently treated as falsy by the caller -- this always re-polls at least
    once (so the common case, the trace lands within a poll or two, needs no
    caller changes) and keeps retrying until either a non-empty trace shows
    up or the bound elapses, at which point it returns `{}` -- the caller
    (`execute_live_run`) is responsible for turning a still-empty trace into
    an explicit warning, never silence.

    `sleep_fn`/`monotonic_fn` are injected so unit tests never do a real
    wall-clock wait (a fake clock advances instantly); production uses
    `time.sleep`/`time.monotonic`, matching `DirectBackend`'s config-reload
    settling pattern.

    Also the seam tests monkeypatch (`monkeypatch.setattr(run_live,
    "stream_trace", ...)`, MILESTONES M7 test 5) to inject a trace-stream
    failure -- unchanged.
    """
    deadline = monotonic_fn() + poll_timeout
    while True:
        trace = get_trace_fn(shadow_id)
        if trace:
            return trace
        if monotonic_fn() >= deadline:
            return {}
        sleep_fn(poll_interval)


def canonical_shadow_json(config: dict[str, Any]) -> str:
    return canonical_json(config)


def render_trace_timeline(trace: dict[str, Any]) -> str:
    """Render a `trace/get` response as a step-by-step timeline (DESIGN
    §10.4 point 3): one line per step path (`trigger`, `condition/0`,
    `action/0`, ...), keyed off `trace["trace"]` (docs/ha-api-notes.md §7's
    capture shape) in the dict's own order (HA returns it execution-ordered).
    Full DSL-source-line mapping is a separate, not-yet-built DESIGN §10.4
    feature -- this renders the step path HA gives, which is already enough
    to locate the corresponding `with if_then(...)`/`service(...)` call in
    the decompiled/authored source.
    """
    steps = trace.get("trace", {})
    lines = [f"trace: run {trace.get('run_id', '?')} ({trace.get('script_execution', '?')})"]
    for path, events in steps.items():
        count = len(events) if isinstance(events, list) else 1
        lines.append(f"  {path} ({count} event{'s' if count != 1 else ''})")
    if not steps:
        lines.append("  (no steps recorded)")
    return "\n".join(lines)
