import os
import json
import secrets
import sqlite3
import threading
from pathlib import Path
from typing import List, Dict, Any, Optional

# Anchored to the project root so the server finds its data from any working directory.
DATA_DIR = Path(os.environ.get("OMNIDOC_DATA_DIR") or Path(__file__).resolve().parent / ".data")
DB_PATH = DATA_DIR / "omnidoc.db"
DB_PATH.parent.mkdir(exist_ok=True, parents=True)

# Chats created without a signed-in profile belong to this local user.
LOCAL_USER_ID = "usr_local_default"


class OmniDocDB:
    """SQLite persistence for users, sessions, chats, messages and documents."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else DB_PATH
        self._local = threading.local()
        self.init_db()

    @property
    def conn(self):
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(str(self.db_path), timeout=30.0, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            # foreign_keys stays off: legacy databases declare chats.document_id
            # with ON DELETE CASCADE, which would delete conversations along with
            # a document. Deletes cascade explicitly in the methods below.
            self._local.conn = conn
        return self._local.conn

    def init_db(self):
        """Initialize the schema and apply additive migrations to older databases."""
        cursor = self.conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                file_hash TEXT UNIQUE,
                upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                size_bytes INTEGER,
                file_type TEXT,
                is_processed BOOLEAN DEFAULT 0,
                chunk_count INTEGER
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chats (
                id TEXT PRIMARY KEY,
                title TEXT,
                document_id TEXT,
                user_id TEXT DEFAULT 'usr_local_default',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

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

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

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

        # Additive migrations for databases created by earlier versions
        for statement in (
            "ALTER TABLE messages ADD COLUMN metadata TEXT",
            "ALTER TABLE chats ADD COLUMN user_id TEXT DEFAULT 'usr_local_default'",
            "ALTER TABLE documents ADD COLUMN chunk_count INTEGER",
        ):
            try:
                cursor.execute(statement)
            except sqlite3.OperationalError:
                pass
        # Older builds stored anonymous chats under 'usr_default'
        cursor.execute(
            "UPDATE chats SET user_id = ? WHERE user_id IS NULL OR user_id = 'usr_default'",
            (LOCAL_USER_ID,),
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_chats_user ON chats(user_id, updated_at)")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS search_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT,
                query TEXT,
                retrieved_chunks TEXT,
                answer TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        self.conn.commit()

    # ------------------------------------------------------------------ users
    def upsert_user(self, user_id: str, email: str, name: str, provider: str = "local", avatar_url: str = "") -> Dict[str, Any]:
        """Insert or update a user profile."""
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
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
        row = cursor.fetchone()
        return dict(row) if row else None

    # --------------------------------------------------------------- sessions
    def create_session(self, user_id: str) -> str:
        """Issue an opaque random session token for a user."""
        token = "sess_" + secrets.token_urlsafe(32)
        self.conn.execute("INSERT INTO sessions (token, user_id) VALUES (?, ?)", (token, user_id))
        self.conn.commit()
        return token

    def get_session_user_id(self, token: str) -> Optional[str]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT user_id FROM sessions WHERE token = ?", (token,))
        row = cursor.fetchone()
        return row["user_id"] if row else None

    def delete_session(self, token: str):
        self.conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        self.conn.commit()

    # ------------------------------------------------------------------ chats
    def create_chat(self, chat_id: str, document_id: Optional[str] = None, title: str = "New conversation", user_id: str = LOCAL_USER_ID):
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO chats (id, document_id, title, user_id)
            VALUES (?, ?, ?, ?)
        """, (chat_id, document_id, title, user_id))
        self.conn.commit()

    def get_chat(self, chat_id: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get a chat. When user_id is given, only that user's chat is returned."""
        cursor = self.conn.cursor()
        if user_id is None:
            cursor.execute("SELECT * FROM chats WHERE id = ?", (chat_id,))
        else:
            cursor.execute("SELECT * FROM chats WHERE id = ? AND user_id = ?", (chat_id, user_id))
        row = cursor.fetchone()
        return dict(row) if row else None

    def list_chats(self, user_id: str) -> List[Dict[str, Any]]:
        """A user's chats with message counts and a preview of the last message, in one query."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT c.*,
                   (SELECT COUNT(*) FROM messages m WHERE m.chat_id = c.id) AS message_count,
                   (SELECT substr(m.content, 1, 120) FROM messages m
                     WHERE m.chat_id = c.id ORDER BY m.id DESC LIMIT 1) AS last_message
            FROM chats c
            WHERE c.user_id = ?
            ORDER BY c.updated_at DESC, c.created_at DESC
        """, (user_id,))
        chats = []
        for row in cursor.fetchall():
            chat = dict(row)
            chat["last_message"] = chat.get("last_message") or ""
            chats.append(chat)
        return chats

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
        return [dict(row) for row in cursor.fetchall()]

    def update_chat_title(self, chat_id: str, title: str):
        self.conn.execute(
            "UPDATE chats SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (title, chat_id),
        )
        self.conn.commit()

    def delete_chat(self, chat_id: str):
        """Delete a chat and all its messages."""
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
        cursor.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
        self.conn.commit()

    # --------------------------------------------------------------- messages
    def add_message(
        self,
        chat_id: str,
        role: str,
        content: str,
        images: Optional[List[Dict]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """Add a message with optional rich metadata (sources, math, charts, graph, steps)."""
        cursor = self.conn.cursor()
        images_json = json.dumps(images, default=str) if images else None
        metadata_json = json.dumps(metadata, default=str) if metadata else None
        cursor.execute("""
            INSERT INTO messages (chat_id, role, content, images, metadata)
            VALUES (?, ?, ?, ?, ?)
        """, (chat_id, role, content, images_json, metadata_json))
        cursor.execute("UPDATE chats SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (chat_id,))
        self.conn.commit()
        return cursor.lastrowid

    def get_messages(self, chat_id: str) -> List[Dict[str, Any]]:
        """Get all messages in a chat in insertion order, deserializing JSON columns."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM messages WHERE chat_id = ? ORDER BY id ASC", (chat_id,))
        messages = []
        for row in cursor.fetchall():
            msg = dict(row)
            for key in ("images", "metadata"):
                if msg.get(key):
                    try:
                        msg[key] = json.loads(msg[key])
                    except (TypeError, ValueError):
                        pass
            messages.append(msg)
        return messages

    def add_search_record(self, chat_id: str, query: str, chunks: List[str], answer: str):
        """Record a search for analytics."""
        self.conn.execute("""
            INSERT INTO search_history (chat_id, query, retrieved_chunks, answer)
            VALUES (?, ?, ?, ?)
        """, (chat_id, query, json.dumps(chunks, default=str), answer))
        self.conn.commit()

    # -------------------------------------------------------------- documents
    def add_document(self, doc_id: str, filename: str, file_hash: str, size_bytes: int, file_type: str, chunk_count: Optional[int] = None):
        """Register a document (no-op if the same file was registered before)."""
        self.conn.execute("""
            INSERT OR IGNORE INTO documents (id, filename, file_hash, size_bytes, file_type, is_processed, chunk_count)
            VALUES (?, ?, ?, ?, ?, 1, ?)
        """, (doc_id, filename, file_hash, size_bytes, file_type, chunk_count))
        self.conn.commit()

    def get_document(self, doc_id: str) -> Optional[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM documents WHERE id = ?", (doc_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_document_by_hash(self, file_hash: str) -> Optional[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM documents WHERE file_hash = ?", (file_hash,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_all_documents(self) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM documents ORDER BY upload_date DESC")
        return [dict(row) for row in cursor.fetchall()]

    def delete_document(self, doc_id: str):
        self.conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        self.conn.commit()

    def close(self):
        """Close this thread's database connection."""
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
