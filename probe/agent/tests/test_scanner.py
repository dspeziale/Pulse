"""Test dell'esecuzione scansioni: runner, self-check, finalizzazione su storage."""

from __future__ import annotations

import subprocess

from pulse_probe import scanner
from pulse_probe.config import Settings
from pulse_probe.server_client import ServerClient
from pulse_probe.state import RuntimeState
from pulse_probe.store import InMemoryStore

_VALID_XML = """<nmaprun>
  <host><status state="up"/><address addr="10.0.0.5" addrtype="ipv4"/>
    <ports><port protocol="tcp" portid="22"><state state="open"/><service name="ssh"/></port></ports>
  </host>
  <runstats><hosts up="1" down="0" total="1"/></runstats>
</nmaprun>"""


def _state(runner) -> RuntimeState:
    settings = Settings(opensearch_url=None, poller_enabled=False, server_query_token="t")
    st = RuntimeState(settings=settings, store=InMemoryStore(), server=ServerClient(settings))
    st.scan_runner = runner
    return st


def _running_doc(st: RuntimeState, scan_id: str = "s1") -> None:
    st.store.index_scan(
        {
            "scan_id": scan_id, "target": "10.0.0.5", "options": {}, "status": "running",
            "started_at": "2026-07-17T00:00:00+00:00", "finished_at": None,
            "error": None, "summary": None, "hosts": [],
        }
    )


# ------------------------------- run_nmap ----------------------------------


def test_run_nmap_invokes_subprocess_list(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _P:
        returncode = 0
        stdout = "out"
        stderr = ""

    def _fake_run(argv, **kwargs):  # type: ignore[no-untyped-def]
        captured["argv"] = argv
        captured["shell"] = kwargs.get("shell", False)
        return _P()

    monkeypatch.setattr(scanner.subprocess, "run", _fake_run)
    rc, out, err = scanner.run_nmap(["nmap", "--version"], 5)
    assert rc == 0 and out == "out" and err == ""
    assert captured["argv"] == ["nmap", "--version"]  # ARGV lista
    assert captured["shell"] is False  # mai shell


# ------------------------------- detect_nmap -------------------------------


def test_detect_nmap_available(monkeypatch) -> None:
    monkeypatch.setattr(scanner, "run_nmap", lambda argv, timeout: (0, "Nmap version 7.94\nblah", ""))
    ok, version = scanner.detect_nmap()
    assert ok is True and version == "Nmap version 7.94"


def test_detect_nmap_available_empty_output(monkeypatch) -> None:
    monkeypatch.setattr(scanner, "run_nmap", lambda argv, timeout: (0, "   ", ""))
    ok, version = scanner.detect_nmap()
    assert ok is True and version is None


def test_detect_nmap_nonzero(monkeypatch) -> None:
    monkeypatch.setattr(scanner, "run_nmap", lambda argv, timeout: (1, "", "err"))
    assert scanner.detect_nmap() == (False, None)


def test_detect_nmap_missing(monkeypatch) -> None:
    def _boom(argv, timeout):  # type: ignore[no-untyped-def]
        raise OSError("nmap not found")

    monkeypatch.setattr(scanner, "run_nmap", _boom)
    assert scanner.detect_nmap() == (False, None)


# ------------------------------- execute_scan ------------------------------


def test_execute_scan_success() -> None:
    st = _state(lambda argv, timeout: (0, _VALID_XML, ""))
    _running_doc(st)
    scanner.execute_scan(st, "s1", ["nmap", "-sT", "-oX", "-", "10.0.0.5"])
    doc = st.store.get_scan("s1")
    assert doc is not None
    assert doc["status"] == "done" and doc["error"] is None
    assert doc["summary"]["ports_open"] == 1
    assert doc["hosts"][0]["ip"] == "10.0.0.5"
    assert doc["finished_at"] is not None


def test_execute_scan_privilege_error() -> None:
    st = _state(lambda argv, timeout: (1, "", "You requested a scan type which requires root privileges."))
    _running_doc(st)
    scanner.execute_scan(st, "s1", ["nmap", "-sS", "-oX", "-", "10.0.0.5"])
    doc = st.store.get_scan("s1")
    assert doc is not None and doc["status"] == "failed"
    assert "CAP_NET_RAW" in doc["error"]


def test_execute_scan_generic_error() -> None:
    st = _state(lambda argv, timeout: (2, "", "some other failure"))
    _running_doc(st)
    scanner.execute_scan(st, "s1", ["nmap", "-oX", "-", "10.0.0.5"])
    doc = st.store.get_scan("s1")
    assert doc is not None and doc["status"] == "failed"
    assert "Errore nmap" in doc["error"]


def test_execute_scan_timeout() -> None:
    def _timeout(argv, timeout):  # type: ignore[no-untyped-def]
        raise subprocess.TimeoutExpired(cmd=argv, timeout=timeout)

    st = _state(_timeout)
    _running_doc(st)
    scanner.execute_scan(st, "s1", ["nmap", "-oX", "-", "10.0.0.5"])
    doc = st.store.get_scan("s1")
    assert doc is not None and doc["status"] == "failed" and "Timeout" in doc["error"]


def test_execute_scan_nmap_missing() -> None:
    def _oserror(argv, timeout):  # type: ignore[no-untyped-def]
        raise OSError("No such file or directory: 'nmap'")

    st = _state(_oserror)
    _running_doc(st)
    scanner.execute_scan(st, "s1", ["nmap", "-oX", "-", "10.0.0.5"])
    doc = st.store.get_scan("s1")
    assert doc is not None and doc["status"] == "failed" and "Impossibile eseguire nmap" in doc["error"]


def test_execute_scan_invalid_xml() -> None:
    st = _state(lambda argv, timeout: (0, "<broken", ""))
    _running_doc(st)
    scanner.execute_scan(st, "s1", ["nmap", "-oX", "-", "10.0.0.5"])
    doc = st.store.get_scan("s1")
    assert doc is not None and doc["status"] == "failed" and "XML nmap non valido" in doc["error"]
