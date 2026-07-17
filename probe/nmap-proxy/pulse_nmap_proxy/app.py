"""App FastAPI del proxy nmap: /health e /scan (mTLS a livello transport).

SICUREZZA:
 - Autenticazione Bearer (token condiviso con l'agent) su OGNI endpoint.
 - mTLS applicato dal server ASGI (vedi __main__): solo client con certificato
   firmato dalla CA sono ammessi al transport.
 - L'argv ricevuto e' SEMPRE ri-validato con ``nmap_scan.assert_safe_argv``
   (stessa whitelist dell'agent): niente comandi arbitrari, output XML solo su
   stdout, target validati. Il binario reale nmap sostituisce argv[0].
 - nmap e' eseguito con argv COME LISTA, shell=False.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from pulse_probe import nmap_scan  # unica fonte di verita' per la validazione

from . import __version__
from .config import ProxySettings, get_settings

logger = logging.getLogger("pulse_nmap_proxy")

#: Firma del runner reale: (argv, timeout) -> (returncode, stdout, stderr).
Runner = Callable[[list[str], int], tuple[int, str, str]]


class ScanArgv(BaseModel):
    """Payload di /scan: argv gia' costruito dall'agent + timeout."""

    argv: list[str] = Field(min_length=1)
    timeout: int = Field(default=1800, ge=1)


def run_nmap(argv: list[str], timeout: int) -> tuple[int, str, str]:
    """Esegue nmap nativo (argv lista, shell=False). Ritorna (rc, stdout, stderr)."""
    proc = subprocess.run(  # noqa: S603 - argv lista ri-validata, shell=False
        argv, capture_output=True, text=True, timeout=timeout, check=False
    )
    return proc.returncode, proc.stdout, proc.stderr


def detect_nmap(nmap_path: str, runner: Runner) -> tuple[bool, str | None]:
    """Verifica nmap nativo e ne ritorna la prima riga di versione."""
    try:
        rc, out, _ = runner([nmap_path, "--version"], 10)
    except (OSError, subprocess.SubprocessError):
        return False, None
    if rc != 0:
        return False, None
    first = out.strip().splitlines()[0] if out.strip() else None
    return True, first


def create_app(settings: ProxySettings | None = None, *, runner: Runner | None = None) -> FastAPI:
    settings = settings or get_settings()
    run: Runner = runner or run_nmap
    app = FastAPI(title="Pulse nmap proxy", version=__version__)

    def require_token(authorization: str | None = Header(default=None)) -> None:
        expected = settings.token
        if not expected:  # configurazione errata: mai autorizzare
            raise HTTPException(status_code=500, detail="Proxy senza token configurato.")
        if authorization != f"Bearer {expected}":
            raise HTTPException(status_code=401, detail="Token non valido.")

    @app.get("/health")
    def health(_: None = Depends(require_token)) -> dict[str, object]:
        ok, version = detect_nmap(settings.nmap_path, run)
        return {"status": "ok", "nmap_available": ok, "nmap_version": version}

    @app.post("/scan")
    def scan(body: ScanArgv, _: None = Depends(require_token)) -> dict[str, object]:
        # Ri-validazione dell'argv (l'argv arriva con binario logico "nmap").
        try:
            nmap_scan.assert_safe_argv(body.argv, binary="nmap")
        except nmap_scan.ScanValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        timeout = min(body.timeout, settings.max_scan_timeout)
        # Sostituisce il binario logico con il percorso reale di nmap sull'host.
        argv = [settings.nmap_path, *body.argv[1:]]
        try:
            rc, out, err = run(argv, timeout)
        except subprocess.TimeoutExpired:
            return {"returncode": 1, "stdout": "",
                    "stderr": "Timeout della scansione nmap superato."}
        except OSError as exc:
            return {"returncode": 1, "stdout": "",
                    "stderr": f"Impossibile eseguire nmap sull'host: {exc}"}
        return {"returncode": rc, "stdout": out, "stderr": err}

    return app
