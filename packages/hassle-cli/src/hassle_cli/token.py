"""Token storage and resolution (DESIGN §14).

Resolution order for a given `ha_url` (highest priority first):

1. The `fake://<token>` test-only seam (see `hassle_cli.backend_factory`):
   the token is embedded verbatim in the URL, so this NEVER consults the
   keyring -- there is nothing to look up, and doing so would make every
   fake-backend-driven CLI test depend on a real OS keyring being present.
2. `HASSLE_TOKEN` env var (CI override / headless-server story -- never
   touches the keyring).
3. The OS keyring (macOS Keychain / Secret Service via `keyring`). If no
   keyring backend is installed (headless Linux servers routinely have none),
   this is treated the same as "not found" rather than crashing -- callers
   still get a clean `TokenResolutionError` if nothing else resolved the
   token either.

Never written into the bundle: `hassle.toml` having a `token` key at all is
treated as a committed-secret bug by `pull`/`doctor` (see `hassle_cli.config`
and `hassle_cli.doctor`), not a legitimate storage location.
"""

from __future__ import annotations

import contextlib
import os

_KEYRING_SERVICE = "hassle"
_FAKE_URL_PREFIX = "fake://"


class TokenResolutionError(Exception):
    """No token could be resolved for `ha_url` -- neither `HASSLE_TOKEN` nor
    the OS keyring (which may simply not exist, e.g. a headless Linux
    server) had one. Raised instead of letting `keyring.errors.NoKeyringError`
    (or a plain "no token" state) reach the user as a bare traceback."""

    def __init__(self, ha_url: str, *, keyring_unavailable: bool) -> None:
        self.ha_url = ha_url
        reason = (
            "no system keyring is available on this machine (common on headless/CI Linux hosts)"
            if keyring_unavailable
            else "no token is stored in the system keyring for this URL"
        )
        super().__init__(
            f"hassle: no token found for {ha_url!r} -- {reason} and the `HASSLE_TOKEN` "
            "env var is not set. Fix: on a desktop, run `hassle login --url "
            f"{ha_url}` to store one in the keyring; on a headless server, export "
            "`HASSLE_TOKEN=<your long-lived token>` before running hassle."
        )


def _keyring_get(url: str) -> str | None:
    import keyring

    return keyring.get_password(_KEYRING_SERVICE, url)


def _keyring_set(url: str, token: str) -> None:
    import keyring

    keyring.set_password(_KEYRING_SERVICE, url, token)


def _keyring_delete(url: str) -> None:
    import keyring
    from keyring.errors import PasswordDeleteError

    with contextlib.suppress(PasswordDeleteError):
        keyring.delete_password(_KEYRING_SERVICE, url)


def resolve_token(ha_url: str, *, env: dict[str, str] | None = None) -> str | None:
    """Resolve the token for `ha_url`.

    `fake://<token>` URLs (the test-only backend seam) are resolved from the
    URL itself and never touch the keyring. Otherwise: `HASSLE_TOKEN` env
    override, else the OS keyring -- a missing keyring backend
    (`keyring.errors.NoKeyringError`) is treated as "no token found" here,
    not a crash; `_require_backend_config` (hassle_cli.cli) is what turns a
    `None` result into the user-facing `TokenResolutionError`.
    """
    if ha_url.startswith(_FAKE_URL_PREFIX):
        return ha_url[len(_FAKE_URL_PREFIX) :]

    environ = env if env is not None else os.environ
    env_token = environ.get("HASSLE_TOKEN")
    if env_token:
        return env_token

    import keyring.errors

    try:
        return _keyring_get(ha_url)
    except keyring.errors.NoKeyringError:
        return None


def resolve_token_or_raise(ha_url: str, *, env: dict[str, str] | None = None) -> str:
    """Like `resolve_token`, but raises `TokenResolutionError` (what/where/fix)
    instead of returning `None` when nothing resolved the token.

    This is what `_require_backend_config` (hassle_cli.cli) uses -- it is the
    one place that turns "no token anywhere" into a user-facing error, so the
    what/where/fix message is written once and reused by every CLI command."""
    if ha_url.startswith(_FAKE_URL_PREFIX):
        return ha_url[len(_FAKE_URL_PREFIX) :]

    environ = env if env is not None else os.environ
    if environ.get("HASSLE_TOKEN"):
        return environ["HASSLE_TOKEN"]

    import keyring.errors

    keyring_unavailable = False
    try:
        token = _keyring_get(ha_url)
    except keyring.errors.NoKeyringError:
        keyring_unavailable = True
        token = None
    if token is None:
        raise TokenResolutionError(ha_url, keyring_unavailable=keyring_unavailable)
    return token


def store_token(ha_url: str, token: str) -> None:
    _keyring_set(ha_url, token)


def forget_token(ha_url: str) -> None:
    _keyring_delete(ha_url)
