"""Sync wiring for the dashboard kind (docs/internals/dashboards-design.md
§4.1/§4.2): `_KIND_ORDER` gains `"dashboard"` LAST (after `"automation"`),
`_CALLER_KEYED_KINDS` gains it too (identity travels in the envelope, exactly
like an automation's intrinsic `id`), and `_create_body` needs NO injection
branch for it. Mirrors `test_apply_group_helpers.py`'s apply-order test.
"""

from __future__ import annotations

from typing import Any

from hassle.backend.fake import FakeBackend
from hassle.sync import Manifest, Plan, PlanAction, PlanEntry
from hassle.sync.apply import (  # pyright: ignore[reportPrivateUsage]
    _CALLER_KEYED_KINDS,
    _create_body,
    apply_plan,
)


def test_dashboard_is_caller_keyed() -> None:
    assert "dashboard" in _CALLER_KEYED_KINDS


def test_create_body_needs_no_injection_branch_for_dashboard() -> None:
    local = {
        "meta": {"url_path": "climate-control", "title": "Climate"},
        "config": {"views": []},
    }
    assert _create_body("dashboard", "climate-control", local) is local


def test_apply_order_places_dashboard_last_after_automation() -> None:
    backend = FakeBackend()
    order: list[str] = []

    original_create = backend.create

    def tracking_create(kind: str, config: dict[str, Any]) -> str:
        order.append(kind)
        return original_create(kind, config)

    backend.create = tracking_create  # type: ignore[method-assign]

    plan = Plan(
        entries=[
            PlanEntry(
                object_key="dashboard:climate-control",
                kind="dashboard",
                action=PlanAction.CREATE,
                local={
                    "meta": {"url_path": "climate-control", "title": "Climate"},
                    "config": {"views": []},
                },
            ),
            PlanEntry(
                object_key="automation:a1",
                kind="automation",
                action=PlanAction.CREATE,
                local={"id": "a1", "alias": "A"},
            ),
            PlanEntry(
                object_key="script:s1",
                kind="script",
                action=PlanAction.CREATE,
                local={"alias": "S"},
            ),
            PlanEntry(
                object_key="input_boolean:b1",
                kind="input_boolean",
                action=PlanAction.CREATE,
                local={"name": "B1"},
            ),
        ]
    )
    manifest = Manifest(synced_at="t", ha_version="v", objects={})
    result = apply_plan(plan, backend, manifest)

    assert result.succeeded is True, result.outcomes
    assert order == ["input_boolean", "script", "automation", "dashboard"]


def test_apply_create_dashboard_identity_travels_in_envelope() -> None:
    # No _create_body injection branch is needed: the dashboard's identity
    # (meta.url_path) is already inside the local envelope, so create()
    # returns exactly that identity with nothing extra threaded through.
    backend = FakeBackend()
    plan = Plan(
        entries=[
            PlanEntry(
                object_key="dashboard:climate-control",
                kind="dashboard",
                action=PlanAction.CREATE,
                local={
                    "meta": {"url_path": "climate-control", "title": "Climate"},
                    "config": {"views": []},
                },
            )
        ]
    )
    manifest = Manifest(synced_at="t", ha_version="v", objects={})
    result = apply_plan(plan, backend, manifest)

    assert result.succeeded is True, result.outcomes
    assert "climate-control" in backend.list_remote("dashboard")
