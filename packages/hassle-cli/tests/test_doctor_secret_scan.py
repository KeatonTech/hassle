"""`hassle_cli.doctor.find_committed_tokens` widened scan (DESIGN §14,
SECURITY.md "No token").

The pre-existing scan only globbed top-level `*.toml` for a `token = "..."`
line. A real bundle is mostly Python, has subdirectories, and secrets get
pasted under other key names (`access_token`, `ha_token`, `HASSLE_TOKEN`) or
straight into a URL. This widens the scan and pins it against both new
detections and false positives.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hassle_cli.doctor import find_committed_tokens

# A synthetic JWT-shaped string (three base64url segments, >180 chars total)
# -- shaped like a real HA long-lived access token, but not one.
_JWT = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJoYXNzbGUiLCJpYXQiOjE3MDAwMDAwMDAsInN1YiI6ImxvbmctbGl2ZWQtYWNjZXNzLXRva2VuLWV4YW1wbGUtdmFsdWUifQ."
    "c2lnbmF0dXJlLXBsYWNlaG9sZGVyLXRoYXQtaXMtbG9uZy1lbm91Z2gtdG8tcGFzcw"
)


def test_finds_token_in_python_file_not_just_toml(bundle_dir: Path) -> None:
    (bundle_dir / "lib").mkdir(exist_ok=True)
    (bundle_dir / "lib" / "config.py").write_text(f'ACCESS_TOKEN = "{_JWT}"\n', encoding="utf-8")
    found = find_committed_tokens(bundle_dir)
    assert any(path.name == "config.py" for path, _reason in found)


def test_finds_token_in_nested_subdirectory(bundle_dir: Path) -> None:
    nested = bundle_dir / "scripts" / "deploy"
    nested.mkdir(parents=True)
    (nested / "notes.txt").write_text(f'token = "{_JWT}"\n', encoding="utf-8")
    found = find_committed_tokens(bundle_dir)
    assert any(path.name == "notes.txt" for path, _reason in found)


def test_finds_token_in_dotenv_file(bundle_dir: Path) -> None:
    (bundle_dir / ".env").write_text(f"HASSLE_TOKEN={_JWT}\n", encoding="utf-8")
    found = find_committed_tokens(bundle_dir)
    assert any(path.name == ".env" for path, _reason in found)


def test_finds_token_in_json_file(bundle_dir: Path) -> None:
    (bundle_dir / "secrets.json").write_text(f'{{"access_token": "{_JWT}"}}\n', encoding="utf-8")
    found = find_committed_tokens(bundle_dir)
    assert any(path.name == "secrets.json" for path, _reason in found)


def test_finds_token_in_yaml_file(bundle_dir: Path) -> None:
    (bundle_dir / "secrets.yaml").write_text(f"ha_token: {_JWT}\n", encoding="utf-8")
    found = find_committed_tokens(bundle_dir)
    assert any(path.name == "secrets.yaml" for path, _reason in found)


@pytest.mark.parametrize("key", ["token", "access_token", "ha_token", "TOKEN", "HASSLE_TOKEN"])
def test_finds_each_key_name_variant(bundle_dir: Path, key: str) -> None:
    (bundle_dir / "variant.py").write_text(f'{key} = "{_JWT}"\n', encoding="utf-8")
    found = find_committed_tokens(bundle_dir)
    assert any(path.name == "variant.py" for path, _reason in found), (
        f"key variant {key!r} was not detected"
    )
    (bundle_dir / "variant.py").unlink()


def test_finds_credentials_embedded_in_ha_url(bundle_dir: Path) -> None:
    (bundle_dir / "hassle.toml").write_text(
        'ha_url = "https://user:sk_live_abcdefghijklmnop@homeassistant.example.com:8123"\n'
        "format_version = 1\n",
        encoding="utf-8",
    )
    found = find_committed_tokens(bundle_dir)
    assert any(path.name == "hassle.toml" for path, _reason in found)


def test_finds_bare_jwt_shaped_string_with_no_recognized_key(bundle_dir: Path) -> None:
    """A JWT-shaped literal is flagged even when it isn't assigned to a
    recognized key name -- catches e.g. `Authorization: Bearer <jwt>` pasted
    into a comment, or the value bound to some other variable name."""
    (bundle_dir / "notes.py").write_text(
        f"# forgot to remove this before committing: {_JWT}\n", encoding="utf-8"
    )
    found = find_committed_tokens(bundle_dir)
    assert any(path.name == "notes.py" for path, _reason in found)


def test_never_returns_the_secret_value_itself(bundle_dir: Path) -> None:
    (bundle_dir / "leak.py").write_text(f'token = "{_JWT}"\n', encoding="utf-8")
    found = find_committed_tokens(bundle_dir)
    assert found
    for _path, reason in found:
        assert _JWT not in reason


# --- false positives -------------------------------------------------------


def test_clean_bundle_is_not_flagged(bundle_dir: Path) -> None:
    assert find_committed_tokens(bundle_dir) == []


def test_docs_file_mentioning_the_word_token_is_not_flagged(bundle_dir: Path) -> None:
    (bundle_dir / "docs").mkdir(exist_ok=True)
    (bundle_dir / "docs" / "AUTH.md").write_text(
        "# Auth\n\nHassle authenticates with a long-lived access token. "
        "The token is never written into this bundle -- see hassle login.\n",
        encoding="utf-8",
    )
    found = find_committed_tokens(bundle_dir)
    assert found == []


def test_non_jwt_base64_string_is_not_flagged(bundle_dir: Path) -> None:
    (bundle_dir / "hashes.py").write_text(
        # A dependency pin and a sha256-shaped hex digest -- both long opaque
        # strings, neither dotted-three-segments nor a `token=`-style key.
        'REQUIRES = "urllib3>=2.0.0,<3.0.0"\n'
        'CHECKSUM = "8f14e45fceea167a5a36dedd4bea25435dfbcbdf7f3a2b3c4d5e6f708192a3b"\n',
        encoding="utf-8",
    )
    found = find_committed_tokens(bundle_dir)
    assert found == []


def test_skips_dot_git_venv_typings_pycache_node_modules(bundle_dir: Path) -> None:
    for skip_dir in (".git", ".venv", "typings", "__pycache__", "node_modules"):
        nested = bundle_dir / skip_dir / "nested"
        nested.mkdir(parents=True)
        (nested / "leftover.py").write_text(f'token = "{_JWT}"\n', encoding="utf-8")
    found = find_committed_tokens(bundle_dir)
    assert found == []


def test_short_placeholder_value_is_not_flagged(bundle_dir: Path) -> None:
    """A short, obviously-a-placeholder value (`token = "..."`,
    `token = "<your-token-here>"`) shouldn't trip the scan -- the whole point
    is a *real* long opaque secret."""
    (bundle_dir / "example.py").write_text('token = "x"\n', encoding="utf-8")
    found = find_committed_tokens(bundle_dir)
    assert found == []


# ---------------------------------------------------------------------------
# Binary detection is by content, not by filename.
#
# An extension list can only ever be a guess: it goes stale as new formats
# appear, and it says nothing about a file whose name doesn't match its
# content. Neither direction is an attack (this scans your own bundle -- a
# secret hidden from the scanner is hidden from you), but both are real
# false-negative/false-positive sources, so the check reads the bytes.
# ---------------------------------------------------------------------------

_JWT = "eyJ" + "a" * 60 + "." + "b" * 80 + "." + "c" * 60


def test_finds_a_token_in_a_text_file_with_an_unrecognized_extension(bundle_dir: Path) -> None:
    """A filename tells us nothing: this is plain text whatever it's called."""
    (bundle_dir / "notes.bak").write_text(f'token = "{_JWT}"\n', encoding="utf-8")
    assert [p.name for p, _ in find_committed_tokens(bundle_dir)] == ["notes.bak"]


def test_finds_a_token_in_a_text_file_named_like_a_binary(bundle_dir: Path) -> None:
    """A `.png` that is actually text is still scanned -- the old extension
    list skipped it outright."""
    (bundle_dir / "secrets.png").write_text(f"access_token: {_JWT}\n", encoding="utf-8")
    assert [p.name for p, _ in find_committed_tokens(bundle_dir)] == ["secrets.png"]


def test_skips_real_binary_content_whatever_it_is_named(bundle_dir: Path) -> None:
    """Genuinely binary content is skipped even with a text-looking name, so
    random bytes can't produce a bogus match."""
    payload = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + bytes(range(256)) * 4
    (bundle_dir / "image.py").write_bytes(payload)
    (bundle_dir / "archive.txt").write_bytes(b"PK\x03\x04\x00\x00" + bytes(range(256)))
    assert find_committed_tokens(bundle_dir) == []


def test_skips_a_binary_file_that_happens_to_contain_a_jwt_shaped_run(bundle_dir: Path) -> None:
    """A compiled artifact embedding a token-shaped string is not a committed
    secret; scanning binaries as text is what produces that false positive."""
    (bundle_dir / "compiled.pyc").write_bytes(b"\x00\x01\x02" + _JWT.encode() + b"\x00\xff")
    assert find_committed_tokens(bundle_dir) == []


def test_utf8_text_with_non_ascii_is_still_scanned(bundle_dir: Path) -> None:
    """Binary detection must not reject ordinary non-ASCII source."""
    (bundle_dir / "café.py").write_text(
        f'# comentário aqui — ç\nhassle_token = "{_JWT}"\n', encoding="utf-8"
    )
    assert len(find_committed_tokens(bundle_dir)) == 1
