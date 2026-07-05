"""`hassle run --live` orchestration: wires `hassle_cli.run_live`'s pure/testable
pieces to a real `Backend` connection (DESIGN §10.4).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.console import Console

from hassle_cli import bundle_ops
from hassle_cli.run_live import run_shadow_session
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

        def trigger_fn(shadow_id: str, **payload: Any) -> None:
            backend.call_service(  # type: ignore[attr-defined]
                "automation", "trigger", entity_id=f"automation.{shadow_id}", **payload
            )

        def get_trace_fn(shadow_id: str) -> dict[str, Any]:
            traces = backend.list_traces("automation", shadow_id)  # type: ignore[attr-defined]
            if not traces:
                return {}
            run_id = traces[0]["run_id"]
            return backend.get_trace("automation", shadow_id, run_id)  # type: ignore[attr-defined]

        result = run_shadow_session(
            backend,
            object_key,
            body,
            trigger_fn=trigger_fn,
            get_trace_fn=get_trace_fn,
            skip_conditions=skip_conditions,
        )

    console.print(f"[green]shadow run complete: {result.shadow_id}[/green]")
    if result.trace:
        console.print("[bold]trace:[/bold]")
        console.print(str(result.trace))
