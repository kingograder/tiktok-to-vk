FROM python:3.12-slim

# hadolint ignore=DL3008
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p data/downloads

HEALTHCHECK --interval=60s --timeout=5s --start-period=30s --retries=3 \
    CMD pgrep -f "python main.py" || exit 1

ENTRYPOINT ["python", "main.py"]
