"""Hassle CLI: the daily-driver tool wiring the compiler, decompiler,
validator, simulator, and sync engine into `hassle init|login|pull|status|
plan|push|validate|test|run|fmt|stubs|explain|render|doctor`.

Framework choice (click, not typer) is documented in
docs/internals/cli.md.
"""

from __future__ import annotations
