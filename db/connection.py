"""
Database Connection Manager for OmniDoc.
Provides PostgreSQL connection with automatic SQLite fallback for zero-downtime local development.
"""
import os
import sqlite3
import logging
from typing import Optional

logger = logging.getLogger("OmniDoc.DB")


class DatabaseManager:
    """Manages persistent database connections (PostgreSQL / SQLite)."""

    def __init__(self, db_url: Optional[str] = None):
        self.db_url = db_url or os.getenv("DATABASE_URL")
        self.is_postgres = False
        self.sqlite_path = ".data/omnidoc.db"
        os.makedirs(".data", exist_ok=True)
        self._init_connection()

    def _init_connection(self):
        """Attempts PostgreSQL connection, falling back to SQLite."""
        if self.db_url and self.db_url.startswith("postgres"):
            try:
                import psycopg2
                conn = psycopg2.connect(self.db_url)
                conn.close()
                self.is_postgres = True
                logger.info("Connected to PostgreSQL persistence layer.")
                self._init_postgres_schema()
                return
            except Exception as e:
                logger.warning(f"PostgreSQL connection failed ({e}). Falling back to SQLite.")

        self.is_postgres = False
        logger.info(f"Using SQLite database at {self.sqlite_path}")
        self._init_sqlite_schema()

    def get_connection(self):
        """Returns active database connection."""
        if self.is_postgres:
            import psycopg2
            return psycopg2.connect(self.db_url)
        return sqlite3.connect(self.sqlite_path)

    def _init_sqlite_schema(self):
        """Initializes tables in SQLite."""
        conn = sqlite3.connect(self.sqlite_path)
        cur = conn.cursor()
        
        cur.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            file_hash TEXT UNIQUE NOT NULL,
            file_type TEXT NOT NULL,
            page_count INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id TEXT PRIMARY KEY,
            title TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            citations TEXT,
            faithfulness_score REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES chat_sessions(id)
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS agent_traces (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            node_name TEXT NOT NULL,
            state_snapshot TEXT,
            duration_ms REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        conn.commit()
        conn.close()

    def _init_postgres_schema(self):
        """Initializes tables in PostgreSQL."""
        conn = self.get_connection()
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id VARCHAR(64) PRIMARY KEY,
            filename TEXT NOT NULL,
            file_hash VARCHAR(64) UNIQUE NOT NULL,
            file_type VARCHAR(16) NOT NULL,
            page_count INT DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id VARCHAR(64) PRIMARY KEY,
            title TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS messages (
            id VARCHAR(64) PRIMARY KEY,
            session_id VARCHAR(64) REFERENCES chat_sessions(id),
            role VARCHAR(16) NOT NULL,
            content TEXT NOT NULL,
            citations JSONB,
            faithfulness_score FLOAT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS agent_traces (
            id VARCHAR(64) PRIMARY KEY,
            session_id VARCHAR(64),
            node_name VARCHAR(64),
            state_snapshot JSONB,
            duration_ms FLOAT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        conn.commit()
        conn.close()
