#!/usr/bin/env python
"""
Build (or rebuild) the IndITR RAG vector index.

What it does:
  1. Loads BGE-small-en-v1.5 via sentence-transformers (~130 MB, cached after first run)
  2. Reads all .md files from inditr/rag/knowledge/
  3. Chunks by heading + sliding window
  4. Embeds each chunk (CPU inference, ~1-2 min for full knowledge base)
  5. Writes to ./rag_index/ (zvec persistent store)

Run from the project root:
    python scripts/build_rag_index.py

Options:
    --model   Override embedding model (default: BAAI/bge-small-en-v1.5)
    --path    Override index output path (default: ./rag_index)
    --verify  After building, run a few test queries to confirm retrieval works
"""
import sys
import os
import argparse
import logging
import time

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("build_rag")


def parse_args():
    p = argparse.ArgumentParser(description="Build IndITR RAG index")
    p.add_argument("--model",  default=None, help="Embedding model name (HuggingFace)")
    p.add_argument("--path",   default=None, help="Output path for zvec index")
    p.add_argument("--verify", action="store_true", help="Run test queries after build")
    return p.parse_args()


VERIFY_QUERIES = [
    ("80C deduction limit for AY 2026-27",         "1,50,000"),
    ("new regime tax slabs AY 2026-27",             "4,00,000"),
    ("LTCG exemption on equity mutual funds",       "1,25,000"),
    ("ITR-1 eligibility house property",            "two house"),
    ("87A rebate under new regime",                 "12,00,000"),
    ("TDS on salary section 192",                   "192"),
]


def main():
    args = parse_args()

    if args.model:
        os.environ["RAG_EMBED_MODEL"] = args.model
    if args.path:
        os.environ["RAG_INDEX_PATH"] = args.path

    logger.info("=" * 60)
    logger.info("IndITR RAG Index Builder")
    logger.info("=" * 60)

    # Show config
    from inditr.rag.store import get_index_path
    embed_model = os.getenv("RAG_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
    logger.info("Embedding model : %s", embed_model)
    logger.info("Index path      : %s", get_index_path())

    # Build
    t0 = time.time()
    try:
        from inditr.rag.indexer import build_index
        total = build_index()
    except ImportError as e:
        logger.error("Missing dependency: %s", e)
        logger.error("Install with: pip install sentence-transformers zvec")
        sys.exit(1)
    except FileNotFoundError as e:
        logger.error("%s", e)
        sys.exit(1)

    elapsed = time.time() - t0
    logger.info("=" * 60)
    logger.info("Build complete: %d chunks indexed in %.1fs", total, elapsed)
    logger.info("=" * 60)

    if not args.verify:
        logger.info("Tip: run with --verify to test retrieval quality")
        return

    # Verification queries
    logger.info("\nRunning verification queries...")
    from inditr.rag.retriever import retrieve_raw

    passed = 0
    for query, expected_substr in VERIFY_QUERIES:
        hits = retrieve_raw(query, topk=3)
        found = any(expected_substr.lower() in h["text"].lower() for h in hits)
        status = "PASS" if found else "FAIL"
        if found:
            passed += 1
        top_score = hits[0]["score"] if hits else 0.0
        logger.info("  [%s] %-50s  top_score=%.3f", status, query[:50], top_score)

    logger.info("\nVerification: %d/%d queries passed", passed, len(VERIFY_QUERIES))
    if passed < len(VERIFY_QUERIES) * 0.8:
        logger.warning("Low pass rate — check knowledge base content or embedding model")
    else:
        logger.info("RAG index is ready to use.")


if __name__ == "__main__":
    main()
