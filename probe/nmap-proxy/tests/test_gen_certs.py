"""Test della generazione del materiale mTLS (CA + server + client)."""
from __future__ import annotations

from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import padding

from pulse_nmap_proxy.gen_certs import generate_all


def test_generate_all_creates_chain(tmp_path):
    paths = generate_all(tmp_path, ["host.docker.internal", "localhost", "127.0.0.1"])
    for p in paths.values():
        assert p.exists() and p.stat().st_size > 0

    ca = x509.load_pem_x509_certificate(paths["ca_cert"].read_bytes())
    server = x509.load_pem_x509_certificate(paths["server_cert"].read_bytes())
    client = x509.load_pem_x509_certificate(paths["client_cert"].read_bytes())

    # Server e client sono firmati dalla CA.
    for leaf in (server, client):
        ca.public_key().verify(
            leaf.signature, leaf.tbs_certificate_bytes,
            padding.PKCS1v15(), leaf.signature_hash_algorithm,
        )

    # Il certificato server include i SAN richiesti (verifica del container).
    san = server.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    dns = san.get_values_for_type(x509.DNSName)
    assert "host.docker.internal" in dns and "localhost" in dns

    # La CA e' marcata come tale.
    bc = ca.extensions.get_extension_for_class(x509.BasicConstraints).value
    assert bc.ca is True
