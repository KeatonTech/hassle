# DB0 runbook — completing the dashboards feature with local access

**Audience: a Claude agent (or human) running LOCALLY** — with Docker or a
reachable Home Assistant instance, i.e. the access the remote build
environment did not have. This is the handoff for the one open workstream of
the dashboards feature (PR #46, branch `claude/hassle-dashboard-design-vkbfpk`)
plus its follow-ups. Delete this file in the PR that completes DB0.

Read first, in this order (all binding):

1. [CONTRIBUTING.md](../../CONTRIBUTING.md) — every rule applies to you,
   especially tests-first, every-bug-becomes-a-regression-test, and the
   ha-api-notes recording rule.
2. [dashboards-design.md](dashboards-design.md) — the governing spec. §2 is
   the source-informed HA-API section you are about to verify; §2.2's
   numbered **DB0 list** is your checklist and this runbook expands it.
3. [ha-api-notes.md](ha-api-notes.md) §0 (the verification methodology) and
   §39 (the first dashboards finding, already recorded).

## 0. State of the work

Everything except live verification is DONE, merged, reviewed, and green on
the branch: IR envelope, DSL (47 card builders, `cond`, raw ladder),
compiler, decompiler (91.8% corpus coverage, byte-exact round-trip),
backends, sync/placement, validation, testing API, docs/cookbook. Final
review (DB9) approved after its blocker was fixed. 6,202 unit tests pass.

What is NOT verified: every statement in dashboards-design.md §2 about how
real HA behaves. The code encodes those statements faithfully (FakeBackend
simulates them; integration tests assert them), but no live instance has
confirmed them. Your job is to make §2 true or fix what isn't.

## 1. Environment setup

```sh
git clone <repo> && cd hassle
git checkout claude/hassle-dashboard-design-vkbfpk
uv sync
uv run pytest -m "not integration" -q       # must be green before you start
```

Stand up HA (either works):

- **Docker (the CI pattern):** `docker run -d --name hassle-ha -p 8123:8123
  ghcr.io/home-assistant/home-assistant:stable` — then complete onboarding
  and mint a long-lived token (ha-api-notes §1 documents the flow, including
  the config-wiring gotcha in §1.1). Repeat against `:dev` before merging.
- **A real instance you own:** fine too, but prefer a disposable one — DB0
  creates and deletes dashboards.

```sh
export HASSLE_TEST_HA_URL=http://localhost:8123
export HASSLE_TEST_HA_TOKEN=<long-lived token>
uv run pytest -m integration -q             # the executable half of DB0
```

`tests/integration/test_live_dashboard_crud.py` (4 tests) encodes the core
CRUD hypotheses. A failure there is a FINDING, not a test bug — see §3.

## 2. The verification checklist

Work through dashboards-design.md §2.2's DB0 list. For each item: probe the
live instance (WS commands via `hassle.backend.client.HaClient`, or
`wscat`/`websocat` by hand), capture the raw request/response pair into
`docs/ha-api-captures/` (existing naming conventions), and write the finding
into ha-api-notes.md as new §39.x subsections. Priority order:

1. **`icon: null` persistence (HIGHEST — DB9 BLOCK-1 reachability).**
   `DirectBackend._dashboard_registry_payload` sends explicit `icon: None`
   on every update (to clear a deleted icon — backend-protocol.md §3.2).
   Question: does `lovelace/dashboards/update` with `icon: null` (a) remove
   the key from the stored item, (b) store a literal null, or (c) reject?
   Probe: create a dashboard with an icon, update with `icon: null`, then
   `dashboards/list`. If (b), every iconless dashboard's registry item
   carries `icon: null` after its first Hassle push — the decompiler now
   handles that correctly (raw escalation, DB9 fix), but you should decide
   whether `DirectBackend` should stop sending null and use a different
   clearing mechanism, and whether `storage_canonical` needs a
   comparison-side rule. If (a), also make `FakeBackend.update` model the
   removal so the fakes stay faithful.
2. **`dashboards/update` field schema.** Confirm the allowlist
   `{title, icon, show_in_sidebar, require_admin}` is exactly right and that
   `url_path` is rejected (`invalid_format`). The DB5 fix was built on
   source-reading; confirm against the wire.
3. **`url_path` hyphen rule.** Create with a hyphen-less `url_path` must be
   rejected (this underwrites the `default` identity sentinel, §3.1). Also
   confirm `url_path` charset (the module-name sanitizer assumes slug-ish).
4. **Config opacity / normalization.** Save a config containing legacy
   `tap_action: {action: call-service, service: light.turn_on}`, unknown
   keys at every level, and oddly-ordered keys; read it back. Byte-verbatim?
   If HA materializes ANY defaults, add them to `storage_canonical`'s
   per-kind table (comparison-side only) with tests.
5. **Delete semantics.** `dashboards/delete` — is the `lovelace.<url_path>`
   config store removed too? Recreate the same `url_path` afterward: clean
   slate or resurrected config?
6. **`config_not_found` behaviors.** (a) Never-customized default dashboard
   → confirm `lovelace/config(url_path=null)` errors and Hassle omits it.
   (b) A UI-created but never-edited dashboard: registry item exists, config
   fetch fails — currently invisible to `list_remote` and a local
   declaration collides loudly on create (design §2.2 item). Decide the
   product behavior (likely: adopt with an empty/absent config marker or
   surface a warning) and implement with tests.
7. **YAML-mode default dashboard.** With `lovelace: mode: yaml` in
   configuration.yaml, confirm whether `lovelace/config(url_path=null)`
   serves ui-lovelace.yaml content; if yes, implement the panel-mode probe
   so `list_remote` filters the default the way it already filters
   registry items (I1 — never manage YAML-mode).
8. **View `type` materialization.** Create sections/masonry views in the UI;
   check whether `type:` is stored explicitly or omitted for masonry. The
   DSL handles both (`type=None` ⇒ no key), but the decompiler-canonical
   expectations and fixtures should match what the UI actually writes.
9. **Badges storage.** Confirm modern object badges vs legacy bare strings
   (the corpus has both; `badge()` cannot express the bare-string form —
   ha-api-notes §39 — confirm the UI never writes it anymore, else consider
   a typed spelling instead of the current raw_view escalation).
10. **`cond.not_` wire shape** (design §5.4 note): confirm Lovelace supports
    a `not` condition and its key shape; `energy_sankey`'s `title=` option
    (cards/energy.py docstring); purpose of `dashboards/list` on a fresh
    instance (empty list vs error).
11. **Update convergence, end-to-end.** With the fakes-only gap recorded in
    §2.2 (FakeBackend stores envelopes verbatim; HA merges), run the real
    loop: push a dashboard with icon → delete the icon locally → push →
    pull → assert the manifest converges (no perpetual-update loop). Add an
    integration test for it.

## 3. When reality disagrees with the design

Do NOT silently work around anything (CONTRIBUTING). The loop for each
divergence:

1. Record the finding in ha-api-notes.md (§39.x, with captures).
2. Write the failing regression test first (unit if FakeBackend can model
   it — and update FakeBackend so it CAN; integration otherwise).
3. Fix the code; update dashboards-design.md in the same commit (dated
   "implementation finding" notes are the established pattern — see §3.3,
   §4.1 for examples).
4. If a frozen contract surface changes (ir-format.md, backend-protocol.md,
   dsl-extensions.md): additive-only, same-PR doc update, per CONTRIBUTING.

## 4. The final acceptance run (design §12.1 DB9's deferred half)

On a live instance, the end-to-end loop that proves the feature:

```
hassle pull                      # adopts your instance's dashboards into dashboards/*.py
<edit a dashboard in the HA UI>
hassle pull                      # refresh splices the UI edit into your file
<edit the same dashboard's Python; add a card in a loop>
uv run pytest                    # sim.dashboard() tests
hassle push                      # plan shows exactly your change; apply
<verify in the HA UI>
```

Run it against both `stable` and `dev` images. Byte-stability check: a
second `hassle pull` immediately after any push must be a NOOP plan.

## 5. Ground rules for the local agent

- **Branch/PR:** continue on `claude/hassle-dashboard-design-vkbfpk` —
  pushes update PR #46. DB0 doc/capture/fix commits belong there. If the PR
  merges first, do follow-ups on fresh `fix/`-prefixed branches from main.
- **Gates before every push:** `uv run pytest -m "not integration" -q`,
  `uv run ruff format --check . && uv run ruff check .`, `uv run pyright`,
  `uv run hassle-dev goldens`, `corpus-stats`, `decompile-coverage`
  (≥90% incl. dashboards), `docs` — plus `-m integration` while HA is up.
  Check EXIT CODES, not output tails.
- **Review:** run the `reviewer` subagent (.claude/agents/reviewer.md) on
  your diff before merging anything, per CLAUDE.md.
- **Commit signing:** the remote session's commits are unsigned (its
  signing daemon broke — an environment failure, not a choice). Locally,
  sign normally. A squash-merge of PR #46 resolves the unsigned history.
- **Separate, do NOT fold into this PR:** the pre-existing CWD-relative
  pull-path bug (pull run from a bundle subdirectory writes files relative
  to CWD, not the bundle root — proven end-to-end during review; affects
  `sync/pull_apply.py`/`source_writer.py` generally). One scoped
  `fix/pull-cwd-paths` branch, regression test first.
- **Corpus enrichment (optional, valuable):** `hassle pull` against your
  real household, then contribute anonymized real dashboard configs to
  `fixtures/configs/` (fixture-wrangler conventions, PROVENANCE entries) —
  the current 12 fixtures are hand-built and marked provisional pending
  exactly this.
