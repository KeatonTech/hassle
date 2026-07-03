"""`hassle-dev` — internal developer CLI.

Stub — subcommands implemented after the M0 test contract is committed red.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hassle-dev")
    parser.add_subparsers(dest="command")
    parser.parse_args(argv)
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
