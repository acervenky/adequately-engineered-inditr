#!/bin/sh
# IndITR container entrypoint
# Builds the RAG index on first startup (writes to the app_data volume so it
# persists across restarts), then hands off to uvicorn.
set -e

RAG_PATH="${RAG_INDEX_PATH:-/data/rag_index}"
MARKER="$RAG_PATH/.index_built"

if [ ! -f "$MARKER" ]; then
    echo "[entrypoint] RAG index not found — building now (this takes ~1-2 min on first run)..."
    python scripts/build_rag_index.py --path "$RAG_PATH"
    touch "$MARKER"
    echo "[entrypoint] RAG index ready."
else
    echo "[entrypoint] RAG index already built — skipping."
fi

exec uvicorn inditr.api.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 1 \
    --timeout-keep-alive 75
