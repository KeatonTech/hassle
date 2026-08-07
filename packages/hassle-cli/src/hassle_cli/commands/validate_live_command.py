"""`hassle validate --live` (DESIGN §9 tier 4): HA's own server-side
`validate_config`, run per automation object -- plus the dashboards
tier-4-absence notice (docs/internals/dashboards-design.md §8's tier-4 row).

**Deviation note, flagged rather than silently worked around** (see this
change's report): DESIGN.md §9's tier table and dashboards-design.md §8 both
write as though `hassle validate --live` already existed before this change --
it did not (`packages/hassle-cli/src/hassle_cli/cli.py`'s `validate` command
had only `--json`; `DirectBackend.validate_config` existed but nothing in the
CLI ever called it, and it is deliberately NOT part of the `Backend` Protocol,
docs/internals/backend-protocol.md). This module is the minimal, honest
version of that command: automations get a REAL server-side check (HA's
`validate_config`, an existing, already-`ha-api-notes.md §6`-documented
WS command -- see `hassle.backend.direct.DirectBackend.validate_config`),
because that command is genuinely automation-block-shaped
(`triggers`/`conditions`/`actions`) and nothing else. Scripts and helpers get
NO live check here either (HA's `validate_config` doesn't apply to them, and
building a per-kind server-side check for those kinds is a separate, unscoped
undertaking, not silently invented in a dashboards workstream) -- only the
dashboards tier-4-absence messaging this workstream owns is new product
surface for those other kinds' silence.
"""

from __future__ import annotations

from typing import Any

from hassle.compiler.bundle import CompileResult
from hassle.ir.models import AutomationConfig
from hassle.registry.finding import Finding

_BLOCK_LABEL: dict[str, str] = {
    "triggers": "trigger",
    "conditions": "condition",
    "actions": "action",
}

#: The one-line dashboards tier-4-absence notice (dashboards-design.md §8):
#: printed at most ONCE per `hassle validate --live` invocation, never per
#: dashboard, whenever the bundle has at least one dashboard object.
DASHBOARD_LIVE_TIER_NOTICE = (
    "hassle validate --live: dashboards have no server-side validation tier -- Home "
    "Assistant exposes no `validate_config` (or equivalent) analogue for Lovelace "
    "dashboard bodies (docs/internals/dashboards-design.md §2.2 item 2, §8). Dashboard "
    "cards are not checked by this pass -- compile + registry entity/area checks "
    "(`hassle validate`, no --live needed) are the full validation surface for this kind."
)


def has_dashboard_objects(result: CompileResult) -> bool:
    """Whether `result` contains at least one compiled dashboard object --
    the gate for printing `DASHBOARD_LIVE_TIER_NOTICE` (once, not per-object)."""
    return any(key.startswith("dashboard:") for key in result.objects)


def live_validate_automations(backend: Any, result: CompileResult) -> list[Finding]:
    """Run HA's `validate_config` (docs/internals/ha-api-notes.md §6: requires the
    plural `triggers`/`conditions`/`actions` keys, returns a per-block
    `{"valid": bool, "error": str | None}` report) against every automation
    object in `result`, converting an invalid block into a `Finding`.

    `backend` is duck-typed (like `hassle_cli.run_live`'s `backend: Any`):
    `validate_config` is a `DirectBackend`-only method, deliberately not part
    of the frozen `Backend` Protocol (docs/internals/backend-protocol.md).
    """
    findings: list[Finding] = []
    for key, obj in result.objects.items():
        if not isinstance(obj, AutomationConfig):
            continue
        report = backend.validate_config(obj.to_ha())
        if not isinstance(report, dict):
            continue
        for block, label in _BLOCK_LABEL.items():
            entry = report.get(block)
            if not isinstance(entry, dict) or entry.get("valid", True):
                continue
            span = result.decl_span_for(key)
            file = span.file if span is not None else None
            line = span.line if span is not None else None
            findings.append(
                Finding(
                    code="live-invalid-config",
                    severity="error",
                    file=file,
                    line=line,
                    message=(
                        f"Home Assistant's server-side `validate_config` rejected `{key}`'s "
                        f"{label} block: {entry.get('error')}."
                    ),
                    fix=(
                        "Fix the config so HA's own validate_config accepts it (this is "
                        "HA's own rejection, not a Hassle compile error), then re-run "
                        "`hassle validate --live`."
                    ),
                )
            )
    return findings
