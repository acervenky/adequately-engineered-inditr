"""
IndITR RAG — in-process vector search powered by zvec + Ollama embeddings.

Usage:
    from inditr.rag.retriever import retrieve
    context = retrieve("what is the 80C deduction limit", topk=3)
    # context is a formatted string ready to inject into any LLM prompt

Build/rebuild the index:
    python scripts/build_rag_index.py
"""
