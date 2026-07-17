"""Test del backend nmap via PROXY esterno.

Copre: ``assert_safe_argv`` (roundtrip con build_nmap_argv + rifiuto tampering),
``ProxyScanRunner`` (chiamate HTTP simulate, gestione errori) e la selezione
automatica del backend all'avvio (``_select_scan_backend``).
"""
from __future__ import annotations

import httpx
import pytest

from pulse_probe import main, nmap_scan
from pulse_probe.config import Settings
from pulse_probe.proxy_runner import ProxyScanRunner
from pulse_probe.schemas import ScanRequest
from pulse_probe.server_client import ServerClient
from pulse_probe.state import RuntimeState
from pulse_probe.store import InMemoryStore


# --------------------------------------------------------------------------- #
# assert_safe_argv: coerenza col builder + rifiuto di argv manomessi
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("req", [
    ScanRequest(target="10.0.0.5", technique="connect", top_ports=100),
    ScanRequest(target="10.0.0.0/24", technique="syn", ports="22,80,443",
                service_version=True, version_intensity=7, no_ping=True),
    ScanRequest(target="host.example.com", technique="udp", os_detection=True,
                min_rate=50, max_rate=500, max_retries=2),
    ScanRequest(target="10.0.0.5", technique="ping"),
    ScanRequest(target="10.0.0.5", technique="connect",
                scripts=["default", "vuln"], script_args="http.useragent=Pulse",
                extra="--traceroute -A"),
])
def test_assert_safe_argv_accepts_builder_output(req: ScanRequest):
    argv = nmap_scan.build_nmap_argv(req)
    assert nmap_scan.assert_safe_argv(argv) is argv


@pytest.mark.parametrize("argv", [
    ["nmap", "-sT", "-oX", "/etc/passwd", "10.0.0.5"],          # output su file
    ["nmap", "-sT", "-T3", "-oX", "-", "-oN", "x", "10.0.0.5"],  # flag non ammessa
    ["nmap", "-sT", "-T3", "-oX", "-", "-target"],               # target = flag
    ["nmap", "-T3", "-oX", "-", "10.0.0.5"],                     # tecnica assente
    ["nmap", "-sT", "-sS", "-T3", "-oX", "-", "10.0.0.5"],       # tecnica doppia
    ["nmap", "-sT", "-T3", "10.0.0.5"],                          # manca -oX -
    ["nmap", "-sT", "-T3", "-oX", "-"],                          # nessun target
    ["/bin/sh", "-sT", "-oX", "-", "10.0.0.5"],                  # binario diverso
    ["nmap", "-sT", "-T3", "-oX", "out.xml", "10.0.0.5"],        # -oX non stdout
])
def test_assert_safe_argv_rejects_tampering(argv: list[str]):
    with pytest.raises(nmap_scan.ScanValidationError):
        nmap_scan.assert_safe_argv(argv)


# --------------------------------------------------------------------------- #
# ProxyScanRunner: HTTP simulato
# --------------------------------------------------------------------------- #
class _FakeResp:
    def __init__(self, status_code=200, json_data=None, text="", ctype="application/json"):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.text = text
        self.headers = {"content-type": ctype}

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


class _FakeClient:
    def __init__(self, *, get=None, post=None, raise_exc=None):
        self._get, self._post, self._raise = get, post, raise_exc
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, headers=None):
        self.calls.append(("GET", url, None))
        if self._raise:
            raise self._raise
        return self._get

    def post(self, url, headers=None, json=None):
        self.calls.append(("POST", url, json))
        if self._raise:
            raise self._raise
        return self._post


def _settings(**kw) -> Settings:
    base = dict(nmap_proxy_url="https://host.docker.internal:8556",
                nmap_proxy_token="tok", opensearch_url=None)
    base.update(kw)
    return Settings(**base)


def _runner_with(monkeypatch, fake: _FakeClient) -> ProxyScanRunner:
    r = ProxyScanRunner(_settings())
    monkeypatch.setattr(r, "_client", lambda timeout: fake)
    return r


def test_proxy_runner_scan_ok(monkeypatch):
    fake = _FakeClient(post=_FakeResp(json_data={"returncode": 0, "stdout": "<x/>",
                                                 "stderr": ""}))
    r = _runner_with(monkeypatch, fake)
    argv = ["nmap", "-sS", "-T3", "-oX", "-", "10.0.0.5"]
    assert r(argv, 120) == (0, "<x/>", "")
    assert fake.calls[0][0] == "POST" and fake.calls[0][1].endswith("/scan")
    assert fake.calls[0][2] == {"argv": argv, "timeout": 120}


def test_proxy_runner_unreachable_returns_failed(monkeypatch):
    fake = _FakeClient(raise_exc=httpx.ConnectError("down"))
    r = _runner_with(monkeypatch, fake)
    rc, out, err = r(["nmap", "-sS", "-oX", "-", "x"], 10)
    assert rc != 0 and "non raggiungibile" in err.lower()


def test_proxy_runner_timeout_returns_failed(monkeypatch):
    fake = _FakeClient(raise_exc=httpx.ReadTimeout("slow"))
    r = _runner_with(monkeypatch, fake)
    rc, _out, err = r(["nmap", "-sS", "-oX", "-", "x"], 10)
    assert rc != 0 and "timeout" in err.lower()


def test_proxy_runner_422_reports_detail(monkeypatch):
    fake = _FakeClient(post=_FakeResp(status_code=422, json_data={"detail": "Flag non consentita"}))
    r = _runner_with(monkeypatch, fake)
    rc, _out, err = r(["nmap", "-sS", "-oX", "-", "x"], 10)
    assert rc != 0 and "Flag non consentita" in err


def test_proxy_runner_health_ok(monkeypatch):
    fake = _FakeClient(get=_FakeResp(json_data={"nmap_available": True,
                                                "nmap_version": "Nmap 7.95"}))
    r = _runner_with(monkeypatch, fake)
    assert r.health() == (True, "Nmap 7.95")


def test_proxy_runner_health_unreachable(monkeypatch):
    fake = _FakeClient(raise_exc=httpx.ConnectError("down"))
    r = _runner_with(monkeypatch, fake)
    assert r.health() == (False, None)


# --------------------------------------------------------------------------- #
# Selezione automatica del backend all'avvio
# --------------------------------------------------------------------------- #
def _state(settings: Settings) -> RuntimeState:
    return RuntimeState(settings=settings, store=InMemoryStore(),
                        server=ServerClient(settings))


def test_select_backend_local_when_not_configured():
    st = _state(Settings(opensearch_url=None))   # nessun proxy
    main._select_scan_backend(st)
    assert st.scan_backend == "local"


def test_select_backend_proxy_when_healthy(monkeypatch):
    st = _state(_settings())
    monkeypatch.setattr(ProxyScanRunner, "health",
                        lambda self: (True, "Nmap 7.95 (host)"))
    main._select_scan_backend(st)
    assert st.scan_backend == "proxy"
    assert isinstance(st.scan_runner, ProxyScanRunner)
    assert st.nmap_available is True and "host" in (st.nmap_version or "")


def test_select_backend_falls_back_when_unreachable(monkeypatch):
    st = _state(_settings())
    monkeypatch.setattr(ProxyScanRunner, "health", lambda self: (False, None))
    main._select_scan_backend(st)
    assert st.scan_backend == "local"
    assert not isinstance(st.scan_runner, ProxyScanRunner)
