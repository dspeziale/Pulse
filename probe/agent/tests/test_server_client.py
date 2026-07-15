"""Test del client verso il Server (mock transport httpx)."""

from __future__ import annotations

import httpx
import pytest

from pulse_probe.config import Settings
from pulse_probe.server_client import ServerClient


def _with_handler(client: ServerClient, handler) -> None:
    transport = httpx.MockTransport(handler)
    client._client = lambda: httpx.Client(transport=transport)  # type: ignore[method-assign]


def test_register() -> None:
    c = ServerClient(Settings(server_base_url="https://s:9443"))

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/api/v1/probe/register"
        return httpx.Response(200, json={"probe_id": "p1", "probe_token": "tok"})

    _with_handler(c, handler)
    data = c.register("enroll", "1.0.0")
    assert data["probe_token"] == "tok"


def test_get_config_and_auth_header() -> None:
    c = ServerClient(Settings())

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["Authorization"] == "Bearer tok"
        return httpx.Response(200, json={"probe_id": "p1", "systems": [], "config_version": "v1"})

    _with_handler(c, handler)
    assert c.get_config("tok")["config_version"] == "v1"


def test_send_liveness_events_rollup() -> None:
    c = ServerClient(Settings())
    _with_handler(c, lambda r: httpx.Response(200, json={"config_version": "v2", "accepted": 1}))
    assert c.send_liveness("tok", {"version": "1"})["config_version"] == "v2"
    _with_handler(c, lambda r: httpx.Response(202, json={"accepted": 3}))
    assert c.send_events("tok", [{"type": "x"}])["accepted"] == 3
    _with_handler(c, lambda r: httpx.Response(202, json={"accepted": True}))
    assert c.send_rollup("tok", {"window": "1h"})["accepted"] is True


def test_missing_token_raises() -> None:
    c = ServerClient(Settings())
    _with_handler(c, lambda r: httpx.Response(200, json={}))
    with pytest.raises(RuntimeError):
        c.get_config("")


def test_raise_for_status_propagates() -> None:
    c = ServerClient(Settings())
    _with_handler(c, lambda r: httpx.Response(401, json={"error": {}}))
    with pytest.raises(httpx.HTTPStatusError):
        c.get_config("tok")


def test_client_builder_defaults() -> None:
    c = ServerClient(Settings())
    hc = c._client()
    assert isinstance(hc, httpx.Client)
    hc.close()


def test_client_builder_with_certs(tmp_path) -> None:
    import datetime as _dt

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    cert = tmp_path / "c.pem"
    key = tmp_path / "k.pem"
    ca = tmp_path / "ca.pem"
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "probe")])
    crt = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(k.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(_dt.datetime.now(_dt.timezone.utc))
        .not_valid_after(_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=1))
        .sign(k, hashes.SHA256())
    )
    key.write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
    cert.write_bytes(crt.public_bytes(serialization.Encoding.PEM))
    ca.write_bytes(crt.public_bytes(serialization.Encoding.PEM))
    c = ServerClient(Settings(tls_client_cert_path=str(cert), tls_client_key_path=str(key), tls_ca_cert_path=str(ca)))
    hc = c._client()
    assert isinstance(hc, httpx.Client)
    hc.close()
