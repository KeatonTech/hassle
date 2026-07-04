"""Bundle loader + compile pipeline: DSL bundle dir -> IR (DESIGN §7.2).

``compile_bundle`` imports a bundle directory as an isolated package (``sys.path``
sandboxed, no network — the compiler executes only the user's own Python, §14),
drains the registry of ``@automation``/``@script`` objects, runs each inside a
:class:`Recorder`, and assembles the IR in HA's canonical plural schema (§7.1).

The result carries the IR objects keyed by object key, plus a span map so every
downstream error (validation, plan conflict, simulator failure) can point at the
user's Python line (M1 test 6). Duplicate object keys are rejected (M1 test 5).
"""

from __future__ import annotations

import contextlib
import importlib
import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hassle_core.compiler.errors import DuplicateObjectError
from hassle_core.compiler.recording import RecordedNode, Recorder, recording
from hassle_core.compiler.registry import RegisteredObject, fresh
from hassle_core.compiler.spans import SourceSpan
from hassle_core.ir import normalize_ha
from hassle_core.ir.models import AutomationConfig, IRObject, ScriptConfig

# object_key -> {"triggers"|"conditions"|"actions": [SourceSpan | None, ...]}
_SectionSpans = dict[str, list["SourceSpan | None"]]


def _empty_objects() -> dict[str, IRObject]:
    return {}


def _empty_spans() -> dict[str, _SectionSpans]:
    return {}


def _empty_decl_spans() -> dict[str, SourceSpan | None]:
    return {}


@dataclass
class CompileResult:
    """The output of compiling a bundle: IR objects + their source spans."""

    objects: dict[str, IRObject] = field(default_factory=_empty_objects)
    # object_key -> per-section span lists (parallel to the IR block lists).
    _spans: dict[str, _SectionSpans] = field(default_factory=_empty_spans)
    # object_key -> the decoration-site span (for whole-object errors like duplicates).
    _decl_spans: dict[str, SourceSpan | None] = field(default_factory=_empty_decl_spans)

    def add(
        self,
        obj: IRObject,
        spans: _SectionSpans,
        decl_span: SourceSpan | None,
        duplicate_of: SourceSpan | None,
    ) -> None:
        """Register a compiled object + its spans; reject a duplicate object key.

        Internal to the pipeline (used by :func:`compile_registered`); downstream
        consumers read via :attr:`objects` and :meth:`spans_for`.
        """
        key = obj.object_key()
        if key in self.objects:
            raise DuplicateObjectError(key, self._decl_spans.get(key), duplicate_of)
        self.objects[key] = obj
        self._spans[key] = spans
        self._decl_spans[key] = decl_span

    def spans_for(self, obj: IRObject, section: str) -> list[SourceSpan]:
        """Return the source spans for ``section`` (triggers/conditions/actions).

        Spans ride alongside the IR (never inside ``to_ha()``); this is the lookup
        the validator/simulator use to map an IR node back to its DSL line.
        """
        key = obj.object_key()
        spans = self._spans.get(key, {}).get(section, [])
        return [s for s in spans if s is not None]


def _flatten_spans(nodes: list[RecordedNode]) -> list[SourceSpan | None]:
    return [n.span for n in nodes]


def _build_automation(
    reg: RegisteredObject, rec: Recorder
) -> tuple[AutomationConfig, _SectionSpans]:
    body: dict[str, Any] = {}
    options = rec.options
    # Ordered: id, alias, then the rest of the declared options, then the blocks.
    body["id"] = options.get("id") or reg.func.__name__
    for key, value in options.items():
        if key == "id":
            continue
        body[key] = value
    body["triggers"] = [n.body for n in rec.triggers]
    body["conditions"] = [n.body for n in rec.conditions]
    body["actions"] = [n.body for n in rec.actions]
    normalized = normalize_ha(body, kind="automation")
    obj = AutomationConfig.model_validate(normalized)
    spans = {
        "triggers": _flatten_spans(rec.triggers),
        "conditions": _flatten_spans(rec.conditions),
        "actions": _flatten_spans(rec.actions),
    }
    return obj, spans


def _build_script(reg: RegisteredObject, rec: Recorder) -> tuple[ScriptConfig, _SectionSpans]:
    body: dict[str, Any] = {}
    options = rec.options
    for key, value in options.items():
        if key == "id":
            continue  # script object_id is extrinsic (the key), not a body field
        body[key] = value
    body["sequence"] = [n.body for n in rec.actions]
    normalized = normalize_ha(body, kind="script")
    obj = ScriptConfig.model_validate(normalized)
    object_id = str(options.get("id") or reg.func.__name__)
    obj.attach_key(object_id)
    spans = {"actions": _flatten_spans(rec.actions)}
    return obj, spans


def compile_registered(registry_objects: list[RegisteredObject]) -> CompileResult:
    """Compile a list of registered objects into IR (the loader-agnostic core)."""
    result = CompileResult()
    for reg in registry_objects:
        with recording(kind=reg.kind, **reg.options) as rec:
            reg.func()
        if reg.kind == "automation":
            obj, spans = _build_automation(reg, rec)
        elif reg.kind == "script":
            obj, spans = _build_script(reg, rec)
        else:  # pragma: no cover - registry only ever holds these two kinds
            raise ValueError(f"unknown registered kind {reg.kind!r}")
        result.add(obj, spans, decl_span=reg.span, duplicate_of=reg.span)
    return result


def compile_bundle(bundle_dir: str | Path) -> CompileResult:
    """Import ``bundle_dir`` in isolation, collect registered objects, compile to IR.

    No network is touched (I/O is import + user code only). Each call installs a
    fresh registry so repeated compiles are independent (R8 determinism).
    """
    bundle_path = Path(bundle_dir).resolve()
    if not bundle_path.is_dir():
        raise FileNotFoundError(f"bundle directory not found: {bundle_path}")

    reg = fresh()
    with _sandboxed_import(bundle_path):
        _import_bundle_modules(bundle_path)
    # Snapshot the registry before compiling (compile opens recorders that must not
    # see leftover registrations).
    return compile_registered(list(reg.objects))


class _sandboxed_import:
    """Context manager: put the bundle dir on ``sys.path`` and clean up its modules.

    Isolation (§7.2/§14): only the bundle dir is added to the import path, and every
    module imported from it is removed from ``sys.modules`` on exit so a second
    compile re-imports fresh (no cross-compile bleed, R8). No network is involved.
    """

    def __init__(self, bundle_path: Path) -> None:
        self._bundle_path = bundle_path
        self._path_entry = str(bundle_path)
        self._preexisting: set[str] = set()

    def __enter__(self) -> _sandboxed_import:
        self._preexisting = set(sys.modules)
        sys.path.insert(0, self._path_entry)
        return self

    def __exit__(self, *exc: object) -> None:
        with contextlib.suppress(ValueError):  # pragma: no cover - defensive
            sys.path.remove(self._path_entry)
        # Drop modules imported from the bundle dir during this compile.
        for name in list(sys.modules):
            if name in self._preexisting:
                continue
            mod = sys.modules.get(name)
            file = getattr(mod, "__file__", None)
            if file and Path(file).resolve().is_relative_to(self._bundle_path):
                del sys.modules[name]


def _import_bundle_modules(bundle_path: Path) -> None:
    """Import every top-level ``*.py`` module in the bundle dir (sorted, stable)."""
    for py in sorted(bundle_path.glob("*.py")):
        if py.name.startswith("_"):
            continue
        module_name = py.stem
        spec = importlib.util.spec_from_file_location(module_name, py)
        if spec is None or spec.loader is None:  # pragma: no cover - defensive
            raise ImportError(f"cannot load bundle module {py}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
