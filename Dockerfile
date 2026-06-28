FROM python:3.12-slim AS base

# hadolint ignore=DL3008
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        curl && \
    rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    /root/.local/bin/uv --version

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN /root/.local/bin/uv sync --frozen --no-dev --no-install-project

COPY . .
RUN /root/.local/bin/uv sync --frozen --no-dev

RUN mkdir -p data/downloads

HEALTHCHECK --interval=60s --timeout=5s --start-period=30s --retries=3 \
    CMD pgrep -f "python main.py" || exit 1

ENTRYPOINT ["python", "main.py"]
