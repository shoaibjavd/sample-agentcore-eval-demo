# Base image pinned by digest (TS011). Tag 3.12-slim is mutable; the digest below
# is python:3.12-slim as verified for linux/arm64. Update deliberately.
FROM --platform=linux/arm64 public.ecr.aws/docker/library/python@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a

# checkov:skip=CKV_DOCKER_2: Liveness/readiness probing is performed by the Bedrock
# AgentCore runtime, not the image. The slim base has no curl/wget, so an in-image
# HEALTHCHECK would add a dependency without being consumed by the platform.

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    DOCKER_CONTAINER=1 \
    AWS_REGION=ap-southeast-2 \
    AWS_DEFAULT_REGION=ap-southeast-2

COPY pyproject.toml pyproject.toml
RUN pip install --no-cache-dir .

ENV BUILD_VERSION=7

RUN useradd -m -u 1000 bedrock_agentcore
USER bedrock_agentcore

EXPOSE 9000
EXPOSE 8000
EXPOSE 8080

COPY src/ .

CMD ["opentelemetry-instrument", "python", "-m", "assistant_agent"]
