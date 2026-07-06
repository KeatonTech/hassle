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

import re

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

# Every config-entry-backed helper domain (M10). A separate set from
# HELPER_DOMAINS (not folded in) because the apply mechanics genuinely differ
# (flow-based vs. direct WS create/update/delete) even though both are
# "helpers" from the DSL/bundle-placement point of view (DESIGN §5.7/§7.3).
CONFIG_ENTRY_DOMAINS: frozenset[str] = TEMPLATE_DOMAINS

# Every object kind Hassle syncs: automation, script, the nine storage-collection
# helpers, and (M10) the config-entry template-helper domains.
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
    §4/§17.5): lowercase, non-alphanumeric runs collapsed to a single
    underscore, leading/trailing underscores stripped.

    F1-compatible addition: shared by `hassle.backend.fake`/`hassle.backend.
    direct` (which previously each carried a private copy of this exact
    logic) and `hassle.registry.validate`'s helper-id/name-slug mismatch
    check (M7, MILESTONES M7 "beyond the milestone text").
    """
    slug = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    return slug or "item"
