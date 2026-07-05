"""Command-specific modules that need a stable, monkeypatchable import path
(e.g. `hassle_cli.commands.login.DirectBackend`, patched by tests to avoid a
real network probe)."""
