"""Middleware di hardening HTTP (SEC-01).

Aggiunge header di sicurezza di base adatti a una API JSON e neutralizza il
banner `Server` di uvicorn (che rivelerebbe lo stack). HSTS e' attivabile via
configurazione, da usare solo quando il servizio e' esposto in HTTPS.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import Response

from .config import get_settings

# CSP restrittiva: una API JSON non serve risorse attive; blocca tutto e nega il
# framing. `frame-ancestors 'none'` rafforza X-Frame-Options.
_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"


async def security_headers_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Imposta gli header di sicurezza su ogni risposta."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = _CSP
    response.headers["Referrer-Policy"] = "no-referrer"
    # Neutralizza il banner dello stack (uvicorn lo imposta a "uvicorn").
    response.headers["Server"] = "Pulse"
    settings = get_settings()
    if settings.hsts_enabled:
        response.headers["Strict-Transport-Security"] = (
            f"max-age={settings.hsts_max_age_seconds}; includeSubDomains"
        )
    return response
