"""DB3b (media half) -- iframe / picture / map card builders.

docs/internals/dashboards-design.md §5.3/§6.1.1, same conventions as
``cards/visual.py`` (that module's docstring has the fuller rationale): every
builder here is a plain leaf-card function, built on ``put``/``merge_extra``/
``normalize_visibility`` and the ``record_card`` seam, registered into
``CARD_REGISTRY`` at import time. ``normalize_rows`` (the ``entities``-varargs
row normalizer, ``hassle.compiler.dashboards.builders``) is the one shared
implementation every row-taking builder in this batch calls -- no per-module
copy.

Two cards in this family carry entity-bearing parameters DB7's table-driven
extraction must see beyond the obvious "one entity" case: ``picture_glance``
has both ``entities`` (its row list) *and* ``camera_image`` (a `camera.*`
entity), and ``picture_elements`` has ``camera_image`` even though it has no
flat ``entities`` list of its own (its ``elements=`` sub-vocabulary is
free-form passthrough, out of ``entity_params`` scope, per §5.3's "elements=
… passthrough-in-v1" note). ``picture`` additionally accepts ``image_entity=``
(an entity whose state is a dynamic image URL) alongside its now-OPTIONAL
``image=`` -- HA requires one of the two, not enforced here (§9, left to HA
like every other cross-field validation); ``image_entity`` is in
``entity_params``/``declared`` since it IS entity-bearing.

Every dict/list-valued typed option in this module (``tap_action=``/
``hold_action=``, ``elements=``, ``geo_location_sources=``) is deep-copied at
record time via ``put_copy`` rather than ``put`` (the review round's
copy-vs-alias fix, SF-3).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from hassle.compiler.dashboards.builders import (
    VisibilityArg,
    merge_extra,
    normalize_rows,
    normalize_visibility,
    put,
    put_copy,
)
from hassle.compiler.dashboards.card_registry import CardSpec, register_card
from hassle.compiler.dashboards.cards.visual import EntityArg
from hassle.compiler.dashboards.recorder import record_card
from hassle.compiler.spans import capture_span

# ---------------------------------------------------------------------------
# iframe
# ---------------------------------------------------------------------------
_IFRAME_DECLARED = frozenset(
    {"type", "url", "title", "aspect_ratio", "allow_open_top_navigation", "visibility"}
)


def iframe(
    url: str,
    *,
    title: Any = None,
    aspect_ratio: Any = None,
    allow_open_top_navigation: Any = None,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """``c.iframe(url, ...)`` -- an embedded ``<iframe>``.

    ``aspect_ratio`` is HA's CSS-style ratio string (``"50%"``).
    """
    span = capture_span(depth=0)
    body: dict[str, Any] = {"type": "iframe", "url": url}
    put(body, "title", title)
    put(body, "aspect_ratio", aspect_ratio)
    put(body, "allow_open_top_navigation", allow_open_top_navigation)
    put(body, "visibility", normalize_visibility(visibility, span=span))
    merge_extra(body, extra, builder="c.iframe", declared=_IFRAME_DECLARED, span=span)
    record_card(body, span=span, what="`c.iframe()`")


register_card(
    CardSpec(
        type="iframe",
        declared=_IFRAME_DECLARED,
        builder="c.iframe",
    )
)


# ---------------------------------------------------------------------------
# picture
# ---------------------------------------------------------------------------
_PICTURE_DECLARED = frozenset(
    {"type", "image", "image_entity", "tap_action", "hold_action", "alt_text", "visibility"}
)


def picture(
    image: str | None = None,
    *,
    image_entity: EntityArg | None = None,
    tap_action: Any = None,
    hold_action: Any = None,
    alt_text: Any = None,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """``c.picture(image, ...)`` -- a static image, no entity of its own.

    ``image=`` is OPTIONAL (review-round fix, #12): ``image_entity=`` (an
    entity whose STATE is a dynamic image URL) can supply the picture instead
    -- HA requires exactly one of the two, not enforced here (§9, left to HA
    like every other cross-field validation this DSL leaves to the backend).
    ``image_entity`` is entity-bearing, so unlike every other option in this
    module it IS in ``entity_params``. ``tap_action``/``hold_action`` are
    HA's action-config dicts, deep-copied at record time (``put_copy``).
    """
    span = capture_span(depth=0)
    body: dict[str, Any] = {"type": "picture"}
    put(body, "image", image)
    put(body, "image_entity", str(image_entity) if image_entity is not None else None)
    put_copy(body, "tap_action", tap_action)
    put_copy(body, "hold_action", hold_action)
    put(body, "alt_text", alt_text)
    put(body, "visibility", normalize_visibility(visibility, span=span))
    merge_extra(body, extra, builder="c.picture", declared=_PICTURE_DECLARED, span=span)
    record_card(body, span=span, what="`c.picture()`")


register_card(
    CardSpec(
        type="picture",
        declared=_PICTURE_DECLARED,
        builder="c.picture",
        entity_params=("image_entity",),
    )
)


# ---------------------------------------------------------------------------
# picture_glance
# ---------------------------------------------------------------------------
_PICTURE_GLANCE_DECLARED = frozenset(
    {
        "type",
        "entities",
        "title",
        "image",
        "camera_image",
        "camera_view",
        "state_filter",
        "tap_action",
        "hold_action",
        "visibility",
    }
)


def picture_glance(
    *entities: EntityArg | dict[str, Any],
    title: Any = None,
    image: Any = None,
    camera_image: Any = None,
    camera_view: Any = None,
    state_filter: Any = None,
    tap_action: Any = None,
    hold_action: Any = None,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """``c.picture_glance(*entities, ...)`` -- an image overlaid with entity
    state icons.

    Either ``image=`` or ``camera_image=`` supplies the background (HA
    requires one; Hassle does not enforce that here -- it would only be
    caught later by HA itself, exactly like every other cross-field HA
    validation this DSL leaves to the backend, §9).
    """
    span = capture_span(depth=0)
    body: dict[str, Any] = {
        "type": "picture-glance",
        "entities": normalize_rows(
            entities, builder="c.picture_glance", param="entities", span=span
        ),
    }
    put(body, "title", title)
    put(body, "image", image)
    put(body, "camera_image", camera_image)
    put(body, "camera_view", camera_view)
    put_copy(body, "state_filter", state_filter)
    put_copy(body, "tap_action", tap_action)
    put_copy(body, "hold_action", hold_action)
    put(body, "visibility", normalize_visibility(visibility, span=span))
    merge_extra(
        body, extra, builder="c.picture_glance", declared=_PICTURE_GLANCE_DECLARED, span=span
    )
    record_card(body, span=span, what="`c.picture_glance()`")


register_card(
    CardSpec(
        type="picture-glance",
        declared=_PICTURE_GLANCE_DECLARED,
        builder="c.picture_glance",
        entity_params=("entities", "camera_image"),
    )
)


# ---------------------------------------------------------------------------
# picture_elements
# ---------------------------------------------------------------------------
_PICTURE_ELEMENTS_DECLARED = frozenset(
    {"type", "image", "elements", "camera_image", "camera_view", "visibility"}
)


def picture_elements(
    image: Any = None,
    *,
    elements: Any = None,
    camera_image: Any = None,
    camera_view: Any = None,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """``c.picture_elements(image, elements=[...], ...)`` -- an image with
    freely-positioned overlay elements.

    ``elements=`` is the passthrough-in-v1 sub-vocabulary (§5.3): a list of
    HA's element-config dicts (``state-icon``, ``state-label``, ``image``,
    ``conditional``, …), kept verbatim -- typed follow-ons are additive and
    welcome, but every element kind round-trips today regardless. ``image``
    is optional because ``camera_image=`` can supply the background instead
    (HA, not Hassle, enforces that at least one is given).
    """
    span = capture_span(depth=0)
    body: dict[str, Any] = {"type": "picture-elements"}
    put(body, "image", image)
    put_copy(body, "elements", elements)
    put(body, "camera_image", camera_image)
    put(body, "camera_view", camera_view)
    put(body, "visibility", normalize_visibility(visibility, span=span))
    merge_extra(
        body, extra, builder="c.picture_elements", declared=_PICTURE_ELEMENTS_DECLARED, span=span
    )
    record_card(body, span=span, what="`c.picture_elements()`")


register_card(
    CardSpec(
        type="picture-elements",
        declared=_PICTURE_ELEMENTS_DECLARED,
        builder="c.picture_elements",
        entity_params=("camera_image",),
    )
)


# ---------------------------------------------------------------------------
# map
# ---------------------------------------------------------------------------
_MAP_DECLARED = frozenset(
    {
        "type",
        "entities",
        "geo_location_sources",
        "hours_to_show",
        "default_zoom",
        "dark_mode",
        "auto_fit",
        "theme_mode",
        "visibility",
    }
)


def map(
    *entities: EntityArg | dict[str, Any],
    geo_location_sources: Any = None,
    hours_to_show: Any = None,
    default_zoom: Any = None,
    dark_mode: Any = None,
    auto_fit: Any = None,
    theme_mode: Any = None,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """``c.map(*entities, ...)`` -- a map card (device trackers + geolocation).

    Named exactly ``map`` on purpose (dashboards-design §5.1): it is a
    ``hassle.cards`` NAMESPACE attribute (``c.map(...)``), never a bare
    top-level name, so it never actually shadows Python's ``map()`` builtin
    for any caller -- only within this module's own top-level namespace,
    which does not use the builtin.
    """
    span = capture_span(depth=0)
    body: dict[str, Any] = {
        "type": "map",
        "entities": normalize_rows(entities, builder="c.map", param="entities", span=span),
    }
    put_copy(body, "geo_location_sources", geo_location_sources)
    put(body, "hours_to_show", hours_to_show)
    put(body, "default_zoom", default_zoom)
    put(body, "dark_mode", dark_mode)
    put(body, "auto_fit", auto_fit)
    put(body, "theme_mode", theme_mode)
    put(body, "visibility", normalize_visibility(visibility, span=span))
    merge_extra(body, extra, builder="c.map", declared=_MAP_DECLARED, span=span)
    record_card(body, span=span, what="`c.map()`")


register_card(
    CardSpec(
        type="map",
        declared=_MAP_DECLARED,
        builder="c.map",
        entity_params=("entities",),
    )
)
