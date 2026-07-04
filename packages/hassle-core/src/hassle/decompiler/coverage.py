"""DSL-coverage metric (MILESTONES M2 test 3): what fraction of objects decompile
with zero ``raw_*`` nodes.

Walks each object's *decompiled source* (not the JSON) counting occurrences of
the granular raw escape hatches (``raw_trigger``/``raw_condition``/``raw_action``)
plus the whole-object ``raw_automation`` fallback, so the count reflects exactly
what ended up in the generated bundle -- the same source the ``>= 90%`` gate and
the CI artifact (``hassle-dev decompile-coverage``) are judged against.

Each exception is also tagged with a human-readable ``justification`` string
(:func:`_justify`) so the tracked artifact (``hassle-dev decompile-coverage``'s
JSON output) is self-describing rather than a bare, mysterious node count --
sourced from the same reasons recorded in docs/ha-api-notes.md §14-§18 and the
corresponding builder-module docstrings/comments.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from hassle.decompiler.codegen import decompile_object
from hassle.ir.models import IRObject

_RAW_NODE_PATTERN = re.compile(
    r"\b(raw_trigger|raw_condition|raw_action|raw_automation)\s*\(((?:[^()]|\([^()]*\))*)\)"
)

# `@raw_automation(id=...)` is a *decorator*: the classifiable content (the
# body's own `platform`/`use_blueprint`/... keys) lives in the decorated
# function's `return {...}` statement, not the decorator's own argument list
# (which is just `id=...`). This matches from the `@raw_automation(` decorator
# through to the end of its function body (the next top-level `@`-decorated
# or bare `def`/assignment line, or end of source) so `_justify` can inspect
# the whole thing.
_RAW_AUTOMATION_BLOCK_PATTERN = re.compile(
    r"@raw_automation\([^\n]*\)\ndef [^\n]*\n(?:(?:    .*)?\n?)*"
)


def _find_raw_nodes(source: str) -> list[tuple[str, str]]:
    """Every ``raw_*(...)`` call in ``source``: ``(builder_name, argument_text)``.

    For ``raw_automation`` specifically, ``argument_text`` is the whole
    decorated-function block (decorator + body), not just the decorator's own
    ``id=...`` argument list -- see the module-level pattern's docstring.
    """
    results: list[tuple[str, str]] = []
    consumed_spans: list[tuple[int, int]] = []
    for block_match in _RAW_AUTOMATION_BLOCK_PATTERN.finditer(source):
        results.append(("raw_automation", block_match.group(0)))
        consumed_spans.append(block_match.span())

    def _inside_raw_automation_block(pos: int) -> bool:
        return any(start <= pos < end for start, end in consumed_spans)

    for m in _RAW_NODE_PATTERN.finditer(source):
        if m.group(1) == "raw_automation":
            continue  # already captured (with full body) above
        if _inside_raw_automation_block(m.start()):
            continue  # a raw_trigger/raw_action nested inside a raw body dict literal
        results.append((m.group(1), m.group(2)))
    return results


# Justification strings, one per recognized raw-node shape, sourced verbatim
# (paraphrased for brevity) from docs/ha-api-notes.md's M2 findings sections
# and the builder-module comments that first noted each gap.
_JUSTIFICATION_DEVICE_TRIGGER = (
    "device trigger: no stable cross-integration schema (DESIGN §5.4 -- "
    "hassle.compiler.triggers._trig_device), always raw by design, docs/ha-api-notes.md §5.4 note"
)
_JUSTIFICATION_DEVICE_CONDITION = (
    "device condition: no stable cross-integration schema (DESIGN §5.4 -- "
    "hassle.compiler.conditions), always raw by design, same rationale as the device trigger"
)
_JUSTIFICATION_INLINE_LEGACY_AUTOMATION = (
    "whole-object raw_automation fallback: this config uses the ancient inline "
    "single-trigger form (bare platform/entity_id/to at the automation's top level, no "
    "trigger:/triggers: wrapper at all) -- no @automation shape can express top-level "
    "fields outside its option set (docs/ha-api-notes.md §14/§16)"
)
_JUSTIFICATION_TEMPLATED_DELAY = (
    "templated delay: the stored delay value is a Jinja template string ({{ ... }}), not a "
    "fixed duration -- the typed delay() builder only accepts int/str/dict duration forms "
    "(docs/ha-api-notes.md §18), so a runtime-templated delay falls back to raw_action"
)
_JUSTIFICATION_UNKNOWN_TRIGGER = (
    "trigger shape not modeled by any typed builder or the 2026.7 purpose-trigger "
    "vocabulary; falls back to raw_trigger so no data is dropped (DESIGN §5.8, I3)"
)
_JUSTIFICATION_UNKNOWN_CONDITION = (
    "condition shape not modeled by any typed builder or the 2026.7 purpose-condition "
    "vocabulary; falls back to raw_condition so no data is dropped (DESIGN §5.8, I3)"
)
_JUSTIFICATION_UNKNOWN_ACTION = (
    "action shape not modeled by any typed action/control-flow builder; falls back to "
    "raw_action so no data is dropped (DESIGN §5.8, I3)"
)
_JUSTIFICATION_UNKNOWN_AUTOMATION = (
    "whole-object shape not expressible as a typed @automation (fields outside its HA "
    "option set, or a use_blueprint shape the blueprint_automation() builder doesn't "
    "recognize); falls back to raw_automation so no data is dropped (DESIGN §5.8, I3)"
)


_DEVICE_TRIGGER_MARKERS = (
    "'platform': 'device'",
    '"platform": "device"',
    "'trigger': 'device'",
    '"trigger": "device"',
)
_DEVICE_CONDITION_MARKERS = (
    "'condition': 'device'",
    '"condition": "device"',
)


def _justify(builder_name: str, argument_text: str) -> str:
    """Best-effort human-readable reason a raw_* node was needed, sourced from
    the documented findings in docs/ha-api-notes.md §14-§18."""
    if builder_name == "raw_trigger":
        if any(marker in argument_text for marker in _DEVICE_TRIGGER_MARKERS):
            return _JUSTIFICATION_DEVICE_TRIGGER
        return _JUSTIFICATION_UNKNOWN_TRIGGER
    if builder_name == "raw_condition":
        if any(marker in argument_text for marker in _DEVICE_CONDITION_MARKERS):
            return _JUSTIFICATION_DEVICE_CONDITION
        return _JUSTIFICATION_UNKNOWN_CONDITION
    if builder_name == "raw_action":
        has_delay = "'delay':" in argument_text or '"delay":' in argument_text
        if has_delay and "{{" in argument_text:
            return _JUSTIFICATION_TEMPLATED_DELAY
        return _JUSTIFICATION_UNKNOWN_ACTION
    # raw_automation (whole-object fallback)
    if "'platform':" in argument_text or '"platform":' in argument_text:
        return _JUSTIFICATION_INLINE_LEGACY_AUTOMATION
    return _JUSTIFICATION_UNKNOWN_AUTOMATION


def _empty_justifications() -> list[str]:
    return []


@dataclass(frozen=True)
class CoverageException:
    """One object whose decompiled source still contains >= 1 ``raw_*`` node.

    ``justifications`` lists one human-readable reason per raw node found (in
    source order) so the tracked artifact explains *why* each exception exists,
    not just that it does.
    """

    object_key: str
    raw_node_count: int
    justifications: list[str] = field(default_factory=_empty_justifications)


def _empty_exceptions() -> list[CoverageException]:
    return []


@dataclass(frozen=True)
class CoverageReport:
    total_objects: int
    clean_objects: int
    exceptions: list[CoverageException] = field(default_factory=_empty_exceptions)

    @property
    def clean_fraction(self) -> float:
        if self.total_objects == 0:
            return 1.0
        return self.clean_objects / self.total_objects

    def to_json_dict(self) -> dict[str, object]:
        return {
            "total_objects": self.total_objects,
            "clean_objects": self.clean_objects,
            "clean_fraction": self.clean_fraction,
            "exceptions": [
                {
                    "object_key": e.object_key,
                    "raw_node_count": e.raw_node_count,
                    "justification": "; ".join(e.justifications),
                }
                for e in sorted(self.exceptions, key=lambda e: e.object_key)
            ],
        }


def analyze_coverage(objects: dict[str, IRObject]) -> CoverageReport:
    """Analyze DSL coverage over ``objects`` (an object-key -> IRObject mapping)."""
    exceptions: list[CoverageException] = []
    clean = 0
    for key in sorted(objects):
        source = decompile_object(key, objects[key])
        raw_nodes = _find_raw_nodes(source)
        if not raw_nodes:
            clean += 1
        else:
            justifications = [_justify(name, args) for name, args in raw_nodes]
            exceptions.append(
                CoverageException(
                    object_key=key,
                    raw_node_count=len(raw_nodes),
                    justifications=justifications,
                )
            )
    return CoverageReport(total_objects=len(objects), clean_objects=clean, exceptions=exceptions)
