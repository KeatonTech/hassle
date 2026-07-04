"""M1 actions/control-flow trap coverage (work item scope, item 5).

DESIGN §5.5: a native Python `if`/`for` on a runtime state expression must
raise `CompileTimeBranchError` loudly rather than silently compiling wrong --
even (especially) when it happens *inside* a nested runtime construct like
`if_then`/`choose`/`repeat_*`/`parallel`. These traps are not just a top-level
guarantee; the recording-context stack must keep `__bool__` trapping no matter
how deep the active context is.
"""

from __future__ import annotations

import pytest

from hassle import service, state
from hassle.compiler import CompileTimeBranchError
from hassle.compiler.control_flow import choose, if_then, parallel, repeat_count
from hassle.compiler.recording import recording


def test_native_if_traps_inside_if_then_body() -> None:
    with (
        recording(alias="x", id="x"),
        pytest.raises(CompileTimeBranchError),
        if_then(state("light.a").is_("on")),
    ):
        expr = state("light.b").is_("on")
        if expr:
            service("light.turn_on", entity_id="light.c")


def test_native_if_traps_inside_repeat_body() -> None:
    with (
        recording(alias="x", id="x"),
        pytest.raises(CompileTimeBranchError),
        repeat_count(3),
    ):
        expr = state("light.b").is_("on")
        if expr:
            service("light.turn_on", entity_id="light.c")


def test_native_if_traps_inside_parallel_body() -> None:
    with (
        recording(alias="x", id="x"),
        pytest.raises(CompileTimeBranchError),
        parallel(),
    ):
        expr = state("light.b").is_("on")
        if expr:
            service("light.turn_on", entity_id="light.c")


def test_native_if_traps_inside_choose_when_branch() -> None:
    with (
        recording(alias="x", id="x"),
        pytest.raises(CompileTimeBranchError),
        choose() as c,
        c.when_(state("light.a").is_("on")),
    ):
        expr = state("light.b").is_("on")
        if expr:
            service("light.turn_on", entity_id="light.c")


def test_native_if_traps_inside_deeply_nested_body() -> None:
    # if inside repeat inside choose -- the same shape as the deep_nesting
    # golden case, but with a native `if` where an `if_then` belongs.
    with (
        recording(alias="x", id="x"),
        pytest.raises(CompileTimeBranchError),
        choose() as c,
        c.when_(state("light.a").is_("on")),
        repeat_count(2),
    ):
        expr = state("light.b").is_("on")
        if expr:
            service("light.turn_on", entity_id="light.c")


def test_native_for_over_runtime_construct_traps() -> None:
    # A native Python `for` iterating a runtime condition expression (rather
    # than a compile-time list) must not silently produce a zero-iteration
    # loop: `StateExpr` defines no `__iter__`, so Python itself raises
    # TypeError -- a loud failure, never a silent no-op.
    with recording(alias="x", id="x"):
        expr = state("light.b").is_("on")
        with pytest.raises(TypeError):
            for _ in expr:  # type: ignore[attr-defined]
                pass
