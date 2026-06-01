# IndITR API — Python 3.12 slim
# Multi-stage: deps layer (slow, cached) + source layer (fast rebuild)

FROM python:3.12-slim AS base

# System libs:
#   poppler-utils  — pdf2image page rasterisation
#   libgl1         — OpenCV dep pulled by some sentence-transformer builds
RUN apt-get update && apt-get install -y --no-install-recommends \
        poppler-utils \
        libgl1 \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Dependency layer (cached until pyproject.toml changes) ────────────────────
COPY pyproject.toml ./
# Stub package so editable install resolves without full source
RUN mkdir -p inditr && touch inditr/__init__.py

# Install CPU-only PyTorch BEFORE everything else.
# sentence-transformers pulls torch as a dep; if torch isn't already present it
# grabs the default wheel which is the full CUDA build (~530 MB).
# Installing the CPU wheel first (~200 MB) prevents that.
RUN pip install --no-cache-dir \
    torch torchvision torchaudio \
    --index-url https://download.pytorch.org/whl/cpu

RUN pip install --no-cache-dir -e ".[dev]"

# ── Source layer (rebuilt on every code change) ───────────────────────────────
COPY . .
# Re-install in editable mode so entry-points point at the real source
RUN pip install --no-cache-dir -e ".[dev]"

# Runtime data dirs (overridden by Docker volumes in compose)
RUN mkdir -p /data/outputs /data/rag_index

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=120s --retries=5 \
    CMD curl -f http://localhost:8000/health || exit 1

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
