"""Database persistence module for OmniDoc."""
import sqlite3
from pathlib import Path
from datetime import datetime
import json
from typing import List, Dict, Any

DB_PATH = Path(".data/omnidoc.db")
DB_PATH.parent.mkdir(exist_ok=True, parents=True)


class OmniDocDB:
    """SQLite database for persisting chats, documents, and embeddings metadata."""
    
    def __init__(self):
        self.db_path = DB_PATH
        self.conn = None
        self.init_db()

    def init_db(self):
        """Initialize database schema."""
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
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
        
        # Messages table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                images TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
            )
        """)
        
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

    def create_chat(self, chat_id: str, document_id: str, title: str = "New Chat"):
        """Create a new chat session."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO chats (id, document_id, title)
            VALUES (?, ?, ?)
        """, (chat_id, document_id, title))
        self.conn.commit()

    def get_chat(self, chat_id: str) -> Dict[str, Any]:
        """Get chat details."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM chats WHERE id = ?", (chat_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def add_message(self, chat_id: str, role: str, content: str, images: List[Dict] = None):
        """Add a message to chat."""
        cursor = self.conn.cursor()
        images_json = json.dumps(images) if images else None
        cursor.execute("""
            INSERT INTO messages (chat_id, role, content, images)
            VALUES (?, ?, ?, ?)
        """, (chat_id, role, content, images_json))
        self.conn.commit()
        return cursor.lastrowid

    def get_messages(self, chat_id: str) -> List[Dict[str, Any]]:
        """Get all messages in a chat."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM messages WHERE chat_id = ? ORDER BY timestamp ASC
        """, (chat_id,))
        rows = cursor.fetchall()
        messages = []
        for row in rows:
            msg = dict(row)
            if msg['images']:
                msg['images'] = json.loads(msg['images'])
            messages.append(msg)
        return messages

    def get_all_chats(self, document_id: str = None) -> List[Dict[str, Any]]:
        """Get all chats, optionally filtered by document."""
        cursor = self.conn.cursor()
        if document_id:
            cursor.execute("""
                SELECT * FROM chats WHERE document_id = ? ORDER BY updated_at DESC
            """, (document_id,))
        else:
            cursor.execute("SELECT * FROM chats ORDER BY updated_at DESC")
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
        chunks_json = json.dumps(chunks)
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

    def delete_chat(self, chat_id: str):
        """Delete a chat and all its messages."""
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
        self.conn.commit()

    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
