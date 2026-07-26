"""Package sources: a bundle source may be a Python PACKAGE, not just a file.

Owner request (2026-07-24): "Right now each file corresponds to a category,
which is somewhat limiting. Expand hassle so that it can work with either a
Python file or a Python *package* -- e.g. an `automatic_hvac` package
containing multiple python files, but they all end up tagged with the
automatic-hvac label."

The contract:

- A ROOT-LEVEL directory holding an ``__init__.py`` is a *category package*.
  Every module inside it (recursively) is attributed to ONE category -- the
  package's own name -- exactly as if every object had been declared in a
  single root-level ``<pkg>.py``.
- ``__init__.py`` is the opt-in marker, and the ONLY discriminator. This is
  what keeps `lib/`, `tests/`, `docs/` and dot-directories working exactly as
  before: they are PEP 420 namespace directories (no ``__init__.py``), so they
  remain uncategorized support code. An existing bundle's behaviour cannot
  change until someone deliberately adds an ``__init__.py``.
- `category_shaped_stem` stays a PURE PATH predicate: it learns about packages
  through an explicit ``package_roots`` argument (computed once, at compile
  time, from the filesystem) rather than by growing a filesystem dependency of
  its own. Omitting the argument reproduces pre-package behaviour byte for
  byte -- which is what every existing caller and test relies on.
"""

from __future__ import annotations

from pathlib import Path

from hassle.compiler.bundle import compile_bundle
from hassle.ir.keys import category_shaped_stem

# --- the predicate ---------------------------------------------------------


def test_package_module_takes_the_package_name_as_its_category() -> None:
    assert (
        category_shaped_stem("automatic_hvac/climate.py", package_roots={"automatic_hvac"})
        == "automatic_hvac"
    )


def test_package_init_itself_is_category_shaped() -> None:
    assert (
        category_shaped_stem("automatic_hvac/__init__.py", package_roots={"automatic_hvac"})
        == "automatic_hvac"
    )


def test_nested_module_inside_a_package_still_takes_the_package_name() -> None:
    # Recursive: depth below the package root does not create sub-categories.
    assert (
        category_shaped_stem("automatic_hvac/rooms/office.py", package_roots={"automatic_hvac"})
        == "automatic_hvac"
    )


def test_a_directory_that_is_not_a_declared_package_is_never_category_shaped() -> None:
    # `lib/` has no __init__.py, so it is not in package_roots -- unchanged.
    assert category_shaped_stem("lib/helpers.py", package_roots={"automatic_hvac"}) is None


def test_omitting_package_roots_reproduces_pre_package_behaviour() -> None:
    # Every pre-existing caller passes nothing; nested paths stay uncategorized.
    assert category_shaped_stem("automatic_hvac/climate.py") is None
    assert category_shaped_stem("hvac.py") == "hvac"


def test_misc_package_is_the_uncategorized_fallback_like_misc_py() -> None:
    assert category_shaped_stem("misc/anything.py", package_roots={"misc"}) is None


def test_root_level_file_is_unaffected_by_package_roots() -> None:
    assert category_shaped_stem("hvac.py", package_roots={"automatic_hvac"}) == "hvac"


# --- compile-time discovery + labelling ------------------------------------


def _write(bundle: Path, rel: str, body: str) -> None:
    path = bundle / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


_AUTOMATION = """
from hassle import automation, service, state, when


@automation(id="{fn}", alias="{name}")
def {fn}():
    when(state("binary_sensor.{fn}").to("on"))
    service("light.turn_on", target={{"entity_id": "light.{fn}"}})
"""


def test_package_modules_all_compile_under_the_package_category(tmp_path: Path) -> None:
    """The owner's shape: one package, several modules, one label."""
    bundle = tmp_path / "bundle"
    _write(bundle, "automatic_hvac/__init__.py", "")
    _write(bundle, "automatic_hvac/climate.py", _AUTOMATION.format(name="Climate", fn="climate"))
    _write(bundle, "automatic_hvac/prompts.py", _AUTOMATION.format(name="Prompts", fn="prompts"))
    _write(bundle, "automatic_hvac/holds.py", _AUTOMATION.format(name="Holds", fn="holds"))

    result = compile_bundle(bundle)

    assert len(result.objects) == 3
    assert result.category_packages == frozenset({"automatic_hvac"})
    for source_path in ("automatic_hvac/climate.py", "automatic_hvac/prompts.py"):
        assert (
            category_shaped_stem(source_path, package_roots=result.category_packages)
            == "automatic_hvac"
        )


def test_support_directories_are_not_category_packages(tmp_path: Path) -> None:
    """`lib/` (no __init__.py) stays uncategorized support code."""
    bundle = tmp_path / "bundle"
    _write(bundle, "lib/helpers.py", "SHARED = 1\n")
    _write(bundle, "hvac.py", _AUTOMATION.format(name="Hvac", fn="hvac"))

    result = compile_bundle(bundle)

    assert result.category_packages == frozenset()


def test_package_and_same_named_module_side_by_side_is_an_error(tmp_path: Path) -> None:
    """Ambiguous: `automatic_hvac.py` and `automatic_hvac/` both claim the
    same category. Product-surface error (what/where/fix), not a silent win."""
    from hassle.compiler.errors import AmbiguousCategorySourceError

    bundle = tmp_path / "bundle"
    _write(bundle, "automatic_hvac.py", _AUTOMATION.format(name="A", fn="a"))
    _write(bundle, "automatic_hvac/__init__.py", "")
    _write(bundle, "automatic_hvac/more.py", _AUTOMATION.format(name="B", fn="b"))

    try:
        compile_bundle(bundle)
    except AmbiguousCategorySourceError as err:
        message = str(err)
        assert "automatic_hvac.py" in message
        assert "automatic_hvac/" in message
    else:  # pragma: no cover - the point of the test
        raise AssertionError("expected AmbiguousCategorySourceError")


# --- parity: a package compiles exactly like the equivalent single file ----


def test_package_and_single_file_produce_identical_ir(tmp_path: Path) -> None:
    """Splitting a file into a package is a pure reorganization: same objects,
    byte-identical compiled IR. This is what makes it safe to split a large
    BrandtCamp file with no behaviour change."""
    single = tmp_path / "single"
    _write(
        single,
        "automatic_hvac.py",
        _AUTOMATION.format(name="Climate", fn="climate")
        + _AUTOMATION.format(name="Prompts", fn="prompts"),
    )

    packaged = tmp_path / "packaged"
    _write(packaged, "automatic_hvac/__init__.py", "")
    _write(packaged, "automatic_hvac/climate.py", _AUTOMATION.format(name="Climate", fn="climate"))
    _write(packaged, "automatic_hvac/prompts.py", _AUTOMATION.format(name="Prompts", fn="prompts"))

    single_result = compile_bundle(single)
    packaged_result = compile_bundle(packaged)

    assert set(single_result.objects) == set(packaged_result.objects)
    for key, obj in single_result.objects.items():
        assert obj.to_ha() == packaged_result.objects[key].to_ha()


def test_package_module_load_order_is_deterministic(tmp_path: Path) -> None:
    """Modules import in sorted order, so compiled output is byte-stable
    regardless of filesystem enumeration order (determinism, CONTRIBUTING §8)."""
    bundle = tmp_path / "bundle"
    _write(bundle, "automatic_hvac/__init__.py", "")
    for name in ("zulu", "alpha", "mike"):
        _write(bundle, f"automatic_hvac/{name}.py", _AUTOMATION.format(name=name, fn=name))

    first = compile_bundle(bundle)
    second = compile_bundle(bundle)

    assert list(first.objects) == list(second.objects)


# --- push-side: a package-sourced object still gets its HA category --------


def test_writeback_resolves_a_package_module_to_the_package_category() -> None:
    """`automatic_hvac/climate.py` must assign the `automatic_hvac` category on
    CREATE, exactly as a root-level `automatic_hvac.py` would -- otherwise
    splitting a file into a package would silently drop objects' categories."""
    from hassle.sync.category_move import local_category_for_source_path

    assert (
        local_category_for_source_path(
            "automation", "automatic_hvac/climate.py", frozenset({"automatic_hvac"})
        )
        == "automatic_hvac"
    )


def test_writeback_without_package_roots_is_unchanged() -> None:
    from hassle.sync.category_move import local_category_for_source_path

    assert local_category_for_source_path("automation", "automatic_hvac/climate.py") is None
    assert local_category_for_source_path("automation", "hvac.py") == "hvac"


def test_category_global_in_a_package_module_validates_against_the_package_name(
    tmp_path: Path,
) -> None:
    """A `CATEGORY` global inside a package module is anchored to the PACKAGE's
    name, not the module's own stem -- so the correct declaration produces no
    `category-slug-mismatch` finding."""
    from hassle.registry.snapshot import RegistrySnapshot
    from hassle.registry.validate import validate_bundle

    bundle = tmp_path / "bundle"
    _write(bundle, "automatic_hvac/__init__.py", "")
    _write(
        bundle,
        "automatic_hvac/climate.py",
        'CATEGORY = "Automatic Hvac"\n' + _AUTOMATION.format(name="Climate", fn="climate"),
    )

    result = compile_bundle(bundle)
    findings = validate_bundle(result, RegistrySnapshot())

    assert [f for f in findings if f.code == "category-slug-mismatch"] == []
