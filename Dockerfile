# Omnipuls in Docker: one image for the web app, the market data recorder and the auto-updater.
# The code itself is NOT baked in: docker-compose mounts this repository folder, and the updater service pulls new
# commits from GitHub every 5 minutes, so merging on GitHub updates the server with no login to it.
ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=Asia/Kolkata PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install -y --no-install-recommends git tzdata ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && sha1sum /tmp/requirements.txt | cut -d" " -f1 > /tmp/.req_hash
COPY deploy/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
WORKDIR /app/code
ENTRYPOINT ["/entrypoint.sh"]
