"""Compatibility re-export of :mod:`hassle.blueprints`.

The blueprint loader/expander was **promoted to core** in stage 1 of
docs/internals/blueprints-design.md (§1): the validator and the backend both
need it, and neither may import from `hassle.testing` (which sits beside them
in the layering, not below — `tests/test_package_layering.py`).

This module stays, re-exporting the *same objects* (not same-spelled copies),
because `hassle.testing.blueprints` is an interface bundles already import —
and the frozen surfaces are additive-only (CONTRIBUTING R5). New code should
import from :mod:`hassle.blueprints` directly.
"""

from __future__ import annotations

from hassle.blueprints import (
    BLUEPRINT_DOMAINS,
    BLUEPRINT_ROOT,
    BLUEPRINT_SUBDIR,
    DEFAULT_BLUEPRINT_DOMAIN,
    Blueprint,
    BlueprintError,
    BlueprintInput,
    InvalidBlueprintError,
    MissingBlueprintInputError,
    blueprint_display_path,
    blueprint_file,
    blueprint_subdir,
    expand_blueprint,
    load_blueprint,
)

__all__ = [
    "BLUEPRINT_DOMAINS",
    "BLUEPRINT_ROOT",
    "BLUEPRINT_SUBDIR",
    "DEFAULT_BLUEPRINT_DOMAIN",
    "Blueprint",
    "BlueprintError",
    "BlueprintInput",
    "InvalidBlueprintError",
    "MissingBlueprintInputError",
    "blueprint_display_path",
    "blueprint_file",
    "blueprint_subdir",
    "expand_blueprint",
    "load_blueprint",
]
