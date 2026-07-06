"""Bundle loader + compile pipeline: DSL bundle dir -> IR (DESIGN §7.2).

``compile_bundle`` imports a bundle directory as an isolated package (``sys.path``
sandboxed, no network — the compiler executes only the user's own Python, §14),
drains the registry of ``@automation``/``@script`` objects, runs each inside a
:class:`Recorder`, and assembles the IR in HA's canonical plural schema (§7.1).

The result carries the IR objects keyed by object key, plus a span map so every
downstream error (validation, plan conflict, simulator failure) can point at the
user's Python line (M1 test 6). Duplicate object keys are rejected (M1 test 5).

The bundle is a package tree (M7.1, DESIGN §6/§7.3, docs/ha-api-notes.md §17.9
RESOLVED): subdirectories are recursively imported as PEP 420 namespace
packages, no ``__init__.py`` required anywhere.

**Symlink policy (review finding F1): every symlink under the bundle
directory is skipped, silently, whether it points at a directory or a
``.py`` file.** Following one would let a file inside the bundle actually
execute code living outside it -- a sandbox escape (§14) -- and would also
break the loader's cleanup/re-import bookkeeping (the target's ``__file__``/
``__path__`` resolves outside ``bundle_path``, so it would never be cleaned
up between compiles, then get silently served stale on the next one). See
``_iter_bundle_source_files`` (skips any symlinked child during the walk) and
``_import_bundle_modules`` (belt-and-suspenders: re-resolves and re-checks
each accepted path is still under the bundle root immediately before
import, catching a symlinked *intermediate* directory a leaf-only check
would miss). Nothing is emitted for a skipped symlink in v1 -- symlinks are
simply outside this loader's contract.
"""

from __future__ import annotations

import contextlib
import importlib
import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hassle.compiler.errors import DuplicateObjectError
from hassle.compiler.recording import RecordedNode, Recorder, record_trigger, recording
from hassle.compiler.registry import PrebuiltObject, RegisteredObject, fresh
from hassle.compiler.spans import SourceSpan
from hassle.ir import normalize_ha
from hassle.ir.models import AutomationConfig, IRObject, ScriptConfig

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

    def span_at(self, obj: IRObject, section: str, index: int) -> SourceSpan | None:
        """Per-item span lookup, positionally parallel to ``obj.to_ha()[section]``.

        Unlike :meth:`spans_for` (which flattens and drops ``None`` entries,
        losing index alignment with the IR block list), this returns the span
        for exactly ``obj.to_ha()[section][index]`` — ``None`` if that item has
        no span (e.g. a prebuilt object) or ``index`` is out of range. Purely
        additive (M3): does not change ``spans_for``'s existing behavior.
        """
        key = obj.object_key()
        spans = self._spans.get(key, {}).get(section, [])
        if 0 <= index < len(spans):
            return spans[index]
        return None

    def decl_span_for(self, object_key: str) -> SourceSpan | None:
        """The declaration-site span for ``object_key`` (M7 addition).

        The same span used to point a `DuplicateObjectError` at each
        conflicting declaration -- exposed publicly so whole-object findings
        (e.g. the M7 helper-id/name-slug mismatch check) can point at *where
        the helper/automation/script was declared*, not just at a
        trigger/condition/action line within it.
        """
        return self._decl_spans.get(object_key)


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


def compile_registered(
    registry_objects: list[RegisteredObject],
    prebuilt_objects: list[PrebuiltObject] | None = None,
) -> CompileResult:
    """Compile registered functions + pre-built objects into IR (loader-agnostic).

    ``registry_objects`` are the function-shaped ``@automation``/``@script``
    registrations (run inside a recorder). ``prebuilt_objects`` are whole IR
    objects already built by the declarative builders — helper declarations
    (DESIGN §5.7) and ``raw_automation``/``@blueprint_automation`` (DESIGN §5.8)
    — added straight to the result with no recording pass (§12 fix).

    Pre-built objects are added first (helpers before automations) so a helper an
    automation references is present, and so duplicate-id detection sees a stable
    order.
    """
    result = CompileResult()
    for pre in prebuilt_objects or []:
        result.add(pre.obj, spans={}, decl_span=pre.span, duplicate_of=pre.span)
    for reg in registry_objects:
        with recording(kind=reg.kind, **reg.options) as rec:
            # `@automation(triggers=[...])` (F3-additive, DESIGN §5.3/§5.5):
            # the decorator's triggers were already built at decoration time --
            # record them first, before running the body, so they land ahead
            # of any `when()` calls inside the body (composition order, both
            # docs/dsl-f3.md and this milestone's contract: "decorator list
            # first, when() appends").
            for trig in reg.decorator_triggers:
                record_trigger(trig, span=reg.span)
            reg.func()
        if reg.kind == "automation":
            obj, spans = _build_automation(reg, rec)
        elif reg.kind == "script":
            obj, spans = _build_script(reg, rec)
        else:  # pragma: no cover - registry only ever holds these two kinds
            raise ValueError(f"unknown registered kind {reg.kind!r}")
        result.add(obj, spans, decl_span=reg.span, duplicate_of=reg.span)

    # M13 reviewer finding B1: sweep for any `template_number`/`template_sensor`/
    # `template_binary_sensor`/`template_select` call that omitted `state=`
    # (the decorator-form signal) but was never actually applied as a
    # decorator over a function -- such a call builds/registers nothing, so
    # without this sweep it would compile clean with the object simply
    # absent (a silent regression from the pre-M13 call form, and an I6
    # hazard if the helper already exists in HA). Runs at the end of this
    # shared core so both `compile_bundle` and any direct caller (e.g. a
    # single-file/fixture compile) are covered alike.
    from hassle.compiler.template_helpers import check_no_dangling_template_helper_declarations

    check_no_dangling_template_helper_declarations()
    return result


def compile_bundle(bundle_dir: str | Path) -> CompileResult:
    """Import ``bundle_dir`` in isolation, collect registered objects, compile to IR.

    No network is touched (I/O is import + user code only). Each call installs a
    fresh registry so repeated compiles are independent (R8 determinism).
    """
    bundle_path = Path(bundle_dir).resolve()
    if not bundle_path.is_dir():
        raise FileNotFoundError(f"bundle directory not found: {bundle_path}")

    # Reset the declarative builders' process-wide lists so a prior compile (or a
    # bundle import in the same process) never bleeds objects into this one (R8).
    # These modules track declarations in module globals in addition to the
    # per-compile registry, so both must be cleared.
    from hassle.compiler.helpers import reset_declared_helpers
    from hassle.compiler.raw_automation import reset_declared_raw_automations
    from hassle.compiler.template_helpers import reset_declared_template_helpers

    reset_declared_helpers()
    reset_declared_template_helpers()
    reset_declared_raw_automations()

    reg = fresh()
    with _sandboxed_import(bundle_path):
        _import_bundle_modules(bundle_path)
    # Snapshot the registry before compiling (compile opens recorders that must not
    # see leftover registrations). Pre-built objects (helpers / raw / blueprint)
    # ride the `prebuilt` stream; function-shaped registrations ride `objects`.
    return compile_registered(list(reg.objects), list(reg.prebuilt))


class _sandboxed_import:
    """Context manager: put the bundle dir on ``sys.path`` and clean up its modules.

    Isolation (§7.2/§14): only the bundle dir is added to the import path, and every
    module imported from it is removed from ``sys.modules`` on exit so a second
    compile re-imports fresh (no cross-compile bleed, R8). No network is involved.

    M7.1: the bundle is now a package tree (subdirectories are importable as
    namespace packages, §17.9), so cleanup must also catch namespace-package
    module objects, which carry no ``__file__`` (only a ``__path__``) --
    ``getattr(mod, "__file__", None)`` alone would leave e.g. ``sys.modules
    ["helpers"]`` behind across compiles.
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
            if _module_belongs_to_bundle(mod, self._bundle_path):
                del sys.modules[name]


def _module_belongs_to_bundle(mod: Any, bundle_path: Path) -> bool:
    """True if ``mod`` (a regular module OR a PEP 420 namespace package) was
    loaded from inside ``bundle_path``."""
    file = getattr(mod, "__file__", None)
    if file and Path(file).resolve().is_relative_to(bundle_path):
        return True
    # Namespace packages (e.g. ``helpers`` with no ``__init__.py``) have no
    # __file__, only a __path__ iterable of the directories that make it up.
    paths = getattr(mod, "__path__", None)
    if paths:
        with contextlib.suppress(TypeError, OSError, ValueError):
            return any(Path(p).resolve().is_relative_to(bundle_path) for p in paths)
    return False


# Directories never treated as importable bundle packages, at any depth
# (DESIGN §6: tests/ is the user's pytest tree, .hassle/ is machine state,
# stubs/ is generated .pyi -- none of these are DSL sources). Dot-directories
# (.git, .vscode, ...) and __pycache__ are skipped unconditionally.
_RESERVED_DIR_NAMES = frozenset({"tests", ".hassle", "stubs"})


def _is_skipped_dir(name: str) -> bool:
    return name in _RESERVED_DIR_NAMES or name.startswith(".") or name == "__pycache__"


def _iter_bundle_source_files(bundle_path: Path) -> list[Path]:
    """Every ``*.py`` file in the bundle tree, at any depth, skipping reserved
    directories (sorted, stable -- so import order never depends on OS
    directory-listing order, R8).

    Symlink policy (review finding F1, docs/ha-api-notes.md §17.9): **every
    symlink is skipped, silently, whether it points at a directory or a
    ``.py`` file.** Following one would let a child inside the bundle
    resolve to code living *outside* it -- a sandbox escape (§7.2/§14: "the
    compiler executes only the user's own Python"). It also breaks cleanup
    and re-import bookkeeping: a followed symlink's target module's
    ``__file__``/``__path__`` resolves outside ``bundle_path``, so
    ``_module_belongs_to_bundle`` would never clean it up, leaking it into
    ``sys.modules`` forever -- and the next compile's double-import guard
    would then silently serve that stale leaked module instead of
    re-importing (or correctly excluding) it. Symlinks are simply outside
    this loader's contract in v1; nothing is emitted for a skipped one.
    """
    out: list[Path] = []
    stack = [bundle_path]
    while stack:
        current = stack.pop()
        children = sorted(current.iterdir())
        for child in children:
            if child.is_symlink():
                continue
            if child.is_dir():
                if not _is_skipped_dir(child.name):
                    stack.append(child)
            elif child.suffix == ".py" and not child.name.startswith("_"):
                out.append(child)
    out.sort()
    return out


def _dotted_module_name(bundle_path: Path, py: Path) -> str:
    """``automations/hallway.py`` (relative to the bundle root) -> ``"automations.hallway"``."""
    rel = py.relative_to(bundle_path).with_suffix("")
    return ".".join(rel.parts)


def _import_bundle_modules(bundle_path: Path) -> None:
    """Import every ``*.py`` module in the bundle tree (sorted, stable), at
    any depth under a subdirectory (M7.1, DESIGN §6/§7.3, docs/ha-api-notes.md
    §17.9 RESOLVED).

    Each file is imported under its dotted package-relative module name
    (``automations.hallway``, not just ``hallway``) so a cross-file
    ``from helpers.modes import guest_mode`` elsewhere in the tree resolves to
    the *same* module object real Python import machinery would use --
    subdirectories need no ``__init__.py`` (PEP 420 namespace packages; the
    bundle root is already on ``sys.path``, see ``_sandboxed_import``).

    Every file is checked against ``sys.modules`` before executing: a prior
    file's own ``from package.module import name`` may have already triggered
    the normal import system to load it (registering the *same* dotted name),
    and re-executing it under a fresh module object here would run the user's
    module body twice (double side effects, duplicate registry entries).

    Belt-and-suspenders (review finding F1): even though
    ``_iter_bundle_source_files`` already skips any symlinked directory or
    file, each accepted path is re-resolved and re-checked against
    ``bundle_path.resolve()`` immediately before import -- defends against a
    symlinked *intermediate* path component (e.g. a non-symlink leaf file
    reached through a symlinked grandparent directory two levels up), which
    ``child.is_symlink()`` on the leaf alone would not catch.
    """
    resolved_bundle_path = bundle_path.resolve()
    for py in _iter_bundle_source_files(bundle_path):
        if not py.resolve().is_relative_to(resolved_bundle_path):
            continue  # defensive: escaped the bundle via some path component
        module_name = _dotted_module_name(bundle_path, py)
        if module_name in sys.modules:
            continue  # already imported via a cross-file `from X import Y`
        spec = importlib.util.spec_from_file_location(module_name, py)
        if spec is None or spec.loader is None:  # pragma: no cover - defensive
            raise ImportError(f"cannot load bundle module {py}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
