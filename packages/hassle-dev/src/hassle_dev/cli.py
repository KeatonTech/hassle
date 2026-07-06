"""`hassle-dev` — internal developer CLI.

Subcommands:
  corpus-stats       Report fixture-corpus construct coverage; enforce the M0 contract.
  goldens            Manage golden files (DSL↔IR pairs land in M1; M0 is the baseline).
  docs               Build/check docs/DSL.md + docs/COOKBOOK.md (MILESTONES M9 tests 1-2).
  acceptance-tasks   Emit the 10 agent-acceptance task prompts for a bundle (MILESTONES M9
                     test 3 -- build only; the orchestrator runs the actual model sessions).
  acceptance-bundle  Generate the sample-house bundle acceptance-tasks' prompts are written
                     against (MILESTONES M9 test 3; see hassle_dev.bundle_gen).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
from collections.abc import Sequence
from pathlib import Path

from hassle_dev.acceptance import emit_tasks
from hassle_dev.bundle_gen import generate_sample_bundle
from hassle_dev.corpus import analyze, find_configs_dir
from hassle_dev.decompile_coverage import run_decompile_coverage
from hassle_dev.docs import find_repo_root, run_docs
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


def _cmd_decompile_coverage(args: argparse.Namespace) -> int:
    configs_dir: Path | None = args.configs or find_configs_dir()
    if configs_dir is None or not configs_dir.is_dir():
        print("decompile-coverage: could not locate fixtures/configs/ (pass --configs DIR)")
        return 2

    out_file: Path = args.out
    exit_code, report = run_decompile_coverage(configs_dir, out_file)
    print(f"decompile-coverage: {report['total_objects']} object(s) analyzed")
    print(f"  clean (zero raw_* nodes): {report['clean_objects']}/{report['total_objects']}")
    print(f"  clean fraction: {report['clean_fraction']:.1%} (gate: 90%)")
    print(f"  report written to {out_file}")
    if report["exceptions"]:
        print("  exceptions:")
        for exc in report["exceptions"]:
            print(f"    {exc['object_key']}: {exc['raw_node_count']} raw_* node(s)")
    if exit_code != 0:
        print("\nDSL COVERAGE GATE NOT MET (< 90%)")
    return exit_code


def _cmd_docs(args: argparse.Namespace) -> int:
    repo_root: Path | None = args.repo_root or find_repo_root()
    if repo_root is None:
        print("docs: could not locate the repo root (pass --repo-root DIR)")
        return 2

    report = run_docs(repo_root, update=args.update)

    if report.missing_dsl_names:
        print(f"docs: MISSING golden pair for {len(report.missing_dsl_names)} name(s):")
        for name in sorted(report.missing_dsl_names):
            print(f"  {name}")

    print(f"docs: cookbook has {report.cookbook_recipe_count} recipe(s) (gate: >= 20)")
    if report.cookbook_recipe_count < 20:
        print("  COOKBOOK GATE NOT MET (< 20 recipes)")

    if report.cookbook_findings:
        print(f"docs: cookbook bundle has {len(report.cookbook_findings)} validation finding(s):")
        for finding in report.cookbook_findings:
            print(f"  {finding}")

    if not report.cookbook_tests_passed:
        print("docs: cookbook simulator tests FAILED:")
        print(report.cookbook_test_output)

    if args.update:
        print("docs: wrote docs/DSL.md and docs/COOKBOOK.md")
        return 0

    if report.dsl_drifted:
        print("docs: docs/DSL.md is stale (run `hassle-dev docs --update`)")
    if report.cookbook_drifted:
        print("docs: docs/COOKBOOK.md is stale (run `hassle-dev docs --update`)")

    if report.ok and report.cookbook_recipe_count >= 20:
        print("docs up to date, all gates satisfied ✓")
        return 0
    return 1


def _cmd_acceptance_tasks(args: argparse.Namespace) -> int:
    bundle_dir: Path = args.bundle
    if not bundle_dir.is_dir():
        print(f"acceptance-tasks: bundle directory not found: {bundle_dir}")
        return 2

    tasks = emit_tasks(bundle_dir)

    if args.json:
        payload = {"tasks": [dataclasses.asdict(t) for t in tasks]}
        print(json.dumps(payload, indent=2))
        return 0

    print(f"acceptance-tasks: {len(tasks)} task(s) for {bundle_dir}")
    for task in tasks:
        print(f"\n[{task.task_id}] ({task.category})")
        print(f"  {task.prompt}")
    return 0


def _cmd_acceptance_bundle(args: argparse.Namespace) -> int:
    out_dir: Path = args.out
    repo_root: Path | None = args.repo_root or find_repo_root()
    if repo_root is None:
        print("acceptance-bundle: could not locate the repo root (pass --repo-root DIR)")
        return 2
    if out_dir.exists() and any(out_dir.iterdir()):
        print(
            f"acceptance-bundle: {out_dir} already exists and is not empty. "
            "Fix: remove it first (this command never merges into an existing bundle)."
        )
        return 2

    generate_sample_bundle(out_dir, repo_root=repo_root)
    print(f"acceptance-bundle: wrote the sample-house bundle to {out_dir}")
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

    p_cov = sub.add_parser(
        "decompile-coverage", help="report/gate DSL-coverage over fixtures/configs"
    )
    p_cov.add_argument("--configs", type=Path, default=None, help="path to fixtures/configs")
    p_cov.add_argument(
        "--out", type=Path, required=True, help="path to write the JSON coverage report"
    )
    p_cov.set_defaults(func=_cmd_decompile_coverage)

    p_docs = sub.add_parser(
        "docs", help="build/check docs/DSL.md + docs/COOKBOOK.md (MILESTONES M9)"
    )
    p_docs.add_argument("--update", action="store_true", help="write docs/*.md in place")
    p_docs.add_argument("--repo-root", type=Path, default=None, help="path to the repo root")
    p_docs.set_defaults(func=_cmd_docs)

    p_acc = sub.add_parser(
        "acceptance-tasks",
        help="emit the 10 agent-acceptance task prompts for a bundle (MILESTONES M9 test 3)",
    )
    p_acc.add_argument("--bundle", type=Path, required=True, help="path to the bundle directory")
    p_acc.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    p_acc.set_defaults(func=_cmd_acceptance_tasks)

    p_bundle = sub.add_parser(
        "acceptance-bundle",
        help="generate the sample-house bundle acceptance-tasks' prompts are written against",
    )
    p_bundle.add_argument(
        "--out", type=Path, required=True, help="directory to write the bundle to"
    )
    p_bundle.add_argument("--repo-root", type=Path, default=None, help="path to the repo root")
    p_bundle.set_defaults(func=_cmd_acceptance_bundle)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
