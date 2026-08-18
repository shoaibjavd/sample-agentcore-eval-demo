FROM --platform=linux/arm64 public.ecr.aws/docker/library/python:3.12-slim

# checkov:skip=CKV_DOCKER_2: Liveness/readiness probing is performed by the Bedrock
# AgentCore runtime, not the image. The slim base has no curl/wget, so an in-image
# HEALTHCHECK would add a dependency without being consumed by the platform.

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Run as an unprivileged user (CKV_DOCKER_3). Dependencies are installed as root
# above; application code below is copied root-owned and world-readable, so the
# runtime user has read-only access to it.
RUN useradd -m -u 1000 bedrock_agentcore
USER bedrock_agentcore

COPY src ./src
COPY server.py .

EXPOSE 8000

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
