"""`@dashboard` / `@raw_dashboard` registration and envelope assembly.

Test contract for DB2 (docs/internals/dashboards-design.md §5.2/§5.5/§6.1):
the decorators register a `RegisteredObject` with `kind="dashboard"`, the
compiler builds the §3.2 two-store envelope, and the compiled object is a real
`DashboardConfig` whose `to_ha()` is exactly that envelope.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from hassle.compiler import compile_bundle
from hassle.compiler.dashboards.errors import DashboardUrlPathError
from hassle.ir.models import DashboardConfig

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "dsl"


def _compile(case: str) -> dict[str, Any]:
    result = compile_bundle(FIXTURES / case / "bundle")
    return {key: obj.to_ha() for key, obj in result.objects.items()}


def test_minimal_sections_dashboard_compiles_to_the_envelope() -> None:
    ir = _compile("dashboard_minimal_sections")
    assert list(ir) == ["dashboard:home-main"]
    envelope = ir["dashboard:home-main"]
    assert envelope["meta"] == {
        "url_path": "home-main",
        "title": "Home",
        "icon": "mdi:home",
        "show_in_sidebar": True,
        "require_admin": False,
    }
    assert envelope["config"]["views"][0]["type"] == "sections"


def test_compiled_object_is_a_dashboard_config_keyed_by_url_path() -> None:
    result = compile_bundle(FIXTURES / "dashboard_minimal_sections" / "bundle")
    obj = result.objects["dashboard:home-main"]
    assert isinstance(obj, DashboardConfig)
    assert obj.kind() == "dashboard"
    assert obj.identity == "home-main"
    # The compiled IR object round-trips its own envelope (I3).
    assert DashboardConfig.model_validate(obj.to_ha()).to_ha() == obj.to_ha()


def test_default_dashboard_has_a_null_meta_and_the_sentinel_identity() -> None:
    ir = _compile("dashboard_default")
    assert list(ir) == ["dashboard:default"]
    assert ir["dashboard:default"]["meta"] is None


def test_two_dashboards_in_one_module_both_compile() -> None:
    # §7's file-discipline pin: the compiler imposes NO file discipline.
    ir = _compile("dashboard_two_in_one_module")
    assert sorted(ir) == ["dashboard:downstairs-lights", "dashboard:upstairs-lights"]


def test_compile_time_loop_generates_one_card_per_list_item() -> None:
    # The headline feature: a Python `for` generating cards at COMPILE time.
    ir = _compile("dashboard_compile_time_loop")
    cards = ir["dashboard:heat-pumps"]["config"]["views"][0]["sections"][0]["cards"]
    assert cards[0] == {"type": "heading", "heading": "Heat pumps"}
    assert [c["entity"] for c in cards[1:]] == [
        "climate.living_room",
        "climate.office",
        "climate.bedroom",
    ]


def test_raw_dashboard_returning_a_full_envelope() -> None:
    ir = _compile("dashboard_raw_dashboard")
    envelope = ir["dashboard:strategy-one"]
    assert envelope["meta"]["url_path"] == "strategy-one"
    assert envelope["config"]["strategy"] == {"type": "original-states"}


def test_raw_dashboard_returning_only_a_config_gets_meta_from_the_decorator() -> None:
    ir = _compile("dashboard_raw_dashboard")
    envelope = ir["dashboard:config-only"]
    assert envelope["meta"] == {"url_path": "config-only"}


def test_raw_dashboard_meta_without_url_path_is_rejected_loudly() -> None:
    # §3.4's identity-sentinel guard: the IR keeps the permissive `default`
    # fallback, but the COMPILE path must never silently key a malformed
    # dashboard as the default dashboard.
    with pytest.raises(DashboardUrlPathError):
        compile_bundle(FIXTURES / "dashboard_error_raw_meta_no_url_path" / "bundle")


def test_dashboards_compile_deterministically() -> None:
    for case in ("dashboard_minimal_sections", "dashboard_compile_time_loop"):
        assert _compile(case) == _compile(case)


def test_node_spans_are_reachable_from_the_compile_result() -> None:
    result = compile_bundle(FIXTURES / "dashboard_minimal_sections" / "bundle")
    obj = result.objects["dashboard:home-main"]
    spans = result.node_spans_for(obj)
    assert "views[0]" in spans
    assert "views[0].sections[0].cards[0]" in spans
    card_span = result.node_span(obj, "views[0].sections[0].cards[0]")
    assert card_span is not None
    assert card_span.file.endswith("minimal_sections.py")


def test_registered_dashboards_use_the_shared_registry_path() -> None:
    from hassle.compiler.registry import fresh
    from hassle.compiler.dashboards.decorators import dashboard

    reg = fresh()

    @dashboard(url_path="test-one", title="T")
    def _t() -> None:
        pass

    assert [(o.kind, o.declared_id) for o in reg.objects] == [("dashboard", "test-one")]
