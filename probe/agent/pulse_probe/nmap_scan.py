"""Motore di scansioni NMAP eseguite DALLA Probe (validazione + argv + parsing).

SICUREZZA (non negoziabile):
 - nmap e' invocato con ARGV COME LISTA (mai shell), quindi nessun input utente
   raggiunge una shell (vedi `scanner.run_nmap`).
 - Ogni parametro e' validato con WHITELIST/regex prima di finire in argv.
 - I target sono validati (IP/rete/hostname) e i token che iniziano con '-' sono
   RIFIUTATI per prevenire l'argument injection (es. un target "-oX" che nmap
   interpreterebbe come flag di output su file).
 - L'output XML e' FORZATO su stdout (`-oX -`); le flag di output/lettura file
   dell'utente non sono ammesse (allowlist `extra` che le esclude).

Il parsing XML opera su output prodotto dal NOSTRO processo nmap (non input di
rete arbitrario).
"""

from __future__ import annotations

import ipaddress
import re
from typing import TYPE_CHECKING, Any
from xml.etree import ElementTree as ET

if TYPE_CHECKING:  # pragma: no cover - solo per i tipi (nessun import a runtime)
    from .schemas import ScanRequest

# --------------------------------------------------------------------------- #
# Regex e whitelist di validazione
# --------------------------------------------------------------------------- #

# hostname: lettere/cifre, punto e trattino (nessun metacarattere, spazio, slash)
_HOSTNAME_RE = re.compile(r"^[A-Za-z0-9.\-]+$")
# ports: solo cifre, virgola e trattino (es. "22,80,1000-2000")
_PORTS_RE = re.compile(r"^[0-9,\-]+$")
# script NSE: categoria o nome (niente slash/percorsi)
_SCRIPT_RE = re.compile(r"^[A-Za-z0-9_\-.\*]+$")
# script-args: coppie chiave=valore, niente metacaratteri di shell
_SCRIPT_ARGS_RE = re.compile(r"^[A-Za-z0-9,=._:/@\- ]+$")
# token di una flag extra: -x / --xxx eventualmente con =valore
_EXTRA_TOKEN_RE = re.compile(r"^-{1,2}[A-Za-z0-9\-]+(=[A-Za-z0-9,._:/\-]+)?$")

# Mappa tecnica -> flag nmap.
TECHNIQUE_FLAGS: dict[str, str] = {
    "connect": "-sT",
    "syn": "-sS",
    "udp": "-sU",
    "ping": "-sn",
}

# Allowlist di flag "extra" avanzate ma sicure (NESSUNA flag di output/lettura
# file, nessuno spoofing di sorgente/decoy). Tutto cio' che non e' qui -> 422.
EXTRA_ALLOWED_FLAGS: frozenset[str] = frozenset(
    {
        "-A",  # aggressive (equiv. -sV -O -sC --traceroute)
        "-sC",  # script di default
        "-f",  # frammentazione pacchetti
        "-6",  # IPv6
        "-n",  # niente risoluzione DNS
        "-R",  # forza risoluzione DNS
        "-v",  # verbose
        "-vv",
        "-d",  # debug
        "--open",  # solo porte aperte
        "--reason",  # motivo dello stato porta
        "--traceroute",
        "--badsum",
        "--defeat-rst-ratelimit",
        "--defeat-icmp-ratelimit",
        "--host-timeout",
        "--scan-delay",
        "--max-scan-delay",
        "--min-hostgroup",
        "--max-hostgroup",
        "--mtu",
    }
)


class ScanValidationError(ValueError):
    """Errore di validazione delle opzioni di scansione (mappato a 422)."""


# --------------------------------------------------------------------------- #
# Validazione dei singoli parametri
# --------------------------------------------------------------------------- #


def _is_valid_host_token(token: str) -> bool:
    """True se `token` e' un IP, una rete CIDR o un hostname valido.

    I token che iniziano con '-' sono sempre rifiutati (argument injection).
    """
    if not token or token.startswith("-"):
        return False
    try:
        ipaddress.ip_address(token)
        return True
    except ValueError:
        pass
    try:
        ipaddress.ip_network(token, strict=False)
        return True
    except ValueError:
        pass
    return bool(_HOSTNAME_RE.match(token))


def validate_target(target: str) -> list[str]:
    """Valida il target (IP/hostname/CIDR o lista separata da spazi).

    Ritorna la lista dei token validati. Solleva ScanValidationError se vuoto o
    se un token non e' un target valido.
    """
    tokens = target.split()
    if not tokens:
        raise ScanValidationError("target obbligatorio.")
    for token in tokens:
        if not _is_valid_host_token(token):
            raise ScanValidationError(f"Target non valido: {token!r}")
    return tokens


def validate_ports(ports: str) -> str:
    """Valida la stringa `ports` (solo cifre, virgola, trattino)."""
    if not _PORTS_RE.match(ports):
        raise ScanValidationError(f"ports non valido: {ports!r}")
    return ports


def validate_scripts(scripts: list[str]) -> list[str]:
    """Valida i nomi/categorie NSE (niente slash/percorsi)."""
    for script in scripts:
        if not _SCRIPT_RE.match(script):
            raise ScanValidationError(f"script NSE non valido: {script!r}")
    return scripts


def validate_script_args(script_args: str) -> str:
    """Valida gli script-args (coppie chiave=valore, niente metacaratteri)."""
    if not _SCRIPT_ARGS_RE.match(script_args):
        raise ScanValidationError(f"script_args non valido: {script_args!r}")
    return script_args


def validate_extra(extra: str) -> list[str]:
    """Tokenizza e valida le flag `extra` contro la allowlist.

    Ogni token deve matchare il formato flag e la sua flag (parte prima di '=')
    deve essere nella allowlist. Le flag di output/lettura file NON sono in
    allowlist e quindi vengono rifiutate.
    """
    tokens = extra.split()
    validated: list[str] = []
    for token in tokens:
        if not _EXTRA_TOKEN_RE.match(token):
            raise ScanValidationError(f"Flag extra non valida: {token!r}")
        flag = token.split("=", 1)[0]
        if flag not in EXTRA_ALLOWED_FLAGS:
            raise ScanValidationError(f"Flag extra non consentita: {flag!r}")
        validated.append(token)
    return validated


# --------------------------------------------------------------------------- #
# Costruzione argv nmap (sempre sicura, sempre -oX -)
# --------------------------------------------------------------------------- #


def build_nmap_argv(req: ScanRequest, *, binary: str = "nmap") -> list[str]:
    """Costruisce l'argv nmap da una richiesta GIA' validata dallo schema.

    Rivalida target/extra (difesa in profondita'): sono le uniche sorgenti di
    piu' token. L'output e' SEMPRE forzato a XML su stdout (`-oX -`) e i target
    sono posti in coda dopo essere stati validati.
    """
    argv: list[str] = [binary]

    # Scansioni RAW (SYN/UDP/OS detection): nmap, eseguito da utente NON-root, non
    # auto-rileva le capabilities del file/container e rifiuterebbe con
    # "requires root privileges. QUITTING!". `--privileged` gli dice di assumere i
    # privilegi: le capabilities SONO presenti (cap_add + setcap), quindi i raw
    # socket funzionano davvero. Per connect/ping (senza OS detection) non serve.
    if req.technique in ("syn", "udp") or req.os_detection:
        argv.append("--privileged")

    argv += [TECHNIQUE_FLAGS[req.technique], f"-{req.timing}"]

    if req.ports:
        argv += ["-p", req.ports]
    elif req.top_ports is not None:
        argv += ["--top-ports", str(req.top_ports)]

    if req.service_version:
        argv.append("-sV")
        if req.version_intensity is not None:
            argv += ["--version-intensity", str(req.version_intensity)]

    if req.os_detection:
        argv.append("-O")
    if req.no_ping:
        argv.append("-Pn")

    if req.scripts:
        argv.append("--script=" + ",".join(validate_scripts(list(req.scripts))))
    if req.script_args:
        argv += ["--script-args", validate_script_args(req.script_args)]

    if req.min_rate is not None:
        argv += ["--min-rate", str(req.min_rate)]
    if req.max_rate is not None:
        argv += ["--max-rate", str(req.max_rate)]
    if req.max_retries is not None:
        argv += ["--max-retries", str(req.max_retries)]

    if req.extra:
        argv += validate_extra(req.extra)

    # Output XML su stdout FORZATO (mai file arbitrari).
    argv += ["-oX", "-"]
    # Target in coda, ognuno gia' validato.
    argv += validate_target(req.target)
    return argv


# --------------------------------------------------------------------------- #
# Parsing dell'XML nmap
# --------------------------------------------------------------------------- #


def _attr(el: ET.Element | None, name: str) -> str | None:
    return el.get(name) if el is not None else None


def _int_or_none(value: str | None) -> int | None:
    return int(value) if value is not None else None


def _parse_scripts(elements: list[ET.Element]) -> list[dict[str, Any]]:
    return [{"id": s.get("id"), "output": s.get("output")} for s in elements]


def _parse_host(host_el: ET.Element) -> tuple[dict[str, Any], int]:
    state = _attr(host_el.find("status"), "state")
    ip: str | None = None
    for addr in host_el.findall("address"):
        if addr.get("addrtype") in ("ipv4", "ipv6"):
            ip = addr.get("addr")
            break
    hostname = _attr(host_el.find("hostnames/hostname"), "name")

    ports: list[dict[str, Any]] = []
    ports_open = 0
    for port_el in host_el.findall("ports/port"):
        pstate = _attr(port_el.find("state"), "state")
        if pstate == "open":
            ports_open += 1
        svc = port_el.find("service")
        ports.append(
            {
                "port": _int_or_none(port_el.get("portid")),
                "protocol": port_el.get("protocol"),
                "state": pstate,
                "service": _attr(svc, "name"),
                "product": _attr(svc, "product"),
                "version": _attr(svc, "version"),
                "scripts": _parse_scripts(port_el.findall("script")),
            }
        )

    os_matches = [
        {"name": o.get("name"), "accuracy": _int_or_none(o.get("accuracy"))}
        for o in host_el.findall("os/osmatch")
    ]
    hostscripts = _parse_scripts(host_el.findall("hostscript/script"))
    host = {
        "ip": ip,
        "hostname": hostname,
        "state": state,
        "ports": ports,
        "os": os_matches,
        "hostscripts": hostscripts,
    }
    return host, ports_open


def parse_nmap_xml(xml_text: str) -> dict[str, Any]:
    """Interpreta l'XML nmap (`-oX -`) in {hosts:[...], summary:{...}}."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ScanValidationError(f"XML nmap non valido: {exc}") from exc

    hosts: list[dict[str, Any]] = []
    ports_open = 0
    for host_el in root.findall("host"):
        host, host_ports_open = _parse_host(host_el)
        ports_open += host_ports_open
        hosts.append(host)

    runstats = root.find("runstats/hosts")
    if runstats is not None:
        hosts_up = int(runstats.get("up") or 0)
        hosts_total = int(runstats.get("total") or 0)
    else:
        hosts_up = sum(1 for h in hosts if h["state"] == "up")
        hosts_total = len(hosts)

    return {
        "hosts": hosts,
        "summary": {
            "hosts_up": hosts_up,
            "hosts_total": hosts_total,
            "ports_open": ports_open,
        },
    }
