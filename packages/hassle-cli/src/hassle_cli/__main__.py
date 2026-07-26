"""Entry point for the `hassle` console script.

Click runs with ``standalone_mode=False`` so commands can control their own
exit codes, which also means click does not render its own usage errors --
this wrapper does, so a mistyped flag prints a one-line message instead of a
traceback.
"""

from __future__ import annotations

import click

from hassle_cli.cli import main as _click_main


def main() -> int:
    try:
        return _click_main(standalone_mode=False) or 0
    except click.ClickException as exc:  # includes UsageError (exit code 2)
        exc.show()
        return exc.exit_code
    except click.Abort:
        click.echo("Aborted!", err=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
