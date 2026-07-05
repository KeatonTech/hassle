"""Intermediate representation (IR) for Home Assistant objects.

Freeze point **F1** (end of M0) covers everything exported here: the IR model
schema, the canonical JSON serialization, and the object-key format
(``"automation:<id>"`` etc.). Downstream milestones depend on these being
stable; changes require a MILESTONES.md update in the same PR (R5).
"""

from __future__ import annotations

from hassle.ir.canonical import canonical_json, sha256_hash
from hassle.ir.keys import HELPER_DOMAINS, OBJECT_KINDS, object_key, slugify
from hassle.ir.models import (
    AutomationConfig,
    HelperConfig,
    IRObject,
    ScriptConfig,
    parse,
    serialize,
)
from hassle.ir.normalize import normalize_ha

__all__ = [
    "HELPER_DOMAINS",
    "OBJECT_KINDS",
    "AutomationConfig",
    "HelperConfig",
    "IRObject",
    "ScriptConfig",
    "canonical_json",
    "normalize_ha",
    "object_key",
    "parse",
    "serialize",
    "sha256_hash",
    "slugify",
]
