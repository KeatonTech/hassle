# Hassle

[![CI](https://github.com/KeatonTech/hassle/actions/workflows/ci.yml/badge.svg)](https://github.com/KeatonTech/hassle/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)

**H**ome **A**ssistant **S**cript **S**ync for **L**ocal **E**diting —
Terraform for your home automations.

Bring your Home Assistant automations, scripts, and helpers under version control —
as a typed, testable Python DSL that compiles to native HA config, syncs both ways,
and never writes a YAML file behind HA's back.

```python
from hassle import automation, delay, only_if, state, sun, when
from hassle.registry import entities as e

@automation(
    id="hall_light_on_motion",
    alias="Hallway: light on motion",
    mode="restart",
    triggers=[state(e.binary_sensor.hall_motion).to("on")]
)
def hall_light_on_motion():
    with only_if(e.input_boolean.guest_mode.state == "off"):
        with only_if(sun(after="sunset", after_offset="-00:30:00")):
            e.light.hallway.turn_on(brightness_pct=60)
            delay(minutes=5)
            e.light.hallway.turn_off()
```

(`e` is the generated, typed entity registry — Pylance autocompletes your real
entity ids and flags typos before anything runs.)

This compiles to exactly the JSON Home Assistant's own UI would save — pull it,
edit it, test it, push it back, and the UI can still edit it too.

## Why

- **Never lose UI-editability:** every write goes through the same config
  APIs the HA frontend uses. No custom YAML packages, no shadow config. Delete
  Hassle entirely and every automation it manages keeps working exactly as-is.
- **Python, not YAML-with-`{{ }}`-strings.** Here is "light on motion, but only
  when it's dark enough" in HA's YAML:

  ```yaml
  condition:
    - condition: template
      value_template: "{{ (states('sensor.hall_lux') | float(999)) < 30 }}"
  ```

  and in Hassle:

  ```python
  from hassle import automation, only_if, state, when
  from hassle.registry import entities as e

  @automation(id="hall_night_light", triggers=[state(e.binary_sensor.hall_motion).to("on")])
  def hall_night_light():
      with only_if(e.sensor.hall_lux.state < 30):  # a typed comparison, not a quoted template
          e.light.hallway.turn_on(brightness_pct=40)
  ```

  No quoting layers, no `| float(999)` fallback rituals, and mistakes fail at
  compile time: a native Python `if` on a live entity state is a compile error
  with a fix hint, not a bug you discover three weeks later.
- **Real tests, in git, forever:** a deterministic simulator (fake clock, no real
  devices, no network) runs your automations' logic in milliseconds. Tests live in
  `tests/`, tracked by the same git history as the automations they cover.
- **Full-state sync, not one-way export:** `hassle pull`/`hassle plan`/`hassle push`
  do a three-way merge (bundle ↔ `manifest.lock` ↔ live HA) — UI edits, local edits,
  and deletions are all detected and never silently clobbered.

See [`DESIGN.md`](DESIGN.md) for the full design (goals table, invariants, DSL
reference, sync semantics). Each package under [`packages/`](packages/) has its
own README describing what is — and is not — in its scope. Curious how it was
built? The project was implemented test-first, milestone by milestone, largely
by AI coding agents — the original plan and its acceptance contracts are
preserved in [`docs/history/`](docs/history/).

## Install

```sh
uv tool install "git+https://github.com/KeatonTech/hassle#subdirectory=packages/hassle-cli"
```

That tracks `main`; append `@v0.1.0` to the URL fragment's repo part to pin a
release instead. `uv` resolves the sibling `hassle-core` package from the same
repo checkout automatically — no extra index or `--find-links` needed. Not on
PyPI yet, so this is an install-from-git tool for now; `pipx` works too, same
syntax.

Requires Python 3.12+. No Home Assistant add-on, no Supervisor, no second
listening service — just this CLI talking to your HA instance's own REST/WebSocket
API with a long-lived access token, same trust model as any other HA client.

## Quickstart (the 6-command demo)

```sh
mkdir my-house && cd my-house
hassle init                                  # scaffold the bundle + AGENTS.md/docs/
hassle login --url http://homeassistant.local:8123   # prompts for the token (hidden input)
hassle pull                                  # adopt everything currently in HA
git add -A && git commit -m "sync: initial pull"

# ...edit the pulled *.py files, add a tests/*.py, whatever you want to change...

hassle validate && hassle test               # offline: compile + lint + simulate
hassle push --yes                            # plan -> apply to HA -> manifest.lock updated
git add -A && git commit -m "push: <what you changed>"
```

That's `init`, `login`, `pull`, `validate`, `test`, `push` — six `hassle` commands,
one working bundle, fully round-trippable (a second `hassle pull` on a clean tree
is a no-op). This exact loop is scripted as a CI-run regression test
(`packages/hassle-cli/tests/test_quickstart_demo.py`), not just a README claim.

Get a long-lived access token from HA: **Profile → Security → Long-Lived Access
Tokens**. `hassle login` prompts for it with hidden input (never echoed, never on
the command line, so it can't land in shell history or another local user's `ps`
output) — or set the `HASSLE_TOKEN` env var for scripts/CI; `--token <value>` still
works too, but only the prompt/env-var forms avoid putting the token in argv. It's
stored in your OS keychain (`keyring`), never written into the bundle — `hassle
doctor` scans for one accidentally committed anyway.

## What you get in a bundle

```
my-house/
├── hassle.toml              # HA URL (never the token), bundle_format, ignore globs
├── lighting.py  security.py  misc.py  ...    # your DSL sources, one file per category
├── lib/                     # shared helpers imported by your DSL sources
├── tests/                   # pytest files against the deterministic simulator
├── typings/                 # generated .pyi -- Pylance autocompletion/typo-catching,
│                             # zero editor configuration (.vscode/settings.json included)
├── .hassle/                 # manifest.lock, registry.json -- machine state, never hand-edit
├── AGENTS.md                 # generated: the workflow contract + hard rules for AI agents
└── docs/DSL.md, docs/COOKBOOK.md   # generated reference + 20+ working recipes
```

Source files are named after your
[HA categories](https://www.home-assistant.io/docs/organizing/categories/)
(`hassle pull` creates them on demand; uncategorized objects land in
`misc.py`), and subdirectories work too — the bundle loader recurses.

- **`AGENTS.md`** and **`docs/`** are regenerated by `hassle init`/`hassle pull` every
  time, so a bundle's own agent docs never drift behind the CLI version that reads
  them. See [`docs/DSL.md`](docs/DSL.md) (every DSL construct, sourced directly
  from real compiled golden pairs — it cannot describe behavior the compiler
  doesn't have) and [`docs/COOKBOOK.md`](docs/COOKBOOK.md) (22 complete recipes,
  each a real automation with a passing simulator test, checked in CI).
- **VS Code**: typed autocompletion needs no extension at all — the generated
  stubs give Pylance everything. A thin optional extension (`vscode-extension/`,
  private install for now, see its own README) adds Problems-pane diagnostics
  from `hassle validate --json` and a "show compiled YAML" panel.

## Feature overview

| Command | What it does |
|---|---|
| `hassle init` | Scaffold a fresh bundle: dirs, `hassle.toml`, `AGENTS.md`/`docs/`, `.vscode/settings.json`, a CI workflow template, optional `git init`. |
| `hassle login` | Validate a long-lived token against HA and store it in the system keyring. |
| `hassle pull` | Three-way merge, driven from HA's side: splice UI edits into your files, adopt UI-created objects, drop UI-deleted ones. **Never writes to HA.** Requires a clean git tree by default. |
| `hassle status` | Plan preview + git status in one view. |
| `hassle plan` | Preview exactly what `push` would do, with DSL-level 3-way diffs for conflicts. |
| `hassle push` | Plan → confirm → apply to HA, in dependency order (helpers → scripts → automations), with pre-write hash re-verification and rollback on failure. |
| `hassle validate [--json]` | Offline: compile + entity/service/area/label reference checks (with did-you-mean) + Jinja lint. `--json` is the editor-integration contract. |
| `hassle test` | Run your bundle's `tests/` against the deterministic simulator (fake clock, no network, no real devices). |
| `hassle run <target>` | Fire one automation directly — on the simulator, or `--live` against real HA (shadow-deployed, traced, cleaned up). |
| `hassle explain <key>` / `hassle render <template>` | Show compiled YAML for one object / render a Jinja template offline. |
| `hassle stubs [--refresh]` | Regenerate the typed `.pyi` stubs from the registry snapshot. |
| `hassle fmt` | Run `ruff format` over the bundle's Python sources. |
| `hassle doctor` | Committed-secret scan, orphaned shadow-automation sweep, HA tested-version-range check. |

The DSL covers: automations; scripts (with typed `fields`); every helper type
HA stores as a collection (`input_boolean`, `input_number`, `input_text`,
`input_select`, `input_datetime`, `input_button`, `counter`, `timer`,
`schedule`); reusable logic via `@macro` (inlined at compile time) and
`@shared_script` (compiles to a real HA script); every classic trigger and
condition type; the purpose-based triggers HA introduced in 2026.7 (e.g.
`motion.detected`); full control flow (`if`/`choose`/`repeat`/`parallel`/
`wait`); a typed Jinja expression builder with math and datetime helpers; and
blueprint automations. Anything the typed surface can't express still compiles,
through a `raw_*` escape hatch, instead of being rejected — **any config HA can
store, Hassle can manage**. The honest-status section below lists the four
shapes that stay `raw_*` today.

## Honest status

This is a from-scratch v1, built test-first against a real fixture corpus and (for
the sync engine and live-run flow) a real, Dockerized Home Assistant. It is not
a 1.0 in the "battle-tested by a community" sense yet — the author's own home is
the first real deployment.

**What's solid:**
- The IR/compiler/decompiler round-trip is the most heavily tested part of the
  codebase: `compile(decompile(x)) == x` for every fixture in the corpus, no
  exceptions, verified on a real 2026.7 HA export (101 objects) during the
  decompiler's coverage-hardening passes (`docs/internals/ha-api-notes.md` §19-21).
- The sync engine (plan/apply/conflict detection) is table-driven directly off the
  design doc's plan-semantics table, plus a 1,000-iteration fuzz test proving no
  edit is ever silently lost.
- The simulator's trigger/mode semantics (`restart` cancelling a pending `delay`,
  the canonical motion-light bug; `numeric_state` firing only on the cross, not
  while already past threshold; etc.) are the actual behavior spec, not an
  afterthought — ~100 small tests pin them down individually.

**Four cases stay `raw_*` by design** (tracked as a CI artifact,
`hassle-dev decompile-coverage`, gate: ≥ 90% of corpus objects decompile with zero
`raw_*` nodes — currently 95.3%):
1. **Device triggers** (`device_trigger_raw`) — no stable cross-integration schema
   to build a typed builder against.
2. **Device conditions** — same reason.
3. **The ancient inline single-trigger automation form** (bare `platform`/`entity_id`/
   `to` at the automation's top level, no `trigger:`/`triggers:` wrapper at all) —
   no `@automation` shape can express fields outside its own option set; this whole
   object falls back to `raw_automation`.
4. **A templated `delay:`** (the stored value is a Jinja string, not a fixed
   duration) — the typed `delay()` builder only accepts int/str/dict duration
   forms; a runtime-templated delay falls back to `raw_action`.

None of these lose data (the round-trip guarantee holds via the `raw_*` escape
hatch); they just don't
get a pretty typed builder. If you hit one, `hassle explain <key>` shows you
exactly what's stored.

**What's out of scope for v1** (see `DESIGN.md` §1's non-goals and §13's
designed-for-later plugin list): YAML-only configuration (packages, Lovelace YAML
mode), config-entry helpers (template sensors, threshold, derivative — these use
HA's config-flow API, not storage collections), scenes, dashboards, multi-user
concurrent editing beyond conflict *detection* (no merge editor), and a Home
Assistant add-on (proven unnecessary by design, §13 — everything here is a laptop
CLI talking straight to HA's own APIs).

**No PyPI publishing yet** — install-from-git only, until a first tagged release.

## Development

```sh
uv sync                       # install the workspace (hassle-core, hassle-cli, hassle-dev)
uv run pytest -m "not integration"   # unit suite (never touches the network)
uv run ruff format --check . && uv run ruff check .
uv run pyright                # strict on hassle-core
uv run hassle-dev corpus-stats       # fixture-corpus contract
uv run hassle-dev goldens            # DSL<->IR golden pairs unchanged
uv run hassle-dev docs               # docs/DSL.md + docs/COOKBOOK.md gates (>= 20 recipes)
```

Integration tests (`-m integration`) need a real Home Assistant instance
(`HASSLE_TEST_HA_URL`/`HASSLE_TEST_HA_TOKEN`) — CI runs them against Docker
`stable` and `dev` images; see `.github/workflows/ci.yml`.

The code examples in this README are executed by
`packages/hassle-cli/tests/test_readme_examples.py` — the DSL example is
compiled and run on the simulator, and every documented CLI command is checked
against the real command tree, so the README cannot drift from the code.

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the engineering rules (tests
first, golden-file discipline, compatibility contracts, error-message style)
and the full set of verification gates.

## Security

Your HA token lives in your OS keyring, never in the bundle. Note that a
bundle is executable Python, and that a committed bundle contains webhook IDs
(which are bearer secrets) and a full map of your home — read
[`SECURITY.md`](SECURITY.md) before publishing a bundle repository, and to
report a vulnerability.

## License

[MIT](LICENSE).
