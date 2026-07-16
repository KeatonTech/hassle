"""``@macro`` -- compile-time inlining (DESIGN §5.6).

A macro is *just a Python function* that calls DSL recording verbs
(``when``/``only_if``/``service``/``delay``/...) in its body. Those verbs
always record into whichever :class:`~hassle.compiler.recording.Recorder`
is active (a `ContextVar` stack, `docs/compiler-api.md` §4) -- so calling a
plain function from inside an ``@automation``/``@script`` body already splices
its recorded actions into the caller, with zero extra machinery: nested Python
calls share the same active recorder. ``@macro`` therefore does not need to
intercept or re-dispatch anything; it exists to:

- mark the function as macro (documentation / introspection -- ``AGENTS.md``
  and the docs generator can tell a macro from an ordinary helper function),
- give a clear, macro-specific error if it is ever called with no recording
  context active at all (a bundle bug: a macro was called at module scope
  instead of from inside an automation/script body), reusing the core's
  ``NoRecordingContextError`` for that so the message/what/where/fix rubric
  and its snapshot test are inherited for free (docs/compiler-api.md §5).

Nesting (a macro calling another macro) and args (ordinary Python parameters,
resolved at compile time before any DSL verb runs) fall out of "it's just a
function call" -- no special-casing needed for either.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

# `_require_active` is private to recording.py, but docs/compiler-api.md §2
# explicitly sanctions importing it ("import it from
# `hassle.compiler.recording`"): pyright's cross-module private-access
# check is silenced here for that one documented reason.
from hassle.compiler.recording import _require_active  # pyright: ignore[reportPrivateUsage]


def macro[F: Callable[..., Any]](func: F) -> F:
    """Mark ``func`` as a macro: compile-time inlining into the active recorder.

    Calling the returned function outside any recording context raises the
    same ``NoRecordingContextError`` as any other DSL verb (docs/compiler-api
    §4/§5), naming this call's file:line.
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        # Assert a recorder is active *before* running the body, so a macro
        # called at module scope (no automation/script context) fails at the
        # macro call site rather than deep inside its first DSL verb.
        _require_active(f"macro {func.__name__}()")
        return func(*args, **kwargs)

    return wrapper  # type: ignore[return-value]
