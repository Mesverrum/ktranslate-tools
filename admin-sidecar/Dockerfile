# Multi-stage so we can pull just the docker CLI binary from the official
# docker:cli image without dragging in the whole engine.
FROM docker:cli AS docker-cli

FROM python:3.11-slim
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker-cli /usr/local/libexec/docker /usr/local/libexec/docker

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
