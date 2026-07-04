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
from hassle_dev.goldens import find_dsl_dir, run_goldens


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
    # DSL↔IR golden pairs live under fixtures/dsl/. Each pair is `compile(bundle) ==
    # expected_ir.json`; --update recompiles and rewrites them (R3: goldens change
    # only through this command, and the PR must show the diff).
    dsl_dir: Path | None = args.dsl or find_dsl_dir()
    if dsl_dir is None or not dsl_dir.is_dir():
        print("goldens: could not locate fixtures/dsl/ (pass --dsl DIR)")
        return 2

    report = run_goldens(dsl_dir, update=args.update)
    if args.update:
        print(f"goldens: checked {report.checked} pair(s) in {dsl_dir}")
        if report.updated:
            print(f"  updated: {report.updated}")
        else:
            print("  all goldens already up to date")
        return 0

    print(f"goldens: checked {report.checked} pair(s) in {dsl_dir}")
    if report.drifted:
        print("\nGOLDEN DRIFT (run `hassle-dev goldens --update` and review the diff):")
        for name in report.drifted:
            print(f"  {name}")
        return 1
    print("goldens up to date ✓")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hassle-dev")
    sub = parser.add_subparsers(dest="command", required=True)

    p_stats = sub.add_parser("corpus-stats", help="report fixture-corpus coverage")
    p_stats.add_argument("--configs", type=Path, default=None, help="path to fixtures/configs")
    p_stats.set_defaults(func=_cmd_corpus_stats)

    p_gold = sub.add_parser("goldens", help="check or update DSL↔IR golden pairs")
    p_gold.add_argument("--update", action="store_true", help="regenerate goldens in place")
    p_gold.add_argument("--dsl", type=Path, default=None, help="path to fixtures/dsl")
    p_gold.set_defaults(func=_cmd_goldens)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
