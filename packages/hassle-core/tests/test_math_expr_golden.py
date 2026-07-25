"""`shade_tracks_sun` golden, byte-for-byte against the corpus
fixture (fixtures/configs/automation_math_shade_sun.json).

This pins the builder's exact parenthesization and function-vs-filter choices:
`state_attr(...)` and `cos(...)` render as bare function calls; `round_(...)`
renders as a `| round(0)` filter; the outer product is parenthesized before
the filter is applied.
"""

from __future__ import annotations

import json
from pathlib import Path

from hassle.compiler import compile_bundle

REPO_ROOT = Path(__file__).resolve().parents[3]
DSL_FIXTURES = REPO_ROOT / "fixtures" / "dsl"
CORPUS_FIXTURE = REPO_ROOT / "fixtures" / "configs" / "automation_math_shade_sun.json"


def test_shade_tracks_sun_matches_corpus_fixture_byte_for_byte() -> None:
    result = compile_bundle(DSL_FIXTURES / "shade_tracks_sun" / "bundle")
    obj = result.objects["automation:shade_tracks_sun"].to_ha()

    corpus = json.loads(CORPUS_FIXTURE.read_text(encoding="utf-8"))

    compiled_position = obj["actions"][0]["data"]["position"]
    corpus_position = corpus["action"][0]["data"]["position"]
    assert compiled_position == corpus_position
    assert compiled_position == (
        "{{ (100 * cos(state_attr('sun.sun', 'elevation') * pi / 180)) | round(0) }}"
    )


def test_shade_tracks_sun_full_shape_matches_corpus() -> None:
    result = compile_bundle(DSL_FIXTURES / "shade_tracks_sun" / "bundle")
    obj = result.objects["automation:shade_tracks_sun"].to_ha()
    corpus = json.loads(CORPUS_FIXTURE.read_text(encoding="utf-8"))

    assert obj["triggers"] == [{"trigger": "time_pattern", "minutes": "/5"}]
    assert obj["conditions"] == [
        {
            "condition": "numeric_state",
            "entity_id": "sun.sun",
            "attribute": "elevation",
            "above": 0,
        }
    ]
    assert obj["actions"][0]["action"] == "cover.set_cover_position"
    assert obj["actions"][0]["target"] == {"entity_id": "cover.living_room_shade"}
    assert obj["actions"][0]["data"]["position"] == corpus["action"][0]["data"]["position"]
