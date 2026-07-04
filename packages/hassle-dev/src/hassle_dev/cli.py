"""`hassle-dev` — internal developer CLI.

Subcommands:
  corpus-stats   Report fixture-corpus construct coverage; enforce the M0 contract.
  goldens        Manage golden files (DSL↔IR pairs land in M1; M0 is the baseline).
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from hassle_dev.corpus import analyze, find_configs_dir


def _cmd_corpus_stats(args: argparse.Namespace) -> int:
    configs_dir: Path | None = args.configs or find_configs_dir()
    if configs_dir is None or not configs_dir.is_dir():
        print("corpus-stats: could not locate fixtures/configs/ (pass --configs DIR)")
        return 2

    report = analyze(configs_dir)
    print(f"corpus: {report.total} fixtures in {configs_dir}")
    for kind, count in sorted(report.by_kind.items()):
        print(f"  {kind:>18}: {count}")
    print(f"  triggers        : {len(report.triggers)} distinct")
    print(f"  conditions      : {len(report.conditions)} distinct")
    print(f"  actions         : {sorted(report.actions)}")
    print(f"  repeat variants : {sorted(report.repeat_variants)}")
    print(f"  modes           : {sorted(report.modes)}")
    print(f"  helper domains  : {len(report.helper_domains)}/9")
    print(f"  blueprint       : {report.has_blueprint}")
    print(f"  script fields   : {report.has_script_fields}")

    gaps = report.missing()
    if gaps:
        print("\nCORPUS CONTRACT NOT MET:")
        for label, items in gaps.items():
            print(f"  {label}: missing {items}")
        return 1
    print("\ncorpus contract satisfied ✓")
    return 0


def _cmd_goldens(args: argparse.Namespace) -> int:
    # DSL↔IR golden pairs are introduced in M1 under fixtures/dsl/. M0 ships the
    # command and its check so CI can gate on golden drift from M1 onward (R3).
    root = find_configs_dir()
    dsl_dir = (root.parent / "dsl") if root is not None else Path("fixtures/dsl")
    pairs = sorted(dsl_dir.glob("*/expected_ir.json")) if dsl_dir.is_dir() else []
    verb = "would update" if args.update else "checked"
    print(f"goldens: {verb} {len(pairs)} golden pair(s) in {dsl_dir}")
    if not pairs:
        print("goldens: no golden pairs registered yet (introduced in M1)")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hassle-dev")
    sub = parser.add_subparsers(dest="command", required=True)

    p_stats = sub.add_parser("corpus-stats", help="report fixture-corpus coverage")
    p_stats.add_argument("--configs", type=Path, default=None, help="path to fixtures/configs")
    p_stats.set_defaults(func=_cmd_corpus_stats)

    p_gold = sub.add_parser("goldens", help="check or update golden files")
    p_gold.add_argument("--update", action="store_true", help="regenerate goldens in place")
    p_gold.set_defaults(func=_cmd_goldens)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
