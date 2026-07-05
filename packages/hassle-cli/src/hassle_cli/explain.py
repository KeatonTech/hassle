"""`hassle explain <object_key>` / `hassle render <template>`: show compiled
output for a bundle object, or render a Jinja template through the
simulator's template engine subset (DESIGN §11: "Show compiled YAML" panel;
`hassle explain --yaml` is the same data VS Code's panel uses).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from hassle.compiler.bundle import compile_bundle


def compiled_config_for(bundle_root: Path, object_key: str) -> dict[str, Any]:
    result = compile_bundle(bundle_root)
    obj = result.objects.get(object_key)
    if obj is None:
        raise KeyError(
            f"no object with key {object_key!r} in this bundle "
            f"(known keys: {sorted(result.objects)})"
        )
    return obj.to_ha()


def as_yaml(config: dict[str, Any]) -> str:
    return yaml.safe_dump(config, sort_keys=False, allow_unicode=True)


def render_template_offline(template: str) -> str:
    """Render `template` through the simulator's Jinja subset (no live HA
    connection needed) -- covers the common case; `--live` (DESIGN §11 "Layer
    3", stretch) would hit `DirectBackend.render_template` for full fidelity."""
    from hassle.testing.clock import FakeClock
    from hassle.testing.state import StateStore
    from hassle.testing.templates import TemplateEngine

    clock = FakeClock()
    states = StateStore()
    engine = TemplateEngine(states, lambda: clock.now)
    return engine.render(template)
