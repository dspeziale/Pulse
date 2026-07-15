"""Pulse Probe agent (FastAPI).

Poller degli heartbeat dei sistemi assegnati, storage su OpenSearch locale, API
di query strutturata e comunicazione cifrata (token/mTLS) col Server centrale.
Aderente al DOCUMENTO_API.md (endpoint Probe §1.9) e allo schema canonico
heartbeat (01_specifica_funzionale.md §4).
"""

__version__ = "1.0.0"
