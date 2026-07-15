# Dashboard SERVER Pulse (Flask servito da gunicorn).
#
# IMPORTANTE (SCOSTAMENTO documentato nel README): il build context DEVE essere la
# radice del repository, perché la dashboard dipende dal pacchetto condiviso
# `frontend_common/` che vive fuori da `server/dashboard/`. Esempio compose:
#
#   dashboard-server:
#     build:
#       context: .
#       dockerfile: server/dashboard/Dockerfile
#     environment:
#       PULSE_SERVER_DASH_PORT: 5000
#       PULSE_SERVER_API_BASE: http://backend:8000/api/v1
#     ports: ["5000:5000"]
#
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PULSE_SERVER_DASH_PORT=5000

WORKDIR /app

# 1) Pacchetto condiviso (sorgente di verità in frontend_common/).
COPY frontend_common/ /app/frontend_common/
RUN pip install --no-cache-dir /app/frontend_common

# 2) Dipendenze e codice della dashboard.
COPY server/dashboard/requirements.txt /app/dashboard/requirements.txt
RUN pip install --no-cache-dir -r /app/dashboard/requirements.txt
COPY server/dashboard/ /app/dashboard/

WORKDIR /app/dashboard

EXPOSE 5000

# La porta è letta da env (default 5000, documentato in .env.example).
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request,sys; p=os.environ.get('PULSE_SERVER_DASH_PORT','5000'); sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+p+'/healthz',timeout=3).status==200 else 1)"

CMD gunicorn --bind 0.0.0.0:${PULSE_SERVER_DASH_PORT:-5000} --workers 2 app:app
