def build_graph(*args, **kwargs):
    # Lazy import: avoids pulling in langgraph at module load time.
    from .graph import build_graph as _build
    return _build(*args, **kwargs)

__all__ = ["build_graph"]
