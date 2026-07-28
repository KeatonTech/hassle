def test_dashboard_kind_is_registered() -> None:
    """`dashboard` — Lovelace storage-mode dashboards
    (docs/internals/dashboards-design.md §3.1). Identity is the `url_path`, so
    unlike every other kind the identity segment routinely contains a HYPHEN
    (HA in fact requires one), which `object_key` must pass through untouched."""
    from hassle.ir.keys import DASHBOARD_KIND, OBJECT_KINDS, object_key

    assert DASHBOARD_KIND == "dashboard"
    assert DASHBOARD_KIND in OBJECT_KINDS
    assert object_key("dashboard", "climate-control") == "dashboard:climate-control"
    # The default dashboard has no registry item and no `url_path`; it keys off
    # the `default` sentinel -- collision-free only by convention, not by
    # construction (ha-api-notes §39.3); nominally a real `url_path` must
    # contain a hyphen.
    assert object_key(DASHBOARD_KIND, "default") == "dashboard:default"


def test_dashboard_identity_is_not_slugified() -> None:
    """A `url_path` is HA's own slug and is used VERBATIM as the identity --
    `slugify` (which would turn "climate-control" into "climate_control")
    must never be applied to it, or every push would target the wrong
    dashboard."""
    from hassle.ir.keys import object_key, slugify

    assert slugify("climate-control") == "climate_control"
    assert object_key("dashboard", "climate-control") == "dashboard:climate-control"


def test_slugify_matches_ha_unicode_transliteration() -> None:
    from hassle.ir.keys import slugify

    """HA derives helper ids via python-slugify, which
    TRANSLITERATES unicode -- "°F" becomes "degf", not "_f". Our old rule
    collapsed it to an underscore, so validate blessed an id HA would never
    derive, and every push re-created the helper under a fresh `_degf_N`."""
    assert (
        slugify("Acceptable temperature variance in occupied rooms, °F")
        == "acceptable_temperature_variance_in_occupied_rooms_degf"
    )
    assert slugify("Café Lights °C") == "cafe_lights_degc"
    assert slugify("hall light  on!") == "hall_light_on"  # ASCII behavior unchanged
    assert slugify("") == "item"  # our empty fallback is preserved
