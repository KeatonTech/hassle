"""Compiler-surface errors (R6: what / where / fix, one paragraph, snapshot-tested).

Every message names *what* went wrong, *where* (file:line where determinable), and
*the fix*, in a single paragraph. These are product surface — the agent docs (§12)
depend on them and they are snapshot-tested (tests/snapshots/errors/).
"""

from __future__ import annotations

from hassle.compiler.spans import SourceSpan


class CompileError(Exception):
    """Base class for all compile-time errors Hassle raises."""


class CompileTimeBranchError(CompileError):
    """Raised when Python ``if``/``bool()`` is used on a runtime state expression.

    DESIGN §5.5: condition/state expressions define ``__bool__`` to raise this so a
    native Python branch on a runtime value cannot silently compile wrong — it fails
    loudly with a teaching error pointing at the ``with if_then(...)`` rewrite.
    """

    def __init__(self, expr_repr: str, span: SourceSpan | None) -> None:
        where = f" at {span.file}:{span.line}" if span is not None else ""
        self.span = span
        super().__init__(
            f"You used a Python `if`/`bool()` on the runtime state expression "
            f"`{expr_repr}`{where}. Python control flow runs at compile time, so a "
            f"branch on a live entity state would be evaluated once during compilation "
            f"and baked in wrong — never re-checked at runtime. Fix: express the branch "
            f"with a runtime construct, e.g. `with if_then({expr_repr}):` (and "
            f"`with else_then():` for the else arm), which compiles to HA's `if`/`choose`."
        )


class DuplicateObjectError(CompileError):
    """Two registered objects resolve to the same object key (id collision)."""

    def __init__(
        self, object_key: str, first: SourceSpan | None, second: SourceSpan | None
    ) -> None:
        self.object_key = object_key
        loc_a = f"{first.file}:{first.line}" if first is not None else "<unknown>"
        loc_b = f"{second.file}:{second.line}" if second is not None else "<unknown>"
        super().__init__(
            f"Duplicate object key `{object_key}`: two objects in this bundle claim the "
            f"same id, first at {loc_a} and again at {loc_b}. An object's id is its HA "
            f"identity and must be unique bundle-wide. Fix: give one of them a distinct "
            f"`id=` (or rename the function, whose name is the default id)."
        )


class UnknownAutomationOptionError(CompileError):
    """``@automation`` (or ``@script``) got a keyword it does not accept."""

    def __init__(self, option: str, allowed: list[str], span: SourceSpan | None) -> None:
        self.option = option
        where = f" at {span.file}:{span.line}" if span is not None else ""
        allowed_str = ", ".join(sorted(allowed))
        super().__init__(
            f"Unknown automation option `{option}`{where}. `@automation` accepts only HA's "
            f"automation options: {allowed_str}. Fix: remove `{option}=` or correct its "
            f"spelling; per-object runtime data belongs in `variables=`/`trigger_variables=`, "
            f"not as a decorator keyword."
        )


class ElseWithoutIfError(CompileError):
    """``else_then``/``else_if`` used when the preceding action isn't an ``if``/``choose``.

    DESIGN §5.5: ``with else_then():`` and ``with else_if(...):`` must attach to
    the action recorded immediately before them in the same action list. Used
    at the start of a list, or after some other action, they have nothing to
    attach to.
    """

    def __init__(self, call: str, span: SourceSpan | None) -> None:
        self.call = call
        where = f" at {span.file}:{span.line}" if span is not None else ""
        super().__init__(
            f"`with {call}(...):`{where} does not immediately follow an `if_then`/"
            f"`choose`/`else_if` action in the same action list. HA's `if`/`choose` "
            f"else-branch is a structural part of that action, so `{call}` must be "
            f"the very next statement after the `with if_then(...):`/`with choose():` "
            f"(or `else_if`) block it belongs to. Fix: move `with {call}(...):` "
            f"directly after its `if`/`choose`, with no other action recorded in "
            f"between."
        )


class NoRecordingContextError(CompileError):
    """A recording call (``when``/``only_if``/service/``delay``) ran outside a context.

    This happens when DSL recording calls are made at module scope instead of inside
    an ``@automation``/``@script`` body (which the compiler invokes inside a context).
    """

    def __init__(self, call: str, span: SourceSpan | None) -> None:
        where = f" at {span.file}:{span.line}" if span is not None else ""
        super().__init__(
            f"`{call}` was called outside any recording context{where}. Trigger, condition "
            f"and action calls only make sense inside an `@automation`/`@script` function "
            f"body, which the compiler runs inside a recording context. Fix: move this call "
            f"into a decorated function body; if you meant to build a value, assign the "
            f"builder to a variable instead of calling `{call}` at module scope."
        )
