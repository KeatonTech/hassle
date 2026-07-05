"""Token storage and resolution (DESIGN §14).

Resolution order for a given `ha_url` (highest priority first):

1. `HASSLE_TOKEN` env var (CI override -- never touches the keyring).
2. The OS keyring (macOS Keychain / Secret Service via `keyring`).

Never written into the bundle: `hassle.toml` having a `token` key at all is
treated as a committed-secret bug by `pull`/`doctor` (see `hassle_cli.config`
and `hassle_cli.doctor`), not a legitimate storage location.
"""

from __future__ import annotations

import contextlib
import os

_KEYRING_SERVICE = "hassle"


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
    """Resolve the token for `ha_url`: `HASSLE_TOKEN` env override, else keyring."""
    environ = env if env is not None else os.environ
    env_token = environ.get("HASSLE_TOKEN")
    if env_token:
        return env_token
    return _keyring_get(ha_url)


def store_token(ha_url: str, token: str) -> None:
    _keyring_set(ha_url, token)


def forget_token(ha_url: str) -> None:
    _keyring_delete(ha_url)
