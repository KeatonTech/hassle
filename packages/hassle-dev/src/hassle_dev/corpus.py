"""Corpus discovery + construct-coverage analysis for `hassle-dev corpus-stats`.

This enforces the corpus contract in CI: at least 40 fixtures, and every
required HA construct represented at least once.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HELPER_DOMAINS: tuple[str, ...] = (
    "input_boolean",
    "input_number",
    "input_select",
    "input_text",
    "input_datetime",
    "input_button",
    "counter",
    "timer",
    "schedule",
)

MIN_FIXTURES = 40

# Required construct coverage (the corpus deliverable checklist).
REQUIRED_TRIGGERS: tuple[str, ...] = (
    "state",
    "numeric_state",
    "time",
    "time_pattern",
    "sun",
    "event",
    "zone",
    "template",
    "webhook",
    "device",
    "mqtt",
    "calendar",
    "persistent_notification",
    "geo_location",
    "homeassistant",
    "tag",
)
REQUIRED_CONDITIONS: tuple[str, ...] = (
    "state",
    "numeric_state",
    "time",
    "sun",
    "zone",
    "template",
    "device",
    "and",
    "or",
    "not",
    "trigger",
)
REQUIRED_ACTIONS: tuple[str, ...] = (
    "choose",
    "if",
    "parallel",
    "wait_template",
    "wait_for_trigger",
    "stop",
    "variables",
)
REQUIRED_REPEAT_VARIANTS: tuple[str, ...] = ("count", "while", "until", "for_each")
REQUIRED_MODES: tuple[str, ...] = ("single", "restart", "queued", "parallel")


def _kind_for(stem: str) -> str:
    if stem.startswith("automation"):
        return "automation"
    if stem.startswith("script"):
        return "script"
    if stem.startswith("dashboard"):
        return "dashboard"
    if stem.startswith("helper_"):
        rest = stem[len("helper_") :]
        for dom in sorted(HELPER_DOMAINS, key=len, reverse=True):
            if rest == dom or rest.startswith(dom + "_"):
                return dom
        raise ValueError(f"cannot determine helper domain from fixture name {stem!r}")
    raise ValueError(f"cannot determine object kind from fixture name {stem!r}")


def find_configs_dir(start: Path | None = None) -> Path | None:
    """Walk up from ``start`` (or cwd) looking for ``fixtures/configs``."""
    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        configs = candidate / "fixtures" / "configs"
        if configs.is_dir():
            return configs
    return None


def _walk(node: Any) -> Any:
    """Yield every dict and list encountered anywhere in ``node``."""
    stack = [node]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            yield cur
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)


def _trigger_platform(item: dict[str, Any]) -> str | None:
    # HA accepts both legacy `platform:` and new `trigger:` keys.
    value = item.get("platform", item.get("trigger"))
    return value if isinstance(value, str) else None


@dataclass
class CoverageReport:
    total: int = 0
    by_kind: Counter[str] = field(default_factory=Counter)
    triggers: set[str] = field(default_factory=set)
    conditions: set[str] = field(default_factory=set)
    actions: set[str] = field(default_factory=set)
    repeat_variants: set[str] = field(default_factory=set)
    modes: set[str] = field(default_factory=set)
    helper_domains: set[str] = field(default_factory=set)
    has_blueprint: bool = False
    has_script_fields: bool = False

    def missing(self) -> dict[str, list[str]]:
        gaps: dict[str, list[str]] = {}
        if self.total < MIN_FIXTURES:
            gaps["fixtures"] = [f"have {self.total}, need >= {MIN_FIXTURES}"]
        for label, required, present in (
            ("triggers", REQUIRED_TRIGGERS, self.triggers),
            ("conditions", REQUIRED_CONDITIONS, self.conditions),
            ("actions", REQUIRED_ACTIONS, self.actions),
            ("repeat_variants", REQUIRED_REPEAT_VARIANTS, self.repeat_variants),
            ("modes", REQUIRED_MODES, self.modes),
            ("helper_domains", HELPER_DOMAINS, self.helper_domains),
        ):
            absent = [x for x in required if x not in present]
            if absent:
                gaps[label] = absent
        if not self.has_blueprint:
            gaps["blueprint"] = ["no blueprint-based automation fixture"]
        if not self.has_script_fields:
            gaps["script_fields"] = ["no script fixture with `fields:`"]
        return gaps

    def ok(self) -> bool:
        return not self.missing()


def analyze(configs_dir: Path) -> CoverageReport:
    report = CoverageReport()
    for path in sorted(configs_dir.glob("*.json")):
        kind = _kind_for(path.stem)
        config = json.loads(path.read_text(encoding="utf-8"))
        report.total += 1
        report.by_kind[kind] += 1
        if kind in HELPER_DOMAINS:
            report.helper_domains.add(kind)
        if kind == "script" and isinstance(config.get("fields"), dict):
            report.has_script_fields = True

        # Triggers (only the object's own trigger blocks, incl. legacy/new keys).
        for key in ("trigger", "triggers"):
            block = config.get(key)
            items = block if isinstance(block, list) else [block]
            for item in items:
                if isinstance(item, dict):
                    platform = _trigger_platform(item)
                    if platform:
                        report.triggers.add(platform)

        for node in _walk(config):
            if "use_blueprint" in node:
                report.has_blueprint = True
            cond = node.get("condition")
            if isinstance(cond, str):
                report.conditions.add(cond)
            mode = node.get("mode")
            if isinstance(mode, str) and mode in REQUIRED_MODES:
                report.modes.add(mode)
            for action_key in REQUIRED_ACTIONS:
                if action_key in node:
                    report.actions.add(action_key)
            if "repeat" in node and isinstance(node["repeat"], dict):
                for variant in REQUIRED_REPEAT_VARIANTS:
                    if variant in node["repeat"]:
                        report.repeat_variants.add(variant)
    return report
