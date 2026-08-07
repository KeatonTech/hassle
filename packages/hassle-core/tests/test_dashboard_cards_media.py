"""DB3b (media half): iframe / picture / map card builders.

Test contract (docs/internals/dashboards-design.md §5.3, §6.1.1): every
builder in `cards/media.py` is a leaf card built on the shared
`put`/`merge_extra`/`normalize_visibility` conventions and the `record_card`
seam, registered exactly once in `CARD_REGISTRY`. `picture_glance` and
`picture_elements` each carry `camera_image` as an entity-bearing param
alongside (for `picture_glance`) its `entities` row list.
"""

from __future__ import annotations

from typing import Any

import pytest

from hassle.cards import cond
from hassle.compiler.dashboards.card_registry import CARD_REGISTRY
from hassle.compiler.dashboards.cards import media as m
from hassle.compiler.dashboards.errors import ExtraShadowsKwargError
from hassle.compiler.dashboards.recorder import dashboard_recording
from hassle.compiler.dashboards.structure import view

MEDIA_TYPES: tuple[str, ...] = (
    "iframe",
    "picture",
    "picture-glance",
    "picture-elements",
    "map",
)


def _cards(build: Any) -> list[dict[str, Any]]:
    """Record cards directly in a `masonry` view (no `section()` needed)."""
    with dashboard_recording(url_path="a-b") as rec:
        with view(title="V", type="masonry"):
            build()
        return rec.build_config()["views"][0]["cards"]


# ---------------------------------------------------------------------------
# iframe
# ---------------------------------------------------------------------------


def test_iframe_typed_options() -> None:
    def build() -> None:
        m.iframe("https://example.com", title="Panel", aspect_ratio="75%")

    assert _cards(build) == [
        {
            "type": "iframe",
            "url": "https://example.com",
            "title": "Panel",
            "aspect_ratio": "75%",
        }
    ]


def test_iframe_extra_merges_verbatim() -> None:
    def build() -> None:
        m.iframe("https://example.com", extra={"loading": "lazy"})

    assert _cards(build) == [{"type": "iframe", "url": "https://example.com", "loading": "lazy"}]


def test_iframe_extra_shadowing_a_declared_kwarg_raises() -> None:
    with dashboard_recording(url_path="a-b"), view(title="V", type="masonry"):  # noqa: SIM117
        with pytest.raises(ExtraShadowsKwargError):
            m.iframe("https://example.com", extra={"url": "https://other.example"})


def test_iframe_visibility_normalizes_conditions() -> None:
    def build() -> None:
        m.iframe("https://example.com", visibility=cond.screen("(max-width: 600px)"))

    assert _cards(build)[0]["visibility"] == [
        {"condition": "screen", "media_query": "(max-width: 600px)"}
    ]


# ---------------------------------------------------------------------------
# picture
# ---------------------------------------------------------------------------


def test_picture_typed_options() -> None:
    def build() -> None:
        m.picture(
            "/local/floorplan.png",
            tap_action={"action": "navigate", "navigation_path": "/x"},
            alt_text="Floorplan",
        )

    assert _cards(build) == [
        {
            "type": "picture",
            "image": "/local/floorplan.png",
            "tap_action": {"action": "navigate", "navigation_path": "/x"},
            "alt_text": "Floorplan",
        }
    ]


def test_picture_image_is_optional_when_image_entity_is_given() -> None:
    # Review-round fix #12: `image=` is optional -- `image_entity=` (an entity
    # whose STATE is a dynamic image URL) can supply the background instead.
    from hassle.registry import entities as e

    def build() -> None:
        m.picture(image_entity=e.image.front_door_snapshot)

    assert _cards(build) == [{"type": "picture", "image_entity": "image.front_door_snapshot"}]


def test_picture_image_entity_is_an_entity_param() -> None:
    # `image_entity` IS entity-bearing (unlike every other option on this
    # card), so DB4's `e.<domain>.<object_id>` rewrite and DB7's unknown-
    # entity lint must both see it.
    assert "image_entity" in CARD_REGISTRY["picture"].entity_params
    assert "image_entity" in CARD_REGISTRY["picture"].declared


# ---------------------------------------------------------------------------
# picture_glance -- entities varargs + camera_image
# ---------------------------------------------------------------------------


def test_picture_glance_entities_varargs_and_camera_image() -> None:
    def build() -> None:
        m.picture_glance(
            "light.hall",
            "lock.front_door",
            title="Entry",
            image="/local/entry.jpg",
            camera_image="camera.front_door",
        )

    assert _cards(build) == [
        {
            "type": "picture-glance",
            "entities": ["light.hall", "lock.front_door"],
            "title": "Entry",
            "image": "/local/entry.jpg",
            "camera_image": "camera.front_door",
        }
    ]


def test_picture_glance_with_no_entities_still_materializes_an_empty_list() -> None:
    def build() -> None:
        m.picture_glance(camera_image="camera.front_door")

    assert _cards(build) == [
        {"type": "picture-glance", "entities": [], "camera_image": "camera.front_door"}
    ]


# ---------------------------------------------------------------------------
# picture_elements -- elements= passthrough, camera_image, no flat entities
# ---------------------------------------------------------------------------


def test_picture_elements_passes_elements_through_verbatim() -> None:
    elements = [
        {"type": "state-icon", "entity": "light.hall", "style": {"top": "20%", "left": "30%"}},
        {"type": "state-label", "entity": "sensor.cpu_temp"},
    ]

    def build() -> None:
        m.picture_elements(
            "/local/floorplan.png", elements=elements, camera_image="camera.front_door"
        )

    assert _cards(build) == [
        {
            "type": "picture-elements",
            "image": "/local/floorplan.png",
            "elements": elements,
            "camera_image": "camera.front_door",
        }
    ]


def test_picture_elements_image_is_optional_when_camera_image_is_given() -> None:
    def build() -> None:
        m.picture_elements(camera_image="camera.front_door", elements=[])

    cards = _cards(build)
    assert "image" not in cards[0]
    assert cards[0]["camera_image"] == "camera.front_door"


def test_picture_elements_has_no_flat_entities_key() -> None:
    def build() -> None:
        m.picture_elements("/local/floorplan.png")

    assert "entities" not in _cards(build)[0]


# ---------------------------------------------------------------------------
# map -- entities varargs + geo_location_sources
# ---------------------------------------------------------------------------


def test_map_entities_varargs_and_geo_location_sources() -> None:
    def build() -> None:
        m.map(
            "device_tracker.phone",
            "person.alex",
            geo_location_sources=["all"],
            hours_to_show=6,
        )

    assert _cards(build) == [
        {
            "type": "map",
            "entities": ["device_tracker.phone", "person.alex"],
            "geo_location_sources": ["all"],
            "hours_to_show": 6,
        }
    ]


def test_map_builder_is_a_namespace_attribute_not_a_bare_name() -> None:
    # §5.1: `map` is a Python builtin, so `c.map(...)` (attribute access) is
    # the sanctioned spelling -- this module's own top-level `map` name is the
    # builder, never the builtin, and that is fine precisely because nothing
    # in this DSL family calls the builtin.
    assert callable(m.map)
    assert m.map.__name__ == "map"


# ---------------------------------------------------------------------------
# CARD_REGISTRY -- each builder registered exactly once, with correct wiring
# ---------------------------------------------------------------------------


def test_every_media_card_type_is_registered_exactly_once() -> None:
    for card_type in MEDIA_TYPES:
        assert card_type in CARD_REGISTRY, f"{card_type!r} missing from CARD_REGISTRY"
    present = [t for t in CARD_REGISTRY if t in MEDIA_TYPES]
    assert sorted(present) == sorted(MEDIA_TYPES)


@pytest.mark.parametrize(
    ("card_type", "builder", "entity_params"),
    [
        ("iframe", "c.iframe", ()),
        ("picture", "c.picture", ("image_entity",)),
        ("picture-glance", "c.picture_glance", ("entities", "camera_image")),
        ("picture-elements", "c.picture_elements", ("camera_image",)),
        ("map", "c.map", ("entities",)),
    ],
)
def test_card_spec_wiring(card_type: str, builder: str, entity_params: tuple[str, ...]) -> None:
    spec = CARD_REGISTRY[card_type]
    assert spec.builder == builder
    assert spec.entity_params == entity_params
    assert spec.container == "leaf"
    assert spec.context_manager is False
