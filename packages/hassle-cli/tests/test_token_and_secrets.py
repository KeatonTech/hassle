"""`test_no_token_in_bundle` -- pull refuses/scrubs if a token appears in
`hassle.toml`; doctor flags a committed token.

DESIGN §14: keyring token storage, `HASSLE_TOKEN` env override; `hassle login`
validates via GET /api/config (401 -> clean error with fix); pull refuses a
token found in `hassle.toml`; doctor scans for committed secrets.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def test_pull_refuses_when_token_found_in_hassle_toml(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    _backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    # Someone accidentally committed a token into hassle.toml.
    with (git_repo / "hassle.toml").open("a", encoding="utf-8") as f:
        f.write('token = "ha_super_secret_long_lived_token_value"\n')

    result = cli(["pull"], cwd=git_repo)
    assert result.exit_code != 0
    assert "token" in result.output.lower()
    assert "keyring" in result.output.lower() or "hassle login" in result.output.lower()


def test_doctor_flags_committed_token_in_bundle(bundle_dir: Path, cli) -> None:
    (bundle_dir / "hassle.toml").write_text(
        'ha_url = "http://homeassistant.local:8123"\n'
        'token = "ha_abcdefghijklmnopqrstuvwxyz0123456789"\n',
        encoding="utf-8",
    )
    result = cli(["doctor"], cwd=bundle_dir)
    assert result.exit_code != 0
    assert "token" in result.output.lower()
    assert "hassle.toml" in result.output


def test_doctor_clean_bundle_has_no_secret_finding(bundle_dir: Path, cli) -> None:
    (bundle_dir / "hassle.toml").write_text(
        'ha_url = "http://homeassistant.local:8123"\n', encoding="utf-8"
    )
    result = cli(["doctor"], cwd=bundle_dir)
    assert result.exit_code == 0, result.output
    assert "committed" not in result.output.lower() or "secret" not in result.output.lower()


def test_login_success_stores_token(tmp_path: Path, cli, monkeypatch) -> None:
    import hassle_cli.token as token_mod

    stored: dict[str, str] = {}
    monkeypatch.setattr(token_mod, "_keyring_set", lambda url, tok: stored.__setitem__(url, tok))

    class _FakeProbe:
        def __init__(self, url: str, token: str) -> None:
            self.url = url
            self.token = token

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr("hassle_cli.commands.login.DirectBackend", _FakeProbe)

    project = tmp_path / "house"
    project.mkdir()
    result = cli(
        ["login", "--url", "http://homeassistant.local:8123", "--token", "good-token"],
        cwd=project,
    )
    assert result.exit_code == 0, result.output
    assert stored.get("http://homeassistant.local:8123") == "good-token"


def test_login_bad_token_gives_clean_401_error(tmp_path: Path, cli, monkeypatch) -> None:
    from hassle.backend.errors import HaAuthError

    class _FailingProbe:
        def __init__(self, url: str, token: str) -> None:
            raise HaAuthError("401 Unauthorized")

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr("hassle_cli.commands.login.DirectBackend", _FailingProbe)

    project = tmp_path / "house"
    project.mkdir()
    result = cli(
        ["login", "--url", "http://homeassistant.local:8123", "--token", "bad-token"], cwd=project
    )
    assert result.exit_code != 0
    assert "401" in result.output or "unauthorized" in result.output.lower()
    assert "token" in result.output.lower()


def test_token_env_override_takes_precedence(tmp_path: Path, cli, monkeypatch) -> None:
    import hassle_cli.token as token_mod

    monkeypatch.setattr(token_mod, "_keyring_get", lambda url: "keyring-token")
    resolved = token_mod.resolve_token(
        "http://homeassistant.local:8123", env={"HASSLE_TOKEN": "env-token"}
    )
    assert resolved == "env-token"


def test_token_falls_back_to_keyring(monkeypatch) -> None:
    import hassle_cli.token as token_mod

    monkeypatch.setattr(token_mod, "_keyring_get", lambda url: "keyring-token")
    resolved = token_mod.resolve_token("http://homeassistant.local:8123", env={})
    assert resolved == "keyring-token"


def test_resolve_token_never_touches_keyring_for_fake_url(monkeypatch) -> None:
    """CI regression (main red for 8 pushes, ubuntu unit job): `fake://` is the
    test-only backend seam (see hassle_cli.backend_factory) -- the token is
    embedded in the URL itself, so resolving it must never consult the OS
    keyring. On headless Linux CI runners there is no keyring backend at all
    and hitting it raises `keyring.errors.NoKeyringError`; macOS Keychain
    masked this locally because it always answers (even with `None`)."""
    import hassle_cli.token as token_mod

    def _boom(url: str) -> str | None:
        raise AssertionError(f"keyring must never be consulted for a fake:// url, got {url!r}")

    monkeypatch.setattr(token_mod, "_keyring_get", _boom)
    resolved = token_mod.resolve_token("fake://some-test-token", env={})
    assert resolved == "some-test-token"


def test_resolve_token_falls_through_to_env_when_keyring_unavailable() -> None:
    """Headless servers (DESIGN §14) are a legit CLI environment: no keyring
    backend installed must not crash `resolve_token` when `HASSLE_TOKEN` is
    set -- it should be used without ever letting the keyring exception
    escape."""
    import keyring.errors as keyring_errors

    import hassle_cli.token as token_mod

    def _raise_no_keyring(url: str) -> str | None:
        raise keyring_errors.NoKeyringError("No recommended backend was available.")

    real_keyring_get = token_mod._keyring_get
    token_mod._keyring_get = _raise_no_keyring  # type: ignore[assignment]
    try:
        resolved = token_mod.resolve_token(
            "http://homeassistant.local:8123", env={"HASSLE_TOKEN": "env-token"}
        )
    finally:
        token_mod._keyring_get = real_keyring_get  # type: ignore[assignment]
    assert resolved == "env-token"


def test_resolve_token_no_keyring_and_no_env_gives_clean_error() -> None:
    """No keyring backend AND no `HASSLE_TOKEN` -- must not leak the raw
    `NoKeyringError` traceback; must raise a what/where/fix `TokenResolutionError`
    naming the headless-server fix (error messages are product surface)."""
    import keyring.errors as keyring_errors

    import hassle_cli.token as token_mod

    def _raise_no_keyring(url: str) -> str | None:
        raise keyring_errors.NoKeyringError("No recommended backend was available.")

    real_keyring_get = token_mod._keyring_get
    token_mod._keyring_get = _raise_no_keyring  # type: ignore[assignment]
    try:
        with pytest.raises(token_mod.TokenResolutionError) as excinfo:
            token_mod.resolve_token_or_raise("http://homeassistant.local:8123", env={})
    finally:
        token_mod._keyring_get = real_keyring_get  # type: ignore[assignment]
    message = str(excinfo.value)
    assert "keyring" in message.lower()
    assert "HASSLE_TOKEN" in message
    assert "http://homeassistant.local:8123" in message


def test_cli_status_against_fake_backend_survives_headless_keyring(
    git_repo: Path, cli, fake_backend, toml_writer, monkeypatch
) -> None:
    """End-to-end version of the CI regression: a `fake://`-backed `hassle
    status` invocation must succeed even when the OS keyring is entirely
    unavailable (simulating the ubuntu unit-test runner)."""
    import keyring.errors as keyring_errors

    def _raise(*_a: object, **_kw: object) -> None:
        raise keyring_errors.NoKeyringError("No recommended backend was available.")

    monkeypatch.setattr("keyring.get_password", _raise)
    monkeypatch.setattr("keyring.set_password", _raise)

    _backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    result = cli(["status"], cwd=git_repo)
    assert result.exit_code == 0, result.output


def _patch_login_probe_and_keyring(monkeypatch) -> dict[str, str]:
    import hassle_cli.token as token_mod

    stored: dict[str, str] = {}
    monkeypatch.setattr(token_mod, "_keyring_set", lambda url, tok: stored.__setitem__(url, tok))

    class _FakeProbe:
        def __init__(self, url: str, token: str) -> None: ...
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr("hassle_cli.commands.login.DirectBackend", _FakeProbe)
    return stored


def test_login_writes_ha_url_into_existing_toml(tmp_path: Path, cli, monkeypatch) -> None:
    # The smoke-test-day regression: login succeeded (keyring only), then pull
    # said "no ha_url configured ... run hassle login first" -- circular.
    _patch_login_probe_and_keyring(monkeypatch)
    bundle = tmp_path / "house"
    bundle.mkdir()
    (bundle / "hassle.toml").write_text(
        '# hassle bundle settings\n# ha_url = "http://homeassistant.local:8123"\n',
        encoding="utf-8",
    )

    result = cli(["login", "--url", "http://ha.lan:8123", "--token", "tok-secret"], cwd=bundle)
    assert result.exit_code == 0, result.output
    content = (bundle / "hassle.toml").read_text(encoding="utf-8")
    assert 'ha_url = "http://ha.lan:8123"' in content
    assert "tok-secret" not in content  # the token NEVER lands in the toml
    assert "# hassle bundle settings" in content  # other lines preserved


def test_login_creates_toml_when_missing(tmp_path: Path, cli, monkeypatch) -> None:
    # login-before-init must also work: no hassle.toml yet -> login creates one.
    _patch_login_probe_and_keyring(monkeypatch)
    bundle = tmp_path / "house"
    bundle.mkdir()

    result = cli(["login", "--url", "http://ha.lan:8123", "--token", "tok-secret"], cwd=bundle)
    assert result.exit_code == 0, result.output
    content = (bundle / "hassle.toml").read_text(encoding="utf-8")
    assert 'ha_url = "http://ha.lan:8123"' in content
    assert "tok-secret" not in content


def test_login_replaces_stale_ha_url(tmp_path: Path, cli, monkeypatch) -> None:
    _patch_login_probe_and_keyring(monkeypatch)
    bundle = tmp_path / "house"
    bundle.mkdir()
    (bundle / "hassle.toml").write_text(
        'mirror = true\nha_url = "http://old-host:8123"\n', encoding="utf-8"
    )

    result = cli(["login", "--url", "http://new-host:8123", "--token", "t"], cwd=bundle)
    assert result.exit_code == 0, result.output
    content = (bundle / "hassle.toml").read_text(encoding="utf-8")
    assert 'ha_url = "http://new-host:8123"' in content
    assert "old-host" not in content
    assert "mirror = true" in content  # unrelated settings preserved
