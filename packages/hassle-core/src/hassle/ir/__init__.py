"""Intermediate representation (IR) for Home Assistant objects.

This is the frozen IR schema: everything exported here -- the IR model
schema, the canonical JSON serialization, and the object-key format
(``"automation:<id>"`` etc.) -- is a stable interface downstream code
depends on.
"""

from __future__ import annotations

from hassle.ir.canonical import canonical_json, sha256_hash
from hassle.ir.keys import (
    BLUEPRINT_KIND,
    CONFIG_ENTRY_DOMAINS,
    DASHBOARD_KIND,
    GROUP_DOMAINS,
    HELPER_DOMAINS,
    OBJECT_KINDS,
    TEMPLATE_DOMAINS,
    object_key,
    slugify,
)
from hassle.ir.models import (
    AutomationConfig,
    BlueprintConfig,
    DashboardConfig,
    GroupHelperConfig,
    HelperConfig,
    IRObject,
    ScriptConfig,
    TemplateHelperConfig,
    parse,
    serialize,
)
from hassle.ir.normalize import normalize_ha

__all__ = [
    "BLUEPRINT_KIND",
    "CONFIG_ENTRY_DOMAINS",
    "DASHBOARD_KIND",
    "GROUP_DOMAINS",
    "HELPER_DOMAINS",
    "OBJECT_KINDS",
    "TEMPLATE_DOMAINS",
    "AutomationConfig",
    "BlueprintConfig",
    "DashboardConfig",
    "GroupHelperConfig",
    "HelperConfig",
    "IRObject",
    "ScriptConfig",
    "TemplateHelperConfig",
    "canonical_json",
    "normalize_ha",
    "object_key",
    "parse",
    "serialize",
    "sha256_hash",
    "slugify",
]
