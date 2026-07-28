"""`hassle.testing.plugin` duplicates the bundle marker filename.

The `sim` fixture discovers a bundle by walking up to `hassle.toml`, the same
rule `hassle_cli.config.find_bundle_root` implements. It cannot import that
constant: hassle-core is a separate distribution that never depends on
hassle-cli (a bundle installs only `hassle-core` in principle), so the name
is duplicated at `hassle.testing.plugin.CONFIG_FILENAME`.

Duplication is fine; silent drift is not. Renaming the CLI's constant without
the plugin's would leave `sim` hunting for a file the CLI no longer writes,
with every other gate still green. This suite is the only one that may import
both packages, so the parity assertion lives here.
"""

from __future__ import annotations

from hassle.testing.plugin import CONFIG_FILENAME as PLUGIN_CONFIG_FILENAME
from hassle_cli.config import CONFIG_FILENAME as CLI_CONFIG_FILENAME


def test_plugin_and_cli_agree_on_the_bundle_marker_filename() -> None:
    assert PLUGIN_CONFIG_FILENAME == CLI_CONFIG_FILENAME
