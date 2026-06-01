"""
RAG retriever — the single import used by graph nodes.

    from inditr.rag.retriever import retrieve, retrieve_raw

retrieve(query, topk=4) → str
    Returns a formatted multi-line string ready to inject into any LLM system prompt.
    Falls back to "" if the index is not built (never raises).

retrieve_raw(query, topk) → list[dict]
    Returns the raw zvec results for programmatic use.
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

_collection = None   # lazy-opened, module-level singleton


def _get_collection():
    global _collection
    if _collection is None:
        from inditr.rag.store import open_collection
        _collection = open_collection()
    return _collection


def retrieve_raw(query: str, topk: int = 4) -> list[dict]:
    """
    Embed query with BGE query prefix and search zvec.
    Returns list of dicts: {text, source, section, score}.
    Returns [] on any error (index not built, model not downloaded, etc.).
    """
    try:
        from inditr.rag.embedder import get_embedder
        from zvec import VectorQuery, HnswQueryParam

        embedder  = get_embedder()
        collection = _get_collection()
        query_vec  = embedder.embed_query(query)

        results = collection.query(
            vectors=VectorQuery(
                field_name="embedding",
                vector=query_vec,
                param=HnswQueryParam(ef=100),
            ),
            topk=topk,
            output_fields=["text", "source", "section"],
        )

        return [
            {
                "text":    r.field("text"),
                "source":  r.field("source"),
                "section": r.field("section"),
                "score":   r.score,
            }
            for r in results
        ]

    except FileNotFoundError:
        logger.warning("RAG index not found — skipping retrieval. Run: python scripts/build_rag_index.py")
        return []
    except Exception as e:
        logger.warning("RAG retrieval failed (%s) — continuing without context", e)
        return []


def retrieve(query: str, topk: int = 4, score_threshold: float = 0.25) -> str:
    """
    Retrieve relevant tax rules and format them for LLM prompt injection.

    score_threshold: cosine similarity cutoff (0-1); drop low-quality matches.
    Returns "" if nothing useful is found or index is not built.

    Inject into a system prompt like:
        if rag_ctx:
            system_prompt += f"\\n\\nRELEVANT TAX RULES (use these, do not contradict):\\n{rag_ctx}"
    """
    hits = retrieve_raw(query, topk=topk)
    # Filter by score — cosine similarity on BGE tends to be ~0.3–0.9 for relevant hits
    hits = [h for h in hits if h["score"] >= score_threshold]

    if not hits:
        return ""

    lines = []
    for i, h in enumerate(hits, 1):
        lines.append(
            f"[{i}] {h['section']} (from {h['source']})\n{h['text']}"
        )

    return "\n\n".join(lines)
