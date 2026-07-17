"""Test del motore NMAP: validazione (sicurezza), costruzione argv, parsing XML."""

from __future__ import annotations

import pydantic
import pytest

from pulse_probe import nmap_scan
from pulse_probe.schemas import ScanRequest

# --------------------------------------------------------------------------- #
# Validazione target
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "target",
    ["10.0.0.5", "::1", "192.168.1.0/24", "fe80::/10", "host.local", "a.b-c.example", "10.0.0.1 10.0.0.2"],
)
def test_validate_target_valid(target: str) -> None:
    tokens = nmap_scan.validate_target(target)
    assert tokens == target.split()


@pytest.mark.parametrize(
    "target",
    ["", "   ", "-oX", "host!", "a b;c", "1.2.3.4/33", "$(rm -rf)", "a/b"],
)
def test_validate_target_invalid(target: str) -> None:
    with pytest.raises(nmap_scan.ScanValidationError):
        nmap_scan.validate_target(target)


# --------------------------------------------------------------------------- #
# Validazione ports / scripts / script_args / extra
# --------------------------------------------------------------------------- #


def test_validate_ports() -> None:
    assert nmap_scan.validate_ports("22,80,1000-2000") == "22,80,1000-2000"
    with pytest.raises(nmap_scan.ScanValidationError):
        nmap_scan.validate_ports("22;rm")
    with pytest.raises(nmap_scan.ScanValidationError):
        nmap_scan.validate_ports("U:53")


def test_validate_scripts() -> None:
    assert nmap_scan.validate_scripts(["default", "http-title", "vuln*"]) == [
        "default",
        "http-title",
        "vuln*",
    ]
    with pytest.raises(nmap_scan.ScanValidationError):
        nmap_scan.validate_scripts(["../evil.nse"])
    with pytest.raises(nmap_scan.ScanValidationError):
        nmap_scan.validate_scripts(["a/b"])


def test_validate_script_args() -> None:
    assert nmap_scan.validate_script_args("user=admin,pass=x") == "user=admin,pass=x"
    with pytest.raises(nmap_scan.ScanValidationError):
        nmap_scan.validate_script_args("user=$(whoami)")


def test_validate_extra_valid() -> None:
    assert nmap_scan.validate_extra("-A --reason --host-timeout=30s") == [
        "-A",
        "--reason",
        "--host-timeout=30s",
    ]


@pytest.mark.parametrize(
    "extra",
    [
        "-oX",  # flag di output: non in allowlist
        "-iL=hosts.txt",  # lettura file: non in allowlist
        "--datadir=/etc",  # non in allowlist
        "-D",  # decoy/spoof: non in allowlist
        "notaflag",  # non matcha il formato flag
        "--script=/tmp/x.nse",  # formato ok ma flag non in allowlist
        "-A;rm",  # metacaratteri
    ],
)
def test_validate_extra_rejected(extra: str) -> None:
    with pytest.raises(nmap_scan.ScanValidationError):
        nmap_scan.validate_extra(extra)


# --------------------------------------------------------------------------- #
# Costruzione argv (sempre -oX -, target in coda, niente flag vietate)
# --------------------------------------------------------------------------- #


def test_build_argv_minimal() -> None:
    argv = nmap_scan.build_nmap_argv(ScanRequest(target="10.0.0.5"))
    assert argv == ["nmap", "-sT", "-T3", "-oX", "-", "10.0.0.5"]


def test_build_argv_full() -> None:
    req = ScanRequest(
        target="10.0.0.5",
        timing="T4",
        technique="syn",
        ports="22,80",
        service_version=True,
        version_intensity=5,
        os_detection=True,
        no_ping=True,
        scripts=["default", "http-title"],
        script_args="user=x",
        min_rate=100,
        max_rate=1000,
        max_retries=2,
        extra="-A --reason",
    )
    argv = nmap_scan.build_nmap_argv(req)
    assert argv[:3] == ["nmap", "-sS", "-T4"]
    assert "-p" in argv and "22,80" in argv
    assert "-sV" in argv and "--version-intensity" in argv and "5" in argv
    assert "-O" in argv and "-Pn" in argv
    assert "--script=default,http-title" in argv
    assert "--script-args" in argv and "user=x" in argv
    assert "--min-rate" in argv and "--max-rate" in argv and "--max-retries" in argv
    assert "-A" in argv and "--reason" in argv
    # output XML forzato e target in coda
    assert argv[-3:] == ["-oX", "-", "10.0.0.5"]
    # nessuna flag di output su file
    assert not any(a in ("-oN", "-oG", "-oA", "-iL") for a in argv)


def test_build_argv_top_ports_and_sv_without_intensity() -> None:
    req = ScanRequest(target="10.0.0.5", top_ports=100, service_version=True)
    argv = nmap_scan.build_nmap_argv(req)
    assert "--top-ports" in argv and "100" in argv
    assert "-sV" in argv and "--version-intensity" not in argv


@pytest.mark.parametrize(
    ("technique", "flag"),
    [("connect", "-sT"), ("syn", "-sS"), ("udp", "-sU"), ("ping", "-sn")],
)
def test_build_argv_technique_mapping(technique: str, flag: str) -> None:
    argv = nmap_scan.build_nmap_argv(ScanRequest(target="10.0.0.5", technique=technique))  # type: ignore[arg-type]
    assert flag in argv


# --------------------------------------------------------------------------- #
# Parsing XML
# --------------------------------------------------------------------------- #

_FULL_XML = """<?xml version="1.0"?>
<nmaprun scanner="nmap">
  <host>
    <status state="up"/>
    <address addr="10.0.0.5" addrtype="ipv4"/>
    <hostnames><hostname name="host.local"/></hostnames>
    <ports>
      <port protocol="tcp" portid="22">
        <state state="open"/>
        <service name="ssh" product="OpenSSH" version="8.9"/>
        <script id="ssh-hostkey" output="AAAA"/>
      </port>
      <port protocol="tcp" portid="80">
        <state state="closed"/>
        <service name="http"/>
      </port>
    </ports>
    <hostscript><script id="smb-os" output="Windows"/></hostscript>
    <os><osmatch name="Linux 5.x" accuracy="95"/></os>
  </host>
  <runstats><hosts up="1" down="0" total="1"/></runstats>
</nmaprun>"""

_EDGE_XML = """<nmaprun>
  <host>
    <address addr="00:11:22:33:44:55" addrtype="mac"/>
    <ports>
      <port protocol="tcp"><state state="open"/></port>
    </ports>
    <os><osmatch name="Unknown"/></os>
  </host>
</nmaprun>"""


def test_parse_full_xml() -> None:
    result = nmap_scan.parse_nmap_xml(_FULL_XML)
    assert result["summary"] == {"hosts_up": 1, "hosts_total": 1, "ports_open": 1}
    host = result["hosts"][0]
    assert host["ip"] == "10.0.0.5"
    assert host["hostname"] == "host.local"
    assert host["state"] == "up"
    ssh = host["ports"][0]
    assert ssh["port"] == 22 and ssh["protocol"] == "tcp" and ssh["state"] == "open"
    assert ssh["service"] == "ssh" and ssh["product"] == "OpenSSH" and ssh["version"] == "8.9"
    assert ssh["scripts"] == [{"id": "ssh-hostkey", "output": "AAAA"}]
    http = host["ports"][1]
    assert http["product"] is None and http["version"] is None and http["state"] == "closed"
    assert host["os"] == [{"name": "Linux 5.x", "accuracy": 95}]
    assert host["hostscripts"] == [{"id": "smb-os", "output": "Windows"}]


def test_parse_edge_xml() -> None:
    result = nmap_scan.parse_nmap_xml(_EDGE_XML)
    host = result["hosts"][0]
    assert host["ip"] is None  # solo address mac
    assert host["hostname"] is None
    assert host["state"] is None
    assert host["ports"][0]["port"] is None  # portid mancante
    assert host["ports"][0]["service"] is None
    assert host["os"] == [{"name": "Unknown", "accuracy": None}]
    # runstats assente -> fallback: state None non e' 'up'
    assert result["summary"] == {"hosts_up": 0, "hosts_total": 1, "ports_open": 1}


def test_parse_invalid_xml() -> None:
    with pytest.raises(nmap_scan.ScanValidationError):
        nmap_scan.parse_nmap_xml("<not-closed>")


# --------------------------------------------------------------------------- #
# Validazione a livello schema (ScanRequest -> 422)
# --------------------------------------------------------------------------- #


def test_scanrequest_explicit_nulls() -> None:
    req = ScanRequest(target="10.0.0.5", ports=None, script_args=None, extra=None)
    assert req.ports is None and req.script_args is None and req.extra is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"target": "-oX"},
        {"target": "10.0.0.5", "ports": "bad;"},
        {"target": "10.0.0.5", "scripts": ["../evil"]},
        {"target": "10.0.0.5", "script_args": "$(whoami)"},
        {"target": "10.0.0.5", "extra": "-oN out.txt"},
    ],
)
def test_scanrequest_validation_errors(kwargs: dict) -> None:
    with pytest.raises(pydantic.ValidationError):
        ScanRequest(**kwargs)
