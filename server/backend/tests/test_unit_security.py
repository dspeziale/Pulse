"""Unit test delle primitive di sicurezza (nessun DB)."""

from __future__ import annotations

import pytest

from pulse_server.security import (
    SecretBox,
    create_access_token,
    decode_token,
    generate_opaque_token,
    hash_password,
    hash_token,
    hmac_sha256_hex,
    verify_hmac_sha256,
    verify_password,
    verify_token_hash,
)


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("secret-password")
    assert hashed.startswith("$2b$")
    assert verify_password("secret-password", hashed)
    assert not verify_password("wrong", hashed)


def test_verify_password_handles_invalid_hash() -> None:
    assert not verify_password("x", "not-a-bcrypt-hash")


def test_seed_bcrypt_matches_changeme() -> None:
    seed_hash = "$2b$12$/dbOlipZecqErctsrVMG1ukAzlM69NU2/WZFPNyTkC8IfvFWmNWeO"
    assert verify_password("ChangeMe123!", seed_hash)


def test_opaque_token_and_hash() -> None:
    token = generate_opaque_token()
    assert len(token) > 20
    h = hash_token(token)
    assert verify_token_hash(token, h)
    assert not verify_token_hash("other", h)


def test_jwt_roundtrip() -> None:
    token = create_access_token(
        secret="s", algorithm="HS256", subject="u1", ttl_seconds=60,
        roles=["Admin"], permissions=["users.read"], extra={"k": "v"},
    )
    payload = decode_token(token, secret="s", algorithm="HS256")
    assert payload["sub"] == "u1"
    assert payload["type"] == "access"
    assert payload["k"] == "v"
    assert "users.read" in payload["permissions"]


def test_jwt_invalid_secret() -> None:
    import jwt

    token = create_access_token(
        secret="s", algorithm="HS256", subject="u", ttl_seconds=60, roles=[], permissions=[]
    )
    with pytest.raises(jwt.PyJWTError):
        decode_token(token, secret="other", algorithm="HS256")


def test_secret_box_roundtrip() -> None:
    box = SecretBox("key-material")
    ct = box.encrypt("segreto")
    assert ct != "segreto"
    assert box.decrypt(ct) == "segreto"


def test_secret_box_wrong_key() -> None:
    ct = SecretBox("a").encrypt("x")
    with pytest.raises(ValueError):
        SecretBox("b").decrypt(ct)


def test_hmac_signature() -> None:
    sig = hmac_sha256_hex("secret", b"payload")
    assert verify_hmac_sha256("secret", b"payload", sig)
    assert verify_hmac_sha256("secret", b"payload", f"sha256={sig}")
    assert not verify_hmac_sha256("secret", b"payload", "deadbeef")
