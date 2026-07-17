"""Test del proxy nmap (logica app: auth, ri-validazione argv, esecuzione).

mTLS e' applicato dal transport uvicorn (__main__) e non e' esercitabile via
TestClient: qui si testa la logica applicativa con un runner iniettato.
"""
from __future__ import annotations

import subprocess

import pytest
from fastapi.testclient import TestClient

from pulse_nmap_proxy.app import create_app, detect_nmap
from pulse_nmap_proxy.config import ProxySettings

TOKEN = "s3cret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

# argv valido tipico prodotto dall'agent (build_nmap_argv): connect + top-ports.
GOOD_ARGV = ["nmap", "-sT", "-T3", "--top-ports", "100", "-oX", "-", "10.0.0.5"]
# argv malevolo: tenta output su file (non consentito).
EVIL_ARGV = ["nmap", "-sT", "-oX", "/etc/pwned", "10.0.0.5"]


def _settings(**kw) -> ProxySettings:
    base = dict(token=TOKEN, nmap_path="nmap", max_scan_timeout=3600,
                tls_cert_path=None, tls_key_path=None, tls_client_ca_path=None)
    base.update(kw)
    return ProxySettings(**base)


def _client(runner) -> TestClient:
    return TestClient(create_app(_settings(), runner=runner))


def test_scan_requires_token():
    c = _client(lambda argv, t: (0, "<nmaprun/>", ""))
    assert c.post("/scan", json={"argv": GOOD_ARGV}).status_code == 401


def test_scan_runs_and_substitutes_binary():
    captured = {}

    def runner(argv, timeout):
        captured["argv"] = argv
        captured["timeout"] = timeout
        return 0, "<nmaprun/>", ""

    c = TestClient(create_app(_settings(nmap_path="/opt/nmap/nmap"), runner=runner))
    r = c.post("/scan", json={"argv": GOOD_ARGV, "timeout": 120}, headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["returncode"] == 0 and body["stdout"] == "<nmaprun/>"
    # argv[0] sostituito col percorso reale; il resto invariato.
    assert captured["argv"][0] == "/opt/nmap/nmap"
    assert captured["argv"][1:] == GOOD_ARGV[1:]
    assert captured["timeout"] == 120


def test_scan_rejects_unsafe_argv():
    c = _client(lambda argv, t: (0, "", ""))
    r = c.post("/scan", json={"argv": EVIL_ARGV}, headers=AUTH)
    assert r.status_code == 422
    assert "stdout" in r.text or "XML" in r.text or "-oX" in r.text


def test_scan_caps_timeout():
    captured = {}

    def runner(argv, timeout):
        captured["timeout"] = timeout
        return 0, "", ""

    c = TestClient(create_app(_settings(max_scan_timeout=300), runner=runner))
    c.post("/scan", json={"argv": GOOD_ARGV, "timeout": 99999}, headers=AUTH)
    assert captured["timeout"] == 300


def test_scan_timeout_returns_failed():
    def runner(argv, timeout):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=timeout)

    r = _client(runner).post("/scan", json={"argv": GOOD_ARGV}, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["returncode"] != 0
    assert "Timeout" in r.json()["stderr"]


def test_scan_oserror_returns_failed():
    def runner(argv, timeout):
        raise OSError("nmap non trovato")

    r = _client(runner).post("/scan", json={"argv": GOOD_ARGV}, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["returncode"] != 0
    assert "nmap" in r.json()["stderr"].lower()


def test_health_reports_nmap():
    def runner(argv, timeout):
        assert argv == ["nmap", "--version"]
        return 0, "Nmap version 7.95 ( https://nmap.org )\n", ""

    r = _client(runner).get("/health", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["nmap_available"] is True
    assert "7.95" in body["nmap_version"]


def test_health_requires_token():
    assert _client(lambda a, t: (0, "", "")).get("/health").status_code == 401


def test_detect_nmap_missing():
    def runner(argv, timeout):
        raise OSError("assente")

    assert detect_nmap("nmap", runner) == (False, None)


def test_missing_token_config_is_500():
    # token non configurato -> mai autorizzare (errore di configurazione).
    c = TestClient(create_app(_settings(token=None), runner=lambda a, t: (0, "", "")))
    assert c.post("/scan", json={"argv": GOOD_ARGV},
                  headers={"Authorization": "Bearer x"}).status_code == 500
