# =============================================================================
# Pulse Server backend (FastAPI) — immagine Python slim
# Build:  docker build -t pulse-server-backend server/backend
# Run:    docker run -p 8443:8443 --env-file server.env pulse-server-backend
# =============================================================================
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PULSE_API_PORT=8443

WORKDIR /app

# Dipendenze prima del codice (cache dei layer).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Codice applicativo.
COPY pulse_server ./pulse_server
COPY pyproject.toml README.md ./

# Utente non-root.
RUN useradd --create-home --uid 10001 pulse
USER pulse

EXPOSE 8443

# Healthcheck applicativo (usa la stdlib, nessun tool extra).
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os,urllib.request,sys; \
port=os.environ.get('PULSE_API_PORT','8443'); \
sys.exit(0) if urllib.request.urlopen(f'http://127.0.0.1:{port}/api/v1/health', timeout=3).status==200 else sys.exit(1)"

# uvicorn con piu' worker; porta via env (default 8443).
# --no-server-header (SEC-01): sopprime il banner "Server: uvicorn"; l'header
# "Server: Pulse" e' impostato dal middleware applicativo.
CMD ["sh", "-c", "uvicorn pulse_server.main:app --host 0.0.0.0 --port ${PULSE_API_PORT:-8443} --workers ${PULSE_WORKERS:-2} --no-server-header"]
