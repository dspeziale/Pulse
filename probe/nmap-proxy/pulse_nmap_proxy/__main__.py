"""Entrypoint del proxy nmap: avvia uvicorn con mTLS obbligatorio.

Avvio (di norma via Scheduled Task creato dall'installer):
    python -m pulse_nmap_proxy

Le impostazioni arrivano da variabili d'ambiente / file .env (prefisso
PULSE_NMAP_PROXY_). mTLS: il server richiede un certificato CLIENT firmato dalla
CA (``tls_client_ca_path``) e presenta il proprio certificato server.
"""

from __future__ import annotations

import logging
import ssl
import sys

import uvicorn

from .app import create_app
from .config import get_settings


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    log = logging.getLogger("pulse_nmap_proxy")
    settings = get_settings()

    missing = [name for name, val in (
        ("PULSE_NMAP_PROXY_TOKEN", settings.token),
        ("PULSE_NMAP_PROXY_TLS_CERT_PATH", settings.tls_cert_path),
        ("PULSE_NMAP_PROXY_TLS_KEY_PATH", settings.tls_key_path),
        ("PULSE_NMAP_PROXY_TLS_CLIENT_CA_PATH", settings.tls_client_ca_path),
    ) if not val]
    if missing:
        log.error("Configurazione mancante: %s", ", ".join(missing))
        return 2

    app = create_app(settings)
    log.info("Proxy nmap in ascolto su https://%s:%s (mTLS obbligatorio)",
             settings.host, settings.port)
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        ssl_certfile=settings.tls_cert_path,
        ssl_keyfile=settings.tls_key_path,
        ssl_ca_certs=settings.tls_client_ca_path,
        ssl_cert_reqs=ssl.CERT_REQUIRED,   # mTLS: certificato client obbligatorio
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
