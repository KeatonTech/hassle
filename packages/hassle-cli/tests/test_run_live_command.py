"""CI-stabilization follow-up (coordinator finding, docs/ha-api-notes.md §27):
`hassle run --live` used to silently print "shadow run complete" and nothing
else when `trace/list` raced HA's async trace persistence and came back empty
-- `execute_live_run` (hassle_cli.commands.run_live_command) never checked
*why* `result.trace` was falsy, it just skipped the `if result.trace:` block.

These are CLI-level tests exercising `execute_live_run` end-to-end (compile ->
push shadow -> trigger -> trace -> cleanup -> render) against a hand-rolled
stub backend (not `FakeBackend`, which has no trace/call_service surface --
those are `DirectBackend`-only, see hassle.backend.fake's docstring) so both
outcomes -- a trace that eventually shows up, and one that never does -- are
covered without a real HA connection (R2).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from rich.console import Console


def _slugify(text: str) -> str:
    """Toy slugify good enough for these tests -- real HA's is more thorough,
    but the point (entity_id derived from alias, NOT from id) only needs
    lowercase + underscores here."""
    return "".join(ch if ch.isalnum() else "_" for ch in text.lower()).strip("_")


class _StubTraceBackend:
    """Minimal stand-in for `DirectBackend`'s trace-relevant surface
    (`create`/`delete` for the shadow automation lifecycle, `call_service`
    for the trigger, `list_traces`/`get_trace` for the trace poll, `states`
    for entity_id resolution). `register_fake_backend` accepts anything
    shaped like the `Backend` protocol -- no isinstance check -- so this
    doesn't need to BE a `FakeBackend`.

    `states()` deliberately reproduces the real (and, before this fix,
    Hassle-mishandled) HA quirk docs/ha-api-notes.md §10.2 documents:
    `entity_id` is `slug(alias)`, NOT `slug(id)` -- so a stub that just used
    `automation.{id}` here would make `test_execute_live_run_uses_bare_
    automation_id_not_entity_id_for_trace_lookup`'s entity_id assertion
    vacuously true even with the old, broken `trigger_fn`.
    """

    def __init__(self, *, empty_polls_before_trace: int | None) -> None:
        """`empty_polls_before_trace=None` means "never produces a trace"
        (the permanently-empty case); an int means `list_traces` returns
        empty for that many calls, then a real trace."""
        self.created: list[tuple[str, dict[str, Any]]] = []
        self.deleted: list[tuple[str, str]] = []
        self.triggered: list[tuple[str, dict[str, Any]]] = []
        self.list_traces_calls: list[tuple[str, str]] = []
        self.get_trace_calls: list[tuple[str, str, str]] = []
        self._empty_polls_before_trace = empty_polls_before_trace

    def create(self, kind: str, config: dict[str, Any]) -> str:
        self.created.append((kind, config))
        return str(config["id"])

    def delete(self, kind: str, identity: str) -> None:
        self.deleted.append((kind, identity))

    def states(self) -> list[dict[str, Any]]:
        out = []
        for kind, config in self.created:
            if kind != "automation":
                continue
            alias = config.get("alias") or config["id"]
            out.append(
                {
                    "entity_id": f"automation.{_slugify(alias)}",
                    "state": "on",
                    "attributes": {"id": config["id"]},
                }
            )
        return out

    def call_service(self, domain: str, service: str, **data: Any) -> None:
        self.triggered.append((f"{domain}.{service}", data))

    def list_traces(self, kind: str, identity: str) -> list[dict[str, Any]]:
        self.list_traces_calls.append((kind, identity))
        if self._empty_polls_before_trace is None:
            return []
        if len(self.list_traces_calls) <= self._empty_polls_before_trace:
            return []
        return [{"run_id": "run-xyz", "state": "stopped"}]

    def get_trace(self, kind: str, identity: str, run_id: str) -> dict[str, Any]:
        self.get_trace_calls.append((kind, identity, run_id))
        return {
            "run_id": run_id,
            "script_execution": "finished",
            "trace": {"trigger": [{}], "action/0": [{}]},
        }


def _write_live_bundle(tmp_path: Path, *, token: str) -> Path:
    root = tmp_path / "house"
    root.mkdir()
    (root / "hassle.toml").write_text(
        f'ha_url = "fake://{token}"\nformat_version = 1\nmirror = false\n', encoding="utf-8"
    )
    (root / "a.py").write_text(
        """
from hassle import automation, service, state, when

@automation(id="live_test_automation", alias="Live test automation")
def live_test_automation():
    when(state("input_boolean.hassle_flag").to("on"))
    service("input_boolean.turn_off", target={"entity_id": "input_boolean.hassle_flag"})
""",
        encoding="utf-8",
    )
    return root


@pytest.fixture
def _registered_stub_backend():
    """Registers a `_StubTraceBackend` under `backend_factory`'s `fake://`
    seam (same mechanism as the `fake_backend` fixture, but with the
    trace/call_service surface `FakeBackend` lacks) and yields
    `(backend_factory_token, make_backend)` so each test can choose the
    backend's trace-polling behavior."""
    from hassle_cli import backend_factory

    tokens: list[str] = []

    def _register(backend: _StubTraceBackend) -> str:
        token = backend_factory.register_fake_backend(backend)  # type: ignore[arg-type]
        tokens.append(token)
        return token

    yield _register

    for token in tokens:
        backend_factory.unregister_fake_backend(token)


def test_execute_live_run_renders_timeline_once_trace_settles(
    tmp_path: Path, _registered_stub_backend, monkeypatch
) -> None:
    """The trace shows up after two empty `trace/list` polls (the async-
    persistence race) -- `execute_live_run` must still render the timeline,
    not silently skip it."""
    from hassle_cli import run_live
    from hassle_cli.commands.run_live_command import execute_live_run

    # Shrink the poll interval so this test doesn't take a real 0.5s+ of
    # wall-clock sleeping (R2: unit tests stay fast) -- still exercises a
    # real multi-poll loop, just with a near-zero interval.
    monkeypatch.setattr(run_live, "DEFAULT_TRACE_POLL_INTERVAL", 0.001)

    backend = _StubTraceBackend(empty_polls_before_trace=2)
    token = _registered_stub_backend(backend)
    bundle = _write_live_bundle(tmp_path, token=token)

    console = Console(no_color=True, width=200)
    with console.capture() as capture:
        execute_live_run(
            bundle, "a.py::live_test_automation", skip_conditions=False, console=console
        )
    output = capture.get()

    assert "shadow run complete" in output
    assert "action/0" in output  # structural: a real step path rendered
    assert "run-xyz" in output
    assert "no trace became available" not in output
    # Cleaned up regardless.
    assert backend.deleted
    # Sanity: this test wouldn't be meaningful if the stub answered on the
    # first poll -- confirm the race was actually exercised.
    assert len(backend.list_traces_calls) >= 3


def test_execute_live_run_uses_bare_automation_id_not_entity_id_for_trace_lookup(
    tmp_path: Path, _registered_stub_backend, monkeypatch
) -> None:
    """Coordinator ask (point 3): rule out "wrong item_id" (e.g. the shadow's
    full `entity_id` instead of its bare automation id) as an alternate
    explanation for the empty-trace symptom -- it would ALSO produce an
    empty `trace/list` and look identical to the settling race. Pin down the
    exact params `trace/list`/`trace/get` receive against the M0.V capture
    shape (docs/ha-api-notes.md §7: `domain` + `item_id` + `run_id`, where
    `item_id` is the automation's own `id`, e.g. `"hassle_skipcond"` -- NOT
    `"automation.hassle_skipcond"`).

    Also pins the §27 addendum fix: `automation.trigger`'s service call must
    target the REAL entity_id -- `slug(alias)`, docs/ha-api-notes.md §10.2 --
    resolved via `/api/states`, not the naive-and-wrong `automation.{shadow_id}`
    (the actual root cause of the missing-trace symptom: that entity never
    existed, so the trigger silently hit nothing)."""
    from hassle_cli import run_live
    from hassle_cli.commands.run_live_command import execute_live_run

    monkeypatch.setattr(run_live, "DEFAULT_TRACE_POLL_INTERVAL", 0.001)

    backend = _StubTraceBackend(empty_polls_before_trace=0)
    token = _registered_stub_backend(backend)
    bundle = _write_live_bundle(tmp_path, token=token)

    console = Console(no_color=True, width=200)
    with console.capture():
        execute_live_run(
            bundle, "a.py::live_test_automation", skip_conditions=False, console=console
        )

    shadow_id = backend.created[0][1]["id"]
    assert isinstance(shadow_id, str)
    assert not shadow_id.startswith("automation.")  # bare id, not an entity_id

    # trace/list and trace/get: item_id is the bare automation id.
    assert backend.list_traces_calls
    for kind, item_id in backend.list_traces_calls:
        assert kind == "automation"
        assert item_id == shadow_id
    assert backend.get_trace_calls
    for kind, item_id, run_id in backend.get_trace_calls:
        assert kind == "automation"
        assert item_id == shadow_id
        assert run_id == "run-xyz"

    # automation.trigger's service call: the REAL entity_id (slug(alias)),
    # NOT the naive-and-wrong f"automation.{shadow_id}" -- the alias is
    # unchanged from the original automation ("Live test automation"), so
    # the shadow's entity_id is automation.live_test_automation, which does
    # NOT textually match automation.hassle_shadow_<hash>. This is exactly
    # the mismatch that silently broke every live trigger before the fix.
    assert backend.triggered
    _service, data = backend.triggered[0]
    assert data["entity_id"] != f"automation.{shadow_id}"
    assert data["entity_id"] == "automation.live_test_automation"


def test_execute_live_run_warns_explicitly_when_trace_never_appears(
    tmp_path: Path, _registered_stub_backend, monkeypatch
) -> None:
    """A permanently-empty trace (never persisted, or HA never returns one)
    must produce an explicit warning naming the run -- never silence."""
    from hassle_cli import run_live
    from hassle_cli.commands.run_live_command import execute_live_run

    # Keep this test fast: shrink the poll bound instead of waiting out the
    # real 5s default.
    monkeypatch.setattr(run_live, "DEFAULT_TRACE_POLL_TIMEOUT", 0.05)
    monkeypatch.setattr(run_live, "DEFAULT_TRACE_POLL_INTERVAL", 0.01)

    backend = _StubTraceBackend(empty_polls_before_trace=None)
    token = _registered_stub_backend(backend)
    bundle = _write_live_bundle(tmp_path, token=token)

    console = Console(no_color=True, width=200)
    with console.capture() as capture:
        execute_live_run(
            bundle, "a.py::live_test_automation", skip_conditions=False, console=console
        )
    output = capture.get()

    assert "shadow run complete" in output
    assert "no trace became available" in output.lower()
    # Explicit about which run, not a bare "something went wrong".
    assert backend.created[0][1]["id"] in output
    # Still cleaned up even though no trace ever showed up.
    assert backend.deleted


def test_execute_live_run_ignores_stale_pre_trigger_trace(
    tmp_path: Path, _registered_stub_backend, monkeypatch
) -> None:
    """Round-6 CI finding: HA retains traces per item_id across the shadow's
    delete/recreate, so a second `run --live` could render the PREVIOUS run's
    trace. Selection must exclude run_ids that existed before this trigger."""
    from hassle_cli import run_live
    from hassle_cli.commands.run_live_command import execute_live_run

    monkeypatch.setattr(run_live, "DEFAULT_TRACE_POLL_INTERVAL", 0.001)

    class _StaleTraceBackend(_StubTraceBackend):
        def __init__(self) -> None:
            super().__init__(empty_polls_before_trace=None)
            self._fresh_landed = False

        def call_service(self, domain: str, service: str, **data: Any) -> None:
            super().call_service(domain, service, **data)
            if domain == "automation" and service == "trigger":
                self._fresh_landed = True

        def list_traces(self, kind: str, identity: str) -> list[dict[str, Any]]:
            self.list_traces_calls.append((kind, identity))
            stale = [{"run_id": "stale-1", "state": "stopped"}]
            if not self._fresh_landed:
                return stale
            return stale + [{"run_id": "fresh-2", "state": "stopped"}]

        def get_trace(self, kind: str, identity: str, run_id: str) -> dict[str, Any]:
            self.get_trace_calls.append((kind, identity, run_id))
            if run_id == "stale-1":
                return {
                    "run_id": "stale-1",
                    "script_execution": "failed_conditions",
                    "trace": {"trigger": [{}], "condition/0": [{}]},
                }
            return {
                "run_id": "fresh-2",
                "script_execution": "finished",
                "trace": {"trigger": [{}], "action/0": [{}]},
            }

    backend = _StaleTraceBackend()
    token = _registered_stub_backend(backend)
    bundle = _write_live_bundle(tmp_path, token=token)

    console = Console(no_color=True, width=200)
    with console.capture() as capture:
        execute_live_run(
            bundle, "a.py::live_test_automation", skip_conditions=False, console=console
        )
    output = capture.get()

    assert "action/0" in output, output
    assert "fresh-2" in output, output
    assert "stale-1" not in output, output
