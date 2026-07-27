"""Bundle loader + compile pipeline: DSL bundle dir -> IR (DESIGN §7.2).

``compile_bundle`` imports a bundle directory as an isolated package (``sys.path``
sandboxed, no network — the compiler executes only the user's own Python, §14),
drains the registry of ``@automation``/``@script`` objects, runs each inside a
:class:`Recorder`, and assembles the IR in HA's canonical plural schema (§7.1).

The result carries the IR objects keyed by object key, plus a span map so every
downstream error (validation, plan conflict, simulator failure) can point at the
user's Python line. Duplicate object keys are rejected.

The bundle is a package tree (DESIGN §6/§7.3, docs/internals/ha-api-notes.md §17.9
RESOLVED): subdirectories are recursively imported as PEP 420 namespace
packages, no ``__init__.py`` required anywhere.

**Symlink policy: every symlink under the bundle
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

import ast
import contextlib
import importlib
import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hassle.compiler.errors import (
    AmbiguousCategorySourceError,
    DuplicateObjectError,
    InvalidCategoryGlobalError,
)
from hassle.compiler.recording import RecordedNode, Recorder, record_trigger, recording
from hassle.compiler.registry import PrebuiltObject, RegisteredObject, fresh
from hassle.compiler.spans import SourceSpan
from hassle.ir import normalize_ha
from hassle.ir.keys import DASHBOARD_KIND, category_shaped_stem
from hassle.ir.models import AutomationConfig, DashboardConfig, IRObject, ScriptConfig

# object_key -> {"triggers"|"conditions"|"actions": [SourceSpan | None, ...]}
_SectionSpans = dict[str, list["SourceSpan | None"]]


def _empty_objects() -> dict[str, IRObject]:
    return {}


def _empty_spans() -> dict[str, _SectionSpans]:
    return {}


def _empty_decl_spans() -> dict[str, SourceSpan | None]:
    return {}


# object_key -> {node path -> span}, for kinds whose body is a TREE rather than
# a set of flat block lists (dashboards; see `CompileResult.node_spans_for`).
_NodeSpans = dict[str, "SourceSpan"]


def _empty_node_spans() -> dict[str, _NodeSpans]:
    return {}


@dataclass(frozen=True)
class CategoryGlobal:
    """One bundle file's module-level ``CATEGORY`` global: its declared
    display-name value plus the assignment's source span (when obtainable —
    a plain top-level `CATEGORY = "..."` executes at import time with no
    Hassle DSL call involved, so it isn't captured by
    :func:`hassle.compiler.spans.capture_span`; the span is instead found by
    a lightweight `ast` scan of the module's own source, giving "file:line
    of the CATEGORY assignment if obtainable, else file")."""

    value: str
    span: SourceSpan | None


def _empty_category_globals() -> dict[str, CategoryGlobal]:
    return {}


@dataclass
class CompileResult:
    """The output of compiling a bundle: IR objects + their source spans."""

    objects: dict[str, IRObject] = field(default_factory=_empty_objects)
    # object_key -> per-section span lists (parallel to the IR block lists).
    _spans: dict[str, _SectionSpans] = field(default_factory=_empty_spans)
    # object_key -> the decoration-site span (for whole-object errors like duplicates).
    _decl_spans: dict[str, SourceSpan | None] = field(default_factory=_empty_decl_spans)
    # bundle-relative source path (POSIX, e.g. "automations/hvac.py") -> that
    # file's module-level `CATEGORY` global, when it declares one. A sidecar
    # map, exactly like `_spans`/`_decl_spans` -- never part of the frozen IR
    # schema.
    _category_globals: dict[str, CategoryGlobal] = field(default_factory=_empty_category_globals)
    # Root-level directories that are CATEGORY PACKAGES (a dir holding an
    # `__init__.py`): every module inside is attributed to the package's own
    # name. A sidecar exactly like `_category_globals` -- never part of the
    # frozen IR schema. Consumers pass it to `category_shaped_stem`.
    _category_packages: frozenset[str] = frozenset()
    # object_key -> {node path -> span}. A sidecar exactly like `_spans`, for
    # kinds whose body is a tree (dashboards): `_spans`' per-section positional
    # lists cannot address a card nested three containers deep.
    _node_spans: dict[str, _NodeSpans] = field(default_factory=_empty_node_spans)

    def add(
        self,
        obj: IRObject,
        spans: _SectionSpans,
        decl_span: SourceSpan | None,
        duplicate_of: SourceSpan | None,
        node_spans: _NodeSpans | None = None,
    ) -> None:
        """Register a compiled object + its spans; reject a duplicate object key.

        Internal to the pipeline (used by :func:`compile_registered`); downstream
        consumers read via :attr:`objects`, :meth:`spans_for` and (for
        tree-shaped bodies) :meth:`node_spans_for`.
        """
        key = obj.object_key()
        if key in self.objects:
            raise DuplicateObjectError(key, self._decl_spans.get(key), duplicate_of)
        self.objects[key] = obj
        self._spans[key] = spans
        self._decl_spans[key] = decl_span
        if node_spans:
            self._node_spans[key] = node_spans

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
        additive: does not change ``spans_for``'s existing behavior.
        """
        key = obj.object_key()
        spans = self._spans.get(key, {}).get(section, [])
        if 0 <= index < len(spans):
            return spans[index]
        return None

    def node_spans_for(self, obj: IRObject) -> _NodeSpans:
        """Every recorded node's span for a TREE-shaped body, keyed by path.

        The dashboard counterpart of :meth:`spans_for`: a dashboard's cards are
        nested arbitrarily deep, so they are addressed by a path rather than by
        a per-section index. Path grammar (frozen with F5): dot-joined
        ``<key>[<index>]`` segments relative to the dashboard's ``config``, e.g.
        ``views[0]``, ``views[0].badges[1]``, ``views[0].sections[0].cards[2]``.
        Empty for every other kind.
        """
        return dict(self._node_spans.get(obj.object_key(), {}))

    def node_span(self, obj: IRObject, path: str) -> SourceSpan | None:
        """The span of one node of a tree-shaped body (see :meth:`node_spans_for`)."""
        return self._node_spans.get(obj.object_key(), {}).get(path)

    def decl_span_for(self, object_key: str) -> SourceSpan | None:
        """The declaration-site span for ``object_key``.

        The same span used to point a `DuplicateObjectError` at each
        conflicting declaration -- exposed publicly so whole-object findings
        (e.g. a helper-id/name-slug mismatch check) can point at *where
        the helper/automation/script was declared*, not just at a
        trigger/condition/action line within it.
        """
        return self._decl_spans.get(object_key)

    def set_category_packages(self, packages: frozenset[str]) -> None:
        """Record the bundle's category packages (see
        :func:`discover_category_packages`)."""
        self._category_packages = packages

    @property
    def category_packages(self) -> frozenset[str]:
        """Root-level package directories whose modules all share one
        category -- pass to `hassle.ir.keys.category_shaped_stem`."""
        return self._category_packages

    def set_category_global(self, source_path: str, category: CategoryGlobal) -> None:
        """Record ``source_path``'s (bundle-relative, POSIX) ``CATEGORY``
        global. Internal to the pipeline (called from
        :func:`compile_bundle` while importing each bundle module); downstream
        consumers read via :meth:`category_global_for`/:attr:`category_globals`.
        """
        self._category_globals[source_path] = category

    def category_global_for(self, source_path: str) -> CategoryGlobal | None:
        """The ``CATEGORY`` global declared by ``source_path`` (bundle-relative,
        POSIX, e.g. ``"automations/hvac.py"``), or ``None`` if that file
        declares none."""
        return self._category_globals.get(source_path)

    @property
    def category_globals(self) -> dict[str, CategoryGlobal]:
        """Every bundle file that declares a ``CATEGORY`` global, keyed by its
        bundle-relative (POSIX) source path -- read-only view for the
        validator (:mod:`hassle.registry.validate`)."""
        return dict(self._category_globals)


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


def _build_dashboard(reg: RegisteredObject) -> tuple[DashboardConfig, _NodeSpans]:
    """Compile one ``@dashboard``/``@raw_dashboard`` into the §3.2 envelope.

    The dashboard sibling of :func:`_build_automation`: it opens a
    :class:`~hassle.compiler.dashboards.recorder.DashboardRecorder` instead of
    the automation ``recording(...)`` context (the two recorders are siblings,
    dashboards-design §6.1), or -- for a ``@raw_dashboard`` -- simply calls the
    function and normalizes whatever envelope/config dict it returned.

    ``normalize_ha`` is deliberately NOT applied: it is an identity function for
    this kind by contract (§3.3), because a card's `tap_action` legitimately
    carries a legacy `service:` key that the generic rewrite would corrupt.
    """
    from hassle.compiler.dashboards.decorators import (
        build_meta,
        build_raw_envelope,
        record_declared,
    )
    from hassle.compiler.dashboards.recorder import dashboard_recording

    node_spans: _NodeSpans = {}
    if reg.raw:
        envelope = build_raw_envelope(reg.func(), reg.options, reg.span)
    else:
        with dashboard_recording(**reg.options) as rec:
            reg.func()
        envelope = {"meta": build_meta(reg.options), "config": rec.build_config()}
        node_spans = rec.node_spans()
    record_declared(envelope)
    obj = DashboardConfig.model_validate(envelope)
    # Extrinsic identity for the default dashboard (`meta: null` carries no
    # `url_path`); harmlessly redundant for every other dashboard, whose
    # identity comes from `meta.url_path` itself.
    obj.attach_key(reg.declared_id)
    return obj, node_spans


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
        if reg.kind == DASHBOARD_KIND:
            # Dashboards trace into their OWN recorder, not `recording(...)`.
            dashboard, dashboard_spans = _build_dashboard(reg)
            result.add(
                dashboard,
                spans={},
                decl_span=reg.span,
                duplicate_of=reg.span,
                node_spans=dashboard_spans,
            )
            continue
        with recording(kind=reg.kind, **reg.options) as rec:
            # `@automation(triggers=[...])` (additive to the frozen DSL
            # surface, DESIGN §5.3/§5.5): the decorator's triggers were
            # already built at decoration time -- record them first, before
            # running the body, so they land ahead of any `when()` calls
            # inside the body (composition order: "decorator list first,
            # when() appends", also documented in docs/internals/dsl-extensions.md).
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

    # Sweep for any `template_number`/`template_sensor`/
    # `template_binary_sensor`/`template_select` call that omitted `state=`
    # (the decorator-form signal) but was never actually applied as a
    # decorator over a function -- such a call builds/registers nothing, so
    # without this sweep it would compile clean with the object simply
    # absent (a silent regression, and a hazard of silently losing track of
    # the helper if it already exists in HA). Runs at the end of this
    # shared core so both `compile_bundle` and any direct caller (e.g. a
    # single-file/fixture compile) are covered alike.
    from hassle.compiler.template_helpers import check_no_dangling_template_helper_declarations

    check_no_dangling_template_helper_declarations()
    return result


def compile_bundle(bundle_dir: str | Path) -> CompileResult:
    """Import ``bundle_dir`` in isolation, collect registered objects, compile to IR.

    No network is touched (I/O is import + user code only). Each call installs a
    fresh registry so repeated compiles are independent (compiled output
    must be byte-stable).
    """
    bundle_path = Path(bundle_dir).resolve()
    if not bundle_path.is_dir():
        raise FileNotFoundError(f"bundle directory not found: {bundle_path}")

    # Reset the declarative builders' process-wide lists so a prior compile (or a
    # bundle import in the same process) never bleeds objects into this one.
    # These modules track declarations in module globals in addition to the
    # per-compile registry, so both must be cleared.
    from hassle.compiler.dashboards.decorators import reset_declared_dashboards
    from hassle.compiler.group_helpers import reset_declared_group_helpers
    from hassle.compiler.helpers import reset_declared_helpers
    from hassle.compiler.raw_automation import reset_declared_raw_automations
    from hassle.compiler.template_helpers import reset_declared_template_helpers

    reset_declared_helpers()
    reset_declared_template_helpers()
    reset_declared_group_helpers()
    reset_declared_raw_automations()
    reset_declared_dashboards()

    category_packages = discover_category_packages(bundle_path)

    reg = fresh()
    with _sandboxed_import(bundle_path):
        category_globals = _import_bundle_modules(bundle_path, category_packages)
    # Snapshot the registry before compiling (compile opens recorders that must not
    # see leftover registrations). Pre-built objects (helpers / raw / blueprint)
    # ride the `prebuilt` stream; function-shaped registrations ride `objects`.
    result = compile_registered(list(reg.objects), list(reg.prebuilt))
    for source_path, category in category_globals.items():
        result.set_category_global(source_path, category)
    result.set_category_packages(category_packages)
    return result


def discover_category_packages(bundle_path: Path) -> frozenset[str]:
    """Finds the bundle's CATEGORY PACKAGES: root-level directories holding an
    ``__init__.py``

    Every module under such a directory is attributed to one category -- the
    package's own name -- exactly as if declared in a root-level ``<pkg>.py``
    (see :func:`hassle.ir.keys.category_shaped_stem`). ``__init__.py`` is the
    opt-in marker and the ONLY discriminator, which is what keeps `lib/`,
    `tests/`, `docs/` and dot-directories unchanged: they are PEP 420
    namespace directories, so an existing bundle cannot change behaviour until
    someone deliberately adds an ``__init__.py``.

    Symlinked directories are skipped for the same sandbox-escape reason the
    module walk skips them (see this module's docstring). A package that
    collides with a same-named root-level file is
    :class:`~hassle.compiler.errors.AmbiguousCategorySourceError` -- nothing
    decides which placement owns the category, so it is not guessed.
    """
    packages: set[str] = set()
    for child in sorted(bundle_path.iterdir()):
        if child.is_symlink() or not child.is_dir():
            continue
        if child.name.startswith(".") or child.name == "__pycache__":
            continue
        if not (child / "__init__.py").is_file():
            continue
        if (bundle_path / f"{child.name}.py").is_file():
            raise AmbiguousCategorySourceError(child.name)
        packages.add(child.name)
    return frozenset(packages)


class _sandboxed_import:
    """Context manager: put the bundle dir on ``sys.path`` and clean up its modules.

    Isolation (§7.2/§14): only the bundle dir is added to the import path, and every
    module imported from it is removed from ``sys.modules`` on exit so a second
    compile re-imports fresh (no cross-compile bleed). No network is involved.

    The bundle is a package tree (subdirectories are importable as
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
    directory-listing order).

    Symlink policy (docs/internals/ha-api-notes.md §17.9): **every
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


def _category_global_span(py: Path) -> SourceSpan | None:
    """The source span of a top-level ``CATEGORY = ...`` assignment in ``py``,
    or ``None`` if it can't be found ("file:line of the CATEGORY
    assignment if obtainable, else file").

    ``CATEGORY`` executes as a plain module-level assignment at import time --
    no Hassle DSL call is involved, so :func:`hassle.compiler.spans.capture_span`
    (which walks live call-stack frames) cannot see it. A lightweight `ast`
    parse of the file's own source is simpler and more reliable than trying to
    thread a frame hook through an ordinary Python assignment statement.
    """
    try:
        tree = ast.parse(py.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError):  # pragma: no cover - defensive
        return None
    for stmt in tree.body:
        if (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
            and stmt.targets[0].id == "CATEGORY"
        ):
            return SourceSpan(file=str(py), line=stmt.lineno)
    return None


def _import_bundle_modules(
    bundle_path: Path, category_packages: frozenset[str] = frozenset()
) -> dict[str, CategoryGlobal]:
    """Import every ``*.py`` module in the bundle tree (sorted, stable), at
    any depth under a subdirectory (DESIGN §6/§7.3, docs/internals/ha-api-notes.md
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

    Belt-and-suspenders: even though ``_iter_bundle_source_files`` already
    skips any symlinked directory or file, each accepted path is
    re-resolved and re-checked against ``bundle_path.resolve()`` immediately
    before import -- defends against a symlinked *intermediate* path
    component (e.g. a non-symlink leaf file reached through a symlinked
    grandparent directory two levels up), which ``child.is_symlink()`` on
    the leaf alone would not catch.

    After each module executes, its namespace is checked for a module-level
    ``CATEGORY`` global -- but ONLY for a file matching
    :func:`hassle.ir.keys.category_shaped_stem`'s ``automations/<stem>.py`` /
    ``scripts/<stem>.py`` shape (an unscoped ``hasattr`` check would be a
    false positive against ordinary bundle code that happens to use the name
    `CATEGORY` for something else entirely -- a `lib/constants.py` support
    module, an unrelated enum value). The path-shape check runs BEFORE even
    looking at the module's namespace for a non-category-shaped file, so the
    non-``str`` guard below only ever fires for a category-shaped file too --
    a `CATEGORY = 5` in `lib/enums.py` is simply never looked at. A
    non-``str`` value in a category-shaped file is a compile-time
    :class:`~hassle.compiler.errors.InvalidCategoryGlobalError`
    (what/where/fix), raised immediately rather than carried forward as a
    bad value some downstream consumer would have to re-validate. Returned
    as a bundle-relative-POSIX-path -> :class:`CategoryGlobal` map for
    :func:`compile_bundle` to attach to the `CompileResult` it builds
    afterward (this function itself never touches `CompileResult` -- it
    runs entirely inside `_sandboxed_import`, before any recorder opens).
    """
    resolved_bundle_path = bundle_path.resolve()
    category_globals: dict[str, CategoryGlobal] = {}
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

        source_path = py.relative_to(bundle_path).as_posix()
        if category_shaped_stem(
            source_path, package_roots=category_packages
        ) is not None and hasattr(module, "CATEGORY"):
            value = module.CATEGORY
            if not isinstance(value, str):
                raise InvalidCategoryGlobalError(str(py), value)
            category_globals[source_path] = CategoryGlobal(
                value=value, span=_category_global_span(py)
            )
    return category_globals
