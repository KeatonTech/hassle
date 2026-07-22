"""Empirical verification of the `capture_span(depth=2)` claim in docs/internals/compiler-api.md §2.

The internal-api doc hard-codes `capture_span(depth=2)` for a `@contextlib.
contextmanager`-decorated nested-construct function, with the comment "skip
the CM + contextlib frames". A prior review flagged this as unverified. This
test pins the actual frame chain and the actual line numbers so a future
change to the machinery (or to Python's contextlib) cannot silently break the
span attribution without failing a test that names exactly why.

Frame chain verified (see module docstring in control_flow.py): from inside a
`@contextlib.contextmanager` generator, walking outward via `frame.f_back`,
frame 0 is the generator's own body, frame 1 is contextlib's
`_GeneratorContextManager.__enter__` trampoline (NOT filtered as "internal" by
`_is_internal`, since its module root is `contextlib`, not `hassle`/
`hassle`), and frame 2 is the user's `with construct(...):` call site.
This holds independent of nesting depth, because each construct's own
`capture_span(depth=2)` call is one contextlib trampoline away from its own
call site regardless of how many other constructs are active above it.

This test builds its own minimal probe construct (rather than importing
`if_then`/`choose`/etc.) so it verifies the *general* CM-nesting fact
docs/internals/compiler-api.md §2 asserts, independent of any one construct's
implementation details.
"""

from __future__ import annotations

import contextlib
from collections.abc import Generator

from hassle.compiler.spans import SourceSpan, capture_span


@contextlib.contextmanager
def _probed_construct(*, probe_depth: int = 2) -> Generator[SourceSpan | None]:
    """Minimal stand-in for if_then/choose/repeat_*/parallel: a bare context
    manager that captures its own span at ``probe_depth`` and yields it."""
    span = capture_span(depth=probe_depth)
    yield span


def test_capture_span_depth_2_is_correct_for_a_bare_context_manager() -> None:
    # Line-pinned: the `with _probed_construct() as span:` call below MUST be
    # on the exact line number asserted, or this test is checking the wrong
    # thing.
    with _probed_construct() as span:  # line 46
        pass
    assert span is not None
    assert span.file.endswith("test_span_depth_empirical.py")
    assert span.line == 46


def test_capture_span_depth_2_holds_under_nesting() -> None:
    # Nesting must not change the depth needed: each construct's own
    # `capture_span(depth=2)` call is made from its own generator frame, one
    # contextlib trampoline away from its own call site, regardless of how
    # many other constructs are active above it on the stack.
    with _probed_construct() as outer_span:  # noqa: SIM117 - line 58, distinct from line 59
        with _probed_construct() as inner_span:  # line 59
            pass
    assert outer_span is not None
    assert inner_span is not None
    assert outer_span.line == 58
    assert inner_span.line == 59


def test_capture_span_depth_2_holds_three_levels_deep() -> None:
    # Matches the deep-nesting golden case (choose > repeat > if_then).
    with _probed_construct() as s1:  # noqa: SIM117 - lines 69/70/71 must stay distinct
        with _probed_construct() as s2:
            with _probed_construct() as s3:
                pass
    assert s1 is not None and s1.line == 69
    assert s2 is not None and s2.line == 70
    assert s3 is not None and s3.line == 71


def test_naive_depths_are_wrong_proving_the_plus_2_is_load_bearing() -> None:
    # depth=0 (no CM/contextlib skip) lands inside the construct's own frame
    # (this module, but not the `with` call site line) -- not the user's line.
    with _probed_construct(probe_depth=0) as span0:
        pass
    assert span0 is not None
    assert span0.file.endswith("test_span_depth_empirical.py")
    # Lands on `_probed_construct`'s own `capture_span(...)` call line (38),
    # never on this function's `with` call site -- proving depth=0 is wrong.
    assert span0.line == 38

    # depth=1 lands inside contextlib's own trampoline frame.
    with _probed_construct(probe_depth=1) as span1:
        pass
    assert span1 is not None
    assert "contextlib" in span1.file
