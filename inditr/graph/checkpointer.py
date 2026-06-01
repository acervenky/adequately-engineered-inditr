"""
SqliteSaver setup for LangGraph checkpointing.
Uses SQLITE_DB_PATH env var (default: sessions.db).
Note: SqliteSaver.from_conn_string is a context manager in langgraph-checkpoint-sqlite >= 3.x.
For long-lived use outside a context manager, use sqlite3.connect directly.
"""
from __future__ import annotations
import os
import sqlite3
from dotenv import load_dotenv

load_dotenv()


def get_checkpointer():
    """Return a configured SqliteSaver instance."""
    db_path = os.getenv("SQLITE_DB_PATH", "sessions.db")
    from langgraph.checkpoint.sqlite import SqliteSaver
    conn = sqlite3.connect(db_path, check_same_thread=False)
    return SqliteSaver(conn)
