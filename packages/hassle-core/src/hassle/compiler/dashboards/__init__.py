"""Lovelace storage-mode dashboards: recorder, structural DSL, conditions.

The implementation home of the dashboard vocabulary
(docs/internals/dashboards-design.md §5/§6.1). The *public* faces are the eight
structural names re-exported through ``hassle.__all__`` (``dashboard``,
``raw_dashboard``, ``view``, ``section``, ``badge``, ``raw_card``,
``raw_section``, ``raw_view``) and the ``hassle.cards`` namespace module (card
builders + ``cond``) — everything else here is a non-public extension seam,
listed as such in docs/internals/dsl-extensions.md.

Layout:

- :mod:`~hassle.compiler.dashboards.recorder` — ``DashboardRecorder``, its
  ``ContextVar`` stack, and the ``record_card``/``record_badge``/
  ``push_container`` seam every card builder drives.
- :mod:`~hassle.compiler.dashboards.builders` — the two shared builder
  conventions (``extra=`` merge + shadow check, ``visibility=`` normalizer).
- :mod:`~hassle.compiler.dashboards.conditions` — the ``cond`` vocabulary.
- :mod:`~hassle.compiler.dashboards.structure` — ``view``/``section``/``badge``
  and the structural raw ladder.
- :mod:`~hassle.compiler.dashboards.decorators` — ``@dashboard`` /
  ``@raw_dashboard`` plus the §3.2 envelope builder.
- :mod:`~hassle.compiler.dashboards.card_registry` — the F5 card-type table
  DB3's builders, DB4's decompiler and DB7's validation all read.
- :mod:`~hassle.compiler.dashboards.errors` — the §5.6 error surface.
"""

from __future__ import annotations

from hassle.compiler.dashboards.builders import (
    merge_extra,
    normalize_visibility,
    put,
)
from hassle.compiler.dashboards.card_registry import (
    CARD_REGISTRY,
    STRUCTURE_REGISTRY,
    CardSpec,
    register_card,
)
from hassle.compiler.dashboards.conditions import (
    DashboardCondition,
    cond,
    normalize_condition,
)
from hassle.compiler.dashboards.decorators import (
    dashboard,
    declared_dashboards,
    raw_dashboard,
    reset_declared_dashboards,
)
from hassle.compiler.dashboards.errors import (
    DashboardConditionInAutomationError,
    DashboardConditionTypeError,
    DashboardNestingError,
    DashboardUrlPathError,
    DefaultDashboardMetadataError,
    ExtraShadowsKwargError,
    NoDashboardContextError,
    PanelViewArityError,
    SectionOutsideSectionsViewError,
    SectionRequiredError,
)
from hassle.compiler.dashboards.recorder import (
    ContainerFrame,
    DashboardRecorder,
    RecordedNode,
    active_dashboard,
    dashboard_recording,
    push_container,
    record_badge,
    record_card,
)
from hassle.compiler.dashboards.structure import (
    badge,
    raw_card,
    raw_section,
    raw_view,
    section,
    view,
)

__all__ = [
    "CARD_REGISTRY",
    "STRUCTURE_REGISTRY",
    "CardSpec",
    "ContainerFrame",
    "DashboardCondition",
    "DashboardConditionInAutomationError",
    "DashboardConditionTypeError",
    "DashboardNestingError",
    "DashboardRecorder",
    "DashboardUrlPathError",
    "DefaultDashboardMetadataError",
    "ExtraShadowsKwargError",
    "NoDashboardContextError",
    "PanelViewArityError",
    "RecordedNode",
    "SectionOutsideSectionsViewError",
    "SectionRequiredError",
    "active_dashboard",
    "badge",
    "cond",
    "dashboard",
    "dashboard_recording",
    "declared_dashboards",
    "merge_extra",
    "normalize_condition",
    "normalize_visibility",
    "push_container",
    "put",
    "raw_card",
    "raw_dashboard",
    "raw_section",
    "raw_view",
    "record_badge",
    "record_card",
    "register_card",
    "reset_declared_dashboards",
    "section",
    "view",
]
