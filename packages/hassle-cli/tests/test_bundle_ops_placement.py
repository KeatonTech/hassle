"""Category-first bundle layout: an object with no existing file and no
UI-assigned category lands in the single, shared root-level ``misc.py``,
whatever its kind (automation/script/every helper domain) -- not in a
per-kind tree (``automations/misc.py`` / ``scripts/misc.py`` /
``helpers/misc.py``)."""

from __future__ import annotations

from hassle_cli.bundle_ops import default_source_path


def test_default_source_path_places_automation_under_root_misc() -> None:
    assert default_source_path("automation:hall_light_on_motion") == "misc.py"


def test_default_source_path_places_script_under_root_misc() -> None:
    assert default_source_path("script:movie_time") == "misc.py"


def test_default_source_path_places_helpers_under_root_misc() -> None:
    assert default_source_path("input_boolean:guest_mode") == "misc.py"
    assert default_source_path("counter:door_opens") == "misc.py"
    assert default_source_path("timer:cooldown") == "misc.py"


def test_default_source_path_places_template_helpers_under_root_misc() -> None:
    # Config-entry template-helper domains use the same shared root-level
    # misc placement rule as the nine storage-collection helper domains.
    assert default_source_path("template_number:active_hvac_zones") == "misc.py"
    assert default_source_path("template_sensor:average_temp") == "misc.py"
    assert default_source_path("template_binary_sensor:any_door_open") == "misc.py"
    assert default_source_path("template_select:house_scene") == "misc.py"
