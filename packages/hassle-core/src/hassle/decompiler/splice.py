"""LibCST-based single-object splice (DESIGN §7.3, MILESTONES M2 test 4).

``splice_object`` replaces exactly one top-level object (a ``def`` -- an
``@automation``/``@script``-decorated function -- or a bare assignment, for
helpers/``blueprint_automation``) in an existing bundle file, leaving every
other statement, blank line, and comment byte-identical. The spliced-in
replacement is tagged with a ``# hassle: updated from UI on <date>`` marker
comment.

R8 (determinism / no wall-clock in core logic): ``updated_on`` is a parameter
the caller passes explicitly -- this module never reads the system clock.
"""

from __future__ import annotations

import libcst as cst

_MARKER_PREFIX = "# hassle: updated from UI on "


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


class _SpliceTransformer(cst.CSTTransformer):
    def __init__(self, object_name: str, replacement: cst.BaseStatement) -> None:
        self._object_name = object_name
        self._replacement = replacement
        self.found = False

    def leave_Module(self, original_node: cst.Module, updated_node: cst.Module) -> cst.Module:
        new_body: list[cst.BaseStatement | cst.BaseCompoundStatement] = []
        for stmt in updated_node.body:
            if _object_name(stmt) == self._object_name:
                new_body.append(self._replacement)
                self.found = True
            else:
                new_body.append(stmt)
        return updated_node.with_changes(body=new_body)


def _parse_replacement(new_source: str, *, updated_on: str) -> cst.BaseStatement:
    """Parse ``new_source`` as a module and return its single top-level
    statement, with the UI-update marker attached as a leading comment.

    ``new_source`` may already start with a ``# hassle: updated from UI on
    <date>`` marker line (the decompiler's own pull output does not add one
    itself; a caller driving a real pull adds it here) -- any existing marker
    line is stripped and replaced so there is never more than one.
    """
    lines = new_source.splitlines()
    lines = [line for line in lines if not line.strip().startswith(_MARKER_PREFIX.strip())]
    stripped_source = "\n".join(lines).strip("\n") + "\n"

    module = cst.parse_module(stripped_source)
    if len(module.body) != 1:
        raise ValueError(
            f"expected exactly one top-level statement in the replacement source, "
            f"got {len(module.body)}"
        )
    (stmt,) = module.body

    marker_comment = cst.Comment(f"{_MARKER_PREFIX}{updated_on}")
    marker_line = cst.EmptyLine(comment=marker_comment)
    existing_leading = list(stmt.leading_lines)
    return stmt.with_changes(leading_lines=[marker_line, *existing_leading])


def splice_object(
    file_source: str,
    *,
    object_name: str,
    new_source: str,
    updated_on: str,
) -> str:
    """Replace the top-level object named ``object_name`` in ``file_source``.

    ``new_source`` is the replacement statement's source (typically
    :func:`hassle.decompiler.decompile_object`'s output for the drifted
    object). ``updated_on`` is an ISO date string supplied by the caller (R8:
    never wall-clock) that becomes the ``# hassle: updated from UI on <date>``
    marker on the spliced-in replacement.

    Raises :class:`ValueError` if no top-level statement named ``object_name``
    is found.
    """
    module = cst.parse_module(file_source)
    replacement = _parse_replacement(new_source, updated_on=updated_on)

    transformer = _SpliceTransformer(object_name, replacement)
    new_module = module.visit(transformer)
    if not transformer.found:
        raise ValueError(f"no top-level object named {object_name!r} found to splice")
    return new_module.code
