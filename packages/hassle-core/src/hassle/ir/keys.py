"""Object-key derivation and the set of managed object kinds (F1).

An object key is ``"<kind>:<identity>"`` — e.g. ``"automation:hall_light_on_motion"``,
``"script:movie_time"``, ``"input_boolean:guest_mode"``. This is the stable key
used by the manifest and the plan/apply engine (DESIGN §8.1); it is frozen at F1.

**M10 addition (additive, F1-compatible):** the object-key *format* itself is
unchanged; ``OBJECT_KINDS`` (the enumerated domain vocabulary) widens to include
the four config-entry template-helper domains (``TEMPLATE_DOMAINS``), exactly as
it would for any future helper domain. See docs/ha-api-notes.md §26 and DESIGN
§13's plugin-protocol amendment for the config-entry apply model these domains
use (flow-based create/update, entry removal for delete) instead of the
storage-collection WS API the nine ``HELPER_DOMAINS`` use.
"""

from __future__ import annotations

from slugify import slugify as _unicode_slugify

# The nine storage-collection helper domains Hassle manages in v1 (DESIGN §4, §13).
HELPER_DOMAINS: frozenset[str] = frozenset(
    {
        "input_boolean",
        "input_number",
        "input_select",
        "input_text",
        "input_datetime",
        "input_button",
        "counter",
        "timer",
        "schedule",
    }
)

# The template-helper config-entry domains (M10, DESIGN §13's "config-entry
# helpers" future plugin, now built). Unlike HELPER_DOMAINS these are backed by
# a config entry (REST flow create, REST options-flow update, REST entry
# removal delete -- docs/ha-api-notes.md §26.0) rather than a WS storage
# collection — see docs/ha-api-notes.md §26 and docs/backend.md's config-entry
# addendum. Object identity is derived from the declared `name` (slugified,
# mirroring HELPER_DOMAINS' "id is a slug of name" rule) -- NOT a caller-set
# unique id: real HA's config flow rejects an unrecognized `unique_id` field
# outright (docs/ha-api-notes.md §26.6), so there is no settable unique id at
# all here. The HA-assigned `entry_id` lives only in the manifest, never in
# the object key or DSL body.
TEMPLATE_DOMAINS: frozenset[str] = frozenset(
    {
        "template_number",
        "template_sensor",
        "template_binary_sensor",
        "template_select",
    }
)

# The group-helper config-entry domains (M21, the "mechanical follow-on" M10
# itself predicted). Same apply mechanics as TEMPLATE_DOMAINS (REST flow
# create, REST options-flow update, REST entry removal delete -- docs/
# ha-api-notes.md §38, mirroring §26.0) and the same identity rule (derived
# from the declared `name`, slugified -- no settable `unique_id`, §38.1). The
# real `group` integration's config flow offers twelve flavors (menu step
# `step_id="user"`); each compiles to its own kind here so `object_key`
# already discriminates them (`"group_cover:entryway_top"`, etc.) without a
# separate sub-kind field anywhere in the IR body.
GROUP_DOMAINS: frozenset[str] = frozenset(
    {
        "group_binary_sensor",
        "group_button",
        "group_cover",
        "group_event",
        "group_fan",
        "group_light",
        "group_lock",
        "group_media_player",
        "group_notify",
        "group_sensor",
        "group_switch",
        "group_valve",
    }
)

# Every config-entry-backed helper domain (M10 + M21). A separate set from
# HELPER_DOMAINS (not folded in) because the apply mechanics genuinely differ
# (flow-based vs. direct WS create/update/delete) even though both are
# "helpers" from the DSL/bundle-placement point of view (DESIGN §5.7/§7.3).
CONFIG_ENTRY_DOMAINS: frozenset[str] = TEMPLATE_DOMAINS | GROUP_DOMAINS

# Every object kind Hassle syncs: automation, script, the nine storage-collection
# helpers, and the config-entry template-helper (M10) + group-helper (M21) domains.
OBJECT_KINDS: frozenset[str] = (
    frozenset({"automation", "script"}) | HELPER_DOMAINS | CONFIG_ENTRY_DOMAINS
)


def object_key(kind: str, identity: str) -> str:
    """Build the ``"<kind>:<identity>"`` object key."""
    if kind not in OBJECT_KINDS:
        raise ValueError(f"unknown object kind {kind!r} (expected one of {sorted(OBJECT_KINDS)})")
    return f"{kind}:{identity}"


def slugify(name: str) -> str:
    """HA's storage-collection helper-id derivation rule (docs/ha-api-notes.md
    §4/§17.5), matched EXACTLY by delegating to the same library HA's own
    ``homeassistant.util.slugify`` wraps (python-slugify): unicode is
    TRANSLITERATED, not collapsed -- "°F" -> "degf", "Café" -> "cafe".
    Owner field report: our old regex collapsed non-alphanumerics to an
    underscore, so validate blessed ids HA would never derive and every
    push re-created such helpers under fresh ``_N`` copies.

    F1-compatible addition: shared by `hassle.backend.fake`/`hassle.backend.
    direct` and `hassle.registry.validate`'s helper-id/name-slug mismatch
    check (M7, MILESTONES M7 "beyond the milestone text").
    """
    slug = _unicode_slugify(name, separator="_")
    return slug or "item"


def category_shaped_stem(source_path: str) -> str | None:
    """The category-name slug/stem a bundle file's OWN placement implies, or
    `None` if `source_path` doesn't have the category-shaped, ROOT-LEVEL
    ``<stem>.py`` shape at all -- any nested path (``lib/x.py``,
    ``tests/test_x.py``, ``docs/x.py``, ``.hassle/x.py``, and -- MILESTONES
    M15 work item B -- the RETIRED per-kind-tree shape ``automations/<stem>.py``
    / ``scripts/<stem>.py`` / ``helpers/<stem>.py``, now just ordinary nested
    paths like any other), or the ``misc`` fallback file.

    **MILESTONES M15 work item B (category-first bundle layout,
    docs/ha-api-notes.md §31.6): root-level, not per-kind-tree.** Every
    kind's category-shaped file is now `<slug(category_name)>.py` directly at
    the bundle root -- a mixed-kind file holding an automation, a script, and
    a helper that all share one category name. `lib/`, `tests/`, `docs/`, and
    any dot-directory (`.hassle/`) are never category-shaped regardless of
    their own filename -- there is no need to special-case them by name here:
    they are never root-level (``len(parts) != 1``), so the depth check alone
    already excludes them.

    **Kind-independent** (MILESTONES M12 reviewer finding, still true under
    the new shape): unlike `hassle.sync.category_writeback.
    _category_slug_from_source_path` (a thin wrapper that no longer even
    consults `kind`, now that there's no per-kind tree left to check), this
    only looks at the PATH. This is the predicate `hassle.compiler.bundle`'s
    `CATEGORY`-global capture needs: at capture time there is no single
    object's kind to check against yet (a category file may hold several
    objects of different kinds, or none), so path-shape alone is the right
    and only test -- exactly mirroring how `bundle_ops.
    default_source_path`/`_category_source_path` derive a category-shaped
    placement from a category NAME in the other direction.

    Shared by :mod:`hassle.compiler.bundle` (CATEGORY-global capture),
    :mod:`hassle.registry.validate` (the `category-slug-mismatch` Finding),
    and :func:`hassle.sync.category_writeback._category_slug_from_source_path`
    -- one predicate, never duplicated.
    """
    if not source_path.endswith(".py"):
        return None
    parts = source_path.split("/")
    if len(parts) != 1:
        return None  # nested (incl. the retired automations//scripts//helpers/ trees)
    stem = parts[0][: -len(".py")]
    if not stem or stem == "misc":
        return None
    return stem


def humanize_slug(slug: str) -> str:
    """The inverse of :func:`slugify`, approximately: ``"automatic_hvac"`` ->
    ``"Automatic Hvac"``. Used only to pick a human-readable ``name`` when
    Hassle creates a brand-new HA UI category on push (MILESTONES M11) for a
    source file that names a category HA doesn't have yet -- there is no way
    to recover the original mixed-case/punctuated name from a slug, so this is
    a best-effort display name, not a round-trip. The category's *identity*
    from that point on is its HA-assigned `category_id`, matched by
    ``slugify(name) == slug`` on every subsequent push/pull (same anchor
    `bundle_ops._category_source_path` already uses in the other direction).
    """
    words = [w for w in slug.split("_") if w]
    return " ".join(w.capitalize() for w in words) or "Misc"
