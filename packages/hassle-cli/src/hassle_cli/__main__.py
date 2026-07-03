"""Entry point stub for the `hassle` CLI.

The real command surface (pull/plan/push/validate/test/run/fmt/stubs/explain/
mirror/doctor) is built in M7. This stub exists so the console script and the
monorepo wiring are exercised by CI from M0 onward.
"""

from __future__ import annotations


def main() -> int:
    print("hassle: CLI not implemented yet (see MILESTONES.md M7).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
