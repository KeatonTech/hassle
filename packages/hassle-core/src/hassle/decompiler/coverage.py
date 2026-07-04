"""DSL-coverage metric (MILESTONES M2 test 3): what fraction of objects decompile
with zero ``raw_*`` nodes.

Walks each object's *decompiled source* (not the JSON) counting occurrences of
the granular raw escape hatches (``raw_trigger``/``raw_condition``/``raw_action``)
plus the whole-object ``raw_automation`` fallback, so the count reflects exactly
what ended up in the generated bundle -- the same source the ``>= 90%`` gate and
the CI artifact (``hassle-dev decompile-coverage``) are judged against.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from hassle.decompiler.codegen import decompile_object
from hassle.ir.models import IRObject

_RAW_NODE_PATTERN = re.compile(r"\b(raw_trigger|raw_condition|raw_action|raw_automation)\s*\(")


def _count_raw_nodes(source: str) -> int:
    return len(_RAW_NODE_PATTERN.findall(source))


@dataclass(frozen=True)
class CoverageException:
    """One object whose decompiled source still contains >= 1 ``raw_*`` node."""

    object_key: str
    raw_node_count: int


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
                {"object_key": e.object_key, "raw_node_count": e.raw_node_count}
                for e in sorted(self.exceptions, key=lambda e: e.object_key)
            ],
        }


def analyze_coverage(objects: dict[str, IRObject]) -> CoverageReport:
    """Analyze DSL coverage over ``objects`` (an object-key -> IRObject mapping)."""
    exceptions: list[CoverageException] = []
    clean = 0
    for key in sorted(objects):
        source = decompile_object(key, objects[key])
        count = _count_raw_nodes(source)
        if count == 0:
            clean += 1
        else:
            exceptions.append(CoverageException(object_key=key, raw_node_count=count))
    return CoverageReport(total_objects=len(objects), clean_objects=clean, exceptions=exceptions)
