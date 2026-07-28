"""The `sim` pytest fixture (DESIGN §10.2).

Registered as a ``pytest11`` entry point on the ``hassle-core`` distribution
(see ``packages/hassle-core/pyproject.toml``), so any environment with
hassle-core installed gets the ``sim`` fixture automatically -- "plain
`pytest` works too" (DESIGN §10.2); `hassle test` is just `pytest` with
this plugin, which is already always loaded.

Bundle discovery: walk UP from the test file looking for ``hassle.toml`` --
the same anchor `hassle_cli.config.find_bundle_root` uses for every
subcommand (reimplemented here rather than imported: hassle-core never
depends on hassle-cli, see `tests/test_package_layering.py`). A test module
can override this with the ``@pytest.mark.hassle_bundle(path)`` marker (used
by this repo's own in-tree tests, since the example bundles live under
``fixtures/sim/``, not inside a bundle of their own).

Discovery deliberately does NOT consult pytest's rootdir. It used to -- "one
level above rootdir", on the assumption that pytest roots at the bundle's
``tests/`` directory -- but pytest derives rootdir by walking up from the
invocation args for a config anchor, never from the working directory, and
`hassle init` scaffolds a ``pyproject.toml`` at the *bundle root*
(`hassle_cli.uv_project`), which pytest selects. rootdir was therefore the
bundle root and ``.parent`` the bundle's parent directory, so `sim` compiled
-- i.e. imported and executed -- every unrelated ``.py`` file sitting next to
the bundle (docs/internals/cli.md, "`hassle test`: bundle discovery must
not go through pytest's rootdir").
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from hassle.testing import Simulator, simulate
from hassle.testing.errors import BundleNotFoundError

#: The bundle marker file (`hassle_cli.config.CONFIG_FILENAME`, duplicated
#: here to keep hassle-core free of any hassle-cli import).
CONFIG_FILENAME = "hassle.toml"


def _find_bundle_root(start: Path) -> Path | None:
    """Nearest directory at or above `start` containing `hassle.toml`."""
    here = start.resolve()
    for directory in (here, *here.parents):
        if (directory / CONFIG_FILENAME).is_file():
            return directory
    return None


def _bundle_dir_for(request: pytest.FixtureRequest) -> Path:
    # `request.node` / `Node.get_closest_marker` are loosely typed in pytest's
    # own stubs (Unknown) -- silenced at this one boundary (pyright is strict
    # on hassle-core) rather than throughout the function.
    node = request.node  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
    marker = cast(
        "pytest.Mark | None",
        node.get_closest_marker("hassle_bundle"),  # pyright: ignore[reportUnknownMemberType]
    )
    if marker is not None:
        return Path(str(marker.args[0]))
    test_file = Path(str(request.path))
    root = _find_bundle_root(test_file.parent)
    if root is None:
        raise BundleNotFoundError(str(test_file))
    return root


def pytest_configure(config: pytest.Config) -> None:
    # Without this, the documented override emits `PytestUnknownMarkWarning`
    # in any bundle that doesn't declare the marker itself -- and a bundle
    # scaffolded by `hassle init` declares no markers at all.
    config.addinivalue_line(
        "markers",
        "hassle_bundle(path): simulator tests -- bundle directory the `sim` fixture compiles",
    )


@pytest.fixture
def sim(request: pytest.FixtureRequest) -> Simulator:
    """A fresh :class:`~hassle.testing.Simulator` per test, auto-compiling the bundle."""
    return simulate(_bundle_dir_for(request))
