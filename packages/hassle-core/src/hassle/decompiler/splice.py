"""LibCST-based single-object splice (DESIGN §7.3).

``splice_object`` replaces exactly one top-level object (a ``def`` -- an
``@automation``/``@script``-decorated function -- or a bare assignment, for
helpers/``blueprint_automation``) in an existing bundle file, leaving every
other statement, blank line, and comment byte-identical. The spliced-in
replacement is tagged with a ``# hassle: updated from UI on <date>`` marker
comment.

The companions that let :class:`hassle.sync.source_writer.SplicingSourceWriter`
drive a real pull-side refresh/drop through this splice (the fix for pull's
REFRESH clobbering sibling objects that share a source file):

- :func:`find_object_statement_name` -- resolve an ``object_key`` to the
  top-level statement NAME currently defining it in a file (the def name is
  arbitrary; identity lives in the decorator/call's ``id=`` kwarg, falling
  back to the statement name exactly like ``hassle.compiler.registry.
  _register`` does at compile time).
- :func:`split_module_source` -- split ``decompile_bundle``'s single-object
  output into its import header and the one object statement
  (:func:`splice_object` accepts exactly one top-level statement).
- :func:`merge_missing_imports` -- add whichever of those header imports the
  target file doesn't already have (a splice alone can never inject one).
- :func:`remove_object` -- the drop-side counterpart: delete one statement,
  keep the rest of the file byte-identical.

:func:`splice_object` and :func:`remove_object` target the SINGLE statement
whose declared ``(kind, identity)`` matches their ``object_key``
(:func:`_resolve_target_index`, shared with
:func:`find_object_statement_name`) -- never "every statement with this
name": two defs may legally share a name while declaring different ids, and
name-based targeting spliced over / removed both (the
``test_splicing_source_writer.py`` name-collision regressions).

Deterministic, no wall-clock in core logic: ``updated_on`` is a parameter
the caller passes explicitly -- this module never reads the system clock.
"""

from __future__ import annotations

import libcst as cst

from hassle._markers import UI_SPLICE_MARKER_PREFIX


def _object_name(stmt: cst.CSTNode) -> str | None:
    """The top-level name a statement defines, or ``None`` if it isn't a
    hassle-managed object statement (a `def` or a simple `name = ...` assign)."""
    if isinstance(stmt, cst.FunctionDef):
        return stmt.name.value
    if isinstance(stmt, cst.SimpleStatementLine):
        for small in stmt.body:
            if isinstance(small, cst.Assign) and len(small.targets) == 1:
                target = small.targets[0].target
                if isinstance(target, cst.Name):
                    return target.value
    return None


def _parse_replacement(new_source: str, *, updated_on: str) -> cst.BaseStatement:
    """Parse ``new_source`` as a module and return its single top-level
    statement, with the UI-update marker attached as a leading comment.

    ``new_source`` may already start with a ``# hassle: updated from UI on
    <date>`` marker line (the decompiler's own pull output does not add one
    itself; a caller driving a real pull adds it here) -- any existing marker
    line is stripped and replaced so there is never more than one.
    """
    lines = new_source.splitlines()
    lines = [line for line in lines if not line.strip().startswith(UI_SPLICE_MARKER_PREFIX)]
    stripped_source = "\n".join(lines).strip("\n") + "\n"

    module = cst.parse_module(stripped_source)
    if len(module.body) != 1:
        raise ValueError(
            f"expected exactly one top-level statement in the replacement source, "
            f"got {len(module.body)}"
        )
    (stmt,) = module.body

    marker_comment = cst.Comment(f"{UI_SPLICE_MARKER_PREFIX} {updated_on}")
    marker_line = cst.EmptyLine(comment=marker_comment)
    existing_leading = list(stmt.leading_lines)
    return stmt.with_changes(leading_lines=[marker_line, *existing_leading])


def splice_object(
    file_source: str,
    *,
    object_key: str,
    new_source: str,
    updated_on: str,
) -> str:
    """Replace the single top-level statement defining ``object_key``
    (``"<kind>:<identity>"``) in ``file_source``.

    ``new_source`` is the replacement statement's source (typically
    :func:`hassle.decompiler.decompile_object`'s output for the drifted
    object). ``updated_on`` is an ISO date string supplied by the caller
    (never wall-clock) that becomes the ``# hassle: updated from UI on <date>``
    marker on the spliced-in replacement.

    The target is resolved by its declared ``(kind, identity)`` (same
    resolution as :func:`find_object_statement_name`), never by statement
    name alone: two defs may legally share a name while declaring different
    ids, and only the one matching ``object_key`` may be touched.

    Raises :class:`ValueError` if the file doesn't define ``object_key``.
    """
    module = cst.parse_module(file_source)
    replacement = _parse_replacement(new_source, updated_on=updated_on)

    index = _resolve_target_index(module, object_key)
    if index is None:
        raise ValueError(f"no top-level object defining {object_key!r} found to splice")
    new_body: list[cst.BaseStatement | cst.BaseCompoundStatement] = list(module.body)
    new_body[index] = replacement
    return module.with_changes(body=new_body).code


# `@<decorator>` -> object-key kind, for the def-shaped object forms.
_DEF_DECORATOR_KINDS = {
    "automation": "automation",
    "raw_automation": "automation",
    "script": "script",
    "shared_script": "script",
}
# `<name> = <call>(...)` object forms whose call name is NOT already the kind
# (helpers -- `guest_mode = input_boolean(id=...)` -- use the kind itself as
# the call name, so they need no entry here).
_ASSIGN_CALL_KINDS = {"blueprint_automation": "automation"}


def _call_name(node: cst.BaseExpression) -> str | None:
    if isinstance(node, cst.Call):
        node = node.func
    if isinstance(node, cst.Name):
        return node.value
    if isinstance(node, cst.Attribute):
        return node.attr.value
    return None


def _id_kwarg(node: cst.BaseExpression) -> str | None:
    """The ``id="..."`` kwarg of a decorator/builder call, when it is a plain
    string literal; ``None`` otherwise."""
    if not isinstance(node, cst.Call):
        return None
    for arg in node.args:
        if arg.keyword is not None and arg.keyword.value == "id":
            if isinstance(arg.value, cst.SimpleString):
                value = arg.value.evaluated_value
                if isinstance(value, str):
                    return value
            return None
    return None


# Assignment-call kinds that ARE object declarations: every helper domain (the
# frozen IR schema) plus `blueprint_automation`'s mapping above. Anything else
# on an assignment's right-hand side (`state(...)`, an arbitrary local call)
# is not a hassle object statement at all.
def _assign_object_kinds() -> frozenset[str]:
    from hassle.ir import HELPER_DOMAINS

    return frozenset(HELPER_DOMAINS) | frozenset(_ASSIGN_CALL_KINDS.values())


def _declared_object(stmt: cst.CSTNode) -> tuple[str, str] | None:
    """The ``(kind, identity)`` ``stmt`` declares, when it is an object
    declaration form this module models (a hassle-decorated ``def``, or a
    helper/``blueprint_automation`` assignment call); ``None`` for anything
    else (imports, local helper functions, unrelated assignments).

    Mirrors compile-time identity: the ``id=`` kwarg when present, else the
    statement's own name (``hassle.compiler.registry._register``:
    ``options.get("id") or func.__name__``).
    """
    name = _object_name(stmt)
    if name is None:
        return None
    if isinstance(stmt, cst.FunctionDef):
        for decorator in stmt.decorators:
            kind = _DEF_DECORATOR_KINDS.get(_call_name(decorator.decorator) or "")
            if kind is not None:
                return kind, _id_kwarg(decorator.decorator) or name
        return None
    if isinstance(stmt, cst.SimpleStatementLine):
        for small in stmt.body:
            if not isinstance(small, cst.Assign):
                continue
            call_name = _call_name(small.value) or ""
            kind = _ASSIGN_CALL_KINDS.get(call_name, call_name)
            if kind in _assign_object_kinds():
                return kind, _id_kwarg(small.value) or name
    return None


def _resolve_target_index(module: cst.Module, object_key: str) -> int | None:
    """Index in ``module.body`` of the SINGLE statement defining
    ``object_key`` (``"<kind>:<identity>"``), or ``None`` if the module
    doesn't define it.

    A statement whose declared ``(kind, identity)`` matches wins. The plain
    name-equals-identity fallback applies ONLY to statement forms this module
    doesn't model as object declarations -- a statement that declares a
    DIFFERENT object (another id, another kind) is never matched by name
    alone, or a refresh/drop driven by a manifest inconsistent with the file
    would splice over / delete the wrong object instead of safely reporting
    not-found. This is the one targeting authority for
    :func:`find_object_statement_name`, :func:`splice_object`, and
    :func:`remove_object`, so a lookup and the mutation it precedes can never
    disagree on which statement is meant -- and a mutation can never touch
    more than this one statement (two defs may legally share a name while
    declaring different ids)."""
    kind, _, identity = object_key.partition(":")
    fallback: int | None = None
    for index, stmt in enumerate(module.body):
        declared = _declared_object(stmt)
        if declared == (kind, identity):
            return index
        if declared is None and fallback is None and _object_name(stmt) == identity:
            fallback = index
    return fallback


def find_object_statement_name(file_source: str, object_key: str) -> str | None:
    """The name of the top-level statement in ``file_source`` that defines
    ``object_key`` (``"<kind>:<identity>"``), or ``None`` if the file doesn't
    define it (targeting rules: :func:`_resolve_target_index`)."""
    module = cst.parse_module(file_source)
    index = _resolve_target_index(module, object_key)
    if index is None:
        return None
    name = _object_name(module.body[index])
    assert name is not None  # both resolution tiers require a named stmt
    return name


def _is_import_statement(stmt: cst.CSTNode) -> bool:
    return isinstance(stmt, cst.SimpleStatementLine) and all(
        isinstance(small, (cst.Import, cst.ImportFrom)) for small in stmt.body
    )


def split_module_source(module_source: str) -> tuple[list[str], list[str]]:
    """Split ``module_source`` into (top-level import statement sources,
    all other top-level statement sources). Raises :class:`ValueError` when
    the source doesn't parse (so callers need not know LibCST's exceptions)."""
    try:
        module = cst.parse_module(module_source)
    except cst.ParserSyntaxError as exc:
        raise ValueError(f"module source does not parse: {exc}") from exc
    imports: list[str] = []
    others: list[str] = []
    for stmt in module.body:
        code = module.code_for_node(stmt)
        if _is_import_statement(stmt):
            imports.append(code.strip())
        else:
            others.append(code)
    return imports, others


def _import_from_module_name(stmt: cst.ImportFrom) -> str | None:
    """Dotted module path of a ``from <module> import ...`` (no relative
    imports in generated/bundle code -- ``None`` for those)."""
    if stmt.relative:
        return None
    node = stmt.module
    parts: list[str] = []
    while isinstance(node, cst.Attribute):
        parts.append(node.attr.value)
        node = node.value
    if not isinstance(node, cst.Name):
        return None
    parts.append(node.value)
    return ".".join(reversed(parts))


def _provided_imports(module: cst.Module) -> tuple[set[str], set[tuple[str, str]]]:
    """(star-imported / plainly-imported module names,
    ``(module, imported-name)`` pairs) already present at ``module``'s top level."""
    star_or_plain: set[str] = set()
    names: set[tuple[str, str]] = set()
    for stmt in module.body:
        if not isinstance(stmt, cst.SimpleStatementLine):
            continue
        for small in stmt.body:
            if isinstance(small, cst.Import):
                for alias in small.names:
                    star_or_plain.add(module.code_for_node(alias.name))
            elif isinstance(small, cst.ImportFrom):
                mod = _import_from_module_name(small)
                if mod is None:
                    continue
                if isinstance(small.names, cst.ImportStar):
                    star_or_plain.add(f"{mod}.*")
                else:
                    for alias in small.names:
                        if isinstance(alias.name, cst.Name):
                            names.add((mod, alias.name.value))
    return star_or_plain, names


def _import_is_satisfied(
    candidate: cst.SimpleStatementLine,
    module: cst.Module,
    star_or_plain: set[str],
    names: set[tuple[str, str]],
) -> bool:
    for small in candidate.body:
        if isinstance(small, cst.Import):
            for alias in small.names:
                if module.code_for_node(alias.name) not in star_or_plain:
                    return False
        elif isinstance(small, cst.ImportFrom):
            mod = _import_from_module_name(small)
            if mod is None:
                return False
            if isinstance(small.names, cst.ImportStar):
                if f"{mod}.*" not in star_or_plain:
                    return False
            else:
                for alias in small.names:
                    if not isinstance(alias.name, cst.Name):
                        return False
                    if alias.asname is not None:
                        # Aliased imports (`entities as e`) are only satisfied
                        # textually -- the caller's exact-statement dedupe
                        # already handled that, so here it's simply missing.
                        return False
                    if (mod, alias.name.value) not in names:
                        return False
        else:
            return False
    return True


def _import_codes(module: cst.Module) -> set[str]:
    return {
        module.code_for_node(stmt).strip() for stmt in module.body if _is_import_statement(stmt)
    }


def merge_missing_imports(file_source: str, import_sources: list[str]) -> str:
    """Insert whichever of ``import_sources`` (one import statement each)
    ``file_source`` doesn't already satisfy, right after its last top-level
    import (or before the first statement when it has none). Byte-identical
    input order is preserved (callers pass deterministic, sorted lines)."""
    module = cst.parse_module(file_source)
    star_or_plain, names = _provided_imports(module)
    existing_codes = _import_codes(module)

    to_insert: list[cst.SimpleStatementLine] = []
    for source in import_sources:
        candidate = cst.parse_module(source.strip() + "\n").body[0]
        if not isinstance(candidate, cst.SimpleStatementLine):
            continue
        if module.code_for_node(candidate).strip() in existing_codes:
            continue
        if _import_is_satisfied(candidate, module, star_or_plain, names):
            continue
        to_insert.append(candidate)
    if not to_insert:
        return file_source

    last_import_index = -1
    for index, stmt in enumerate(module.body):
        if _is_import_statement(stmt):
            last_import_index = index
    new_body = list(module.body)
    new_body[last_import_index + 1 : last_import_index + 1] = to_insert
    return module.with_changes(body=new_body).code


def remove_object(file_source: str, *, object_key: str) -> str | None:
    """Remove the single top-level statement defining ``object_key``; every
    other statement stays byte-identical. Returns ``None`` when nothing but
    imports (and comments) would remain -- the caller should delete the file,
    matching drop's whole-file semantics for a single-object file.

    Same identity-based target resolution as :func:`splice_object` (never by
    statement name alone -- see :func:`_resolve_target_index`).

    Raises :class:`ValueError` if the file doesn't define ``object_key``.
    """
    module = cst.parse_module(file_source)
    index = _resolve_target_index(module, object_key)
    if index is None:
        raise ValueError(f"no top-level object defining {object_key!r} found to remove")
    new_body = list(module.body)
    del new_body[index]
    new_module = module.with_changes(body=new_body)
    if all(_is_import_statement(stmt) for stmt in new_module.body):
        return None
    return new_module.code
