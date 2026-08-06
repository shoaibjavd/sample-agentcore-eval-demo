FROM --platform=linux/arm64 public.ecr.aws/docker/library/python:3.12-slim
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
