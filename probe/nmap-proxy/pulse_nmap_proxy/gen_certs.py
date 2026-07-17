"""Generazione del materiale mTLS del proxy nmap (CA + server + client).

Cross-platform (usa ``cryptography``), cosi' l'installer non dipende da openssl.
Produce, nella cartella indicata:
    ca.crt / ca.key           CA privata (firma server e client)
    server.crt / server.key   certificato del proxy (SAN: host.docker.internal, ...)
    client.crt / client.key   certificato del client (agent nel container)

La CA e le chiavi restano sull'host; nel container si montano solo ca.crt,
client.crt e client.key (sola lettura).
"""

from __future__ import annotations

import argparse
import datetime as dt
import ipaddress
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def _key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _write_key(path: Path, key: rsa.RSAPrivateKey) -> None:
    path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ))


def _write_cert(path: Path, cert: x509.Certificate) -> None:
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def _name(cn: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _sans(entries: list[str]) -> x509.SubjectAlternativeName:
    items: list[x509.GeneralName] = []
    for e in entries:
        e = e.strip()
        if not e:
            continue
        try:
            items.append(x509.IPAddress(ipaddress.ip_address(e)))
        except ValueError:
            items.append(x509.DNSName(e))
    return x509.SubjectAlternativeName(items)


def generate_all(out_dir: Path, server_sans: list[str], *, days: int = 3650) -> dict[str, Path]:
    """Genera CA, certificato server e client. Ritorna i path prodotti."""
    out_dir.mkdir(parents=True, exist_ok=True)
    # NB: niente Date.now vietato qui — questo modulo gira sull'host, non nel workflow.
    now = dt.datetime.now(dt.timezone.utc)
    not_after = now + dt.timedelta(days=days)

    # --- CA ---
    ca_key = _key()
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(_name("Pulse nmap-proxy CA"))
        .issuer_name(_name("Pulse nmap-proxy CA"))
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(not_after)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=True, key_cert_sign=True, crl_sign=True,
            key_encipherment=False, content_commitment=False, data_encipherment=False,
            key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
        .sign(ca_key, hashes.SHA256())
    )

    def _leaf(cn: str, sans: x509.SubjectAlternativeName | None, server: bool) -> tuple[x509.Certificate, rsa.RSAPrivateKey]:
        key = _key()
        builder = (
            x509.CertificateBuilder()
            .subject_name(_name(cn))
            .issuer_name(ca_cert.subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(not_after)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([
                x509.oid.ExtendedKeyUsageOID.SERVER_AUTH if server
                else x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False)
        )
        if sans is not None:
            builder = builder.add_extension(sans, critical=False)
        return builder.sign(ca_key, hashes.SHA256()), key

    server_cert, server_key = _leaf("pulse-nmap-proxy", _sans(server_sans), server=True)
    client_cert, client_key = _leaf("pulse-probe-agent", None, server=False)

    paths = {
        "ca_cert": out_dir / "ca.crt", "ca_key": out_dir / "ca.key",
        "server_cert": out_dir / "server.crt", "server_key": out_dir / "server.key",
        "client_cert": out_dir / "client.crt", "client_key": out_dir / "client.key",
    }
    _write_cert(paths["ca_cert"], ca_cert)
    _write_key(paths["ca_key"], ca_key)
    _write_cert(paths["server_cert"], server_cert)
    _write_key(paths["server_key"], server_key)
    _write_cert(paths["client_cert"], client_cert)
    _write_key(paths["client_key"], client_key)
    return paths


def main() -> int:
    ap = argparse.ArgumentParser(description="Genera il materiale mTLS del proxy nmap.")
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--server-san", default="host.docker.internal,localhost,127.0.0.1",
                    help="SAN del certificato server, separati da virgola.")
    ap.add_argument("--days", type=int, default=3650)
    args = ap.parse_args()
    paths = generate_all(args.out_dir, args.server_san.split(","), days=args.days)
    for name, p in paths.items():
        print(f"{name}: {p}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
