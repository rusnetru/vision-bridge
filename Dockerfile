FROM python:3.11-slim

WORKDIR /app

# System deps for OCR fallback (optional — server works without)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-rus \
    && rm -rf /var/lib/apt/lists/*

# Install project
COPY pyproject.toml README.md ./
COPY src/ src/
RUN pip install --no-cache-dir .

# MCP stdio transport — Glama проверяет introspection
CMD ["python", "-m", "vision_bridge.server"]
