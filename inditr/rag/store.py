"""
Zvec collection management for IndITR RAG.

Schema:
    id          — chunk ID (doc_slug + chunk index)
    embedding   — VECTOR_FP32, dim from embedder (384 for bge-small)
    fields:
        text    — raw chunk text (returned in results)
        source  — filename / document slug
        section — heading context (e.g. "80C Deductions > PPF")

Collection persists at RAG_INDEX_PATH (default: ./rag_index/).
"""
from __future__ import annotations
import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_INDEX_PATH = "./rag_index"


def get_index_path() -> str:
    return os.getenv("RAG_INDEX_PATH", _DEFAULT_INDEX_PATH)


def _build_schema(dimension: int):
    import zvec
    from zvec import CollectionSchema, VectorSchema, DataType, HnswIndexParam, MetricType, FieldSchema

    return CollectionSchema(
        name="inditr_rag",
        vectors=VectorSchema(
            name="embedding",
            data_type=DataType.VECTOR_FP32,
            dimension=dimension,
            index_param=HnswIndexParam(
                ef_construction=200,
                m=16,
                metric_type=MetricType.COSINE,
            ),
        ),
        fields=[
            FieldSchema(name="text",    data_type=zvec.DataType.STRING),
            FieldSchema(name="source",  data_type=zvec.DataType.STRING),
            FieldSchema(name="section", data_type=zvec.DataType.STRING),
        ],
    )


def create_collection(dimension: int):
    """Create a fresh zvec collection (wipes existing data at path)."""
    import zvec
    import shutil

    path = get_index_path()
    if Path(path).exists():
        shutil.rmtree(path)
        logger.info("Removed existing index at %s", path)

    schema = _build_schema(dimension)
    collection = zvec.create_and_open(path=path, schema=schema)
    logger.info("Created zvec collection at %s (dim=%d)", path, dimension)
    return collection


def open_collection():
    """Open an existing zvec collection. Raises FileNotFoundError if not built yet."""
    import zvec

    path = get_index_path()
    if not Path(path).exists():
        raise FileNotFoundError(
            f"RAG index not found at '{path}'. "
            "Build it first: python scripts/build_rag_index.py"
        )
    collection = zvec.open(path=path)
    logger.info("Opened zvec collection at %s", path)
    return collection


def index_ready() -> bool:
    """Return True if the RAG index has been built and exists on disk."""
    return Path(get_index_path()).exists()
