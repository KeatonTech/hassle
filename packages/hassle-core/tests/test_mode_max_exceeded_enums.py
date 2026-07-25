"""`Mode`/`MaxExceeded` StrEnum for HA's enumerated `mode:`/`max_exceeded:`
automation/script options.

`StrEnum` IS a `str` subclass: `Mode.RESTART == "restart"` and serializes
identically, so passing an enum member anywhere the DSL accepts `mode=`/
`max_exceeded=` compiles byte-identical to the equivalent plain string. The
decompiler emits the enum member for a recognized value, and falls back to
the raw string for anything else (never fails on an unrecognized future
value).
"""

from __future__ import annotations

from hassle import MaxExceeded, Mode
from hassle.decompiler.codegen import decompile_bundle
from hassle.ir.canonical import sha256_hash
from hassle.ir.models import parse


def test_mode_is_str_subclass_and_equals_plain_string() -> None:
    assert isinstance(Mode.RESTART, str)
    assert Mode.RESTART == "restart"
    assert Mode.SINGLE == "single"
    assert Mode.QUEUED == "queued"
    assert Mode.PARALLEL == "parallel"


def test_max_exceeded_is_str_subclass_and_equals_plain_string() -> None:
    assert isinstance(MaxExceeded.SILENT, str)
    assert MaxExceeded.SILENT == "silent"
    assert MaxExceeded.WARNING == "warning"
    assert MaxExceeded.ERROR == "error"


def _write_bundle(tmp_path, source: str) -> str:
    (tmp_path / "objects.py").write_text(source, encoding="utf-8")
    return str(tmp_path)


def test_enum_mode_compiles_byte_identical_to_plain_string(tmp_path) -> None:
    """Builders accept enum or str, and compiling either produces
    byte-identical IR."""
    from hassle.compiler.bundle import compile_bundle

    enum_source = (
        "from hassle import Mode, MaxExceeded, automation, service\n\n\n"
        '@automation(id="a1", alias="A1", mode=Mode.RESTART, max_exceeded=MaxExceeded.SILENT)\n'
        "def a1():\n"
        '    service("light.turn_on")\n'
    )
    str_source = (
        "from hassle import automation, service\n\n\n"
        '@automation(id="a1", alias="A1", mode="restart", max_exceeded="silent")\n'
        "def a1():\n"
        '    service("light.turn_on")\n'
    )

    enum_dir = tmp_path / "enum_bundle"
    enum_dir.mkdir()
    (enum_dir / "objects.py").write_text(enum_source, encoding="utf-8")
    str_dir = tmp_path / "str_bundle"
    str_dir.mkdir()
    (str_dir / "objects.py").write_text(str_source, encoding="utf-8")

    enum_result = compile_bundle(str(enum_dir))
    str_result = compile_bundle(str(str_dir))

    (enum_obj,) = enum_result.objects.values()
    (str_obj,) = str_result.objects.values()
    assert sha256_hash(enum_obj.to_ha()) == sha256_hash(str_obj.to_ha())
    assert enum_obj.to_ha()["mode"] == "restart"
    assert enum_obj.to_ha()["max_exceeded"] == "silent"


def test_decompiler_emits_mode_enum_for_recognized_value() -> None:
    config = {
        "id": "a1",
        "alias": "A1",
        "mode": "restart",
        "triggers": [],
        "conditions": [],
        "actions": [],
    }
    obj = parse(config, kind="automation")
    source = decompile_bundle({obj.object_key(): obj})
    assert "mode=Mode.RESTART" in source


def test_decompiler_emits_max_exceeded_enum_for_recognized_value() -> None:
    config = {
        "id": "a1",
        "alias": "A1",
        "max_exceeded": "warning",
        "triggers": [],
        "conditions": [],
        "actions": [],
    }
    obj = parse(config, kind="automation")
    source = decompile_bundle({obj.object_key(): obj})
    assert "max_exceeded=MaxExceeded.WARNING" in source


def test_decompiler_falls_back_to_raw_string_for_unrecognized_mode() -> None:
    """An unrecognized future HA value must never fail decompilation --
    it falls back to the raw string, exactly as before this feature existed."""
    config = {
        "id": "a1",
        "alias": "A1",
        "mode": "some_future_mode_value",
        "triggers": [],
        "conditions": [],
        "actions": [],
    }
    obj = parse(config, kind="automation")
    source = decompile_bundle({obj.object_key(): obj})
    assert "mode='some_future_mode_value'" in source or 'mode="some_future_mode_value"' in source
    assert "Mode." not in source


def test_decompiler_falls_back_to_raw_string_for_unrecognized_max_exceeded() -> None:
    config = {
        "id": "a1",
        "alias": "A1",
        "max_exceeded": "some_future_value",
        "triggers": [],
        "conditions": [],
        "actions": [],
    }
    obj = parse(config, kind="automation")
    source = decompile_bundle({obj.object_key(): obj})
    assert (
        "max_exceeded='some_future_value'" in source or 'max_exceeded="some_future_value"' in source
    )
    assert "MaxExceeded." not in source


def test_mode_enum_roundtrips_byte_identical(tmp_path) -> None:
    from hassle.compiler.bundle import compile_bundle

    config = {
        "id": "a1",
        "alias": "A1",
        "mode": "queued",
        "max_exceeded": "error",
        "triggers": [],
        "conditions": [],
        "actions": [],
    }
    obj = parse(config, kind="automation")
    source = decompile_bundle({obj.object_key(): obj})
    bundle_dir = _write_bundle(tmp_path, source)
    result = compile_bundle(bundle_dir)
    (recompiled,) = result.objects.values()
    assert sha256_hash(recompiled.to_ha()) == sha256_hash(obj.to_ha())
