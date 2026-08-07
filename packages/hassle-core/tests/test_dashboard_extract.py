"""Entity/area reference extraction from a compiled dashboard's card tree
(DESIGN §9 tier 2; docs/internals/dashboards-design.md §8).

Table-driven off `CARD_REGISTRY.entity_params`/`.declared` (F5), plus the
special-cased shapes it cannot express: badges (both shapes, view-level and
a card's own), visibility/conditional conditions, the `area` card's AREA id,
and the conservative raw-node/undeclared-key scan.
"""

from __future__ import annotations

from pathlib import Path

from hassle.compiler.bundle import compile_bundle
from hassle.registry.dashboard_extract import extract_dashboard_references


def _write_bundle(tmp_path: Path, code: str) -> Path:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "dash.py").write_text(code, encoding="utf-8")
    return bundle


def _entity_ids(tmp_path: Path, code: str) -> set[str]:
    result = compile_bundle(_write_bundle(tmp_path, code))
    refs = extract_dashboard_references(result)
    return {r.entity_id for r in refs if r.entity_id is not None}


# --- single entity_params (scalar) ------------------------------------------


def test_extract_scalar_entity_param(tmp_path: Path) -> None:
    ids = _entity_ids(
        tmp_path,
        """
from hassle import dashboard, section, view
from hassle import cards as c

@dashboard(url_path="a-b")
def d():
    with view(title="V"), section():
        c.tile("climate.living_room")
""",
    )
    assert "climate.living_room" in ids


# --- list-shaped entity_params (rows: bare string or dict with "entity") ----


def test_extract_entities_rows_bare_strings(tmp_path: Path) -> None:
    ids = _entity_ids(
        tmp_path,
        """
from hassle import dashboard, section, view
from hassle import cards as c

@dashboard(url_path="a-b")
def d():
    with view(title="V"), section():
        c.entities("light.a", "light.b", title="All")
""",
    )
    assert {"light.a", "light.b"} <= ids


def test_extract_entities_rows_dict_with_entity_key_via_raw(tmp_path: Path) -> None:
    ids = _entity_ids(
        tmp_path,
        """
from hassle import dashboard, raw_card, section, view

@dashboard(url_path="a-b")
def d():
    with view(title="V"), section():
        raw_card({
            "type": "entities",
            "entities": [
                "climate.living_room",
                {"type": "divider"},
                {"entity": "climate.office"},
            ],
        })
""",
    )
    assert {"climate.living_room", "climate.office"} <= ids


def test_extract_entities_row_divider_dict_has_no_entity(tmp_path: Path) -> None:
    ids = _entity_ids(
        tmp_path,
        """
from hassle import dashboard, raw_card, section, view

@dashboard(url_path="a-b")
def d():
    with view(title="V"), section():
        raw_card({"type": "entities", "entities": [{"type": "divider"}]})
""",
    )
    assert not ids


# --- badges: view-level, both shapes -----------------------------------------


def test_extract_view_badges_object_form(tmp_path: Path) -> None:
    ids = _entity_ids(
        tmp_path,
        """
from hassle import badge, dashboard, section, view

@dashboard(url_path="a-b")
def d():
    with view(title="V"):
        badge("sensor.outside_temp")
        with section():
            pass
""",
    )
    assert "sensor.outside_temp" in ids


def test_extract_view_badges_bare_legacy_string(tmp_path: Path) -> None:
    # A legacy bare-string badge, as real HA storage (or a pulled config)
    # writes it -- not reachable through the `badge()` builder itself (which
    # always emits the object form), but real via raw_dashboard/adopted JSON.
    ids = _entity_ids(
        tmp_path,
        """
from hassle import raw_dashboard

@raw_dashboard(url_path="a-b")
def d():
    return {"config": {"views": [{"title": "V", "badges": ["sensor.legacy_bare_badge"]}]}}
""",
    )
    assert "sensor.legacy_bare_badge" in ids


# --- badges nested inside a KNOWN card (heading) -----------------------------


def test_extract_heading_card_badges_object_form(tmp_path: Path) -> None:
    ids = _entity_ids(
        tmp_path,
        """
from hassle import dashboard, section, view
from hassle import cards as c

@dashboard(url_path="a-b")
def d():
    with view(title="V"), section():
        c.heading(heading="Heat pumps", badges=["climate.living_room"])
""",
    )
    assert "climate.living_room" in ids


def test_extract_heading_card_badges_bare_string_via_raw(tmp_path: Path) -> None:
    ids = _entity_ids(
        tmp_path,
        """
from hassle import dashboard, raw_card, section, view

@dashboard(url_path="a-b")
def d():
    with view(title="V"), section():
        raw_card({"type": "heading", "heading": "H", "badges": ["sensor.legacy_heading_badge"]})
""",
    )
    assert "sensor.legacy_heading_badge" in ids


# --- visibility / conditional conditions -------------------------------------


def test_extract_visibility_condition_entity(tmp_path: Path) -> None:
    ids = _entity_ids(
        tmp_path,
        """
from hassle import dashboard, section, view
from hassle import cards as c
from hassle.cards import cond

@dashboard(url_path="a-b")
def d():
    with view(title="V"), section():
        c.tile("light.hall", visibility=[cond.state("input_boolean.guest_mode", "on")])
""",
    )
    assert "input_boolean.guest_mode" in ids


def test_extract_conditional_card_conditions_entity(tmp_path: Path) -> None:
    ids = _entity_ids(
        tmp_path,
        """
from hassle import dashboard, section, view
from hassle import cards as c
from hassle.cards import cond

@dashboard(url_path="a-b")
def d():
    with view(title="V"), section():
        with c.conditional(cond.state("input_boolean.guest_mode", "on")):
            c.tile("light.hall")
""",
    )
    assert {"input_boolean.guest_mode", "light.hall"} <= ids


def test_extract_nested_any_all_not_conditions(tmp_path: Path) -> None:
    ids = _entity_ids(
        tmp_path,
        """
from hassle import dashboard, section, view
from hassle import cards as c
from hassle.cards import cond

@dashboard(url_path="a-b")
def d():
    with view(title="V"), section():
        c.tile(
            "light.hall",
            visibility=[cond.any(cond.state("light.a", "on"), cond.state("light.b", "on"))],
        )
""",
    )
    assert {"light.a", "light.b"} <= ids


# --- area card: AREA id, not an entity id ------------------------------------


def test_area_card_extracts_area_id_not_entity_id(tmp_path: Path) -> None:
    result = compile_bundle(
        _write_bundle(
            tmp_path,
            """
from hassle import dashboard, section, view
from hassle import cards as c

@dashboard(url_path="a-b")
def d():
    with view(title="V"), section():
        c.area("living_room")
""",
        )
    )
    from hassle.registry.dashboard_extract import extract_dashboard_references

    refs = extract_dashboard_references(result)
    area_ids = {r.area_id for r in refs if r.area_id is not None}
    entity_ids = {r.entity_id for r in refs if r.entity_id is not None}
    assert "living_room" in area_ids
    assert "living_room" not in entity_ids


# --- raw/unknown card type: conservative entity-shaped-string + Jinja scan --


def test_raw_card_unknown_type_conservative_literal_scan(tmp_path: Path) -> None:
    ids = _entity_ids(
        tmp_path,
        """
from hassle import dashboard, raw_card, section, view

@dashboard(url_path="a-b")
def d():
    with view(title="V"), section():
        raw_card({
            "type": "custom:bubble-card",
            "card_type": "button",
            "tap_action": {"action": "call-service", "service": "light.toggle"},
            "entity": "light.bubble_target",
        })
""",
    )
    assert "light.bubble_target" in ids


def test_raw_card_unknown_type_jinja_scan(tmp_path: Path) -> None:
    ids = _entity_ids(
        tmp_path,
        """
from hassle import dashboard, raw_card, section, view

@dashboard(url_path="a-b")
def d():
    with view(title="V"), section():
        raw_card({
            "type": "custom:bubble-card",
            "content": "{{ states('sensor.templated_target') }}",
        })
""",
    )
    assert "sensor.templated_target" in ids


def test_known_card_undeclared_extra_key_gets_conservative_scan(tmp_path: Path) -> None:
    # `extra={...}` merges a stored key `tile` does not itself declare --
    # exactly the "unknown keys" half of §8's tier-2 row.
    ids = _entity_ids(
        tmp_path,
        """
from hassle import dashboard, section, view
from hassle import cards as c

@dashboard(url_path="a-b")
def d():
    with view(title="V"), section():
        c.tile("light.hall", extra={"icon_tap_action": {
            "action": "call-service",
            "service": "light.toggle",
            "target": {"entity_id": "light.extra_key_target"},
        }})
""",
    )
    assert "light.extra_key_target" in ids


def test_known_card_declared_non_entity_key_is_not_scanned(tmp_path: Path) -> None:
    # `name`/`icon` are DECLARED, non-entity options -- known surface, never
    # rescanned (even though "mdi:thermostat"-shaped strings would never
    # match the entity regex anyway, this pins the declared-key exclusion
    # itself rather than relying on the regex to save us).
    ids = _entity_ids(
        tmp_path,
        """
from hassle import dashboard, section, view
from hassle import cards as c

@dashboard(url_path="a-b")
def d():
    with view(title="V"), section():
        c.tile("light.hall", name="light.not_a_reference")
""",
    )
    assert "light.not_a_reference" not in ids


# --- markdown content: tier-2 scope boundary ---------------------------


def test_markdown_content_is_out_of_tier_2_scope(tmp_path: Path) -> None:
    # `content` is a DECLARED markdown-card key (known, non-entity_params
    # surface), not an unknown card type or an unknown/`extra=` key -- so the
    # §8 tier-2 conservative scan deliberately does not reach into it. Jinja
    # entity references embedded in markdown content are §8's SEPARATE tier-3
    # row ("template lint"), out of this workstream's scope.
    ids = _entity_ids(
        tmp_path,
        """
from hassle import dashboard, section, view
from hassle import cards as c

@dashboard(url_path="a-b")
def d():
    with view(title="V"), section():
        c.markdown("{{ states('sensor.markdown_target') }}")
""",
    )
    assert "sensor.markdown_target" not in ids


# --- entity-filter / conditional nesting reaches the wrapped card -----------


def test_entity_filter_reaches_its_rows_and_wrapped_card(tmp_path: Path) -> None:
    ids = _entity_ids(
        tmp_path,
        """
from hassle import dashboard, section, view
from hassle import cards as c

@dashboard(url_path="a-b")
def d():
    with view(title="V"), section():
        with c.entity_filter(entities=["light.a", "light.b"]):
            c.glance("light.c")
""",
    )
    assert {"light.a", "light.b", "light.c"} <= ids


def test_extraction_reaches_deeply_nested_stack(tmp_path: Path) -> None:
    ids = _entity_ids(
        tmp_path,
        """
from hassle import dashboard, section, view
from hassle import cards as c

@dashboard(url_path="a-b")
def d():
    with view(title="V"), section():
        with c.vertical_stack():
            with c.horizontal_stack():
                c.tile("light.deeply_nested")
""",
    )
    assert "light.deeply_nested" in ids


# --- spans --------------------------------------------------------------


def test_reference_span_points_at_the_card_line(tmp_path: Path) -> None:
    result = compile_bundle(
        _write_bundle(
            tmp_path,
            """
from hassle import dashboard, section, view
from hassle import cards as c

@dashboard(url_path="a-b")
def d():
    with view(title="V"), section():
        c.tile("light.hall")
""",
        )
    )
    from hassle.registry.dashboard_extract import extract_dashboard_references

    refs = extract_dashboard_references(result)
    matches = [r for r in refs if r.entity_id == "light.hall"]
    assert matches
    assert matches[0].span is not None
    assert matches[0].span.file.endswith("dash.py")


def test_conditional_wrapped_card_reference_has_a_span(tmp_path: Path) -> None:
    # The single-child `card:` slot -- currently addressed by the recorder's
    # `card[0]` spelling (see this test's own module docstring note on the
    # documented span-grammar discrepancy); must not silently lose its span
    # either way.
    result = compile_bundle(
        _write_bundle(
            tmp_path,
            """
from hassle import dashboard, section, view
from hassle import cards as c
from hassle.cards import cond

@dashboard(url_path="a-b")
def d():
    with view(title="V"), section():
        with c.conditional(cond.state("input_boolean.guest_mode", "on")):
            c.tile("light.wrapped")
""",
        )
    )
    from hassle.registry.dashboard_extract import extract_dashboard_references

    refs = extract_dashboard_references(result)
    matches = [r for r in refs if r.entity_id == "light.wrapped"]
    assert matches
    assert matches[0].span is not None
