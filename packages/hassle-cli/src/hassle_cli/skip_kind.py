"""``--skip-kind``: exclude a whole object kind from ONE run.

The transient sibling of ``hassle.toml``'s ``ignore`` globs
(:mod:`hassle_cli.ignore_filter`), and the difference is the whole point:

- ``ignore`` is permanent and **unmanages** an object.
  :func:`~hassle_cli.ignore_filter.migrate_manifest_for_ignores` drops its
  manifest entry, so Hassle forgets that object's sync base entirely.
- ``--skip-kind`` is per-invocation and is a **pure no-op**. The object stays
  managed, its manifest entry is preserved, and the next run without the flag
  behaves exactly as if the skipped run had not happened.

**Why this filters plan entries rather than the manifest.** ``ignore`` filters
`local_objects`/`remote_objects` *before* ``compute_plan``, which is why it
also has to migrate the manifest: ``compute_plan`` keys off
``manifest.objects | local | remote``, so a manifest entry with neither side
present would otherwise plan a delete/drop. Doing that for a transient flag
would destroy sync bases as a side effect of a read-only-looking option.

Filtering the computed plan instead gives the right semantics by construction:
:func:`hassle.sync.apply._advance_manifest` starts from
``dict(manifest.objects)`` and only rewrites keys that appear in the plan it is
given, so an object dropped from the plan keeps its manifest entry untouched --
and, having no entry, is unreachable by both the apply engine and the pull
writer.
"""

from __future__ import annotations

from dataclasses import dataclass

from hassle.ir.keys import OBJECT_KINDS
from hassle.sync.models import Plan


def parse_skip_kinds(values: tuple[str, ...] | list[str]) -> frozenset[str]:
    """Validate ``--skip-kind`` values against the real kind vocabulary.

    A typo must fail loudly and immediately: silently skipping nothing because
    the user wrote ``--skip-kind dashboards`` would look like the flag worked
    while every dashboard was still pushed.
    """
    unknown = [value for value in values if value not in OBJECT_KINDS]
    if unknown:
        near = sorted(
            kind
            for kind in OBJECT_KINDS
            for bad in unknown
            if kind.startswith(bad[:6]) or bad.startswith(kind[:6])
        )
        suggestion = f" Did you mean: {', '.join(near)}?" if near else ""
        raise ValueError(
            f"unknown object kind(s) for --skip-kind: {', '.join(sorted(unknown))}."
            f"{suggestion} Fix: pass one of {', '.join(sorted(OBJECT_KINDS))} "
            "(repeat the flag to skip several), or drop the flag to include "
            "every kind."
        )
    return frozenset(values)


@dataclass(frozen=True)
class SkipResult:
    """The filtered plan plus the keys that were held back (for the notice)."""

    plan: Plan
    skipped_keys: list[str]


def drop_skipped_kinds(plan: Plan, skip_kinds: frozenset[str]) -> SkipResult:
    """Remove every entry whose ``kind`` is skipped, preserving order.

    Returns the plan unchanged (same object) when nothing is skipped, so the
    common path costs nothing and ``plan is result.plan`` holds.
    """
    if not skip_kinds:
        return SkipResult(plan, [])
    kept = [entry for entry in plan.entries if entry.kind not in skip_kinds]
    skipped = [entry.object_key for entry in plan.entries if entry.kind in skip_kinds]
    if not skipped:
        return SkipResult(plan, [])
    return SkipResult(plan.model_copy(update={"entries": kept}), skipped)
