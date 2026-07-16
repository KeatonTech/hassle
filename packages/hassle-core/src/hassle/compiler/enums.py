"""Enums for HA's enumerated automation/script options.

``Mode`` (HA's automation/script ``mode:``) and ``MaxExceeded`` (``max_exceeded:``) are
``StrEnum`` -- a real ``str`` subclass, so passing an enum member anywhere the DSL currently
accepts a plain string (``@automation(mode=Mode.RESTART, max_exceeded=MaxExceeded.SILENT)``)
compiles to the exact same HA value, byte-identical to the equivalent plain string (there is
nothing to normalize: ``Mode.RESTART == "restart"`` and serializes as ``"restart"`` in JSON,
since ``StrEnum`` members *are* their string value).

Value sets verified against the fixture corpus (``fixtures/configs/*.json``, docs/dsl-extensions.md)
and HA's own schema (``homeassistant/helpers/script.py``'s ``CONF_MODE``/``CONF_MAX_EXCEEDED``
option lists, docs/ha-api-notes.md): ``Mode`` is ``single``/``restart``/``queued``/``parallel``;
``MaxExceeded`` is ``silent``/``warning``/``error``. The corpus only contains ``silent``/
``warning`` examples (``docs/ha-api-notes.md``, recorded finding) -- ``error`` is included on
the strength of HA's schema (every mode/max_exceeded option is a fixed, small, well-known
enumeration, unlike the open-ended 2026.7 purpose vocabulary, DESIGN §5.4) but has no fixture
corpus example backing it; the decompiler's fallback-to-raw-string rule (below) means this
is safe even if that turns out to be wrong for some HA version.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["MaxExceeded", "Mode"]


class Mode(StrEnum):
    """HA automation/script ``mode:`` (DESIGN §5.3/§5.7)."""

    SINGLE = "single"
    RESTART = "restart"
    QUEUED = "queued"
    PARALLEL = "parallel"


class MaxExceeded(StrEnum):
    """HA automation/script ``max_exceeded:`` (DESIGN §5.3/§5.7)."""

    SILENT = "silent"
    WARNING = "warning"
    ERROR = "error"
