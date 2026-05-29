# Multi-stage so we can pull just the docker CLI binary from the official
# docker:cli image without dragging in the whole engine.
FROM docker:cli AS docker-cli

FROM python:3.11-slim
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker-cli /usr/local/libexec/docker /usr/local/libexec/docker

# Tools that KtransToGrafana's scripts/ rely on:
#   - envsubst (from gettext-base)   used by generate-groups.sh
#   - yq (Mike Farah's Go version)   used by run-discovery.sh and preflight.sh
# Debian's apt `yq` package is a different (Python) tool — pull the real one
# from GitHub releases instead.
RUN apt-get update && \
    apt-get install -y --no-install-recommends gettext-base ca-certificates curl && \
    curl -sSL -o /usr/local/bin/yq \
      https://github.com/mikefarah/yq/releases/latest/download/yq_linux_amd64 && \
    chmod +x /usr/local/bin/yq && \
    apt-get purge -y curl && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# Where the KtransToGrafana checkout is bind-mounted at runtime. The
# sidecar reads groups/*.env, writes them back, runs generate-groups.sh,
# and signals pollers via `docker compose kill -s HUP` from this path.
ENV WORKSPACE=/workspace

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
