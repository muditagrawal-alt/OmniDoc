import os
import json
import time
import zlib
import base64
import hashlib
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


def _pack(text: str) -> str:
    """Stores long JSON compressed (an answer's sources and checks shrink about four times); short text as is."""
    if len(text) < 2048:
        return text
    return "z1:" + base64.b64encode(zlib.compress(text.encode("utf-8"), 9)).decode("ascii")


def _unpack(text: str) -> str:
    if isinstance(text, str) and text.startswith("z1:"):
        return zlib.decompress(base64.b64decode(text[3:])).decode("utf-8")
    return text


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

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS oauth_states (
                state_hash TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                created_at REAL NOT NULL
            )
        """)

        # Additive migrations for databases created by earlier versions
        for statement in (
            "ALTER TABLE messages ADD COLUMN metadata TEXT",
            "ALTER TABLE chats ADD COLUMN user_id TEXT DEFAULT 'usr_local_default'",
            "ALTER TABLE documents ADD COLUMN chunk_count INTEGER",
            # Rolling memory: a summary of the turns older than the recent window, and how many messages it covers.
            "ALTER TABLE chats ADD COLUMN memory TEXT",
            "ALTER TABLE chats ADD COLUMN memory_upto INTEGER DEFAULT 0",
            "ALTER TABLE sessions ADD COLUMN expires_at REAL",
            "ALTER TABLE users ADD COLUMN last_login_at TIMESTAMP",
            # Accounts without e-mail (passkeys, guests), two-step sign-in, and the devices list.
            "ALTER TABLE users ADD COLUMN kind TEXT DEFAULT 'user'",
            "ALTER TABLE users ADD COLUMN webauthn_handle TEXT",
            "ALTER TABLE users ADD COLUMN totp_secret TEXT",
            "ALTER TABLE users ADD COLUMN totp_enabled INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN totp_last_step INTEGER DEFAULT 0",
            "ALTER TABLE sessions ADD COLUMN user_agent TEXT",
            "ALTER TABLE sessions ADD COLUMN ip TEXT",
            "ALTER TABLE sessions ADD COLUMN last_used_at REAL",
            "ALTER TABLE oauth_states ADD COLUMN user_id TEXT",
            # Free answers on the server's keys, over the account's lifetime (then the user's own key).
            "ALTER TABLE users ADD COLUMN trial_used INTEGER DEFAULT 0",
            # Administrators who claimed the role with the server's setup code (others are listed by e-mail).
            "ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0",
            # Password sign-in: a unique username and a scrypt hash (core/passwords.py).
            "ALTER TABLE users ADD COLUMN username TEXT",
            "ALTER TABLE users ADD COLUMN password_hash TEXT",
            "ALTER TABLE users ADD COLUMN password_set_at REAL",
        ):
            try:
                cursor.execute(statement)
            except sqlite3.OperationalError:
                pass
        self._migrate_document_owners(cursor)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS otp_codes (
                email TEXT PRIMARY KEY,
                code_hash TEXT NOT NULL,
                expires_at REAL NOT NULL,
                attempts INTEGER DEFAULT 0,
                sends INTEGER DEFAULT 0,
                window_start REAL DEFAULT 0,
                last_sent REAL DEFAULT 0
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS usage (
                user_id TEXT NOT NULL,
                day TEXT NOT NULL,
                questions INTEGER DEFAULT 0,
                uploads INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, day)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS passkeys (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                public_key TEXT NOT NULL,
                sign_count INTEGER DEFAULT 0,
                transports TEXT,
                label TEXT,
                created_at REAL NOT NULL,
                last_used_at REAL
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_passkeys_user ON passkeys(user_id)")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS auth_challenges (
                id TEXT PRIMARY KEY,
                purpose TEXT NOT NULL,
                challenge TEXT NOT NULL,
                user_id TEXT,
                data TEXT,
                created_at REAL NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS recovery_codes (
                code_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                used_at REAL
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_recovery_user ON recovery_codes(user_id)")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS mfa_tickets (
                ticket_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                method TEXT,
                created_at REAL NOT NULL,
                attempts INTEGER DEFAULT 0
            )
        """)
        # API keys a user chose to keep on the server (encrypted); the default is to keep them on the device only.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_keys (
                user_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                key_enc TEXT NOT NULL,
                last4 TEXT,
                added_at REAL NOT NULL,
                PRIMARY KEY (user_id, provider)
            )
        """)
        # Data kept to the minimum: sessions record a device label, never an IP address.
        cursor.execute("UPDATE sessions SET ip = NULL WHERE ip IS NOT NULL")
        # Notices: security events for one account (user_id set) or announcements for everyone (NULL).
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT,
                url TEXT,
                created_at REAL NOT NULL
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_notices_user ON notices(user_id, created_at)")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notice_reads (
                user_id TEXT NOT NULL,
                notice_id INTEGER NOT NULL,
                PRIMARY KEY (user_id, notice_id)
            )
        """)
        # Older builds stored anonymous chats under 'usr_default'
        cursor.execute(
            "UPDATE chats SET user_id = ? WHERE user_id IS NULL OR user_id = 'usr_default'",
            (LOCAL_USER_ID,),
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_chats_user ON chats(user_id, updated_at)")

        # Feedback left on the product page: a rating and a message, and a way to reply only if given.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rating INTEGER,
                message TEXT NOT NULL,
                contact TEXT,
                created_at REAL NOT NULL
            )
        """)

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

    @staticmethod
    def _migrate_document_owners(cursor) -> None:
        """
        Documents belong to a user. Older databases allowed one copy of a file in the whole library
        (file_hash UNIQUE); with accounts each user keeps their own copy, so the table is rebuilt
        once with an owner column and a (owner, file) uniqueness instead.
        """
        row = cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='documents'").fetchone()
        sql = (row[0] if row else "") or ""
        if "owner_id" not in sql:
            cursor.execute("""
                CREATE TABLE documents_new (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    file_hash TEXT,
                    upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    size_bytes INTEGER,
                    file_type TEXT,
                    is_processed BOOLEAN DEFAULT 0,
                    chunk_count INTEGER,
                    owner_id TEXT DEFAULT 'usr_local_default'
                )
            """)
            cursor.execute("""
                INSERT INTO documents_new (id, filename, file_hash, upload_date, size_bytes, file_type, is_processed, chunk_count, owner_id)
                SELECT id, filename, file_hash, upload_date, size_bytes, file_type, is_processed, chunk_count, 'usr_local_default'
                FROM documents
            """)
            cursor.execute("DROP TABLE documents")
            cursor.execute("ALTER TABLE documents_new RENAME TO documents")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_owner_hash ON documents(owner_id, file_hash)")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_documents_owner ON documents(owner_id, upload_date)")

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

    def create_user(self, user_id: str, name: str, provider: str, kind: str = "user", email: Optional[str] = None,
                    webauthn_handle: Optional[str] = None) -> Dict[str, Any]:
        """A new account; passkey accounts and guests have no e-mail address."""
        self.conn.execute("""
            INSERT INTO users (id, email, name, provider, avatar_url, kind, webauthn_handle)
            VALUES (?, ?, ?, ?, '', ?, ?)
        """, (user_id, email, name, provider, kind, webauthn_handle))
        self.conn.commit()
        return self.get_user(user_id)

    def set_user_email(self, user_id: str, email: str, avatar_url: str = "") -> None:
        self.conn.execute("UPDATE users SET email = ?, avatar_url = CASE WHEN COALESCE(avatar_url, '') = '' THEN ? ELSE avatar_url END WHERE id = ?",
                          (email, avatar_url, user_id))
        self.conn.commit()

    def set_webauthn_handle(self, user_id: str, handle: str) -> None:
        self.conn.execute("UPDATE users SET webauthn_handle = ? WHERE id = ?", (handle, user_id))
        self.conn.commit()

    def set_totp(self, user_id: str, secret: Optional[str], enabled: bool, step: int = 0) -> None:
        self.conn.execute("UPDATE users SET totp_secret = ?, totp_enabled = ?, totp_last_step = ? WHERE id = ?",
                          (secret, 1 if enabled else 0, step, user_id))
        self.conn.commit()

    def set_totp_step(self, user_id: str, step: int) -> None:
        self.conn.execute("UPDATE users SET totp_last_step = ? WHERE id = ?", (step, user_id))
        self.conn.commit()

    def stale_guests(self, older_than_days: float) -> List[str]:
        rows = self.conn.execute("SELECT id FROM users WHERE kind = 'guest' AND created_at < datetime('now', ?)",
                                 (f"-{older_than_days} days",)).fetchall()
        return [r[0] for r in rows]

    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return dict(row) if row else None

    def set_username(self, user_id: str, username: str) -> None:
        self.conn.execute("UPDATE users SET username = ? WHERE id = ?", (username, user_id))
        self.conn.commit()

    def set_password(self, user_id: str, password_hash: Optional[str]) -> None:
        """Sets or (None) removes the account's password."""
        self.conn.execute("UPDATE users SET password_hash = ?, password_set_at = ? WHERE id = ?",
                          (password_hash, time.time() if password_hash else None, user_id))
        self.conn.commit()

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
        row = cursor.fetchone()
        return dict(row) if row else None

    # --------------------------------------------------------------- sessions
    @staticmethod
    def _token_key(token: str) -> str:
        # Only a hash of each session token is stored: a copy of the database cannot be used to sign in.
        return "sha256:" + hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _session_id(stored: str) -> str:
        # A short public id for the devices list, derived from the stored hash (never the token).
        digest = stored[7:] if stored.startswith("sha256:") else hashlib.sha256(stored.encode("utf-8")).hexdigest()
        return digest[:16]

    def create_session(self, user_id: str, ttl_days: Optional[float] = None, device: Optional[str] = None) -> str:
        """Issue an opaque random session token for a user (expiring after ttl_days when given)."""
        token = "sess_" + secrets.token_urlsafe(32)
        expires = time.time() + ttl_days * 86400 if ttl_days else None
        self.conn.execute("INSERT INTO sessions (token, user_id, expires_at, user_agent, last_used_at) VALUES (?, ?, ?, ?, ?)",
                          (self._token_key(token), user_id, expires, (device or "")[:80] or None, time.time()))
        if ttl_days:
            self.conn.execute("UPDATE users SET last_login_at = CURRENT_TIMESTAMP WHERE id = ?", (user_id,))
        self.conn.commit()
        return token

    def get_session_user_id(self, token: str, touch: bool = False) -> Optional[str]:
        cursor = self.conn.cursor()
        # Sessions issued before tokens were hashed are still found by their plain value.
        cursor.execute("SELECT token, user_id, expires_at, last_used_at FROM sessions WHERE token IN (?, ?)",
                       (self._token_key(token), token))
        row = cursor.fetchone()
        if not row:
            return None
        now = time.time()
        if row["expires_at"] and row["expires_at"] < now:
            self.delete_session(token)
            return None
        if touch and now - (row["last_used_at"] or 0) > 300:  # "last active" for the devices list, at most every 5 minutes
            self.conn.execute("UPDATE sessions SET last_used_at = ? WHERE token = ?", (now, row["token"]))
            self.conn.commit()
        return row["user_id"]

    def session_id(self, token: str) -> str:
        return self._session_id(self._token_key(token))

    def list_sessions(self, user_id: str) -> List[Dict[str, Any]]:
        now = time.time()
        rows = self.conn.execute("""
            SELECT token, user_agent, created_at, last_used_at, expires_at FROM sessions
            WHERE user_id = ? ORDER BY COALESCE(last_used_at, 0) DESC
        """, (user_id,)).fetchall()
        return [{"id": self._session_id(r["token"]), "user_agent": r["user_agent"] or "",
                 "created_at": r["created_at"], "last_used_at": r["last_used_at"]}
                for r in rows if not r["expires_at"] or r["expires_at"] >= now]

    def delete_session_by_id(self, user_id: str, session_id: str) -> bool:
        rows = self.conn.execute("SELECT token FROM sessions WHERE user_id = ?", (user_id,)).fetchall()
        doomed = [r["token"] for r in rows if self._session_id(r["token"]) == session_id]
        for stored in doomed:
            self.conn.execute("DELETE FROM sessions WHERE token = ?", (stored,))
        self.conn.commit()
        return bool(doomed)

    def delete_other_sessions(self, user_id: str, keep_token: str) -> int:
        cur = self.conn.execute("DELETE FROM sessions WHERE user_id = ? AND token NOT IN (?, ?)",
                                (user_id, self._token_key(keep_token), keep_token))
        self.conn.commit()
        return cur.rowcount

    def delete_session(self, token: str):
        self.conn.execute("DELETE FROM sessions WHERE token IN (?, ?)", (self._token_key(token), token))
        self.conn.commit()

    def delete_user_sessions(self, user_id: str):
        self.conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        self.conn.commit()

    # ------------------------------------------------------------- sign-in codes
    def put_otp(self, email: str, code_hash: str, expires_at: float, sends: int, window_start: float) -> None:
        self.conn.execute("""
            INSERT INTO otp_codes (email, code_hash, expires_at, attempts, sends, window_start, last_sent)
            VALUES (?, ?, ?, 0, ?, ?, ?)
            ON CONFLICT(email) DO UPDATE SET code_hash = excluded.code_hash, expires_at = excluded.expires_at,
                attempts = 0, sends = excluded.sends, window_start = excluded.window_start, last_sent = excluded.last_sent
        """, (email, code_hash, expires_at, sends, window_start, time.time()))
        self.conn.commit()

    def get_otp(self, email: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute("SELECT * FROM otp_codes WHERE email = ?", (email,)).fetchone()
        return dict(row) if row else None

    def otp_attempt(self, email: str) -> None:
        self.conn.execute("UPDATE otp_codes SET attempts = attempts + 1 WHERE email = ?", (email,))
        self.conn.commit()

    def otp_used(self, email: str) -> None:
        # The code is spent; the send counters stay so the hourly limit still applies.
        self.conn.execute("UPDATE otp_codes SET code_hash = '', expires_at = 0 WHERE email = ?", (email,))
        self.conn.commit()

    # ------------------------------------------------------------- OAuth states
    def put_oauth_state(self, state_hash: str, provider: str, user_id: Optional[str] = None) -> None:
        now = time.time()
        self.conn.execute("DELETE FROM oauth_states WHERE created_at < ?", (now - 900,))
        self.conn.execute("INSERT INTO oauth_states (state_hash, provider, created_at, user_id) VALUES (?, ?, ?, ?)",
                          (state_hash, provider, now, user_id))
        self.conn.commit()

    def take_oauth_state(self, state_hash: str, provider: str, max_age: float = 600) -> Optional[Dict[str, Any]]:
        """Consumes a state issued for this provider in the last max_age seconds (each state works once)."""
        row = self.conn.execute("SELECT provider, created_at, user_id FROM oauth_states WHERE state_hash = ?", (state_hash,)).fetchone()
        self.conn.execute("DELETE FROM oauth_states WHERE state_hash = ?", (state_hash,))
        self.conn.commit()
        if row and row["provider"] == provider and time.time() - row["created_at"] <= max_age:
            return {"provider": row["provider"], "user_id": row["user_id"]}
        return None

    # ------------------------------------------------------- passkey ceremonies
    def put_challenge(self, challenge_id: str, purpose: str, challenge: str, user_id: Optional[str], data: str) -> None:
        now = time.time()
        self.conn.execute("DELETE FROM auth_challenges WHERE created_at < ?", (now - 900,))
        self.conn.execute("INSERT INTO auth_challenges (id, purpose, challenge, user_id, data, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                          (challenge_id, purpose, challenge, user_id, data, now))
        self.conn.commit()

    def take_challenge(self, challenge_id: str, purpose: str, max_age: float) -> Optional[Dict[str, Any]]:
        """Consumes a challenge (each works once) issued for this purpose in the last max_age seconds."""
        row = self.conn.execute("SELECT * FROM auth_challenges WHERE id = ?", (challenge_id,)).fetchone()
        self.conn.execute("DELETE FROM auth_challenges WHERE id = ?", (challenge_id,))
        self.conn.commit()
        if row and row["purpose"] == purpose and time.time() - row["created_at"] <= max_age:
            return dict(row)
        return None

    # ----------------------------------------------------------------- passkeys
    def add_passkey(self, credential_id: str, user_id: str, public_key: str, sign_count: int, transports: str, label: str) -> None:
        self.conn.execute("""
            INSERT INTO passkeys (id, user_id, public_key, sign_count, transports, label, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (credential_id, user_id, public_key, sign_count, transports, label, time.time()))
        self.conn.commit()

    def get_passkey(self, credential_id: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute("SELECT * FROM passkeys WHERE id = ?", (credential_id,)).fetchone()
        return dict(row) if row else None

    def passkey_used(self, credential_id: str, sign_count: int, when: float) -> None:
        self.conn.execute("UPDATE passkeys SET sign_count = ?, last_used_at = ? WHERE id = ?", (sign_count, when, credential_id))
        self.conn.commit()

    def list_passkeys(self, user_id: str) -> List[Dict[str, Any]]:
        rows = self.conn.execute("SELECT id, label, transports, created_at, last_used_at FROM passkeys WHERE user_id = ? ORDER BY created_at",
                                 (user_id,)).fetchall()
        return [dict(r) for r in rows]

    def delete_passkey(self, user_id: str, credential_id: str) -> bool:
        cur = self.conn.execute("DELETE FROM passkeys WHERE user_id = ? AND id = ?", (user_id, credential_id))
        self.conn.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------------ recovery codes
    def replace_recovery_codes(self, user_id: str, hashes: List[str]) -> None:
        self.conn.execute("DELETE FROM recovery_codes WHERE user_id = ?", (user_id,))
        self.conn.executemany("INSERT INTO recovery_codes (code_hash, user_id) VALUES (?, ?)", [(h, user_id) for h in hashes])
        self.conn.commit()

    def spend_recovery_code(self, code_hash: str, user_id: Optional[str], when: float) -> Optional[str]:
        row = self.conn.execute("SELECT user_id FROM recovery_codes WHERE code_hash = ? AND used_at IS NULL", (code_hash,)).fetchone()
        if not row or (user_id and row["user_id"] != user_id):
            return None
        cur = self.conn.execute("UPDATE recovery_codes SET used_at = ? WHERE code_hash = ? AND used_at IS NULL", (when, code_hash))
        self.conn.commit()
        return row["user_id"] if cur.rowcount else None

    def recovery_codes_left(self, user_id: str) -> int:
        row = self.conn.execute("SELECT COUNT(*) FROM recovery_codes WHERE user_id = ? AND used_at IS NULL", (user_id,)).fetchone()
        return int(row[0])

    # ---------------------------------------------------- two-step sign-in tickets
    def put_mfa_ticket(self, ticket_hash: str, user_id: str, method: str) -> None:
        now = time.time()
        self.conn.execute("DELETE FROM mfa_tickets WHERE created_at < ?", (now - 3600,))
        self.conn.execute("INSERT INTO mfa_tickets (ticket_hash, user_id, method, created_at) VALUES (?, ?, ?, ?)",
                          (ticket_hash, user_id, method, now))
        self.conn.commit()

    def get_mfa_ticket(self, ticket_hash: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute("SELECT * FROM mfa_tickets WHERE ticket_hash = ?", (ticket_hash,)).fetchone()
        return dict(row) if row else None

    def mfa_attempt(self, ticket_hash: str) -> None:
        self.conn.execute("UPDATE mfa_tickets SET attempts = attempts + 1 WHERE ticket_hash = ?", (ticket_hash,))
        self.conn.commit()

    def delete_mfa_ticket(self, ticket_hash: str) -> None:
        self.conn.execute("DELETE FROM mfa_tickets WHERE ticket_hash = ?", (ticket_hash,))
        self.conn.commit()

    # ------------------------------------------------------------------ notices
    def add_notice(self, user_id: Optional[str], kind: str, title: str, body: str = "", url: Optional[str] = None) -> int:
        cur = self.conn.execute("INSERT INTO notices (user_id, kind, title, body, url, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                                (user_id, kind, title, body, url, time.time()))
        self.conn.commit()
        return cur.lastrowid

    def list_notices(self, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """The account's own notices and every announcement, newest first, each with read: true/false."""
        rows = self.conn.execute("""
            SELECT n.*, (r.notice_id IS NOT NULL) AS read FROM notices n
            LEFT JOIN notice_reads r ON r.notice_id = n.id AND r.user_id = ?
            WHERE n.user_id = ? OR n.user_id IS NULL
            ORDER BY n.created_at DESC, n.id DESC LIMIT ?
        """, (user_id, user_id, limit)).fetchall()
        return [{**dict(r), "read": bool(r["read"])} for r in rows]

    def mark_notices_read(self, user_id: str, notice_ids: Optional[List[int]] = None) -> None:
        if notice_ids is None:
            notice_ids = [n["id"] for n in self.list_notices(user_id, limit=500) if not n["read"]]
        self.conn.executemany("INSERT OR IGNORE INTO notice_reads (user_id, notice_id) VALUES (?, ?)",
                              [(user_id, int(i)) for i in notice_ids])
        self.conn.commit()

    # -------------------------------------------------------------------- usage
    def usage_today(self, user_id: str) -> Dict[str, int]:
        day = time.strftime("%Y-%m-%d", time.gmtime())
        row = self.conn.execute("SELECT questions, uploads FROM usage WHERE user_id = ? AND day = ?", (user_id, day)).fetchone()
        return {"questions": row["questions"], "uploads": row["uploads"]} if row else {"questions": 0, "uploads": 0}

    # ---- feedback -------------------------------------------------------------
    def add_feedback(self, message: str, rating: Optional[int] = None, contact: Optional[str] = None) -> int:
        cur = self.conn.execute("INSERT INTO feedback (rating, message, contact, created_at) VALUES (?, ?, ?, ?)",
                                (rating, message, contact or None, time.time()))
        self.conn.commit()
        return cur.lastrowid

    def list_feedback(self, limit: int = 200) -> List[Dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM feedback ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def delete_feedback(self, feedback_id: int) -> bool:
        cur = self.conn.execute("DELETE FROM feedback WHERE id = ?", (feedback_id,))
        self.conn.commit()
        return cur.rowcount > 0

    # ---- administration -------------------------------------------------------
    def set_admin(self, user_id: str, admin: bool = True) -> None:
        self.conn.execute("UPDATE users SET is_admin = ? WHERE id = ?", (1 if admin else 0, user_id))
        self.conn.commit()

    def list_admins(self) -> List[Dict[str, Any]]:
        rows = self.conn.execute("SELECT id, name, email, username FROM users WHERE is_admin = 1 ORDER BY name").fetchall()
        return [dict(r) for r in rows]

    def admin_stats(self) -> Dict[str, Any]:
        """Counts for the administrator's overview: accounts, library, and questions over time."""
        def one(sql: str, args: tuple = ()) -> int:
            row = self.conn.execute(sql, args).fetchone()
            return int(row[0] or 0) if row else 0

        today = time.strftime("%Y-%m-%d", time.gmtime())
        month = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 30 * 86400))
        week = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 7 * 86400))
        days = self.conn.execute(
            "SELECT day, SUM(questions) AS questions, SUM(uploads) AS uploads FROM usage WHERE day >= ? GROUP BY day ORDER BY day",
            (month,),
        ).fetchall()
        return {
            "accounts": one("SELECT COUNT(*) FROM users WHERE COALESCE(kind, 'user') != 'guest'"),
            "guests": one("SELECT COUNT(*) FROM users WHERE kind = 'guest'"),
            "documents": one("SELECT COUNT(*) FROM documents"),
            "chats": one("SELECT COUNT(*) FROM chats"),
            "questions_today": one("SELECT SUM(questions) FROM usage WHERE day = ?", (today,)),
            "questions_7d": one("SELECT SUM(questions) FROM usage WHERE day >= ?", (week,)),
            "questions_30d": one("SELECT SUM(questions) FROM usage WHERE day >= ?", (month,)),
            "uploads_30d": one("SELECT SUM(uploads) FROM usage WHERE day >= ?", (month,)),
            "feedback": one("SELECT COUNT(*) FROM feedback"),
            "rating": round(float(self.conn.execute("SELECT AVG(rating) FROM feedback WHERE rating IS NOT NULL").fetchone()[0] or 0), 1),
            "active_30d": one("SELECT COUNT(DISTINCT user_id) FROM usage WHERE day >= ? AND questions > 0", (month,)),
            "by_day": [{"day": r["day"], "questions": int(r["questions"] or 0), "uploads": int(r["uploads"] or 0)} for r in days],
        }

    def count_usage(self, user_id: str, kind: str) -> None:
        if kind not in ("questions", "uploads"):
            return
        day = time.strftime("%Y-%m-%d", time.gmtime())
        self.conn.execute(f"""
            INSERT INTO usage (user_id, day, {kind}) VALUES (?, ?, 1)
            ON CONFLICT(user_id, day) DO UPDATE SET {kind} = {kind} + 1
        """, (user_id, day))
        # Only today's counts matter for limits: older rows are not kept beyond 40 days.
        self.conn.execute("DELETE FROM usage WHERE day < ?", (time.strftime("%Y-%m-%d", time.gmtime(time.time() - 40 * 86400)),))
        self.conn.commit()

    def trial_used(self, user_id: str) -> int:
        row = self.conn.execute("SELECT trial_used FROM users WHERE id = ?", (user_id,)).fetchone()
        return int((row[0] if row else 0) or 0)

    def add_trial_use(self, user_id: str) -> None:
        self.conn.execute("UPDATE users SET trial_used = COALESCE(trial_used, 0) + 1 WHERE id = ?", (user_id,))
        self.conn.commit()

    # -------------------------------------------------------------- own API keys
    def put_user_key(self, user_id: str, provider: str, key_enc: str, last4: str) -> None:
        self.conn.execute("""
            INSERT INTO user_keys (user_id, provider, key_enc, last4, added_at) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, provider) DO UPDATE SET key_enc = excluded.key_enc, last4 = excluded.last4, added_at = excluded.added_at
        """, (user_id, provider, key_enc, last4, time.time()))
        self.conn.commit()

    def user_keys(self, user_id: str) -> List[Dict[str, Any]]:
        rows = self.conn.execute("SELECT provider, key_enc, last4, added_at FROM user_keys WHERE user_id = ? ORDER BY provider",
                                 (user_id,)).fetchall()
        return [dict(r) for r in rows]

    def delete_user_key(self, user_id: str, provider: str) -> bool:
        cur = self.conn.execute("DELETE FROM user_keys WHERE user_id = ? AND provider = ?", (user_id, provider))
        self.conn.commit()
        return cur.rowcount > 0

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

    def set_chat_memory(self, chat_id: str, memory: str, upto: int):
        self.conn.execute("UPDATE chats SET memory = ?, memory_upto = ? WHERE id = ?", (memory, upto, chat_id))
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
        metadata_json = _pack(json.dumps(metadata, default=str)) if metadata else None
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
                        msg[key] = json.loads(_unpack(msg[key]))
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
    def add_document(self, doc_id: str, filename: str, file_hash: str, size_bytes: int, file_type: str,
                     chunk_count: Optional[int] = None, owner_id: str = LOCAL_USER_ID):
        """Register a document (no-op if its owner registered the same file before)."""
        self.conn.execute("""
            INSERT OR IGNORE INTO documents (id, filename, file_hash, size_bytes, file_type, is_processed, chunk_count, owner_id)
            VALUES (?, ?, ?, ?, ?, 1, ?, ?)
        """, (doc_id, filename, file_hash, size_bytes, file_type, chunk_count, owner_id))
        self.conn.commit()

    def get_document(self, doc_id: str) -> Optional[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM documents WHERE id = ?", (doc_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_document_by_hash(self, file_hash: str, owner_id: str = LOCAL_USER_ID) -> Optional[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM documents WHERE file_hash = ? AND owner_id = ?", (file_hash, owner_id))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_all_documents(self, owner_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Every document, or one owner's."""
        cursor = self.conn.cursor()
        if owner_id is None:
            cursor.execute("SELECT * FROM documents ORDER BY upload_date DESC")
        else:
            cursor.execute("SELECT * FROM documents WHERE owner_id = ? ORDER BY upload_date DESC", (owner_id,))
        return [dict(row) for row in cursor.fetchall()]

    def document_ids(self, owner_id: str) -> List[str]:
        return [r[0] for r in self.conn.execute("SELECT id FROM documents WHERE owner_id = ?", (owner_id,))]

    def storage_used(self, owner_id: str) -> int:
        row = self.conn.execute("SELECT COALESCE(SUM(size_bytes), 0) FROM documents WHERE owner_id = ?", (owner_id,)).fetchone()
        return int(row[0] or 0)

    def delete_user(self, user_id: str) -> None:
        """Removes a user with their chats, messages, sessions, passkeys, codes, notices and usage (the caller removes documents)."""
        user = self.get_user(user_id)
        cur = self.conn.cursor()
        cur.execute("DELETE FROM messages WHERE chat_id IN (SELECT id FROM chats WHERE user_id = ?)", (user_id,))
        cur.execute("DELETE FROM chats WHERE user_id = ?", (user_id,))
        cur.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        cur.execute("DELETE FROM usage WHERE user_id = ?", (user_id,))
        for table in ("passkeys", "recovery_codes", "mfa_tickets", "notices", "notice_reads", "auth_challenges", "user_keys"):
            cur.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
        if user and user.get("email"):
            cur.execute("DELETE FROM otp_codes WHERE email = ?", (user["email"],))
        cur.execute("DELETE FROM documents WHERE owner_id = ?", (user_id,))
        cur.execute("DELETE FROM users WHERE id = ?", (user_id,))
        self.conn.commit()

    def delete_document(self, doc_id: str):
        self.conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        self.conn.commit()

    def close(self):
        """Close this thread's database connection."""
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
