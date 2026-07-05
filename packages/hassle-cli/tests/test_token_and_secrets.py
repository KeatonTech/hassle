"""MILESTONES M7 test 6: `test_no_token_in_bundle` -- pull refuses/scrubs if a
token appears in `hassle.toml`; doctor flags a committed token.

DESIGN §14: keyring token storage, `HASSLE_TOKEN` env override; `hassle login`
validates via GET /api/config (401 -> clean error with fix); pull refuses a
token found in `hassle.toml`; doctor scans for committed secrets.
"""

from __future__ import annotations

from pathlib import Path


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
