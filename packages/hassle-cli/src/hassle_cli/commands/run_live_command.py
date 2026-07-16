"""`hassle run --live` orchestration: wires `hassle_cli.run_live`'s pure/testable
pieces to a real `Backend` connection (DESIGN §10.4).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.console import Console

from hassle_cli import bundle_ops
from hassle_cli import run_live as run_live_module
from hassle_cli.run_live import render_trace_timeline, run_shadow_session
from hassle_cli.run_sim import parse_target


def execute_live_run(root: Path, target: str, *, skip_conditions: bool, console: Console) -> None:
    from hassle_cli import backend_factory
    from hassle_cli.cli import _require_backend_config

    _path_part, function_name = parse_target(target)
    local_objects, _compile_result = bundle_ops.compile_local_objects(root)

    object_key = None
    body: dict[str, Any] | None = None
    for key, (_kind, config) in local_objects.items():
        if key.endswith(f":{function_name}"):
            object_key = key
            body = config
            break
    if object_key is None or body is None:
        console.print(
            f"[red]hassle run: no automation named {function_name!r} in this bundle[/red]"
        )
        raise SystemExit(1)

    ha_url, token = _require_backend_config(root)

    with backend_factory.connect(ha_url, token) as backend:

        def resolve_shadow_entity_id(shadow_id: str) -> str:
            """The automation `entity_id` is `slug(alias)`, NOT `slug(id)`
            (docs/ha-api-notes.md §10.2, confirmed against real HA) --
            `automation.{shadow_id}` was a latent bug that made every live
            trigger silently target a nonexistent entity (§29 addendum: this,
            not disabled-automation semantics, is why no trace ever appeared).
            Resolve the real entity_id the same way `DirectBackend.
            _alist_automations` enumerates: match `attributes.id` on
            `/api/states`.
            """
            for state in backend.states():  # type: ignore[attr-defined]
                entity_id = str(state.get("entity_id", ""))
                if entity_id.startswith("automation.") and (
                    state.get("attributes", {}).get("id") == shadow_id
                ):
                    return entity_id
            raise RuntimeError(
                f"hassle run --live: the shadow automation {shadow_id!r} was created but no "
                "automation.* entity with that id showed up in /api/states. Fix: this usually "
                "means the config-REST reload settle (DirectBackend._await_config_entity) timed "
                "out -- check HA's own logs for the shadow automation, or retry."
            )

        def trigger_fn(shadow_id: str, **payload: Any) -> None:
            entity_id = resolve_shadow_entity_id(shadow_id)
            backend.call_service(  # type: ignore[attr-defined]
                "automation", "trigger", entity_id=entity_id, **payload
            )

        def list_run_ids_fn(shadow_id: str) -> list[str]:
            traces = backend.list_traces("automation", shadow_id)  # type: ignore[attr-defined]
            return [t["run_id"] for t in traces]

        def get_trace_fn(
            shadow_id: str, exclude_run_ids: frozenset[str] = frozenset()
        ) -> dict[str, Any]:
            traces = backend.list_traces("automation", shadow_id)  # type: ignore[attr-defined]
            candidates = [t for t in traces if t["run_id"] not in exclude_run_ids]
            if not candidates:
                return {}
            # Exactly one new run exists per trigger; [-1] guards against
            # either list ordering.
            run_id = candidates[-1]["run_id"]
            return backend.get_trace("automation", shadow_id, run_id)  # type: ignore[attr-defined]

        # Read the poll bound off the module at call time (not as bound
        # defaults on run_shadow_session) so tests can monkeypatch
        # hassle_cli.run_live.DEFAULT_TRACE_POLL_TIMEOUT/_INTERVAL down to
        # keep the permanently-empty-trace test fast (unit tests never touch
        # the network or wait on a real clock).
        result = run_shadow_session(
            backend,
            object_key,
            body,
            list_run_ids_fn=list_run_ids_fn,
            trigger_fn=trigger_fn,
            get_trace_fn=get_trace_fn,
            skip_conditions=skip_conditions,
            poll_timeout=run_live_module.DEFAULT_TRACE_POLL_TIMEOUT,
            poll_interval=run_live_module.DEFAULT_TRACE_POLL_INTERVAL,
        )

    console.print(f"[green]shadow run complete: {result.shadow_id}[/green]")
    if result.trace:
        console.print(render_trace_timeline(result.trace))
    else:
        # Never silent (docs/ha-api-notes.md §29): the
        # shadow ran and was cleaned up, but no trace ever appeared even
        # after `stream_trace`'s bounded poll -- tell the user explicitly
        # instead of just printing "shadow run complete" and nothing else.
        # Note the shadow is already deleted by the time we get here (cleanup
        # always runs) -- there is nothing left to
        # inspect for THIS run; the fix hint points at HA's own automation
        # traces list for the next attempt / a longer-running one instead.
        console.print(
            f"[yellow]hassle run --live: no trace became available for run "
            f"{result.shadow_id!r} within the poll window, even though the "
            "shadow automation was created, triggered, and cleaned up "
            "successfully. Fix: check Settings > Automations > Traces in the "
            "Home Assistant UI while the run is in progress next time, or "
            "re-run -- a slow HA instance may need more than the default "
            f"{run_live_module.DEFAULT_TRACE_POLL_TIMEOUT:.0f}s poll window.[/yellow]"
        )
