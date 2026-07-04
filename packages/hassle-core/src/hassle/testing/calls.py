"""Recorded service calls (DESIGN §10.1: "service calls (recorded, not executed)")."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _empty_str_any_dict() -> dict[str, Any]:
    return {}


@dataclass(frozen=True)
class ServiceCall:
    """One recorded ``action:``/``service:`` call. Never actually executed."""

    action: str
    data: dict[str, Any] = field(default_factory=_empty_str_any_dict)
    target: dict[str, Any] | None = None
