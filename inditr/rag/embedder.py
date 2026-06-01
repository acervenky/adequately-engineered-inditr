"""
Local dense embedder for IndITR RAG.

Default model: BAAI/bge-small-en-v1.5
  - 33M params, 384 dims
  - Runs on CPU without a GPU or network call
  - Slightly outperforms GTE-small on MTEB retrieval benchmarks (~62.7 vs 61.4)
  - First call downloads ~130 MB from HuggingFace (cached in ~/.cache/huggingface/)

Override via env:
    RAG_EMBED_MODEL=BAAI/bge-base-en-v1.5   # 768 dims, better quality, 109M params
    RAG_EMBED_MODEL=thenlper/gte-small        # alternative 384-dim model

The class implements the DenseEmbeddingFunction protocol expected by zvec:
    embedder.embed(text: str) -> list[float]
    embedder.dimension: int
"""
from __future__ import annotations
import os
import logging

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
_BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class BgeEmbedder:
    """
    Wraps sentence-transformers for zvec's DenseEmbeddingFunction protocol.

    BGE models expect a query-time prefix for retrieval tasks (not at index time):
        https://huggingface.co/BAAI/bge-small-en-v1.5#usage

    Use embed() for document indexing (no prefix).
    Use embed_query() for search queries (adds prefix for better retrieval).
    """

    def __init__(self, model_name: str | None = None) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise ImportError(
                "sentence-transformers is required for RAG. "
                "Install with: pip install sentence-transformers"
            ) from e

        self.model_name = model_name or os.getenv("RAG_EMBED_MODEL", _DEFAULT_MODEL)
        logger.info("Loading embedding model: %s", self.model_name)
        self._model = SentenceTransformer(self.model_name)
        # get_embedding_dimension() is the new name; fall back for older versions
        _dim_fn = getattr(
            self._model, "get_embedding_dimension",
            getattr(self._model, "get_sentence_embedding_dimension", None),
        )
        self.dimension: int = _dim_fn() if _dim_fn else 384
        self._is_bge = "bge" in self.model_name.lower()
        logger.info("Embedder ready — model=%s, dim=%d", self.model_name, self.dimension)

    def embed(self, text: str) -> list[float]:
        """Embed a document chunk (no query prefix — for indexing)."""
        vec = self._model.encode(
            text,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return vec.tolist()

    def embed_query(self, query: str) -> list[float]:
        """Embed a search query (adds BGE retrieval prefix if applicable)."""
        if self._is_bge:
            query = _BGE_QUERY_PREFIX + query
        return self.embed(query)

    # ── zvec DenseEmbeddingFunction protocol ────────────────────────────────
    # zvec calls embedder.embed(text) at query time (treat as embed_query).
    # We expose both methods so callers can be explicit.


_embedder: BgeEmbedder | None = None


def get_embedder() -> BgeEmbedder:
    """Return the shared singleton embedder (lazy-loaded on first call)."""
    global _embedder
    if _embedder is None:
        _embedder = BgeEmbedder()
    return _embedder
