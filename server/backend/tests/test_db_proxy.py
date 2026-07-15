"""Test del layer DB (db.py) e del client proxy (proxy.py)."""

from __future__ import annotations

import httpx
import pytest

from pulse_server import db, errors
from pulse_server.config import Settings
from pulse_server.proxy import ProbeQueryClient


def test_db_engine_and_session(db_engine) -> None:
    db.set_engine(db_engine)
    assert db.get_engine() is db_engine
    factory = db.get_session_factory()
    assert factory is not None
    gen = db.get_session()
    session = next(gen)
    try:
        from sqlalchemy import text

        assert session.execute(text("SELECT 1")).scalar_one() == 1
    finally:
        gen.close()


def _client_with(handler) -> ProbeQueryClient:
    settings = Settings()
    client = ProbeQueryClient(settings)
    transport = httpx.MockTransport(handler)

    def _mk() -> httpx.Client:
        return httpx.Client(transport=transport)

    client._client = _mk  # type: ignore[method-assign]
    return client


def test_proxy_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer tok"
        return httpx.Response(200, json={"items": [], "total": 0})

    c = _client_with(handler)
    assert c.get_heartbeats("https://p", "tok", {"system_id": "s"}) == {"items": [], "total": 0}
    assert c.post_query("https://p", "tok", {"filters": []}) == {"items": [], "total": 0}


def test_proxy_400_maps_bad_request() -> None:
    c = _client_with(lambda r: httpx.Response(400, json={}))
    with pytest.raises(errors.ApiError) as exc:
        c.get_heartbeats("https://p", "t", {})
    assert exc.value.status_code == 400


def test_proxy_500_maps_service_unavailable() -> None:
    c = _client_with(lambda r: httpx.Response(500, json={}))
    with pytest.raises(errors.ApiError) as exc:
        c.get_heartbeats("https://p", "t", {})
    assert exc.value.status_code == 503


def test_proxy_unexpected_status_maps_503() -> None:
    c = _client_with(lambda r: httpx.Response(418, json={}))
    with pytest.raises(errors.ApiError) as exc:
        c.post_query("https://p", "t", {})
    assert exc.value.status_code == 503


def test_proxy_client_builder_with_certs(tmp_path) -> None:
    """Copre la costruzione del client httpx con cert/verify da settings reali."""
    import ssl

    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    ca = tmp_path / "ca.pem"
    # genera una coppia cert/chiave self-signed valida per httpx/ssl
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    import datetime as _dt

    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "pulse-test")])
    crt = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name).public_key(k.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(_dt.datetime.now(_dt.timezone.utc))
        .not_valid_after(_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=1))
        .sign(k, hashes.SHA256())
    )
    key.write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
    cert.write_bytes(crt.public_bytes(serialization.Encoding.PEM))
    ca.write_bytes(crt.public_bytes(serialization.Encoding.PEM))
    assert ssl  # usato implicitamente da httpx

    settings = Settings(
        probe_client_cert_path=str(cert),
        probe_client_key_path=str(key),
        tls_ca_cert_path=str(ca),
    )
    client = ProbeQueryClient(settings)
    httpx_client = client._client()
    assert isinstance(httpx_client, httpx.Client)
    httpx_client.close()


def test_proxy_client_builder_defaults() -> None:
    client = ProbeQueryClient(Settings())
    httpx_client = client._client()
    assert isinstance(httpx_client, httpx.Client)
    httpx_client.close()
