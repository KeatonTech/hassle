# Hassle documentation

Two audiences, two tiers:

**For users** (people managing their own Home Assistant config with Hassle, or
building on the DSL) — these are also regenerated into every bundle by
`hassle init`/`hassle pull`:

- [DSL.md](DSL.md) — every DSL construct, generated from real compiled golden
  pairs, so it cannot describe behavior the compiler doesn't have.
- [COOKBOOK.md](COOKBOOK.md) — complete, tested recipes (each one is a real
  automation with a passing simulator test, checked in CI).

**For developers of Hassle itself:**

- [internals/](internals/) — per-area design notes (compiler, decompiler,
  backend, sync, CLI), the empirical HA API findings
  ([internals/ha-api-notes.md](internals/ha-api-notes.md), §-numbered and cited
  from code comments), and the three frozen compatibility contracts:
  [internals/ir-format.md](internals/ir-format.md),
  [internals/backend-protocol.md](internals/backend-protocol.md), and
  [internals/dsl-extensions.md](internals/dsl-extensions.md).
- [history/](history/) — the original milestone-driven implementation plan and
  its acceptance contracts, preserved as a record with a vocabulary legend.

The binding engineering rules live in [CONTRIBUTING.md](../CONTRIBUTING.md);
the design doc is [DESIGN.md](../DESIGN.md) at the repo root.
