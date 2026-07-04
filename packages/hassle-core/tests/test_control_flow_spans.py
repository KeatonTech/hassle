"""M1 actions/control-flow work item, item 6: span tests pinning file:line for
actions recorded inside nested contexts (if inside repeat inside choose, and
if/then/else at one level).

`CompileResult.spans_for(obj, "actions")` returns the *top-level* action-list
spans (per docs/m1-internal-api.md §2: "For M1-core, spans are tracked per
top-level block"). Every construct in this module is itself a top-level
action (the `if`/`choose`/`repeat`/`parallel` container), so its span must
point at its own `with construct(...):` line -- not at any of its nested
children's lines, and not at contextlib/compiler internals.
"""

from __future__ import annotations

from pathlib import Path

from hassle.compiler import compile_bundle

DSL_DIR = Path(__file__).resolve().parents[3] / "fixtures" / "dsl"


def test_if_then_else_top_level_span_points_at_with_if_then_line() -> None:
    result = compile_bundle(DSL_DIR / "if_then_else" / "bundle")
    obj = result.objects["automation:thermostat_if_then"]
    spans = result.spans_for(obj, "actions")
    assert len(spans) == 1
    # thermostat.py: `with if_then(...):` is line 13.
    assert spans[0].file.endswith("thermostat.py")
    assert spans[0].line == 13


def test_deep_nesting_top_level_span_points_at_with_choose_line() -> None:
    result = compile_bundle(DSL_DIR / "deep_nesting" / "bundle")
    obj = result.objects["automation:deep_nesting"]
    spans = result.spans_for(obj, "actions")
    assert len(spans) == 1
    # nested.py: the outermost `with choose() as c:` is line 15 -- not the
    # `repeat_count`/`if_then` lines nested inside it (17/18).
    assert spans[0].file.endswith("nested.py")
    assert spans[0].line == 15


def test_nested_container_spans_never_leak_compiler_internals() -> None:
    # Every construct's own span must land in the user's bundle file, never in
    # contextlib or hassle -- the exact bug the depth=2 empirical check
    # guards against.
    cases = ("if_then_else", "choose_action", "repeat_count", "parallel_action", "deep_nesting")
    for case in cases:
        result = compile_bundle(DSL_DIR / case / "bundle")
        for obj in result.objects.values():
            for span in result.spans_for(obj, "actions"):
                assert "contextlib" not in span.file
                assert "hassle" not in span.file
                assert span.file.endswith(".py")
