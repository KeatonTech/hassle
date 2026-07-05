"""Object-key derivation and the set of managed object kinds (F1).

An object key is ``"<kind>:<identity>"`` — e.g. ``"automation:hall_light_on_motion"``,
``"script:movie_time"``, ``"input_boolean:guest_mode"``. This is the stable key
used by the manifest and the plan/apply engine (DESIGN §8.1); it is frozen at F1.
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

# Every object kind Hassle syncs in v1: automation, script, and the nine helpers.
OBJECT_KINDS: frozenset[str] = frozenset({"automation", "script"}) | HELPER_DOMAINS


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
