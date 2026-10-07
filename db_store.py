import sqlite3
import threading
from pathlib import Path
from datetime import datetime
import json
from typing import List, Dict, Any, Optional

DB_PATH = Path(".data/omnidoc.db")
DB_PATH.parent.mkdir(exist_ok=True, parents=True)


class OmniDocDB:
    """SQLite database for persisting chats, documents, and embeddings metadata."""
    
    def __init__(self):
        self.db_path = DB_PATH
        self._local = threading.local()
        self.init_db()

    @property
    def conn(self):
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(str(self.db_path), timeout=30.0, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return self._local.conn

    def init_db(self):
        """Initialize database schema."""
        cursor = self.conn.cursor()
        
        # Documents table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                file_hash TEXT UNIQUE,
                upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                size_bytes INTEGER,
                file_type TEXT,
                is_processed BOOLEAN DEFAULT 0
            )
        """)
        
        # Chats table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chats (
                id TEXT PRIMARY KEY,
                title TEXT,
                document_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
            )
        """)
        
        # Users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE,
                name TEXT,
                provider TEXT,
                avatar_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Messages table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                images TEXT,
                metadata TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
            )
        """)

        # Safe schema migrations for existing databases
        try:
            cursor.execute("ALTER TABLE messages ADD COLUMN metadata TEXT")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE chats ADD COLUMN user_id TEXT DEFAULT 'usr_default'")
        except Exception:
            pass
        
        # Vector metadata (for retrieval tracking)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS vector_metadata (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id TEXT NOT NULL,
                chunk_index INTEGER,
                chunk_text TEXT,
                embedding_hash TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
            )
        """)
        
        # Search history
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS search_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT,
                query TEXT,
                retrieved_chunks TEXT,
                answer TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
            )
        """)
        
        self.conn.commit()

    def add_document(self, doc_id: str, filename: str, file_hash: str, size_bytes: int, file_type: str):
        """Register a document."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO documents (id, filename, file_hash, size_bytes, file_type)
            VALUES (?, ?, ?, ?, ?)
        """, (doc_id, filename, file_hash, size_bytes, file_type))
        self.conn.commit()

    def upsert_user(self, user_id: str, email: str, name: str, provider: str = "email", avatar_url: str = "") -> Dict[str, Any]:
        """Insert or update user profile."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO users (id, email, name, provider, avatar_url)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                email = excluded.email,
                name = excluded.name,
                provider = excluded.provider,
                avatar_url = excluded.avatar_url
        """, (user_id, email, name, provider, avatar_url))
        self.conn.commit()
        return self.get_user(user_id)

    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user by ID."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get user by email."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def create_chat(self, chat_id: str, document_id: Optional[str] = None, title: str = "New Chat", user_id: str = "usr_default"):
        """Create a new chat session."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO chats (id, document_id, title, user_id)
            VALUES (?, ?, ?, ?)
        """, (chat_id, document_id, title, user_id))
        self.conn.commit()

    def get_chat(self, chat_id: str) -> Optional[Dict[str, Any]]:
        """Get chat details."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM chats WHERE id = ?", (chat_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def add_message(
        self,
        chat_id: str,
        role: str,
        content: str,
        images: Optional[List[Dict]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """Add a message to chat with optional rich metadata (math, viz, citations, graph)."""
        cursor = self.conn.cursor()
        images_json = json.dumps(images, default=str) if images else None
        metadata_json = json.dumps(metadata, default=str) if metadata else None
        cursor.execute("""
            INSERT INTO messages (chat_id, role, content, images, metadata)
            VALUES (?, ?, ?, ?, ?)
        """, (chat_id, role, content, images_json, metadata_json))
        # Update chat updated_at
        cursor.execute("UPDATE chats SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (chat_id,))
        self.conn.commit()
        return cursor.lastrowid

    def get_messages(self, chat_id: str) -> List[Dict[str, Any]]:
        """Get all messages in a chat, deserializing images and metadata."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM messages WHERE chat_id = ? ORDER BY timestamp ASC
        """, (chat_id,))
        rows = cursor.fetchall()
        messages = []
        for row in rows:
            msg = dict(row)
            if msg.get('images'):
                try:
                    msg['images'] = json.loads(msg['images'])
                except Exception:
                    pass
            if msg.get('metadata'):
                try:
                    msg['metadata'] = json.loads(msg['metadata'])
                except Exception:
                    pass
            messages.append(msg)
        return messages

    def get_all_chats(self, user_id: Optional[str] = None, document_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all chats, optionally filtered by user and document."""
        cursor = self.conn.cursor()
        query = "SELECT * FROM chats WHERE 1=1"
        params = []
        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)
        if document_id:
            query += " AND document_id = ?"
            params.append(document_id)
        query += " ORDER BY updated_at DESC"
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def update_chat_title(self, chat_id: str, title: str):
        """Update chat title."""
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE chats SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?
        """, (title, chat_id))
        self.conn.commit()

    def add_search_record(self, chat_id: str, query: str, chunks: List[str], answer: str):
        """Record a search for analytics."""
        cursor = self.conn.cursor()
        chunks_json = json.dumps(chunks, default=str)
        cursor.execute("""
            INSERT INTO search_history (chat_id, query, retrieved_chunks, answer)
            VALUES (?, ?, ?, ?)
        """, (chat_id, query, chunks_json, answer))
        self.conn.commit()

    def get_document_by_hash(self, file_hash: str) -> Dict[str, Any]:
        """Get document by file hash."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM documents WHERE file_hash = ?", (file_hash,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_all_documents(self) -> List[Dict[str, Any]]:
        """Get all registered documents."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM documents ORDER BY upload_date DESC")
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def delete_document(self, doc_id: str):
        """Delete a document and cascade to its associated records."""
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        self.conn.commit()

    def delete_chat(self, chat_id: str):
        """Delete a chat and all its messages."""
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
        self.conn.commit()

    def close(self):
        """Close database connection."""
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
