"""AGENTS.md generator (DESIGN §12).

`generate_agents_md` produces the bundle-specific agent contract: the
edit -> validate -> test -> plan workflow, hard rules (never change `id=`,
never edit `.hassle/`, the `CompileTimeBranchError` teaching text, commit
UI-sync pulls separately, ignore-glob semantics, the helper id/name slug
rule for NEW helpers), and pointers into docs/.
"""

from __future__ import annotations

from hassle.compiler.dashboards.errors import DashboardConditionTypeError
from hassle.compiler.errors import CompileTimeBranchError
from hassle.docs.agents_md import generate_agents_md


def test_contains_workflow_contract() -> None:
    text = generate_agents_md(bundle_name="my-home")
    # edit -> validate -> test -> plan, in that order
    validate_pos = text.index("hassle validate")
    test_pos = text.index("hassle test")
    plan_pos = text.index("hassle plan")
    assert validate_pos < test_pos < plan_pos


def test_contains_never_change_id_rule() -> None:
    text = generate_agents_md(bundle_name="my-home")
    assert "never change" in text.lower() and "`id`" in text.lower().replace("id=", "`id`")
    assert "id=" in text or "`id`" in text


def test_contains_never_edit_hassle_dir_rule() -> None:
    text = generate_agents_md(bundle_name="my-home")
    assert ".hassle/" in text
    assert "never" in text.lower()


def test_contains_compile_time_branch_error_teaching_text() -> None:
    """The AGENTS.md rule about Python `if` being compile-time must quote the
    actual error text an agent will see (not a paraphrase) -- so it can
    pattern-match the error back to this rule."""
    text = generate_agents_md(bundle_name="my-home")
    assert "if_then" in text
    assert "compile time" in text.lower()
    # The actual exception class name should appear so an agent grepping the
    # traceback for it finds this doc.
    assert CompileTimeBranchError.__name__ in text


def test_contains_commit_ui_sync_separately_rule() -> None:
    text = generate_agents_md(bundle_name="my-home")
    lowered = text.lower()
    assert "separate" in lowered or "separately" in lowered
    assert "pull" in lowered and "commit" in lowered


def test_contains_ignore_glob_semantics() -> None:
    text = generate_agents_md(bundle_name="my-home")
    assert "ignore" in text.lower()
    assert "hassle.toml" in text


def test_contains_helper_id_name_slug_rule() -> None:
    text = generate_agents_md(bundle_name="my-home")
    lowered = text.lower()
    assert "helper" in lowered
    assert "slug" in lowered or "id=" in text


def test_contains_bundle_name() -> None:
    text = generate_agents_md(bundle_name="chez-kai")
    assert "chez-kai" in text


def test_is_deterministic() -> None:
    a = generate_agents_md(bundle_name="my-home")
    b = generate_agents_md(bundle_name="my-home")
    assert a == b


def test_points_into_docs_dir() -> None:
    text = generate_agents_md(bundle_name="my-home")
    assert "docs/DSL.md" in text
    assert "docs/COOKBOOK.md" in text


# -- dashboards (dashboards-design.md §10) -----------------------------------


def test_contains_card_and_cond_import_convention() -> None:
    text = generate_agents_md(bundle_name="my-home")
    assert "from hassle import cards as c" in text
    assert "from hassle.cards import cond" in text


def test_contains_compile_time_loop_generates_cards_note() -> None:
    text = generate_agents_md(bundle_name="my-home")
    lowered = text.lower()
    assert "for" in lowered and "compile time" in lowered
    assert "card" in lowered


def test_contains_dashboard_condition_trap_and_error_class() -> None:
    """The automation-vs-dashboard condition trap must name the actual
    exception class (so a session can grep the traceback for this doc) and
    point at the `cond.*` fix."""
    text = generate_agents_md(bundle_name="my-home")
    assert DashboardConditionTypeError.__name__ in text
    assert "cond." in text


def test_contains_third_party_custom_card_rule() -> None:
    text = generate_agents_md(bundle_name="my-home")
    lowered = text.lower()
    assert "raw_card" in text
    assert "third-party" in lowered or "custom" in lowered


def test_contains_dashboard_file_placement_rule() -> None:
    text = generate_agents_md(bundle_name="my-home")
    assert "dashboards/" in text
    assert "one per file" in text.lower()


def test_contains_toolchain_note() -> None:
    """A short note on how the `hassle` CLI itself gets onto PATH -- either a
    pre-PyPI `uv tool install -e` of the CLI package, or (once packaging
    support lands) the bundle's own uv project."""
    text = generate_agents_md(bundle_name="my-home")
    assert "## Toolchain" in text
    lowered = text.lower()
    assert "path" in lowered
    assert "uv tool install -e" in text
    assert "packages/hassle-cli" in text
    assert "bundle" in lowered and "uv project" in lowered
