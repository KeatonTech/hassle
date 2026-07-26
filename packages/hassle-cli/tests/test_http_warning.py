"""Plain-HTTP-to-a-non-private-address warning (DESIGN §14, SECURITY.md
"Use HTTPS").

`hassle_cli.http_warning.plaintext_http_warning` is the pure classifier;
`test_cli_commands.py`-style integration is covered here too, for the two
places DESIGN §14 says must warn: `hassle login` and any command that builds
a backend (`_require_backend_config`, exercised via `hassle status`).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hassle_cli.http_warning import plaintext_http_warning


@pytest.mark.parametrize(
    "url",
    [
        "http://homeassistant.local:8123",
        "http://homeassistant.local",
        "http://my-ha.lan:8123",
        "http://localhost:8123",
        "http://127.0.0.1:8123",
        "http://[::1]:8123",
        "http://10.0.1.5:8123",
        "http://172.16.4.9:8123",
        "http://192.168.1.50:8123",
        "http://169.254.1.2:8123",
    ],
)
def test_no_warning_for_private_or_loopback_http(url: str) -> None:
    assert plaintext_http_warning(url) is None


@pytest.mark.parametrize(
    "url",
    [
        "http://ha.example.com:8123",
        "http://1.2.3.4:8123",  # public-looking literal IP
        "http://mysmarthome.duckdns.org",
    ],
)
def test_warning_for_plain_http_to_public_looking_address(url: str) -> None:
    message = plaintext_http_warning(url)
    assert message is not None
    assert url in message
    assert "cleartext" in message.lower()
    assert "https" in message.lower()


@pytest.mark.parametrize(
    "url",
    [
        "https://ha.example.com:8123",  # https -- never warn regardless of host
        "https://1.2.3.4:8123",
        "fake://some-test-token",  # the test-only backend seam
    ],
)
def test_no_warning_for_https_or_fake_scheme(url: str) -> None:
    assert plaintext_http_warning(url) is None


def test_login_warns_on_plain_http_to_public_address(tmp_path: Path, cli, monkeypatch) -> None:
    import hassle_cli.token as token_mod

    monkeypatch.setattr(token_mod, "_keyring_set", lambda url, tok: None)

    class _FakeProbe:
        def __init__(self, url: str, token: str) -> None: ...
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr("hassle_cli.commands.login.DirectBackend", _FakeProbe)

    project = tmp_path / "house"
    project.mkdir()
    result = cli(
        ["login", "--url", "http://ha.example.com:8123", "--token", "good-token"], cwd=project
    )
    assert result.exit_code == 0, result.output
    assert "cleartext" in result.output.lower()
    assert "https" in result.output.lower()


def test_login_no_warning_for_private_address(tmp_path: Path, cli, monkeypatch) -> None:
    import hassle_cli.token as token_mod

    monkeypatch.setattr(token_mod, "_keyring_set", lambda url, tok: None)

    class _FakeProbe:
        def __init__(self, url: str, token: str) -> None: ...
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
    assert "cleartext" not in result.output.lower()


def test_status_warns_on_plain_http_to_public_address(
    git_repo: Path, cli, fake_backend, monkeypatch
) -> None:
    """`_require_backend_config` is the single choke point behind
    `pull`/`plan`/`status`/`push`/`stubs --refresh`/`run --live` -- exercising
    it via `status` (cheapest to set up) proves every one of them warns."""
    from hassle_cli import backend_factory

    _backend, token = fake_backend
    (git_repo / "hassle.toml").write_text(
        'ha_url = "http://ha.example.com:8123"\nformat_version = 1\n', encoding="utf-8"
    )
    # Route the (non-fake) URL to the same FakeBackend -- status must never
    # touch the network in a unit test. HASSLE_TOKEN supplies the token
    # (env override, checked before the keyring) so this never needs the
    # keyring either.
    real_connect = backend_factory.connect
    monkeypatch.setattr(
        backend_factory, "connect", lambda url, tok: real_connect(f"fake://{token}", tok)
    )

    result = cli(["status"], cwd=git_repo, env={"HASSLE_TOKEN": token})
    assert result.exit_code == 0, result.output
    assert "cleartext" in result.output.lower()
