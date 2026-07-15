# =============================================================================
# Pulse Probe agent (FastAPI) — immagine Python slim
# Build:  docker build -t pulse-probe-agent probe/agent
# Run:    docker run -p 8444:8444 --env-file probe.env pulse-probe-agent
# =============================================================================
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PULSE_PROBE_API_PORT=8444

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY pulse_probe ./pulse_probe
COPY pyproject.toml README.md ./

RUN useradd --create-home --uid 10002 pulse
USER pulse

EXPOSE 8444

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os,urllib.request,sys; \
port=os.environ.get('PULSE_PROBE_API_PORT','8444'); \
sys.exit(0) if urllib.request.urlopen(f'http://127.0.0.1:{port}/api/v1/health', timeout=3).status==200 else sys.exit(1)"

CMD ["sh", "-c", "gunicorn pulse_probe.main:app -k uvicorn.workers.UvicornWorker -b 0.0.0.0:${PULSE_PROBE_API_PORT:-8444} --workers 1 --access-logfile - --error-logfile -"]
