"""Entry point for the `hassle` console script (MILESTONES M7)."""

from __future__ import annotations

from hassle_cli.cli import main as _click_main


def main() -> int:
    return _click_main(standalone_mode=False) or 0


if __name__ == "__main__":
    _click_main()
