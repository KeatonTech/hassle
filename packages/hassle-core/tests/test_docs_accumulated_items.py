"""M9 "accumulated doc items" (field-hardening phase): things learned during
M2-M7 that must be folded into generated docs where users/agents will see
them, not left buried in code comments.

- upgrade-can-surface-one-time-modernization-diffs (plan labeling context)
- validator coverage boundaries (validate.py's docstring, verbatim intent)
- expression sugar is one-way (decompiler keeps Jinja as `template(...)`)
- scripts-as-functions rules (when a call rewrites vs. stays `service()`)
- category-based file placement + file organization is user-controlled after
  adoption
"""

from __future__ import annotations

from pathlib import Path

from hassle.docs.agents_md import generate_agents_md
from hassle.docs.dsl_reference import generate_dsl_reference

REPO_ROOT = Path(__file__).resolve().parents[3]
DSL_FIXTURES = REPO_ROOT / "fixtures" / "dsl"


def test_agents_md_mentions_modernization_diffs() -> None:
    text = generate_agents_md(bundle_name="my-home")
    lowered = text.lower()
    assert "modernization" in lowered
    assert "one-time" in lowered or "one time" in lowered


def test_agents_md_mentions_file_organization_is_user_controlled() -> None:
    text = generate_agents_md(bundle_name="my-home")
    lowered = text.lower()
    assert "category" in lowered
    assert "user-controlled" in lowered or "user controlled" in lowered


def test_dsl_reference_documents_one_way_expression_sugar() -> None:
    text = generate_dsl_reference(DSL_FIXTURES)
    lowered = text.lower()
    assert "one-way" in lowered or "one way" in lowered
    assert "template(" in text


def test_dsl_reference_documents_script_call_rewrite_rule() -> None:
    text = generate_dsl_reference(DSL_FIXTURES)
    lowered = text.lower()
    assert "shared_script" in lowered
    assert "service(" in text


def test_dsl_reference_includes_validator_coverage_boundaries() -> None:
    """Sourced from validate.py's own docstring section (verbatim intent, not
    re-derived) so it can't drift from the real permissiveness rules."""
    text = generate_dsl_reference(DSL_FIXTURES)
    lowered = text.lower()
    assert "empty `fields: {}`" in text.lower().replace("fields:{}", "fields: {}") or (
        "empty" in lowered and "fields" in lowered
    )
    assert "entity_id" in text
