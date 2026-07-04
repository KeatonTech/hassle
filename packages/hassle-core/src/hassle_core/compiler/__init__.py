"""The recording-context compiler (DESIGN §5, §7.2) — the M1 core.

Public surface used by the pipeline, the CLI, and the follow-on M1 workstreams:

- :func:`compile_bundle` / :func:`compile_registered` / :class:`CompileResult`
- the recording verbs (:func:`when`, :func:`only_if`) and the ``@automation`` /
  ``@script`` decorators
- the M1-core builders (:func:`state`, :func:`service`, :func:`delay`)
- the extension-point protocols (:class:`TriggerBuilder` / :class:`ConditionBuilder`
  / :class:`ActionBuilder`) and the record functions the builder families call
- the compile errors (:class:`CompileTimeBranchError` et al.)
- :class:`SourceSpan`

Import the *user-facing* names from the top-level :mod:`hassle` package instead;
this module is the implementation home.
"""

from __future__ import annotations

from hassle_core.compiler.actions import delay, service
from hassle_core.compiler.builders import (
    DelayAction,
    ServiceAction,
    StateExpr,
    state,
)
from hassle_core.compiler.bundle import (
    CompileResult,
    compile_bundle,
    compile_registered,
)
from hassle_core.compiler.errors import (
    CompileError,
    CompileTimeBranchError,
    DuplicateObjectError,
    NoRecordingContextError,
    UnknownAutomationOptionError,
)
from hassle_core.compiler.protocols import (
    ActionBuilder,
    ConditionBuilder,
    TriggerBuilder,
)
from hassle_core.compiler.recording import (
    RecordedNode,
    Recorder,
    only_if,
    record_action,
    record_condition,
    record_trigger,
    recording,
    when,
)
from hassle_core.compiler.registry import (
    RegisteredObject,
    Registry,
    automation,
    current_registry,
    fresh,
    script,
)
from hassle_core.compiler.spans import SourceSpan, capture_span

__all__ = [
    "ActionBuilder",
    "CompileError",
    "CompileResult",
    "CompileTimeBranchError",
    "ConditionBuilder",
    "DelayAction",
    "DuplicateObjectError",
    "NoRecordingContextError",
    "RecordedNode",
    "Recorder",
    "RegisteredObject",
    "Registry",
    "ServiceAction",
    "SourceSpan",
    "StateExpr",
    "TriggerBuilder",
    "UnknownAutomationOptionError",
    "automation",
    "capture_span",
    "compile_bundle",
    "compile_registered",
    "current_registry",
    "delay",
    "fresh",
    "only_if",
    "record_action",
    "record_condition",
    "record_trigger",
    "recording",
    "script",
    "service",
    "state",
    "when",
]
