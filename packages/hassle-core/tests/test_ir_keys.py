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
