"""The card-type registry — one table, three consumers (freeze F5).

Frozen with F5 (design doc §6.1.1) as the single description of every card type
Hassle models. It exists so the three layers that need "what does an
``<HA type string>`` card look like in the DSL?" answer it from ONE place
instead of three hand-maintained parallel switch statements:

- **DB3's builders** register their entry here (one append-only line each);
- **DB4's decompiler** picks the emitter for a stored card by its ``type``
  string, reads ``builder`` for the call to emit, ``entity_params`` to decide
  which argument positions get the ``e.<domain>.<object_id>`` registry-accessor
  treatment, and ``container`` to know whether to open a ``with`` block (and
  which key holds the children);
- **DB7's validation** walks the same ``entity_params`` for table-driven
  card-tree entity extraction — explicitly "not per-card ad-hoc code" (§8's
  tier-2 row).

A type ABSENT from this table is never an error: it decompiles to ``raw_card``
and shows up in the coverage metric (§6.4), which is exactly the tracked signal
that a new HA release added a card.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

#: How a card holds its children, if at all.
#:
#: - ``"leaf"`` — no children (a function call in the DSL);
#: - ``"cards"`` — a list of child cards under ``cards`` (a ``with`` block);
#: - ``"card"`` — exactly ONE child card under ``card`` (a ``with`` block);
#: - ``"sections"`` — a list of sections under ``sections`` (views only).
ContainerShape = Literal["leaf", "cards", "card", "sections"]


def _empty_params() -> tuple[str, ...]:
    return ()


def _empty_declared() -> frozenset[str]:
    return frozenset()


@dataclass(frozen=True)
class CardSpec:
    """One row of the registry: everything a consumer needs about a card type."""

    #: The HA ``type`` string as stored (``"vertical-stack"``, ``"tile"``, …).
    #: For the structural pieces below, the pseudo-types ``"view"``/``"badge"``.
    type: str
    #: The DSL name that builds it, qualified as an author would write it
    #: (``"c.tile"``, ``"view"``, ``"section"``).
    builder: str
    #: **Stored config keys** whose value is an entity id (or a list of them) --
    #: NOT Python parameter names. The two usually coincide (a builder's kwarg
    #: mirrors the HA option name), but where they diverge it is the STORED key
    #: that matters: DB7 walks these against the compiled card body to extract
    #: entity references, and DB4 rewrites exactly these value positions to
    #: ``e.<domain>.<object_id>``. Both operate on stored config, never on the
    #: DSL call. Every one of them is therefore also in :attr:`declared`.
    entity_params: tuple[str, ...] = field(default_factory=_empty_params)
    #: Every **stored config key** this builder writes from its own typed
    #: keywords -- the set a generic decompiler emitter subtracts from a stored
    #: card body to decide what must go into ``extra={...}`` (§5.3's
    #: forward-compatibility valve). Include the ``type`` key and any structural
    #: child key (``cards``/``card``) the builder writes itself.
    #:
    #: Defaulted so a row is one line to add, but **every real registration must
    #: populate it** -- an empty set makes a generic emitter dump the entire card
    #: into ``extra=``. ``tests/test_dashboard_card_registry.py`` enforces this
    #: for every row in the table.
    declared: frozenset[str] = field(default_factory=_empty_declared)
    #: How the card holds its children (see :data:`ContainerShape`).
    container: ContainerShape = "leaf"
    #: Whether the builder is a context manager (``with`` block) in the DSL.
    #: Always true for a non-``leaf`` container, and stated explicitly so a
    #: consumer never has to infer it.
    context_manager: bool = False


#: type string -> spec. DB3 batches append their families; nothing is removed.
CARD_REGISTRY: dict[str, CardSpec] = {}


def register_card(spec: CardSpec) -> CardSpec:
    """Add ``spec`` to :data:`CARD_REGISTRY` (append-only; re-registration is a bug)."""
    if spec.type in CARD_REGISTRY:
        raise ValueError(f"card type {spec.type!r} is already registered")
    CARD_REGISTRY[spec.type] = spec
    return spec


# ---------------------------------------------------------------------------
# DB2's structural pieces. These are not "cards" HA stores with a `type` key of
# their own -- a view and a badge are their own node classes -- so they are
# keyed by a pseudo-type prefixed `structure:` and kept OUT of `CARD_REGISTRY`
# (a decompiler looking up a stored card's `type` must never match them).
# ---------------------------------------------------------------------------
STRUCTURE_REGISTRY: dict[str, CardSpec] = {
    "structure:view": CardSpec(
        type="structure:view",
        builder="view",
        # Mirrors `structure._VIEW_DECLARED` -- the same set `extra=` may not
        # shadow, which is exactly the set an emitter must NOT put in `extra=`.
        declared=frozenset(
            {
                "type",
                "title",
                "path",
                "icon",
                "theme",
                "background",
                "max_columns",
                "subview",
                "visible",
                "header",
                "visibility",
                "badges",
                "cards",
                "sections",
            }
        ),
        container="sections",  # or "cards" -- decided by the view's own `type`
        context_manager=True,
    ),
    "structure:badge": CardSpec(
        type="structure:badge",
        builder="badge",
        entity_params=("entity",),
        # `badge(**options)` accepts arbitrary HA badge options, so an emitter
        # keeps unknown keys as kwargs rather than `extra=`; these are the ones
        # the builder itself always writes.
        declared=frozenset({"type", "entity", "visibility"}),
        container="leaf",
    ),
    # A section is stored as `{"type": "grid", "cards": [...]}` -- the SAME type
    # string DB3a's `c.grid(...)` card uses. POSITION disambiguates, which is
    # why it is not a `CARD_REGISTRY` row: a `grid` in a view's `sections` list
    # decompiles to `with section(...):`, a `grid` in a `cards` list decompiles
    # to `with c.grid(...):`. A consumer walking a `sections` list looks the
    # node up here; one walking a `cards` list looks it up in `CARD_REGISTRY`.
    "structure:section": CardSpec(
        type="grid",
        builder="section",
        declared=frozenset({"type", "column_span", "visibility", "cards"}),
        container="cards",
        context_manager=True,
    ),
}
