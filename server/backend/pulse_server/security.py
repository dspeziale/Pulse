"""Primitive di sicurezza: hashing password (bcrypt), JWT, token opachi,
cifratura segreti a riposo (Fernet), firma HMAC.

Hashing password: **bcrypt** coerente col seed (`$2b$12$...` di 'ChangeMe123!'),
come indicato in deploy/seed.sql (RNF-003).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets as _secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt
from cryptography.fernet import Fernet, InvalidToken


# --- Password (bcrypt) -------------------------------------------------------


def hash_password(plain: str) -> str:
    """Genera l'hash bcrypt (cost 12) di una password."""
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(plain.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Verifica una password contro l'hash bcrypt memorizzato."""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# --- Token opachi (refresh, probe, enrollment) -------------------------------


def generate_opaque_token(nbytes: int = 32) -> str:
    """Genera un token opaco URL-safe."""
    return _secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """Hash SHA-256 di un token opaco (per confronto costante in DB)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_token_hash(token: str, token_hash: str) -> bool:
    return hmac.compare_digest(hash_token(token), token_hash)


# --- JWT ---------------------------------------------------------------------


def create_access_token(
    *,
    secret: str,
    algorithm: str,
    subject: str,
    ttl_seconds: int,
    roles: list[str],
    permissions: list[str],
    extra: dict[str, Any] | None = None,
) -> str:
    """Crea un access token JWT firmato."""
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": "access",
        "roles": roles,
        "permissions": permissions,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, secret, algorithm=algorithm)


def decode_token(token: str, *, secret: str, algorithm: str) -> dict[str, Any]:
    """Decodifica e valida un JWT. Solleva jwt.PyJWTError se invalido/scaduto."""
    return jwt.decode(token, secret, algorithms=[algorithm])


# --- Cifratura segreti a riposo (Fernet, RNF-004) ----------------------------


def _derive_fernet_key(material: str) -> bytes:
    """Deriva una chiave Fernet valida (32 byte urlsafe-b64) da materiale arbitrario."""
    digest = hashlib.sha256(material.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


class SecretBox:
    """Cifra/decifra segreti applicativi (config canali) a riposo."""

    def __init__(self, key_material: str) -> None:
        self._fernet = Fernet(_derive_fernet_key(key_material))

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        except InvalidToken:  # pragma: no cover - difensivo: chiave rotante/errata
            raise ValueError("Impossibile decifrare il segreto (chiave errata).")


# --- HMAC (firme webhook / anti-replay opzionale) ----------------------------


def hmac_sha256_hex(secret: str, payload: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def verify_hmac_sha256(secret: str, payload: bytes, signature: str) -> bool:
    expected = hmac_sha256_hex(secret, payload)
    candidate = signature.split("=", 1)[-1] if "=" in signature else signature
    return hmac.compare_digest(expected, candidate)
