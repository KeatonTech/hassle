"""Golden case: view badges, both shapes.

`badge(entity_or_dict, **options)` records into the enclosing view's `badges`
list: an entity id (or `e.`-ref) builds the modern object form, a plain dict
passes through verbatim for legacy/unknown badge shapes
(docs/internals/dashboards-design.md §5.2, §2.2 item 6).
"""

from hassle import badge, dashboard, raw_card, section, view


@dashboard(url_path="badge-wall", title="Badges")
def badge_wall():
    with view(title="Overview", path="overview"):
        badge("sensor.outside_temp", name="Outside")
        badge("binary_sensor.front_door", extra={"show_state": False})
        badge({"type": "custom:legacy-badge", "entity": "sensor.legacy"})
        with section():
            raw_card({"type": "markdown", "content": "Badges above."})
