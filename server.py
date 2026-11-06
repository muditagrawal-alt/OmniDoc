"""
OmniDoc FastAPI backend.

Serves the React frontend's API:
1. Local profiles with opaque session tokens
2. Conversation sessions and message history (SQLite)
3. The multi-agent Graph RAG pipeline (LangGraph + LanceDB + Kùzu + Ollama),
   with Server-Sent Events streaming of per-agent progress
4. Document ingestion (PDF, scans and images with OCR, Word, text, spreadsheets) with
   background summaries and knowledge-graph extraction
5. The document viewer: page images, citation highlights, document text and summaries
6. Schema extraction: fill a set of fields from documents, with a checked citation per value
7. Knowledge-graph export for the 3D globe
8. PDF (WeasyPrint) and DOCX (python-docx) report export
"""
import os
import re
import io
import sys
import json
import time
import uuid
import queue
import zipfile
import tempfile
import hashlib
import hmac
import logging
import secrets
import threading
import urllib.parse
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Dict, Any, Optional, Iterator

# Homebrew Cairo / Pango for WeasyPrint on macOS (must be set before WeasyPrint loads)
os.environ.setdefault("DYLD_FALLBACK_LIBRARY_PATH", "/opt/homebrew/lib")

# Ensure project root is importable when run as a script
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pydantic import BaseModel, Field
from fastapi import FastAPI, HTTPException, UploadFile, File, Header, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse, RedirectResponse, JSONResponse

from db_store import OmniDocDB, LOCAL_USER_ID, DATA_DIR
from export.report_compiler import ReportCompiler
from core.pipeline import AgenticGraphRAGPipeline
from core import accounts, chat_memory, abuse, memory, passkeys, passwords, proxy, two_factor
from agents import llm_providers

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("OmniDoc.Server")

VERSION = "2.2.0"
OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
# A hosted free-tier model when an API key is configured (see .env.example), else local Ollama.
DEFAULT_MODEL = llm_providers.default_spec()
MAX_UPLOAD_BYTES = int(os.environ.get("OMNIDOC_MAX_UPLOAD_MB", "100")) * 1024 * 1024
IMAGE_TYPES = {"png", "jpg", "jpeg", "tif", "tiff", "webp", "bmp"}
MEDIA_FILE_TYPES = {"mp3", "wav", "m4a", "ogg", "flac", "webm", "mp4", "mov", "mpeg", "mpga", "aac"}
# Shown as page images in the viewer (with highlights); other types are shown as text.
PAGED_TYPES = {"pdf"} | IMAGE_TYPES
ALLOWED_EXTENSIONS = ({"pdf", "docx", "txt", "md", "csv", "tsv", "xlsx", "pptx", "eml", "epub", "html", "htm"}
                      | IMAGE_TYPES | MEDIA_FILE_TYPES)
MEDIA_TYPES = {
    "pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "tif": "image/tiff", "tiff": "image/tiff", "webp": "image/webp", "bmp": "image/bmp",
    "txt": "text/plain; charset=utf-8", "md": "text/markdown; charset=utf-8", "csv": "text/csv; charset=utf-8",
    "tsv": "text/tab-separated-values; charset=utf-8",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "eml": "message/rfc822", "epub": "application/epub+zip", "html": "text/html; charset=utf-8", "htm": "text/html; charset=utf-8",
    "mp3": "audio/mpeg", "wav": "audio/wav", "m4a": "audio/mp4", "ogg": "audio/ogg", "flac": "audio/flac", "aac": "audio/aac",
    "webm": "video/webm", "mp4": "video/mp4", "mov": "video/quicktime", "mpeg": "video/mpeg", "mpga": "audio/mpeg",
}
UPLOAD_DIR = DATA_DIR / "uploads"
# Written by the pipeline at upload; read directly so listing documents never waits for the models.
LAYOUT_DIR = DATA_DIR / "layout"
SUMMARY_DIR = DATA_DIR / "summaries"
PAGE_CACHE_DIR = DATA_DIR / "page_cache"
PAGE_WIDTHS = (400, 700, 1000, 1400, 2000)
MAX_PAGE_PIXELS = 24_000_000
SETTINGS_PATH = DATA_DIR / "settings.json"
DOC_ID_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,128}$")
NEW_CHAT_TITLE = "New conversation"

@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Load the models in the background so the first question does not wait for them.
    if os.environ.get("OMNIDOC_WARMUP", "1") != "0":
        threading.Thread(target=get_pipeline, name="pipeline-warmup", daemon=True).start()
    if accounts.demo_enabled():
        threading.Thread(target=_seed_demo_library, name="demo-library", daemon=True).start()
    announce_setup_code()
    yield


app = FastAPI(
    title="OmniDoc API",
    description="Local multi-agent document intelligence: cited answers, knowledge graph, reports.",
    version=VERSION,
    lifespan=lifespan,
)

# The API authenticates with a bearer header, not cookies, so credentials are not
# needed cross-origin. Only the local frontend origins may call it from a browser.
CORS_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "OMNIDOC_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173",
    ).split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "X-OmniDoc-Token", "X-OmniDoc-Keys", "Content-Type", "Accept"],
)

# Optional password gate for deployments: OMNIDOC_AUTH="user:password" asks every visitor for it
# (HTTP basic auth; serve over HTTPS). /api/health stays open for health checks.
_GATE = os.environ.get("OMNIDOC_AUTH", "").strip()
if _GATE:
    import base64
    import secrets
    from starlette.responses import Response as _PlainResponse

    @app.middleware("http")
    async def password_gate(request, call_next):
        if request.url.path == "/api/health" or request.method == "OPTIONS":
            return await call_next(request)
        header = request.headers.get("authorization", "")
        given = ""
        if header.startswith("Basic "):
            try:
                given = base64.b64decode(header[6:]).decode("utf-8", errors="ignore")
            except ValueError:
                given = ""
        if not secrets.compare_digest(given.encode(), _GATE.encode()):
            return _PlainResponse(status_code=401, headers={"WWW-Authenticate": 'Basic realm="OmniDoc", charset="UTF-8"'})
        return await call_next(request)

db = OmniDocDB()
report_compiler = ReportCompiler()

# Accounts (OMNIDOC_ACCOUNTS=1, a hosted OmniDoc): every API call needs a signed-in session, except
# the health check and signing in. Without accounts, requests act as the local profile, as before.
_OPEN_API = ("/api/health", "/api/auth/methods", "/api/auth/code/", "/api/auth/oauth/", "/api/auth/passkey/",
             "/api/auth/challenge", "/api/auth/recovery", "/api/auth/mfa", "/api/auth/guest", "/api/auth/password/",
             "/api/feedback")
NO_DOCUMENTS = "doc_none"  # a scope that matches nothing: the account has no documents yet
API_PER_MINUTE = int(os.environ.get("OMNIDOC_API_PER_MINUTE", "240"))

# Besides reading, a guest (the demo) may ask, compare, search, extract and keep conversations; nothing else.
_GUEST_WRITES = (
    re.compile(r"^/api/chats(/[^/]+(/query(/stream)?)?)?$"),
    re.compile(r"^/api/(query|compare|search|extract/stream|documents/summaries|auth/logout|auth/media|notices/read|keys/check|export/(pdf|docx))$"),
    re.compile(r"^/api/documents/[^/]+/(locate|redact)$"),
)


def accounts_on() -> bool:
    return accounts.enabled()


def is_guest(user_id: str) -> bool:
    return user_id.startswith("gst_")


def _client_ip(request: Request) -> str:
    cached = getattr(request.state, "client_ip", None)
    if cached:
        return cached
    return abuse.client_ip(request.client.host if request.client else None, request.headers.get("x-forwarded-for"))


def _guest_may(method: str, path: str) -> bool:
    if path.startswith(("/api/account/", "/api/admin")):
        return False
    if method in ("GET", "HEAD"):
        return True
    return any(rule.match(path) for rule in _GUEST_WRITES)


def _header_keys(request: Request) -> Optional[Dict[str, str]]:
    """Keys the browser keeps for the user (X-OmniDoc-Keys: base64url of {"provider": "key"}); never stored here."""
    raw = request.headers.get("x-omnidoc-keys", "").strip()
    if not raw or len(raw) > 4096:
        return None
    try:
        import base64
        data = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8"))
        return llm_providers.clean_keys(data) if isinstance(data, dict) else None
    except Exception:
        return None


def _stored_keys(user_id: Optional[str]) -> Dict[str, str]:
    if not user_id or not accounts_on():
        return {}
    out = {}
    for row in db.user_keys(user_id):
        key = accounts.decrypt(DATA_DIR, row["key_enc"])
        if key:
            out[row["provider"]] = key
    return out


@app.middleware("http")
async def require_session(request, call_next):
    path = request.url.path
    if request.method == "OPTIONS" or not path.startswith("/api/"):
        return await call_next(request)
    if not accounts_on():
        # A local install answers with the server's keys, or the ones the browser brings.
        llm_providers.use_keys(_header_keys(request))
        return await call_next(request)
    ip = _client_ip(request)
    request.state.client_ip = ip
    wait = abuse.limiter.hit(f"api:{ip}", API_PER_MINUTE, 60)
    if wait:
        return JSONResponse({"detail": "Too many requests. Wait a moment and try again."}, status_code=429,
                            headers={"Retry-After": str(int(wait))})
    if path.startswith(_OPEN_API):
        llm_providers.use_keys(None)
        return await call_next(request)
    token = _bearer(request.headers.get("authorization"), request.headers.get("x-omnidoc-token")) or _media_token(request)
    user_id = db.get_session_user_id(token, touch=True) if token else None
    if not user_id:
        return JSONResponse({"detail": "Sign in to continue."}, status_code=401)
    if is_guest(user_id) and not _guest_may(request.method, path):
        return JSONResponse({"detail": "The demo is read-only. Sign in to add documents and keep your own library."},
                            status_code=403)
    # The user's own keys (kept on the server if they chose, overridden by the browser's) answer for them.
    keys = {**_stored_keys(user_id), **(_header_keys(request) or {})}
    llm_providers.use_keys(keys or None)
    return await call_next(request)


# Outermost: a front end on another host (Vercel) forwards /api here under a secret prefix; the
# prefix comes off before anything above sees the path (core/proxy.py).
app.add_middleware(proxy.FrontProxy)


# ---------------------------------------------------------------------------
# Settings & pipeline lifecycle
# ---------------------------------------------------------------------------
def _load_settings() -> Dict[str, Any]:
    try:
        return json.loads(SETTINGS_PATH.read_text())
    except (OSError, ValueError):
        return {}


def _save_settings(settings: Dict[str, Any]) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2))


_pipeline: Optional[AgenticGraphRAGPipeline] = None
_pipeline_lock = threading.Lock()


def get_pipeline() -> AgenticGraphRAGPipeline:
    """Builds the pipeline once (thread-safe); heavy models load on first use."""
    global _pipeline
    if _pipeline is None:
        with _pipeline_lock:
            if _pipeline is None:
                model = _load_settings().get("model") or DEFAULT_MODEL
                logger.info(f"Initializing agentic pipeline with model {model}...")
                pipeline = AgenticGraphRAGPipeline(data_dir=str(DATA_DIR), model_name=model)
                pipeline.doc_title_provider = _doc_titles  # library names for summaries and citations
                pipeline.doc_list_provider = db.get_all_documents
                try:
                    pipeline.backfill_types()
                except Exception as e:
                    logger.warning(f"Type detection for earlier documents failed: {e}")
                pipeline.refresh_records()
                _pipeline = pipeline
    return _pipeline


def current_model() -> str:
    if _pipeline is not None:
        return _pipeline.model_name
    return _load_settings().get("model") or DEFAULT_MODEL


def available_models() -> List[Dict[str, Any]]:
    """Models that can answer: the configured hosted providers' models, then local Ollama models."""
    models: List[Dict[str, Any]] = []
    for p in llm_providers.chat_providers():
        for name, tier in ((p.model, "smart"), (p.fast_model, "fast")):
            if name and not any(m["name"] == f"{p.name}:{name}" for m in models):
                models.append({"name": f"{p.name}:{name}", "label": name.split("/")[-1], "provider": p.name,
                               "provider_label": p.label, "hosted": True, "tier": tier, "size_gb": None, "parameter_size": None})
    for m in ollama_models(timeout=1.0) or []:
        models.append({**m, "label": m["name"], "provider": "ollama", "provider_label": "Ollama (this computer)", "hosted": False})
    return models


def ollama_models(timeout: float = 2.0) -> Optional[List[Dict[str, Any]]]:
    """Lists locally installed Ollama models, or None if Ollama is unreachable."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    models = []
    for m in data.get("models", []):
        caps = m.get("capabilities") or []
        name = m.get("name", "")
        if "embedding" in caps or "embed" in name:
            continue  # embedding-only models cannot answer questions
        details = m.get("details") or {}
        models.append({
            "name": name,
            "size_gb": round(m.get("size", 0) / 1e9, 1) if m.get("size") else None,
            "parameter_size": details.get("parameter_size"),
        })
    return models


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------
class LoginRequest(BaseModel):
    provider: str = Field("local", description="Profile type; only local profiles exist")
    email: Optional[str] = None
    name: Optional[str] = None


class CreateChatRequest(BaseModel):
    title: Optional[str] = NEW_CHAT_TITLE
    document_id: Optional[str] = None


class RenameChatRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=8000)
    document_ids: Optional[List[str]] = None
    session_id: Optional[str] = None
    language: Optional[str] = "en"
    # "auto": search the web when the question needs it or the documents do not answer it
    web: Optional[str] = Field("auto", pattern="^(auto|on|off)$")
    # How much evidence to read: "quick", "balanced" (the benchmarked pipeline) or "thorough"
    effort: Optional[str] = Field("balanced", pattern="^(quick|balanced|thorough)$")
    # The user's own choice of answer model ("provider:model" from /api/models); the server's default when empty
    model: Optional[str] = Field(None, max_length=200)


class ModelRequest(BaseModel):
    model: str


class ExportRequest(BaseModel):
    chat_id: Optional[str] = None
    title: Optional[str] = "OmniDoc analysis"
    messages: Optional[List[Dict[str, Any]]] = None
    metadata: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Auth: opaque session tokens; requests without one act as the local user
# ---------------------------------------------------------------------------
def _bearer(authorization: Optional[str], omnidoc_token: Optional[str] = None) -> Optional[str]:
    """The profile token: X-OmniDoc-Token (used by the app, so a password gate can use Authorization), or a Bearer header."""
    if omnidoc_token and omnidoc_token.strip():
        return omnidoc_token.strip()
    if authorization and authorization.startswith("Bearer "):
        token = authorization[len("Bearer "):].strip()
        return token or None
    return None


# Images, the original file and recordings are loaded by <img>, <a> and <audio>, which cannot send the
# session header: for those GETs alone the session also travels in an HttpOnly, SameSite=Strict cookie.
MEDIA_COOKIE = "omnidoc_media"
_MEDIA_PATH = re.compile(r"^/api/documents/[A-Za-z0-9_.\-]{1,128}/(pages/\d+|file)$")


def _media_token(request: Request) -> Optional[str]:
    if request.method in ("GET", "HEAD") and _MEDIA_PATH.match(request.url.path):
        return request.cookies.get(MEDIA_COOKIE) or None
    return None


def current_user_id(request: Request, authorization: Optional[str] = Header(None),
                    x_omnidoc_token: Optional[str] = Header(None)) -> str:
    token = _bearer(authorization, x_omnidoc_token) or _media_token(request)
    if not token:
        if accounts_on():
            raise HTTPException(status_code=401, detail="Sign in to continue.")
        return LOCAL_USER_ID
    user_id = db.get_session_user_id(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Session expired. Sign in again.")
    return user_id


def library_owner(user_id: str) -> str:
    """
    Whose documents a request sees: each account its own on a hosted server, guests the shared demo
    library, and one shared library on a local install.
    """
    if not accounts_on():
        return LOCAL_USER_ID
    return accounts.DEMO_OWNER if is_guest(user_id) else user_id


def is_admin(user_id: str) -> bool:
    """An administrator: listed in OMNIDOC_ADMIN_EMAILS, or claimed the role with the server's setup code."""
    if not accounts_on():
        return False
    user = db.get_user(user_id) or {}
    return accounts.is_admin(user.get("email")) or bool(user.get("is_admin"))


def has_two_step(user_id: str) -> bool:
    return bool((db.get_user(user_id) or {}).get("totp_enabled")) or bool(db.list_passkeys(user_id))


def require_admin(user_id: str) -> None:
    """Administrator settings on a hosted server need an admin account protected by a passkey or an authenticator app."""
    if not accounts_on():
        return
    if not is_admin(user_id):
        raise HTTPException(status_code=403, detail="Only an administrator can change this.")
    if not has_two_step(user_id) and os.environ.get("OMNIDOC_ADMIN_TWO_STEP", "1") != "0":
        raise HTTPException(status_code=403, detail="Turn on two-step sign-in (a passkey or an authenticator app) under Account first.")


def check_quota(user_id: str, kind: str) -> None:
    """Daily limits per account on a hosted server (admins, the demo library and local installs have none)."""
    if not accounts_on() or is_admin(user_id) or user_id == accounts.DEMO_OWNER:
        return
    if is_guest(user_id):
        if kind != "questions":
            raise HTTPException(status_code=403, detail="The demo is read-only. Sign in to add documents.")
        limit = accounts.guest_limits()["questions_per_day"]
        if db.usage_today(user_id)["questions"] >= limit:
            raise HTTPException(status_code=429, detail=f"The demo allows {limit} questions. Sign in to keep going with your own documents.")
        return
    limit = accounts.limits()["questions_per_day" if kind == "questions" else "uploads_per_day"]
    if db.usage_today(user_id)[kind] >= limit:
        what = "questions" if kind == "questions" else "uploads"
        raise HTTPException(status_code=429, detail=f"You have reached today's limit of {limit} {what}. It resets at midnight UTC.")


def _answer_gate(user_id: str, request: Request) -> None:
    """
    Before a model answers: the daily limit, then the free trial. Without their own key an account
    (or guest) gets OMNIDOC_TRIAL_ANSWERS answers on the server's keys; after that the reply is 402
    and the app asks for the user's own free key.
    """
    check_quota(user_id, "questions")
    if not accounts_on() or is_admin(user_id) or llm_providers.current_keys():
        return
    limit = accounts.trial_answers()
    if db.trial_used(user_id) >= limit:
        raise HTTPException(status_code=402, headers={"X-OmniDoc-Need": "api-key"}, detail=(
            f"You have used your {limit} free answers. Add your own free API key to keep going: it takes a minute."))
    if abuse.limiter.hit(f"trial:{_client_ip(request)}", accounts.trial_per_ip(), 86400):
        raise HTTPException(status_code=402, headers={"X-OmniDoc-Need": "api-key"}, detail=(
            "Today's free answers for your network are used up. Add your own free API key to keep going."))


def _charge(user_id: str) -> None:
    """Counts an answer: toward the daily limit, and toward the free trial when the server's keys wrote it."""
    if not accounts_on():
        return
    db.count_usage(user_id, "questions")
    if not is_admin(user_id) and not llm_providers.current_keys():
        db.add_trial_use(user_id)


def scoped_ids(doc_ids: Optional[List[str]], user_id: str) -> List[str]:
    """
    The documents a question may read. Locally: the selected ones (none selected: the whole library).
    With accounts: the selected ones the user owns, else all of theirs, never anyone else's.
    """
    ids = [d for d in (doc_ids or []) if DOC_ID_RE.match(d)]
    if not accounts_on():
        return ids
    mine = set(db.document_ids(library_owner(user_id)))
    return [d for d in ids if d in mine] or sorted(mine) or [NO_DOCUMENTS]


def owned_chat(chat_id: str, user_id: str) -> Dict[str, Any]:
    chat = db.get_chat(chat_id, user_id=user_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return chat


@app.post("/api/auth/login")
def login(req: LoginRequest):
    """Creates or reuses a local profile and returns a new session token (local installs only)."""
    if accounts_on():
        raise HTTPException(status_code=404, detail="Sign in with an e-mailed code, Google or GitHub.")
    email = (req.email or "").strip().lower()
    name = (req.name or "").strip()
    if not email or "@" not in email:
        raise HTTPException(status_code=422, detail="Enter a valid email address")
    existing = db.get_user_by_email(email)
    user_id = existing["id"] if existing else f"usr_{uuid.uuid4().hex[:12]}"
    user = db.upsert_user(
        user_id=user_id,
        email=email,
        name=name or (existing or {}).get("name") or email.split("@")[0],
        provider="local",
        avatar_url="",
    )
    token = db.create_session(user_id)
    return {"status": "success", "token": token, "user": _public_user(user)}


class CodeRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)


class CodeVerifyRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    code: str = Field(..., min_length=4, max_length=12)
    name: Optional[str] = Field(None, max_length=120)


_PRIVATE_USER_FIELDS = ("totp_secret", "totp_last_step", "webauthn_handle", "is_admin", "password_hash")


def _public_user(user: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """A user record without its secrets, as the app sees it."""
    user = dict(user or {})
    admin = accounts.is_admin(user.get("email")) or bool(user.get("is_admin"))
    user["has_password"] = bool(user.get("password_hash"))
    for key in _PRIVATE_USER_FIELDS:
        user.pop(key, None)
    user["totp_enabled"] = bool(user.get("totp_enabled"))
    user["email"] = user.get("email") or ""
    # A local install has no accounts: whoever runs it administers it.
    user["admin"] = admin or not accounts_on()
    return user


def _device(stored: Optional[str]) -> str:
    """The device label kept with a session (older sessions kept the raw User-Agent)."""
    stored = stored or ""
    return accounts.device_label(stored) if "Mozilla/" in stored or not stored else stored


def _new_session(user_id: str, request: Optional[Request], days: Optional[float] = None) -> str:
    """
    A session for a signed-in user. Only a device label ("Chrome on macOS") is kept with it, no IP
    address; a sign-in from a kind of device the account has not used before leaves a notice.
    """
    label = accounts.device_label(request.headers.get("user-agent", "") if request is not None else "")
    seen = {_device(s["user_agent"]) for s in db.list_sessions(user_id)}
    token = db.create_session(user_id, ttl_days=days or accounts.SESSION_DAYS, device=label)
    if seen and label not in seen:
        db.add_notice(user_id, "security", f"New sign-in: {label}",
                      "If this was not you, sign that device out under Account, Devices.")
    return token


def _sign_in(email: str, name: str, provider: str, avatar_url: str = "", request: Optional[Request] = None) -> Dict[str, Any]:
    """
    The account for a verified e-mail address (created on first sign-in) and a new session, or, when
    the account has an authenticator app, a ticket for the second step instead of a session.
    """
    existing = db.get_user_by_email(email)
    user = db.upsert_user(
        user_id=existing["id"] if existing else f"usr_{uuid.uuid4().hex[:12]}",
        email=email, name=name or (existing or {}).get("name") or email.split("@")[0],
        provider=(existing or {}).get("provider") if (existing or {}).get("provider") == "passkey" else provider,
        avatar_url=avatar_url or (existing or {}).get("avatar_url") or "")
    if user.get("totp_enabled"):
        return {"mfa": two_factor.issue_ticket(db, DATA_DIR, user["id"], provider)}
    return {"token": _new_session(user["id"], request), "user": _public_user(user)}


def _limit(request: Request, name: str, limit: int, window_s: float) -> None:
    if not accounts_on():
        return
    wait = abuse.limiter.hit(f"{name}:{_client_ip(request)}", limit, window_s)
    if wait:
        minutes = max(1, round(wait / 60))
        raise HTTPException(status_code=429, detail=f"Too many attempts. Try again in {minutes} minute{'s' if minutes != 1 else ''}.",
                            headers={"Retry-After": str(int(wait))})


def _limit_key(key: str, limit: int, window_s: float) -> None:
    """A limit on something other than the address (a username being guessed at, for one)."""
    if not accounts_on():
        return
    wait = abuse.limiter.hit(key, limit, window_s)
    if wait:
        minutes = max(1, round(wait / 60))
        raise HTTPException(status_code=429, detail=f"Too many attempts. Try again in {minutes} minute{'s' if minutes != 1 else ''}.",
                            headers={"Retry-After": str(int(wait))})


def _require_proof(solution: Optional[Dict[str, Any]]) -> None:
    """The browser's proof-of-work answer (see core/abuse.py); OMNIDOC_POW=0 turns the check off."""
    if os.environ.get("OMNIDOC_POW", "1") == "0":
        return
    ok, why = abuse.check_solution(accounts.derived_key(DATA_DIR, "pow"), solution)
    if not ok:
        raise HTTPException(status_code=400, detail=why)


@app.get("/api/auth/methods")
def auth_methods():
    """Which ways of signing in this server offers (accounts: false means a local single-user install)."""
    return accounts.methods()


@app.post("/api/auth/code/request")
def request_sign_in_code(req: CodeRequest):
    """E-mails a six-digit sign-in code. The reply is the same whether or not the address has an account."""
    if not accounts.methods()["email"]:
        raise HTTPException(status_code=404, detail="E-mail sign-in is not available on this server.")
    email = accounts.normalize_email(req.email)
    if not email:
        raise HTTPException(status_code=422, detail="Enter a valid e-mail address.")
    if not accounts.allowed(email):
        raise HTTPException(status_code=403, detail="This address is not invited to this OmniDoc. Ask its administrator.")
    try:
        accounts.request_code(db, DATA_DIR, email)
    except accounts.CodeError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    except Exception as e:
        logger.error(f"Could not send a sign-in code: {e}")
        raise HTTPException(status_code=502, detail="The e-mail could not be sent. Try again in a minute.")
    return {"status": "sent", "expires_in": accounts.CODE_TTL_S}


@app.post("/api/auth/code/verify")
def verify_sign_in_code(req: CodeVerifyRequest, request: Request):
    email = accounts.normalize_email(req.email)
    if not email or not accounts.methods()["email"]:
        raise HTTPException(status_code=422, detail="Enter a valid e-mail address.")
    try:
        accounts.verify_code(db, DATA_DIR, email, req.code)
    except accounts.CodeError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    return {"status": "success", **_sign_in(email, (req.name or "").strip(), "email", request=request)}


@app.get("/api/auth/oauth/{provider}/start")
def oauth_start(provider: str):
    try:
        return RedirectResponse(accounts.authorize_url(db, DATA_DIR, provider), status_code=302)
    except accounts.CodeError as e:
        raise HTTPException(status_code=e.status, detail=str(e))


@app.get("/api/auth/oauth/{provider}/callback")
def oauth_callback(request: Request, provider: str, code: str = "", state: str = "", error: str = ""):
    """
    Finishes Google or GitHub sign-in and returns to the app with the session (or the ticket for the
    second step) in the address fragment. A flow started from Account links the address instead.
    """
    home = accounts.public_url() + "/"
    try:
        if error or not code:
            raise accounts.CodeError("Sign-in was cancelled.")
        identity = accounts.oauth_identity(db, DATA_DIR, provider, code, state)
        email = accounts.normalize_email(identity["email"])
        if not email:
            raise accounts.CodeError("Your account has no usable e-mail address.")
        if not accounts.allowed(email):
            raise accounts.CodeError("This address is not invited to this OmniDoc. Ask its administrator.")
        target = identity.get("link_user_id")
        if target:
            other = db.get_user_by_email(email)
            if other and other["id"] != target:
                raise accounts.CodeError("That address already belongs to another OmniDoc account.")
            db.set_user_email(target, email, identity.get("avatar_url") or "")
            db.add_notice(target, "security", f"{provider.title()} sign-in linked", f"You can now also sign in with {provider.title()} ({email}).")
            return RedirectResponse(f"{home}#linked={provider}", status_code=302)
        session = _sign_in(email, identity.get("name") or "", provider, identity.get("avatar_url") or "", request)
        # The fragment never reaches a server or its logs; the app reads it and removes it.
        if "mfa" in session:
            return RedirectResponse(f"{home}#mfa={urllib.parse.quote(session['mfa'])}", status_code=302)
        return RedirectResponse(f"{home}#auth={urllib.parse.quote(session['token'])}", status_code=302)
    except accounts.CodeError as e:
        return RedirectResponse(f"{home}#auth_error={urllib.parse.quote(str(e))}", status_code=302)
    except Exception as e:
        logger.error(f"{provider} sign-in failed: {e}", exc_info=True)
        return RedirectResponse(f"{home}#auth_error={urllib.parse.quote('Sign-in failed. Try again.')}", status_code=302)


@app.get("/api/auth/challenge")
def proof_of_work_challenge(request: Request):
    """A small puzzle the browser solves before creating an account or a guest session (see core/abuse.py)."""
    _limit(request, "challenge", 30, 60)
    return abuse.new_challenge(accounts.derived_key(DATA_DIR, "pow"))


class PasskeySignupRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    pow: Optional[Dict[str, Any]] = None


class PasskeyVerifyRequest(BaseModel):
    challenge_id: str = Field(..., min_length=8, max_length=64)
    credential: Dict[str, Any]
    label: Optional[str] = Field(None, max_length=80)


def _passkeys_on() -> None:
    if not passkeys.enabled():
        raise HTTPException(status_code=404, detail="Passkeys are not available on this server.")


def _passkey_label(given: Optional[str], request: Request) -> str:
    return re.sub(r"\s+", " ", given or "").strip()[:80] or accounts.device_label(request.headers.get("user-agent"))


@app.post("/api/auth/passkey/signup/options")
def passkey_signup_options(req: PasskeySignupRequest, request: Request):
    """Starts creating an account with a passkey: no e-mail, just a name the account is shown with."""
    _passkeys_on()
    _limit(request, "signup", 10, 3600)
    _require_proof(req.pow)
    name = re.sub(r"\s+", " ", req.name).strip()
    if not name:
        raise HTTPException(status_code=422, detail="Enter your name.")
    challenge_id, options = passkeys.registration_options(db, "signup", passkeys.new_user_handle(), name)
    return {"challenge_id": challenge_id, "options": options}


@app.post("/api/auth/passkey/signup/verify")
def passkey_signup_verify(req: PasskeyVerifyRequest, request: Request):
    """Creates the account with its first passkey, signs it in and returns its ten recovery codes (shown once)."""
    _passkeys_on()
    try:
        reg = passkeys.verify_registration(db, req.challenge_id, "signup", req.credential)
    except passkeys.PasskeyError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    if db.get_passkey(reg["credential_id"]):
        raise HTTPException(status_code=409, detail="This passkey already belongs to an account. Sign in with it instead.")
    user_id = f"usr_{uuid.uuid4().hex[:12]}"
    user = db.create_user(user_id, reg["name"], "passkey", webauthn_handle=reg["handle"])
    db.add_passkey(reg["credential_id"], user_id, reg["public_key"], reg["sign_count"], reg["transports"],
                   _passkey_label(req.label, request))
    codes = two_factor.new_recovery_codes(db, DATA_DIR, user_id)
    return {"status": "success", "token": _new_session(user_id, request), "user": _public_user(user), "recovery_codes": codes}


@app.post("/api/auth/passkey/signin/options")
def passkey_signin_options(request: Request):
    _passkeys_on()
    _limit(request, "signin", 30, 300)
    challenge_id, options = passkeys.authentication_options(db)
    return {"challenge_id": challenge_id, "options": options}


@app.post("/api/auth/passkey/signin/verify")
def passkey_signin_verify(req: PasskeyVerifyRequest, request: Request):
    """Signs in with a passkey. A passkey is already two factors (the device and its lock), so no code follows."""
    _passkeys_on()
    try:
        user_id = passkeys.verify_authentication(db, req.challenge_id, req.credential)
    except passkeys.PasskeyError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    user = db.get_user(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="This passkey's account no longer exists.")
    return {"status": "success", "token": _new_session(user_id, request), "user": _public_user(user)}


class RecoveryRequest(BaseModel):
    code: str = Field(..., min_length=8, max_length=40)
    pow: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Passwords (core/passwords.py): username and password instead of a passkey; no e-mail, so a forgotten
# password is reset with one of the recovery codes given at sign-up.
# ---------------------------------------------------------------------------
class PasswordSignupRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=passwords.MAX_LENGTH)
    name: Optional[str] = Field(None, max_length=80)
    pow: Optional[Dict[str, Any]] = None


class PasswordSigninRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=passwords.MAX_LENGTH)


class PasswordResetRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    code: str = Field(..., min_length=8, max_length=40)
    password: str = Field(..., min_length=1, max_length=passwords.MAX_LENGTH)
    pow: Optional[Dict[str, Any]] = None


def _passwords_on() -> None:
    if not accounts.passwords_enabled():
        raise HTTPException(status_code=404, detail="Passwords are not available on this server.")


def _check_new_password(password: str, username: str) -> None:
    problem = passwords.password_problem(password, username)
    if problem:
        raise HTTPException(status_code=400, detail=problem)


@app.post("/api/auth/password/signup")
def password_signup(req: PasswordSignupRequest, request: Request):
    """Creates an account with a username and password, signs it in, and returns its ten recovery codes (shown once)."""
    _passwords_on()
    _limit(request, "signup", 10, 3600)
    _require_proof(req.pow)
    username = passwords.clean_username(req.username)
    problem = passwords.username_problem(username)
    if problem:
        raise HTTPException(status_code=400, detail=problem)
    _check_new_password(req.password, username)
    if db.get_user_by_username(username):
        raise HTTPException(status_code=409, detail="That username is taken. Choose another.")
    user_id = f"usr_{uuid.uuid4().hex[:12]}"
    db.create_user(user_id, (req.name or "").strip() or username, "password")
    db.set_username(user_id, username)
    db.set_password(user_id, passwords.hash_password(req.password))
    codes = two_factor.new_recovery_codes(db, DATA_DIR, user_id)
    return {"status": "success", "token": _new_session(user_id, request), "user": _public_user(db.get_user(user_id)),
            "recovery_codes": codes}


@app.post("/api/auth/password/signin")
def password_signin(req: PasswordSigninRequest, request: Request):
    """Signs in with a username and password, or returns a ticket for the authenticator-app step."""
    _passwords_on()
    username = passwords.clean_username(req.username)
    _limit(request, "password", 20, 600)
    _limit_key(f"password-user:{username}", 10, 900)
    user = db.get_user_by_username(username)
    if not passwords.verify_password(req.password, (user or {}).get("password_hash")):
        raise HTTPException(status_code=401, detail="That username and password do not match.")
    if user.get("totp_enabled"):
        return {"mfa": two_factor.issue_ticket(db, DATA_DIR, user["id"], "password")}
    return {"status": "success", "token": _new_session(user["id"], request), "user": _public_user(user)}


@app.post("/api/auth/password/reset")
def password_reset(req: PasswordResetRequest, request: Request):
    """Forgot password: one of the account's recovery codes and a new password. Other devices are signed out."""
    _passwords_on()
    _limit(request, "recovery", 10, 3600)
    _require_proof(req.pow)
    username = passwords.clean_username(req.username)
    user = db.get_user_by_username(username)
    if not user or not two_factor.use_recovery_code(db, DATA_DIR, req.code, user_id=user["id"]):
        raise HTTPException(status_code=401, detail="That username and recovery code do not match, or the code was already used.")
    _check_new_password(req.password, username)
    db.set_password(user["id"], passwords.hash_password(req.password))
    for s in db.list_sessions(user["id"]):
        db.delete_session_by_id(user["id"], s["id"])
    left = db.recovery_codes_left(user["id"])
    db.add_notice(user["id"], "security", "Your password was reset with a recovery code",
                  f"Other devices were signed out. {left} recovery code{'' if left == 1 else 's'} left.")
    return {"status": "success", "token": _new_session(user["id"], request), "user": _public_user(db.get_user(user["id"])),
            "recovery_codes_left": left}


@app.post("/api/auth/recovery")
def recovery_sign_in(req: RecoveryRequest, request: Request):
    """Signs in with a one-time recovery code (for an account whose passkeys are lost). The code is spent."""
    if not accounts_on():
        raise HTTPException(status_code=404, detail="Not available on a local install.")
    _limit(request, "recovery", 10, 3600)
    _require_proof(req.pow)
    user_id = two_factor.use_recovery_code(db, DATA_DIR, req.code)
    if not user_id or not db.get_user(user_id):
        raise HTTPException(status_code=401, detail="That recovery code is not valid, or it was already used.")
    left = db.recovery_codes_left(user_id)
    db.add_notice(user_id, "security", "A recovery code was used to sign in",
                  f"{left} recovery code{'' if left == 1 else 's'} left. Add a new passkey and, if few are left, make new codes under Account.")
    return {"status": "success", "token": _new_session(user_id, request), "user": _public_user(db.get_user(user_id)),
            "recovery_codes_left": left}


class TwoStepRequest(BaseModel):
    ticket: str = Field(..., min_length=8, max_length=100)
    code: str = Field(..., min_length=6, max_length=40)


@app.post("/api/auth/mfa")
def finish_two_step(req: TwoStepRequest, request: Request):
    """The second step after GitHub, Google or an e-mailed code: a code from the authenticator app, or a recovery code."""
    _limit(request, "mfa", 20, 300)
    try:
        user_id = two_factor.redeem_ticket(db, DATA_DIR, req.ticket, req.code)
    except two_factor.TwoFactorError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    return {"status": "success", "token": _new_session(user_id, request), "user": _public_user(db.get_user(user_id))}


class GuestRequest(BaseModel):
    pow: Optional[Dict[str, Any]] = None


@app.post("/api/auth/guest")
def start_guest_session(req: GuestRequest, request: Request):
    """A one-day guest session on the shared sample library (OMNIDOC_DEMO=1): read and ask, change nothing."""
    if not accounts.demo_enabled():
        raise HTTPException(status_code=404, detail="The demo is not available on this server.")
    _limit(request, "guest", accounts.guest_limits()["guests_per_ip_per_day"], 86400)
    _require_proof(req.pow)
    for old in db.stale_guests(older_than_days=2):
        db.delete_user(old)  # guests own conversations only; the sample library is shared
    user_id = f"gst_{uuid.uuid4().hex[:12]}"
    user = db.create_user(user_id, "Guest", "guest", kind="guest")
    token = db.create_session(user_id, ttl_days=accounts.GUEST_SESSION_DAYS,
                              device=accounts.device_label(request.headers.get("user-agent", "")))
    return {"status": "success", "token": token, "user": _public_user(user)}


@app.get("/api/auth/me")
def get_current_user(authorization: Optional[str] = Header(None), x_omnidoc_token: Optional[str] = Header(None)):
    token = _bearer(authorization, x_omnidoc_token)
    if not token:
        raise HTTPException(status_code=401, detail="Not signed in")
    user_id = db.get_session_user_id(token)
    if user_id:
        user = db.get_user(user_id)
        if user:
            return {"user": _public_user(user)}
    raise HTTPException(status_code=401, detail="Session expired. Sign in again.")


@app.post("/api/auth/logout")
def logout(authorization: Optional[str] = Header(None), x_omnidoc_token: Optional[str] = Header(None)):
    token = _bearer(authorization, x_omnidoc_token)
    if token:
        db.delete_session(token)
    response = JSONResponse({"status": "success"})
    response.delete_cookie(MEDIA_COOKIE, path="/api/documents")
    return response


@app.post("/api/auth/media")
def media_cookie(authorization: Optional[str] = Header(None), x_omnidoc_token: Optional[str] = Header(None)):
    """Puts the session in the cookie that page images, files and recordings are loaded with."""
    token = _bearer(authorization, x_omnidoc_token)
    if not token or not db.get_session_user_id(token):
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    response = JSONResponse({"status": "success"})
    response.set_cookie(MEDIA_COOKIE, token, max_age=30 * 86400, path="/api/documents", httponly=True, samesite="strict",
                        secure=os.environ.get("OMNIDOC_PUBLIC_URL", "").startswith("https://"))
    return response


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------
@app.get("/api/account")
def account_overview(user_id: str = Depends(current_user_id)):
    """The signed-in account, how it signs in, today's usage and its limits."""
    user = db.get_user(user_id) or {"id": user_id}
    guest = accounts_on() and is_guest(user_id)
    used = 0 if guest else db.storage_used(library_owner(user_id))
    if not accounts_on() or is_admin(user_id):
        limits = None
    elif guest:
        limits = {"questions_per_day": accounts.guest_limits()["questions_per_day"], "uploads_per_day": 0, "storage_mb": 0}
    else:
        limits = accounts.limits()
    trial = ({"limit": accounts.trial_answers(), "used": db.trial_used(user_id)}
             if accounts_on() and not is_admin(user_id) else None)
    return {"user": _public_user(user), "accounts": accounts_on(), "admin": is_admin(user_id), "guest": guest,
            "usage": db.usage_today(user_id), "storage_bytes": used, "limits": limits, "trial": trial,
            "own_keys": {"server": [r["provider"] for r in db.user_keys(user_id)] if accounts_on() and not guest else [],
                         "in_use": sorted(llm_providers.current_keys() or {})},
            "security": {"passkeys": len(db.list_passkeys(user_id)), "totp": bool(user.get("totp_enabled")),
                         "recovery_codes_left": db.recovery_codes_left(user_id), "email": user.get("email") or ""}}


# ---------------------------------------------------------------------------
# Account security: passkeys, authenticator app, recovery codes, devices, linked sign-in, export
# ---------------------------------------------------------------------------
def account_user(user_id: str = Depends(current_user_id)) -> str:
    if not accounts_on():
        raise HTTPException(status_code=404, detail="A local install has no account settings.")
    if is_guest(user_id):
        raise HTTPException(status_code=403, detail="Sign in to manage an account.")
    return user_id


def _ways_in(user_id: str, without_passkey: Optional[str] = None, without_password: bool = False) -> int:
    """How many independent ways the account can sign in: its passkeys, a password, and a linked address when a provider is on."""
    keys = [k for k in db.list_passkeys(user_id) if k["id"] != without_passkey]
    methods = accounts.methods()
    user = db.get_user(user_id) or {}
    linked = bool(user.get("email")) and (methods["github"] or methods["google"] or methods["email"])
    password = bool(user.get("password_hash")) and methods.get("password") and not without_password
    return len(keys) + (1 if linked else 0) + (1 if password else 0)


class PasswordChangeRequest(BaseModel):
    password: str = Field(..., min_length=1, max_length=passwords.MAX_LENGTH)
    current_password: Optional[str] = Field(None, max_length=passwords.MAX_LENGTH)
    # Needed the first time an account without one (a passkey or GitHub account) sets a password
    username: Optional[str] = Field(None, max_length=32)


@app.put("/api/account/password")
def set_account_password(req: PasswordChangeRequest, request: Request, user_id: str = Depends(account_user)):
    """Sets a password (and a username, the first time) or changes it; changing needs the current one."""
    _passwords_on()
    user = db.get_user(user_id) or {}
    if user.get("password_hash"):
        _limit_key(f"password-change:{user_id}", 10, 900)
        if not passwords.verify_password(req.current_password or "", user["password_hash"]):
            raise HTTPException(status_code=403, detail="The current password is not right.")
    username = user.get("username")
    if not username:
        username = passwords.clean_username(req.username or "")
        problem = passwords.username_problem(username)
        if problem:
            raise HTTPException(status_code=400, detail=problem)
        if db.get_user_by_username(username):
            raise HTTPException(status_code=409, detail="That username is taken. Choose another.")
        db.set_username(user_id, username)
    _check_new_password(req.password, username)
    changed = bool(user.get("password_hash"))
    db.set_password(user_id, passwords.hash_password(req.password))
    db.add_notice(user_id, "security", "Your password was changed" if changed else "A password was added to your account",
                  "If this was not you, reset it with a recovery code and sign other devices out under Devices.")
    return {"status": "success", "user": _public_user(db.get_user(user_id))}


@app.delete("/api/account/password")
def remove_account_password(user_id: str = Depends(account_user)):
    if _ways_in(user_id, without_password=True) < 1:
        raise HTTPException(status_code=400, detail="Add a passkey first: the password is the only way into this account.")
    db.set_password(user_id, None)
    db.add_notice(user_id, "security", "The password was removed from your account", "You sign in with a passkey or a linked account now.")
    return {"status": "success", "user": _public_user(db.get_user(user_id))}


@app.get("/api/account/passkeys")
def list_passkeys(user_id: str = Depends(account_user)):
    return {"passkeys": db.list_passkeys(user_id)}


@app.post("/api/account/passkeys/options")
def add_passkey_options(user_id: str = Depends(account_user)):
    _passkeys_on()
    user = db.get_user(user_id) or {}
    handle = user.get("webauthn_handle")
    if not handle:
        from webauthn.helpers import bytes_to_base64url
        handle = bytes_to_base64url(passkeys.new_user_handle())
        db.set_webauthn_handle(user_id, handle)
    from webauthn.helpers import base64url_to_bytes
    name = user.get("email") or user.get("name") or "OmniDoc account"
    challenge_id, options = passkeys.registration_options(
        db, "add", base64url_to_bytes(handle), name, user_id=user_id, exclude=[k["id"] for k in db.list_passkeys(user_id)])
    return {"challenge_id": challenge_id, "options": options}


@app.post("/api/account/passkeys/verify")
def add_passkey_verify(req: PasskeyVerifyRequest, request: Request, user_id: str = Depends(account_user)):
    _passkeys_on()
    try:
        reg = passkeys.verify_registration(db, req.challenge_id, "add", req.credential)
    except passkeys.PasskeyError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    if reg["user_id"] != user_id:
        raise HTTPException(status_code=400, detail="This request expired. Try again.")
    if db.get_passkey(reg["credential_id"]):
        raise HTTPException(status_code=409, detail="This passkey is already registered.")
    label = _passkey_label(req.label, request)
    db.add_passkey(reg["credential_id"], user_id, reg["public_key"], reg["sign_count"], reg["transports"], label)
    db.add_notice(user_id, "security", f"Passkey added: {label}", "")
    codes = two_factor.new_recovery_codes(db, DATA_DIR, user_id) if not db.recovery_codes_left(user_id) else None
    return {"status": "success", "passkeys": db.list_passkeys(user_id), "recovery_codes": codes}


@app.delete("/api/account/passkeys/{credential_id}")
def remove_passkey(credential_id: str, user_id: str = Depends(account_user)):
    if not any(k["id"] == credential_id for k in db.list_passkeys(user_id)):
        raise HTTPException(status_code=404, detail="Passkey not found")
    if _ways_in(user_id, without_passkey=credential_id) < 1:
        raise HTTPException(status_code=409, detail="This is your only way to sign in. Add another passkey or link GitHub first.")
    db.delete_passkey(user_id, credential_id)
    db.add_notice(user_id, "security", "A passkey was removed", "")
    return {"status": "success", "passkeys": db.list_passkeys(user_id)}


@app.post("/api/account/totp/setup")
def totp_setup(user_id: str = Depends(account_user)):
    """A new authenticator-app secret and its QR code; it takes effect once a code from the app is confirmed."""
    user = db.get_user(user_id) or {}
    secret = two_factor.new_secret()
    uri = two_factor.provisioning_uri(secret, user.get("email") or user.get("name") or user_id)
    challenge_id = secrets.token_urlsafe(18)
    db.put_challenge(challenge_id, "totp", "-", user_id, json.dumps({"secret": accounts.encrypt(DATA_DIR, secret)}))
    return {"challenge_id": challenge_id, "secret": secret, "uri": uri, "qr_svg": two_factor.qr_svg(uri)}


class TotpEnableRequest(BaseModel):
    challenge_id: str = Field(..., min_length=8, max_length=64)
    code: str = Field(..., min_length=6, max_length=12)


@app.post("/api/account/totp/enable")
def totp_enable(req: TotpEnableRequest, user_id: str = Depends(account_user)):
    row = db.take_challenge(req.challenge_id, "totp", 900)
    if not row or row.get("user_id") != user_id:
        raise HTTPException(status_code=400, detail="The setup expired. Start again.")
    sealed = json.loads(row.get("data") or "{}").get("secret", "")
    secret = accounts.decrypt(DATA_DIR, sealed)
    step = two_factor.check_totp(secret, req.code, 0) if secret else None
    if step is None:
        # The setup stays usable for another try.
        db.put_challenge(req.challenge_id, "totp", "-", user_id, row.get("data") or "{}")
        raise HTTPException(status_code=400, detail="That code is not right. Check the app's clock and try the newest code.")
    db.set_totp(user_id, sealed, True, step)
    db.add_notice(user_id, "security", "Two-step sign-in turned on", "Signing in with GitHub, Google or an e-mailed code now also asks for a code from your authenticator app.")
    codes = two_factor.new_recovery_codes(db, DATA_DIR, user_id) if not db.recovery_codes_left(user_id) else None
    return {"status": "success", "recovery_codes": codes}


class CodeCheckRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=40)


def _check_second_factor(user_id: str, code: str) -> None:
    user = db.get_user(user_id) or {}
    secret = accounts.decrypt(DATA_DIR, user.get("totp_secret") or "")
    step = two_factor.check_totp(secret, code, int(user.get("totp_last_step") or 0)) if secret else None
    if step is not None:
        db.set_totp_step(user_id, step)
        return
    if not two_factor.use_recovery_code(db, DATA_DIR, code, user_id=user_id):
        raise HTTPException(status_code=400, detail="That code is not right.")


@app.post("/api/account/totp/disable")
def totp_disable(req: CodeCheckRequest, user_id: str = Depends(account_user)):
    if not (db.get_user(user_id) or {}).get("totp_enabled"):
        return {"status": "success"}
    _check_second_factor(user_id, req.code)
    db.set_totp(user_id, None, False)
    db.add_notice(user_id, "security", "Two-step sign-in turned off", "")
    return {"status": "success"}


@app.post("/api/account/recovery-codes")
def new_recovery_codes(user_id: str = Depends(account_user)):
    """Ten new recovery codes; the old ones stop working."""
    codes = two_factor.new_recovery_codes(db, DATA_DIR, user_id)
    db.add_notice(user_id, "security", "New recovery codes were made", "The previous codes no longer work.")
    return {"recovery_codes": codes}


@app.get("/api/account/sessions")
def list_sessions(user_id: str = Depends(account_user), authorization: Optional[str] = Header(None),
                  x_omnidoc_token: Optional[str] = Header(None)):
    current = db.session_id(_bearer(authorization, x_omnidoc_token) or "")
    return {"sessions": [{"id": s["id"], "device": _device(s["user_agent"]), "created_at": s["created_at"],
                          "last_used_at": s["last_used_at"], "current": s["id"] == current}
                         for s in db.list_sessions(user_id)]}


@app.delete("/api/account/sessions/{session_id}")
def end_session(session_id: str, user_id: str = Depends(account_user)):
    if not db.delete_session_by_id(user_id, session_id):
        raise HTTPException(status_code=404, detail="Device not found")
    return {"status": "success"}


@app.post("/api/account/sessions/sign-out-others")
def end_other_sessions(user_id: str = Depends(account_user), authorization: Optional[str] = Header(None),
                       x_omnidoc_token: Optional[str] = Header(None)):
    ended = db.delete_other_sessions(user_id, _bearer(authorization, x_omnidoc_token) or "")
    return {"status": "success", "signed_out": ended}


@app.post("/api/account/link/{provider}")
def link_provider(provider: str, user_id: str = Depends(account_user)):
    """The consent page that adds GitHub or Google (its verified address) as another way into this account."""
    try:
        return {"url": accounts.authorize_url(db, DATA_DIR, provider, link_user_id=user_id)}
    except accounts.CodeError as e:
        raise HTTPException(status_code=e.status, detail=str(e))


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text or "").strip("-")[:60] or "untitled"


@app.get("/api/account/export")
def export_account(user_id: str = Depends(account_user)):
    """Everything the account holds, as a zip: the original documents, every conversation and the account record."""
    user = _public_user(db.get_user(user_id))
    spool = tempfile.SpooledTemporaryFile(max_size=32 * 1024 * 1024)
    with zipfile.ZipFile(spool, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.txt", "Your OmniDoc data, exported on " + time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()) + ".\n\n"
                   "account.json        the account, its passkeys and signed-in devices\n"
                   "documents/          the files you uploaded, as uploaded\n"
                   "conversations/      each conversation as Markdown and as JSON (with its sources)\n")
        z.writestr("account.json", json.dumps({
            "user": user, "passkeys": db.list_passkeys(user_id),
            "devices": [{"device": _device(s["user_agent"]), "created_at": s["created_at"],
                         "last_used_at": s["last_used_at"]} for s in db.list_sessions(user_id)],
            "usage_today": db.usage_today(user_id)}, indent=2, default=str))
        documents = []
        for doc in db.get_all_documents(owner_id=user_id):
            try:
                _, path = _stored_document(doc["id"], user_id)
            except HTTPException:
                continue
            name = f"documents/{doc['id']}-{Path(doc['filename']).name}"
            z.write(path, name)
            documents.append({"id": doc["id"], "filename": doc["filename"], "file": name, "uploaded": doc.get("upload_date"),
                              "size_bytes": doc.get("size_bytes")})
        z.writestr("documents/index.json", json.dumps(documents, indent=2, default=str))
        for n, chat in enumerate(db.list_chats(user_id), start=1):
            messages = db.get_messages(chat["id"])
            base = f"conversations/{n:03d}-{_slug(chat.get('title') or '')}"
            z.writestr(base + ".json", json.dumps({"chat": chat, "messages": messages}, indent=2, default=str))
            lines = [f"# {chat.get('title') or 'Conversation'}", ""]
            for m in messages:
                lines += [f"**{'You' if m['role'] == 'user' else 'OmniDoc'}** · {m.get('timestamp') or ''}", "", m.get("content") or "", ""]
            z.writestr(base + ".md", "\n".join(lines))
    size = spool.tell()
    spool.seek(0)

    def chunks():
        try:
            while True:
                block = spool.read(1024 * 1024)
                if not block:
                    break
                yield block
        finally:
            spool.close()

    stamp = time.strftime("%Y%m%d", time.gmtime())
    return StreamingResponse(chunks(), media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="omnidoc-export-{stamp}.zip"', "Content-Length": str(size)})


# ---------------------------------------------------------------------------
# Bring your own key: after the free answers, users answer with their own free model key. By default
# the browser keeps it and sends it with each request (X-OmniDoc-Keys); it is stored here, encrypted,
# only if the user asks, so it works on their other devices.
# ---------------------------------------------------------------------------
@app.get("/api/keys/providers")
def own_key_providers():
    """The providers a user can bring a free key for, where to get one, and the free answers before that."""
    providers = []
    for name in llm_providers.BYOK_PROVIDERS:
        p = llm_providers.REGISTRY[name]
        providers.append({"name": name, "label": p.label, "sign_up": p.sign_up, "free_note": p.free_note, "model": p.model})
    return {"providers": providers, "trial_answers": accounts.trial_answers()}


class KeyCheckRequest(BaseModel):
    provider: str = Field(..., min_length=2, max_length=40)
    key: str = Field(..., min_length=8, max_length=400)


@app.post("/api/keys/check")
def check_own_key(req: KeyCheckRequest, request: Request):
    """Tries a key with one tiny request to its provider. Nothing is stored."""
    _limit(request, "keycheck", 20, 3600)
    ok, why = llm_providers.check_key(req.provider, req.key)
    return {"ok": ok, "reason": why}


class OwnKeyRequest(BaseModel):
    key: str = Field(..., min_length=8, max_length=400)


def _own_keys_list(user_id: str) -> List[Dict[str, Any]]:
    return [{"provider": r["provider"], "last4": r["last4"], "added_at": r["added_at"]} for r in db.user_keys(user_id)]


@app.get("/api/account/keys")
def list_own_keys(user_id: str = Depends(account_user)):
    """Keys this account keeps on the server (only the last four characters are shown)."""
    return {"keys": _own_keys_list(user_id)}


@app.put("/api/account/keys/{provider}")
def save_own_key(provider: str, req: OwnKeyRequest, request: Request, user_id: str = Depends(account_user)):
    """Checks a key, then keeps it encrypted on the server so the account can use it from any device."""
    if provider not in llm_providers.BYOK_PROVIDERS:
        raise HTTPException(status_code=404, detail="Unknown provider")
    _limit(request, "keycheck", 20, 3600)
    ok, why = llm_providers.check_key(provider, req.key)
    if not ok:
        raise HTTPException(status_code=400, detail=why)
    key = req.key.strip()
    db.put_user_key(user_id, provider, accounts.encrypt(DATA_DIR, key), key[-4:])
    label = llm_providers.REGISTRY[provider].label
    db.add_notice(user_id, "security", f"{label} key saved on the server", "It is stored encrypted and used only for your answers.")
    return {"keys": _own_keys_list(user_id)}


@app.delete("/api/account/keys/{provider}")
def delete_own_key(provider: str, user_id: str = Depends(account_user)):
    if not db.delete_user_key(user_id, provider):
        raise HTTPException(status_code=404, detail="No key saved for this provider")
    return {"keys": _own_keys_list(user_id)}


# ---------------------------------------------------------------------------
# Notices: security events for the account and announcements (What's new)
# ---------------------------------------------------------------------------
@app.get("/api/notices")
def list_notices(user_id: str = Depends(current_user_id)):
    notices = db.list_notices(user_id)
    return {"notices": notices, "unread": sum(1 for n in notices if not n["read"])}


class NoticesReadRequest(BaseModel):
    ids: Optional[List[int]] = Field(None, max_length=500)


@app.post("/api/notices/read")
def read_notices(req: NoticesReadRequest, user_id: str = Depends(current_user_id)):
    db.mark_notices_read(user_id, req.ids)
    return {"status": "success"}


@app.delete("/api/account")
def delete_account(user_id: str = Depends(current_user_id)):
    """Deletes the account with all its documents (and their indexes, graph and files), chats and sessions."""
    if not accounts_on():
        raise HTTPException(status_code=404, detail="Local installs have no account to delete.")
    for doc_id in db.document_ids(user_id):
        _remove_document(doc_id)
    db.delete_user(user_id)
    try:
        get_pipeline().refresh_records()
    except Exception:
        pass
    return {"status": "success"}


@app.get("/api/health")
def health_check():
    stores: Dict[str, str] = {}
    try:
        db.conn.execute("SELECT 1").fetchone()
        stores["sqlite"] = "ok"
    except Exception as e:
        stores["sqlite"] = f"error: {e}"
    if _pipeline is not None:
        stores["kuzu"] = "ok" if _pipeline.graph_store.conn is not None else "unavailable"
        stores["lancedb"] = "ok" if getattr(_pipeline.lance_store, "table", None) is not None else "empty"
    else:
        stores["kuzu"] = stores["lancedb"] = "not loaded"
    return {
        "status": "healthy" if stores["sqlite"] == "ok" else "degraded",
        "service": "OmniDoc",
        "version": VERSION,
        "model": current_model(),
        "ollama": ollama_models(timeout=1.0) is not None,
        "providers": [p.name for p in llm_providers.chat_providers()],
        "stores": stores,
        "memory_mb": round(memory.rss_mb()),
        "timestamp": time.time(),
    }


@app.get("/api/models")
def list_models(user_id: str = Depends(current_user_id)):
    models = available_models()
    if not models:
        raise HTTPException(status_code=503, detail="No model is available: add a free API key to .env (see .env.example) or start Ollama.")
    # Everyone picks a model for their own questions; only an administrator changes the server's default.
    return {"models": models, "current": current_model(), "can_set_default": not accounts_on() or is_admin(user_id)}


def chosen_model(req: "QueryRequest") -> Optional[str]:
    """The answer model a question asked for, if it is one this server (or the user's own key) can use."""
    if not req.model or req.model == current_model():
        return None
    if req.model not in {m["name"] for m in available_models()}:
        raise HTTPException(status_code=400, detail="That model is not available here. Choose another in the model picker.")
    return req.model


@app.put("/api/models/current")
def set_model(req: ModelRequest, user_id: str = Depends(current_user_id)):
    require_admin(user_id)
    names = {m["name"] for m in available_models()}
    if req.model not in names:
        raise HTTPException(status_code=404, detail=f"Model {req.model} is not available (configure its API key or install it in Ollama)")
    settings = _load_settings()
    settings["model"] = req.model
    _save_settings(settings)
    if _pipeline is not None:
        _pipeline.set_model(req.model)
    return {"current": req.model}


@app.get("/api/providers")
def list_providers():
    """Which hosted model, embedding and web-search providers are configured, with their free-tier notes."""
    from agents.web_search_agent import search_providers
    pipeline = _pipeline
    return {
        "llm": llm_providers.provider_status(),
        "search": [{k: v for k, v in p.items() if k != "fn"} for p in search_providers()],
        "embedding_model": pipeline.embed_service.model_name if pipeline else None,
        "reindex": pipeline.reindex_status if pipeline else None,
        "ollama": ollama_models(timeout=1.0) is not None,
        "current_model": current_model(),
    }


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------
@app.get("/api/chats")
def list_chats(user_id: str = Depends(current_user_id)):
    return {"chats": db.list_chats(user_id)}


@app.post("/api/chats")
def create_chat(req: CreateChatRequest, user_id: str = Depends(current_user_id)):
    chat_id = f"chat_{uuid.uuid4().hex[:12]}"
    title = (req.title or NEW_CHAT_TITLE).strip()[:200] or NEW_CHAT_TITLE
    db.create_chat(chat_id=chat_id, document_id=req.document_id, title=title, user_id=user_id)
    return {"status": "success", "chat": db.get_chat(chat_id)}


@app.get("/api/chats/{chat_id}")
def get_chat(chat_id: str, user_id: str = Depends(current_user_id)):
    chat = owned_chat(chat_id, user_id)
    return {"chat": chat, "messages": db.get_messages(chat_id)}


@app.patch("/api/chats/{chat_id}")
def rename_chat(chat_id: str, req: RenameChatRequest, user_id: str = Depends(current_user_id)):
    owned_chat(chat_id, user_id)
    title = req.title.strip()
    db.update_chat_title(chat_id, title)
    return {"status": "success", "title": title}


@app.delete("/api/chats/{chat_id}")
def delete_chat(chat_id: str, user_id: str = Depends(current_user_id)):
    owned_chat(chat_id, user_id)
    db.delete_chat(chat_id)
    return {"status": "success", "deleted_chat_id": chat_id}


# ---------------------------------------------------------------------------
# Answer assembly: everything shown to the user comes from real pipeline state
# ---------------------------------------------------------------------------
LANGUAGE_NAMES = {
    "hi": "Hindi (हिन्दी)",
    "mr": "Marathi (मराठी)",
    "ta": "Tamil (தமிழ்)",
    "te": "Telugu (తెలుగు)",
    "kn": "Kannada (ಕನ್ನಡ)",
    "as": "Assamese (অসমীয়া)",
    "bn": "Bengali (বাংলা)",
    "gu": "Gujarati (ગુજરાતી)",
}


def to_jsonable(obj: Any) -> Any:
    """Recursively converts Pydantic models and containers to plain JSON values."""
    if hasattr(obj, "model_dump"):
        return to_jsonable(obj.model_dump())
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)


def _doc_titles() -> Dict[str, str]:
    return {d["id"]: d.get("filename") or d["id"] for d in db.get_all_documents()}


def _with_titles(sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    titles = _doc_titles()
    for s in sources:
        if isinstance(s, dict) and s.get("doc_id") and not s.get("doc_title"):
            s["doc_title"] = titles.get(s["doc_id"], s["doc_id"])
    return sources


def build_sources(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Numbered sources matching the [n] citations in the answer."""
    titles = _doc_titles()
    sources = to_jsonable(state.get("sources") or [])
    if not sources:
        # Older synthesis output without a numbered list: fall back to the real
        # retrieval results, keeping their real scores.
        package = state.get("evidence_package")
        items = getattr(package, "items", None) or []
        if items:
            for i, item in enumerate(items, start=1):
                prov = getattr(item, "provenance", {}) or {}
                sources.append({
                    "n": i,
                    "kind": "graph" if getattr(item, "source_type", "") == "kg_triple" else "chunk",
                    "doc_id": prov.get("doc_id", ""),
                    "chunk_id": prov.get("chunk_id", ""),
                    "page": prov.get("page_no") or prov.get("page_number") or prov.get("page"),
                    "section": prov.get("section_title") or prov.get("section") or "",
                    "snippet": (getattr(item, "content", "") or "")[:320],
                    "score": getattr(item, "relevance_score", None),
                })
        else:
            for i, ch in enumerate((state.get("chunk_context") or [])[:8], start=1):
                ch = to_jsonable(ch)
                sources.append({
                    "n": i,
                    "kind": "chunk",
                    "doc_id": ch.get("doc_id", ""),
                    "chunk_id": ch.get("chunk_id", ""),
                    "page": ch.get("page_number"),
                    "section": ch.get("section_title") or "",
                    "snippet": (ch.get("text") or "")[:320],
                    "score": ch.get("score"),
                })
    for s in sources:
        doc_id = s.get("doc_id") or ""
        if doc_id and not s.get("doc_title"):
            s["doc_title"] = titles.get(doc_id, doc_id)
    return sources


def build_verification(state: Dict[str, Any]) -> Dict[str, Any]:
    v = state.get("verification")
    if v is None:
        return {"status": "unverified", "score": None, "supported": 0, "unsupported": 0,
                "feedback": "The answer was not verified."}
    score = getattr(v, "faithfulness_score", None)
    supported = len(getattr(v, "supported_claims", []) or [])
    unsupported = len(getattr(v, "unsupported_claims", []) or [])
    feedback = getattr(v, "feedback", "") or ""
    sentences = to_jsonable(getattr(v, "sentences", None) or [])
    if score is None or (score == 0 and supported == 0 and unsupported == 0):
        status = "unverified"
        score = None
    elif getattr(v, "is_grounded", False) and unsupported == 0:
        status = "verified"
    else:
        status = "partial"
    return {"status": status, "score": None if score is None else round(float(score), 3),
            "supported": supported, "unsupported": unsupported, "feedback": feedback,
            "partial": sum(1 for s in sentences if s.get("verdict") == "partial"),
            "corrected": sum(1 for s in sentences if s.get("corrected_to")),
            "sentences": sentences}


def build_graph(state: Dict[str, Any]) -> Dict[str, Any]:
    nodes: Dict[str, Dict[str, Any]] = {}
    edges: Dict[tuple, Dict[str, Any]] = {}
    for sub in to_jsonable(state.get("graph_context") or []):
        if not isinstance(sub, dict):
            continue
        for n in sub.get("nodes", []):
            if n.get("id"):
                nodes[n["id"]] = {"id": n["id"], "name": n.get("name", n["id"]),
                                  "category": n.get("category") or "Entity",
                                  "description": n.get("description") or ""}
        for e in sub.get("edges", []):
            src = e.get("source_id") or e.get("source")
            tgt = e.get("target_id") or e.get("target")
            if src and tgt:
                edges[(src, tgt, e.get("relation"))] = {
                    "source": src, "target": tgt,
                    "source_name": e.get("source_name", ""), "target_name": e.get("target_name", ""),
                    "relation": e.get("relation") or "RELATED_TO", "description": e.get("description") or "",
                }
    return {"nodes": list(nodes.values()), "edges": list(edges.values())}


def build_answer(state: Dict[str, Any], steps: List[Dict[str, Any]], doc_ids: List[str], elapsed_ms: int) -> Dict[str, Any]:
    answer = state.get("verified_response") or state.get("draft_response") or ""
    if not answer.strip():
        answer = "I couldn't produce an answer from the current documents."
    visible_steps = [
        {k: s[k] for k in ("node", "label", "detail", "duration_ms") if k in s}
        for s in steps if not s.get("skipped")
    ]
    return {
        "answer": answer,
        "sources": build_sources(state),
        "math_results": to_jsonable(state.get("math_results") or []),
        "table_results": to_jsonable(state.get("table_results") or []),
        "visual_artifacts": to_jsonable(state.get("visual_artifacts") or []),
        "conflicts": to_jsonable(state.get("conflicts") or []),
        "graph": build_graph(state),
        "steps": visible_steps,
        "verification": build_verification(state),
        "model": current_model(),
        "elapsed_ms": elapsed_ms,
        "document_ids": doc_ids,
        # Model calls, tokens and the models that answered (from the execution budget)
        "usage": to_jsonable(state.get("usage") or {}),
    }


def _query_inputs(chat: Dict[str, Any], req: QueryRequest, user_id: str):
    """(what the model reads of the conversation, the documents the question may read, the question, the selected documents)."""
    messages = db.get_messages(chat["id"])
    # The last three exchanges in full, older ones as the chat's rolling summary (core/chat_memory.py).
    history = chat_memory.history_for(messages, chat.get("memory"), chat.get("memory_upto") or 0)
    selected = [d for d in (req.document_ids or []) if DOC_ID_RE.match(d)]
    if not selected and chat.get("document_id"):
        selected = [chat["document_id"]]
    doc_ids = scoped_ids(selected, user_id)
    query_text = req.query.strip()
    if req.language and req.language in LANGUAGE_NAMES:
        query_text += (
            f"\n\n[Instruction: write the complete final answer in {LANGUAGE_NAMES[req.language]}, "
            "keeping numbers, formulas and names exact.]"
        )
    return history, doc_ids, query_text, selected


def _summarize_for_memory(prompt: str) -> str:
    from agents.llm_utils import chat
    return chat(current_model(), [{"role": "user", "content": prompt}], fast=True, temperature=0.1, num_predict=400)


def _after_turn(chat_id: str, user_id: str) -> None:
    """Counts the question and brings the chat's memory up to date in the background."""
    _charge(user_id)
    chat_memory.update_in_background(chat_id, db.get_messages, db.get_chat, db.set_chat_memory, _summarize_for_memory)
    memory.release()


def _persist_turn(chat: Dict[str, Any], query: str, payload: Dict[str, Any], first_turn: bool) -> int:
    db.add_message(chat_id=chat["id"], role="user", content=query)
    metadata = {k: v for k, v in payload.items() if k != "answer"}
    # Plain-text trace kept for older clients and the report compiler
    metadata["thought_process"] = [
        f"{s['label']}" + (f" — {s['detail']}" if s.get("detail") else "") for s in payload["steps"]
    ]
    metadata["groundedness_score"] = payload["verification"]["score"]
    msg_id = db.add_message(chat_id=chat["id"], role="assistant", content=payload["answer"], metadata=metadata)
    if first_turn and chat.get("title") in (None, "", NEW_CHAT_TITLE, "New Conversation"):
        words = re.sub(r"\s+", " ", query).strip().split(" ")
        title = " ".join(words[:7]).rstrip("?.!,;:")
        db.update_chat_title(chat["id"], (title[:60] + "…") if len(title) > 60 else title)
    return msg_id


@app.post("/api/chats/{chat_id}/query")
def execute_chat_query(chat_id: str, req: QueryRequest, request: Request, user_id: str = Depends(current_user_id)):
    """Runs the agent pipeline and returns the complete answer."""
    chat = owned_chat(chat_id, user_id)
    _answer_gate(user_id, request)
    model = chosen_model(req)
    history, doc_ids, query_text, selected = _query_inputs(chat, req, user_id)
    first_turn = not chat.get("memory_upto") and not db.get_messages(chat_id)
    started = time.perf_counter()
    steps: List[Dict[str, Any]] = []
    state: Dict[str, Any] = {}
    try:
        for kind, data in get_pipeline().query_stream(
            user_query=query_text, document_ids=doc_ids, session_id=chat_id, conversation_history=history,
            web_mode=req.web or "auto", owner_id=library_owner(user_id) if accounts_on() else None,
            effort=req.effort or "balanced", model=model,
        ):
            if kind == "step":
                steps.append(data)
            elif kind == "result":
                state = data
    except Exception as e:
        logger.error(f"Pipeline failed for chat {chat_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="The agent pipeline failed. Check that Ollama is running and try again.")
    payload = build_answer(state, steps, selected, int((time.perf_counter() - started) * 1000))
    msg_id = _persist_turn(chat, req.query.strip(), payload, first_turn=first_turn)
    _after_turn(chat_id, user_id)
    return {"status": "success", "message_id": msg_id, **payload}


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str, ensure_ascii=False)}\n\n"


@app.post("/api/chats/{chat_id}/query/stream")
def stream_chat_query(chat_id: str, req: QueryRequest, request: Request, user_id: str = Depends(current_user_id)):
    """Runs the agent pipeline, streaming one `step` event per agent and a final `result`."""
    chat = owned_chat(chat_id, user_id)
    _answer_gate(user_id, request)
    model = chosen_model(req)
    history, doc_ids, query_text, selected = _query_inputs(chat, req, user_id)
    first_turn = not chat.get("memory_upto") and not db.get_messages(chat_id)

    def events() -> Iterator[str]:
        started = time.perf_counter()
        steps: List[Dict[str, Any]] = []
        state: Dict[str, Any] = {}
        try:
            for kind, data in get_pipeline().query_stream(
                user_query=query_text, document_ids=doc_ids, session_id=chat_id, conversation_history=history,
                web_mode=req.web or "auto", owner_id=library_owner(user_id) if accounts_on() else None,
                effort=req.effort or "balanced", model=model,
            ):
                if kind == "step":
                    steps.append(data)
                    if not data.get("skipped"):
                        yield _sse("step", {k: data[k] for k in ("node", "label", "detail", "duration_ms")})
                    continue
                if kind in ("sources", "reset"):
                    yield _sse(kind, _with_titles(to_jsonable(data or [])))
                    continue
                if kind == "delta":
                    yield _sse("delta", {"text": data})
                    continue
                if kind == "result":
                    state = data
            payload = build_answer(state, steps, selected, int((time.perf_counter() - started) * 1000))
            msg_id = _persist_turn(chat, req.query.strip(), payload, first_turn=first_turn)
            _after_turn(chat_id, user_id)
            yield _sse("result", {"status": "success", "message_id": msg_id, **payload})
        except Exception as e:
            logger.error(f"Streaming pipeline failed for chat {chat_id}: {e}", exc_info=True)
            yield _sse("error", {"message": "The agent pipeline failed. Check that a model is available (an API key in .env, or Ollama running) and try again."})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/query")
def standalone_query(req: QueryRequest, request: Request, user_id: str = Depends(current_user_id)):
    """One-off agentic query without a stored conversation (used by scripts and evals)."""
    _answer_gate(user_id, request)
    model = chosen_model(req)
    started = time.perf_counter()
    doc_ids = scoped_ids(req.document_ids, user_id)
    steps: List[Dict[str, Any]] = []
    state: Dict[str, Any] = {}
    for kind, data in get_pipeline().query_stream(
        user_query=req.query, document_ids=doc_ids,
        session_id=req.session_id or f"session_{uuid.uuid4().hex[:8]}",
        web_mode=req.web or "auto", owner_id=library_owner(user_id) if accounts_on() else None,
        effort=req.effort or "balanced", model=model,
    ):
        if kind == "step":
            steps.append(data)
        elif kind == "result":
            state = data
    _charge(user_id)
    return {"status": "success", **build_answer(state, steps, doc_ids, int((time.perf_counter() - started) * 1000))}


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
def _graph_status(doc_id: str) -> Optional[Dict[str, Any]]:
    if _pipeline is None:
        return None
    job = _pipeline.graph_jobs.get(doc_id)
    return dict(job) if job else None


def _record_summary(doc_id: str) -> Optional[Dict[str, Any]]:
    """Fields found and failed checks of a document's extracted record (None when it has none)."""
    try:
        rec = json.loads((DATA_DIR / "records" / f"{doc_id}.json").read_text())
    except (OSError, ValueError):
        return None
    fields = rec.get("fields") or []
    checks = rec.get("validation") or []
    return {"found": sum(1 for f in fields if f.get("status") == "found"), "total": len(fields),
            "failed_checks": sum(1 for c in checks if c.get("status") == "fail"), "template": rec.get("template")}


def _doc_meta(doc_id: str) -> Dict[str, Any]:
    """Pages, OCR and table counts recorded at upload (empty for documents uploaded earlier)."""
    try:
        return json.loads((LAYOUT_DIR / f"{doc_id}.meta.json").read_text())
    except (OSError, ValueError):
        return {}


@app.get("/api/documents")
def list_documents(user_id: str = Depends(current_user_id)):
    # Extraction progress lives in memory; after a restart fall back to what the graph holds.
    counts = _pipeline.graph_store.entity_counts_by_document() if _pipeline is not None else {}
    docs = []
    for d in db.get_all_documents(owner_id=library_owner(user_id)):
        d = dict(d)
        status = _graph_status(d["id"])
        if status is None and d["id"] in counts:
            status = {"status": "done", "processed": 0, "total": 0}
        if status is not None and _pipeline is not None:
            status["entities"] = counts.get(d["id"], 0)
        d["graph_status"] = status
        meta = _doc_meta(d["id"])
        d["pages"] = meta.get("pages")
        d["ocr_pages"] = len(meta.get("ocr_pages") or [])
        d["ocr_languages"] = meta.get("ocr_languages") or []
        d["table_count"] = meta.get("tables", 0)
        d["has_summary"] = (SUMMARY_DIR / f"{d['id']}.json").is_file()
        d["doc_type"] = meta.get("doc_type") or None
        d["doc_type_label"] = meta.get("doc_type_label") or None
        d["record"] = _record_summary(d["id"])
        d["viewer"] = "pages" if (d.get("file_type") or "").lower() in PAGED_TYPES else "text"
        docs.append(d)
    return {"documents": docs}


def _ingest_bytes(contents: bytes, original_name: str, ext: str, user_id: str = LOCAL_USER_ID) -> Dict[str, Any]:
    """Stores and indexes a document's bytes (shared by uploads and URL imports) in the user's library."""
    if not contents:
        raise HTTPException(status_code=400, detail="The file is empty")
    owner = library_owner(user_id)
    file_hash = hashlib.sha256(contents).hexdigest()
    existing = db.get_document_by_hash(file_hash, owner)
    if existing:
        return {"status": "success", "doc_id": existing["id"], "filename": existing["filename"],
                "chunk_count": existing.get("chunk_count") or 0, "duplicate": True}
    if accounts_on() and not is_admin(user_id) and user_id != accounts.DEMO_OWNER:
        check_quota(user_id, "uploads")
        cap = accounts.limits()["storage_mb"] * 1024 * 1024
        if db.storage_used(owner) + len(contents) > cap:
            raise HTTPException(status_code=413, detail=f"Your library is full ({cap // (1024 * 1024)} MB). Delete documents to add more.")

    # Each account keeps its own copy (and index) of a file; the local library keeps its ids.
    doc_id = (f"doc_{file_hash[:12]}" if owner == LOCAL_USER_ID
              else "doc_" + hashlib.sha256(f"{owner}:{file_hash}".encode()).hexdigest()[:12])
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    saved_path = UPLOAD_DIR / f"{doc_id}.{ext}"  # never trust the client filename in a path
    saved_path.write_bytes(contents)

    from parsing.transcribe import TranscriptionUnavailable
    try:
        parsed = get_pipeline().ingest_document(
            file_path=str(saved_path), doc_id=doc_id, doc_hash=file_hash,
            fast_mode=True, background_graph=True, title=original_name,
        )
    except TranscriptionUnavailable as e:
        saved_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"Ingestion failed for {original_name}: {e}", exc_info=True)
        saved_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="Could not read this document. It may be encrypted or corrupted.")

    chunk_count = len(parsed.chunks)
    db.add_document(doc_id=doc_id, filename=original_name, file_hash=file_hash,
                    size_bytes=len(contents), file_type=ext, chunk_count=chunk_count, owner_id=owner)
    if accounts_on():
        db.count_usage(user_id, "uploads")
    get_pipeline().refresh_records()
    memory.release()
    result = {"status": "success", "doc_id": doc_id, "filename": original_name,
              "chunk_count": chunk_count, "duplicate": False,
              "visual_element_count": len(getattr(parsed, "visual_elements", []) or []),
              "ocr_pages": len(getattr(parsed, "ocr_pages", []) or []),
              "table_count": len(getattr(parsed, "tables", []) or [])}
    if chunk_count == 0:
        from parsing import ocr
        result["warning"] = ("No text was found in this file." if ocr.tesseract_available() else
                             "No text was found. Install Tesseract (brew install tesseract) to read scanned pages and images.")
    return result


@app.post("/api/documents/upload")
def upload_document(file: UploadFile = File(...), user_id: str = Depends(current_user_id)):
    """Stores and indexes a document. Summaries, field extraction and the knowledge graph continue in the background."""
    original_name = Path(file.filename or "document").name or "document"
    ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail=f"Unsupported file type. Upload {', '.join(sorted(ALLOWED_EXTENSIONS))}.")
    contents = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"File is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    return _ingest_bytes(contents, original_name, ext, user_id)


class ImportUrlRequest(BaseModel):
    url: str = Field(..., min_length=8, max_length=2000)


@app.post("/api/documents/import-url")
def import_url(req: ImportUrlRequest, user_id: str = Depends(current_user_id)):
    """Adds a web page or an online PDF to the library (public addresses only)."""
    from parsing.web import safe_get, readable, FetchError
    try:
        body, ctype, final_url = safe_get(req.url.strip(), max_bytes=MAX_UPLOAD_BYTES)
    except FetchError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.warning(f"Import of {req.url} failed: {e}")
        raise HTTPException(status_code=502, detail="Could not download that address.")
    path_name = Path(urllib.parse.urlparse(final_url).path).name
    if ctype == "application/pdf" or body[:5] == b"%PDF-":
        name = path_name if path_name.lower().endswith(".pdf") else (path_name or "document") + ".pdf"
        return {**_ingest_bytes(body, name, "pdf", user_id), "url": final_url}
    if ctype.startswith("text/plain"):
        return {**_ingest_bytes(body, (path_name or "page") + ".txt", "txt", user_id), "url": final_url}
    title = readable(body.decode("utf-8", errors="replace"), final_url).get("title") or final_url
    safe_title = re.sub(r"[\\/:*?\"<>|]+", " ", title).strip()[:90] or "Web page"
    return {**_ingest_bytes(body, f"{safe_title}.html", "html", user_id), "url": final_url}


DEMO_DIR = Path(os.environ.get("OMNIDOC_DEMO_DIR") or DATA_DIR / "demo")


def _seed_demo_library() -> None:
    """Adds each file in the demo folder (once) to the shared sample library that guests read."""
    if not DEMO_DIR.is_dir():
        logger.info(f"Demo on, but {DEMO_DIR} has no files yet: guests will see an empty library.")
        return
    seeded = {d["filename"]: d for d in db.get_all_documents(owner_id=accounts.DEMO_OWNER)}
    for path in sorted(DEMO_DIR.iterdir()):
        ext = path.suffix.lower().lstrip(".")
        if not path.is_file() or ext not in ALLOWED_EXTENSIONS:
            continue
        try:
            contents = path.read_bytes()
            # A newer version of a sample replaces the old one instead of sitting beside it.
            old = seeded.get(path.name)
            if old and old.get("file_hash") != hashlib.sha256(contents).hexdigest():
                _remove_document(old["id"])
                logger.info(f"Demo library: replacing {path.name} with its new version")
            result = _ingest_bytes(contents, path.name, ext, accounts.DEMO_OWNER)
            if not result.get("duplicate"):
                logger.info(f"Demo library: added {path.name}")
        except Exception as e:
            logger.warning(f"Demo library: could not add {path.name}: {getattr(e, 'detail', e)}")


def _remove_document(doc_id: str) -> None:
    """Removes a document from SQLite, LanceDB, the knowledge graph, the record tables and disk."""
    get_pipeline().delete_document(doc_id)
    db.delete_document(doc_id)
    get_pipeline().refresh_records()
    for path in UPLOAD_DIR.glob(f"{doc_id}*"):
        path.unlink(missing_ok=True)


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: str, user_id: str = Depends(current_user_id)):
    """Removes a document from SQLite, LanceDB, the knowledge graph and disk."""
    if not DOC_ID_RE.match(doc_id):
        raise HTTPException(status_code=400, detail="Invalid document id")
    doc = db.get_document(doc_id)
    if doc and doc.get("owner_id", LOCAL_USER_ID) != library_owner(user_id):
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        _remove_document(doc_id)
    except Exception as e:
        logger.error(f"Failed to delete document {doc_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not delete the document")
    return {"status": "success", "deleted_doc_id": doc_id}


class SummariesRequest(BaseModel):
    document_ids: Optional[List[str]] = Field(None, max_length=500)


@app.post("/api/documents/summaries")
def summarize_documents(req: Optional[SummariesRequest] = None, user_id: str = Depends(current_user_id)):
    """Writes summaries, in the background, for documents (all by default) that have none yet."""
    doc_ids = [d for d in (req.document_ids or []) if DOC_ID_RE.match(d)] if req and req.document_ids else None
    if accounts_on():
        mine = set(db.document_ids(library_owner(user_id)))
        doc_ids = [d for d in (doc_ids or mine) if d in mine] or [NO_DOCUMENTS]
    queued = get_pipeline().summarize_missing(doc_ids)
    return {"status": "success", "queued": queued}


# ---------------------------------------------------------------------------
# Document viewer: the original file, page images, citation highlights, text, summary
# ---------------------------------------------------------------------------
_render_lock = threading.Lock()


def _stored_document(doc_id: str, user_id: str = LOCAL_USER_ID):
    """The library record and the stored upload of a document the user may read (404 otherwise)."""
    if not DOC_ID_RE.match(doc_id):
        raise HTTPException(status_code=400, detail="Invalid document id")
    doc = db.get_document(doc_id)
    if not doc or doc.get("owner_id", LOCAL_USER_ID) != library_owner(user_id):
        raise HTTPException(status_code=404, detail="Document not found")
    ext = (doc.get("file_type") or "").lower()
    path = UPLOAD_DIR / f"{doc_id}.{ext}"
    if not path.is_file():
        # Older versions stored uploads as "<doc_id>_<original name>".
        matches = sorted(p for p in UPLOAD_DIR.glob(f"{doc_id}*") if p.is_file())
        if not matches:
            raise HTTPException(status_code=404, detail="The original file is no longer on disk")
        path = matches[0]
    return doc, path


def _file_type(path: Path) -> str:
    return path.suffix.lower().lstrip(".")


@app.get("/api/documents/{doc_id}/file")
def document_file(doc_id: str, user_id: str = Depends(current_user_id)):
    """The original uploaded file, shown inline by the browser where it can."""
    doc, path = _stored_document(doc_id, user_id)
    name = doc.get("filename") or path.name
    disposition = _attachment(name.rsplit(".", 1)[0], _file_type(path))["Content-Disposition"].replace("attachment", "inline", 1)
    return FileResponse(path, media_type=MEDIA_TYPES.get(_file_type(path), "application/octet-stream"),
                        headers={"Content-Disposition": disposition})


@app.get("/api/documents/{doc_id}/info")
def document_info(doc_id: str, user_id: str = Depends(current_user_id)):
    """What the viewer needs: page sizes (with OCR language per page), tables and summary state."""
    doc, path = _stored_document(doc_id, user_id)
    ftype = _file_type(path)
    pipeline = get_pipeline()
    layout = pipeline.layout(doc_id)
    pages = [{"w": p.get("w"), "h": p.get("h"), "ocr": bool(p.get("ocr")), "lang": p.get("lang")}
             for p in layout.get("pages", [])]
    if ftype in PAGED_TYPES and not pages:
        # Uploaded before layouts were stored: read the page sizes from the file.
        from parsing import ocr
        with _render_lock:
            with ocr.open_as_pdf(str(path)) as pdf:
                pages = [{"w": round(pg.rect.width, 1), "h": round(pg.rect.height, 1), "ocr": False, "lang": None}
                         for pg in pdf]
    meta = _doc_meta(doc_id)
    tables = [{"table": t["table"], "title": t["title"], "page": t["page"], "n_rows": t["n_rows"],
               "columns": [c["name"] for c in t["columns"]]} for t in pipeline.table_store.tables_for([doc_id])]
    return {
        "id": doc_id,
        "filename": doc.get("filename") or path.name,
        "file_type": ftype,
        "media": layout.get("media") if ftype in MEDIA_FILE_TYPES else None,
        "attachments": layout.get("attachments") or [],
        "size_bytes": doc.get("size_bytes"),
        "viewer": "pages" if ftype in PAGED_TYPES else "text",
        "pages": pages,
        "ocr_pages": meta.get("ocr_pages") or [p for p, info in enumerate(pages, 1) if info["ocr"]],
        "ocr_languages": meta.get("ocr_languages") or [],
        "tables": tables,
        "has_summary": pipeline.summarizer.has(doc_id),
    }


@app.get("/api/documents/{doc_id}/pages/{page_no}")
def document_page(doc_id: str, page_no: int, width: int = 1000, user_id: str = Depends(current_user_id)):
    """One page as a PNG at the nearest standard width (cached on disk; ids are content hashes)."""
    _, path = _stored_document(doc_id, user_id)
    if _file_type(path) not in PAGED_TYPES:
        raise HTTPException(status_code=404, detail="This document has no page images")
    width = min(PAGE_WIDTHS, key=lambda w: abs(w - width))
    cache = PAGE_CACHE_DIR / doc_id / f"p{page_no}_w{width}.png"
    if not cache.is_file():
        import fitz
        from parsing import ocr
        with _render_lock:
            with ocr.open_as_pdf(str(path)) as pdf:
                if not 1 <= page_no <= len(pdf):
                    raise HTTPException(status_code=404, detail="Page not found")
                page = pdf[page_no - 1]
                zoom = width / (float(page.rect.width) or 1.0)
                # Very tall pages (receipts, long scans): cap the pixel count.
                zoom = min(zoom, (MAX_PAGE_PIXELS / max(1.0, page.rect.width * page.rect.height)) ** 0.5)
                png = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False).tobytes("png")
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_name(cache.name + ".part")
        tmp.write_bytes(png)
        os.replace(tmp, cache)
    return FileResponse(cache, media_type="image/png", headers={"Cache-Control": "private, max-age=604800"})


class LocateRequest(BaseModel):
    page: Optional[int] = Field(None, ge=1, le=100000)
    chunk_id: Optional[str] = Field(None, max_length=200)
    claim: Optional[str] = Field(None, max_length=4000)
    passage: Optional[str] = Field(None, max_length=12000)
    table: Optional[str] = Field(None, max_length=200)
    exact: bool = False


@app.post("/api/documents/{doc_id}/locate")
def locate_citation(doc_id: str, req: LocateRequest, user_id: str = Depends(current_user_id)):
    """
    Where a cited passage, and the sentence of it that supports the claim, sits in the
    document: normalised rectangles on a page for PDFs and images, or the chunk and quote to
    mark in the text of other documents.
    """
    from parsing.locate import locate, best_sentence
    _, path = _stored_document(doc_id, user_id)
    pipeline = get_pipeline()
    passage, page_no, chunk_id = req.passage or "", req.page, ""
    if req.chunk_id and DOC_ID_RE.match(req.chunk_id):
        chunk = pipeline.lance_store.get_chunk(req.chunk_id)
        if chunk is not None and chunk.doc_id == doc_id:
            # The full passage, not the shortened snippet the client has.
            passage, chunk_id = chunk.text, chunk.chunk_id
            page_no = page_no or chunk.page_number
    table_box = None
    if req.table:
        entry = next((t for t in pipeline.table_store.tables_for([doc_id])
                      if req.table in (t["table"], t["table_id"])), None)
        if entry and entry.get("bbox") and entry.get("page"):
            table_box, page_no = entry["bbox"], entry["page"]
    claim = (req.claim or "").strip()

    if _file_type(path) not in PAGED_TYPES:
        quote = (claim if req.exact else best_sentence(passage, claim)) if claim and passage else ""
        return {"page": page_no, "rects": [], "quote": quote, "method": "text", "chunk_id": chunk_id}

    from parsing import ocr
    with _render_lock:
        with ocr.open_as_pdf(str(path)) as pdf:
            result = locate(pdf, pipeline.layout(doc_id), page_no or 1, passage=passage, claim=claim,
                            chunk_id=chunk_id, table=table_box, exact=req.exact)
    result["chunk_id"] = chunk_id
    return result


def _strip_overlap(previous: str, text: str, max_words: int = 80) -> str:
    """Drops the words a chunk repeats from the end of the one before it (chunks overlap)."""
    prev_words, words = previous.split(), text.split()
    for k in range(min(max_words, len(prev_words), len(words) - 1), 4, -1):
        if prev_words[-k:] == words[:k]:
            return " ".join(words[k:])
    return text


@app.get("/api/documents/{doc_id}/text")
def document_text(doc_id: str, user_id: str = Depends(current_user_id)):
    """The document's text in reading order, as its indexed passages (overlaps removed)."""
    doc, _ = _stored_document(doc_id, user_id)
    chunks = get_pipeline().lance_store.get_document_chunks(doc_id)
    out, previous = [], ""
    for c in chunks:
        out.append({"chunk_id": c.chunk_id, "page": c.page_number, "section": c.section_title,
                    "text": _strip_overlap(previous, c.text) if previous else c.text})
        previous = c.text
    return {"doc_id": doc_id, "title": doc.get("filename") or doc_id, "chunks": out}


@app.get("/api/documents/{doc_id}/tables/{table}")
def document_table(doc_id: str, table: str, limit: int = 200, user_id: str = Depends(current_user_id)):
    """Rows of one extracted table (for the viewer of spreadsheets and table citations)."""
    _stored_document(doc_id, user_id)
    store = get_pipeline().table_store
    entry = next((t for t in store.tables_for([doc_id]) if table in (t["table"], t["table_id"])), None)
    if entry is None:
        raise HTTPException(status_code=404, detail="Table not found")
    limit = min(max(1, limit), 1000)
    try:
        result = store.run_select(f'SELECT * FROM "{entry["table"]}"', [entry["table"]], max_rows=limit)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"table": entry["table"], "title": entry["title"], "page": entry["page"], "n_rows": entry["n_rows"],
            "columns": [c["name"] for c in entry["columns"]], "rows": result["rows"],
            "truncated": result["truncated"]}


@app.get("/api/documents/{doc_id}/summary")
def document_summary(doc_id: str, user_id: str = Depends(current_user_id)):
    _stored_document(doc_id, user_id)
    summary = get_pipeline().summarizer.load(doc_id)
    if summary is not None:
        return {"status": "ready", "summary": summary}
    job = _graph_status(doc_id) or {}
    pending = job.get("stage") == "summary" and job.get("status") in ("queued", "running")
    return {"status": "pending" if pending else "missing", "summary": None,
            "progress": {"processed": job.get("processed", 0), "total": job.get("total", 0)} if pending else None}


class RecordRequest(BaseModel):
    doc_type: Optional[str] = Field(None, max_length=40)


@app.get("/api/documents/{doc_id}/record")
def document_record(doc_id: str, user_id: str = Depends(current_user_id)):
    """The document's detected type and the fields extracted from it, with consistency checks."""
    _stored_document(doc_id, user_id)
    meta = _doc_meta(doc_id)
    job = _graph_status(doc_id) or {}
    return {
        "doc_type": meta.get("doc_type") or "other",
        "label": meta.get("doc_type_label") or "Document",
        "confidence": meta.get("doc_type_confidence"),
        "record": get_pipeline().records.load(doc_id),
        "pending": job.get("stage") == "extract" and job.get("status") in ("queued", "running"),
    }


@app.post("/api/documents/{doc_id}/record")
def extract_record(doc_id: str, req: RecordRequest, user_id: str = Depends(current_user_id)):
    """(Re-)extracts the fields of the document's type; ``doc_type`` corrects a wrong detection."""
    from agents.extraction_agent import TYPE_PRESETS
    from agents.doc_classifier import LABELS
    doc, _ = _stored_document(doc_id, user_id)
    pipeline = get_pipeline()
    meta_path = LAYOUT_DIR / f"{doc_id}.meta.json"
    meta = _doc_meta(doc_id)
    if req.doc_type:
        if req.doc_type not in TYPE_PRESETS:
            raise HTTPException(status_code=400, detail=f"No template for {req.doc_type}")
        meta.update(doc_type=req.doc_type, doc_type_label=LABELS.get(req.doc_type, req.doc_type), doc_type_confidence=1.0)
        meta_path.write_text(json.dumps(meta))
    if not TYPE_PRESETS.get(meta.get("doc_type") or ""):
        raise HTTPException(status_code=400, detail="This document type has no extraction template; choose a type first.")
    pipeline.records.delete(doc_id)
    pipeline._auto_extract(doc_id, doc.get("filename") or doc_id)
    return document_record(doc_id)


def _pii_findings(doc_id: str, path: Path, kinds: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    from parsing import pii
    if _file_type(path) in PAGED_TYPES:
        from parsing import ocr
        with _render_lock:
            with ocr.open_as_pdf(str(path)) as pdf:
                return pii.find_in_document(pdf, get_pipeline().layout(doc_id), kinds)
    findings = []
    for c in document_text(doc_id)["chunks"]:
        for f in pii.find_in_text(c["text"], kinds):
            findings.append({**f, "page": c["page"], "chunk_id": c["chunk_id"], "rects": [],
                             "context": c["text"][max(0, f["start"] - 50):f["end"] + 50].replace(f["value"], f["masked"])})
    return findings


@app.get("/api/documents/{doc_id}/sensitive")
def sensitive_data(doc_id: str, user_id: str = Depends(current_user_id)):
    """Personal and financial identifiers found in the document (values masked), with where they are."""
    _, path = _stored_document(doc_id, user_id)
    findings = _pii_findings(doc_id, path)
    counts: Dict[str, int] = {}
    for f in findings:
        counts[f["label"]] = counts.get(f["label"], 0) + 1
    public = [{k: f[k] for k in ("type", "label", "masked", "page", "rects", "context") if k in f} | {"chunk_id": f.get("chunk_id")}
              for f in findings]
    return {"findings": public, "counts": counts}


class RedactRequest(BaseModel):
    types: Optional[List[str]] = Field(None, max_length=20)


@app.post("/api/documents/{doc_id}/redact")
def redact_document(doc_id: str, req: RedactRequest, user_id: str = Depends(current_user_id)):
    """A copy with the sensitive values removed: real PDF redactions for PDFs and scans, blacked-out text otherwise."""
    from parsing import pii
    doc, path = _stored_document(doc_id, user_id)
    kinds = [k for k in (req.types or []) if k in pii.LABELS] or None
    base = (doc.get("filename") or doc_id).rsplit(".", 1)[0] + " (redacted)"
    if _file_type(path) in PAGED_TYPES:
        from parsing import ocr
        findings = _pii_findings(doc_id, path, kinds)
        with _render_lock:
            with ocr.open_as_pdf(str(path)) as pdf:
                data = pii.redact_pdf(pdf, findings)
        return StreamingResponse(io.BytesIO(data), media_type="application/pdf", headers=_attachment(base, "pdf"))
    text = "\n\n".join(c["text"] for c in document_text(doc_id)["chunks"])
    redacted, _ = pii.redact_text(text, kinds)
    return StreamingResponse(io.BytesIO(redacted.encode("utf-8")), media_type="text/plain; charset=utf-8",
                             headers=_attachment(base, "txt"))


class CompareRequest(BaseModel):
    a: str = Field(..., max_length=128)
    b: str = Field(..., max_length=128)
    summarize: bool = False


@app.post("/api/compare")
def compare_documents(req: CompareRequest, request: Request, user_id: str = Depends(current_user_id)):
    """Sentence-level comparison of two documents (modified, added, removed, changed figures); optional summary."""
    from agents.compare_agent import compare, summarize
    if req.summarize:
        _answer_gate(user_id, request)  # the comparison itself needs no model; its summary does
    doc_a, _ = _stored_document(req.a, user_id)
    doc_b, _ = _stored_document(req.b, user_id)
    store = get_pipeline().lance_store
    result = compare(store.get_document_chunks(req.a), store.get_document_chunks(req.b))
    result["a"] = {"id": req.a, "title": doc_a.get("filename") or req.a}
    result["b"] = {"id": req.b, "title": doc_b.get("filename") or req.b}
    if req.summarize and result["changes"]:
        try:
            result["summary"] = summarize(current_model(), result["a"]["title"], result["b"]["title"], result["changes"])
            _charge(user_id)
        except Exception as e:
            logger.warning(f"Change summary failed: {e}")
            result["summary_error"] = "The summary could not be written (no model answered)."
    return result


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    document_ids: Optional[List[str]] = None
    top_k: int = Field(8, ge=1, le=30)


@app.post("/api/search")
def search_documents(req: SearchRequest, user_id: str = Depends(current_user_id)):
    """Hybrid search (vectors + BM25, reranked) without a model call: the passages, with their document and page."""
    doc_ids = scoped_ids(req.document_ids, user_id) or None
    hits, pool = get_pipeline().hybrid_agent.search([req.query], doc_ids, top_k=req.top_k)
    titles = _doc_titles()
    return {"candidates": pool, "results": [{
        "doc_id": h.doc_id, "title": titles.get(h.doc_id, h.doc_id), "chunk_id": h.chunk_id, "page": h.page_number,
        "section": h.section_title, "score": h.score, "text": h.text} for h in hits]}


@app.get("/api/web/page")
def web_page(url: str, passage: str = "", claim: str = ""):
    """
    A web page cited in an answer, read on the server (public addresses only) and returned as
    clean paragraphs, with the paragraph and sentence to highlight.
    """
    from parsing.web import read_page, FetchError
    from parsing.locate import best_sentence, norm_tokens
    try:
        page = read_page(url, cache_dir=str(DATA_DIR / "web_cache"))
    except FetchError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.warning(f"Could not read {url}: {e}")
        raise HTTPException(status_code=502, detail="Could not read that page.")
    target = set(norm_tokens(passage or claim))
    best_i, best_score = None, 0.0
    for i, para in enumerate(page.get("paragraphs") or []):
        tokens = set(norm_tokens(para))
        score = len(tokens & target) / max(1, len(target))
        if score > best_score:
            best_i, best_score = i, score
    quote = ""
    if best_i is not None and claim:
        quote = best_sentence(page["paragraphs"][best_i], claim)
    return {**page, "highlight": {"paragraph": best_i if best_score >= 0.3 else None, "quote": quote}}


# ---------------------------------------------------------------------------
# Schema extraction
# ---------------------------------------------------------------------------
class ExtractRequest(BaseModel):
    document_ids: List[str] = Field(..., min_length=1, max_length=50)
    fields: List[Dict[str, Any]] = Field(default_factory=list, max_length=30)
    preset: Optional[str] = Field(None, max_length=40)


@app.get("/api/extract/presets")
def extract_presets():
    from agents.extraction_agent import presets_payload, FIELD_TYPES
    return {"presets": presets_payload(), "types": list(FIELD_TYPES)}


@app.post("/api/extract/stream")
def extract_stream(req: ExtractRequest, request: Request, user_id: str = Depends(current_user_id)):
    """
    Fills the fields from each document, streaming `start`, then per document `doc_start`,
    `progress` and `doc_result` (or `doc_error`), and finally `done` with CSV rows.
    """
    from agents.extraction_agent import PRESETS, normalise_fields, results_to_csv_rows
    fields = normalise_fields(req.fields or (PRESETS.get(req.preset or "") or {}).get("fields") or [])
    if not fields:
        raise HTTPException(status_code=400, detail="Add at least one field to extract")
    _answer_gate(user_id, request)
    _charge(user_id)  # one extraction run counts as one answer
    titles = _doc_titles()
    mine = set(db.document_ids(library_owner(user_id)))
    doc_ids = [d for d in dict.fromkeys(req.document_ids) if DOC_ID_RE.match(d) and d in titles and d in mine]
    if not doc_ids:
        raise HTTPException(status_code=404, detail="None of the selected documents exist")
    agent = get_pipeline().extraction_agent

    def run_one(doc_id: str, updates: "queue.Queue") -> None:
        try:
            result = agent.extract(doc_id, titles[doc_id], fields,
                                   progress=lambda done, total: updates.put(("progress", {"doc_id": doc_id, "done": done, "total": total})))
            for f in result["fields"]:
                f.pop("_text", None)
            updates.put(("doc_result", result))
        except Exception as e:
            logger.error(f"Extraction failed for {doc_id}: {e}", exc_info=True)
            updates.put(("doc_error", {"doc_id": doc_id, "title": titles[doc_id], "message": "Extraction failed for this document."}))
        finally:
            updates.put(("finished", None))

    def events() -> Iterator[str]:
        started = time.perf_counter()
        results: List[Dict[str, Any]] = []
        yield _sse("start", {"documents": len(doc_ids), "fields": fields})
        for i, doc_id in enumerate(doc_ids, 1):
            yield _sse("doc_start", {"doc_id": doc_id, "title": titles[doc_id], "index": i, "total": len(doc_ids)})
            updates: "queue.Queue" = queue.Queue()
            threading.Thread(target=llm_providers.carry(run_one), args=(doc_id, updates), name=f"extract-{doc_id}", daemon=True).start()
            while True:
                try:
                    kind, data = updates.get(timeout=15)
                except queue.Empty:
                    yield ": keep-alive\n\n"  # local models can take a while per batch
                    continue
                if kind == "finished":
                    break
                if kind == "doc_result":
                    results.append(data)
                yield _sse(kind, data)
        yield _sse("done", {"elapsed_ms": int((time.perf_counter() - started) * 1000),
                            "csv_rows": results_to_csv_rows(results)})

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------------------
# Knowledge graph
# ---------------------------------------------------------------------------
@app.get("/api/graph")
def get_knowledge_graph(limit: int = 2000, user_id: str = Depends(current_user_id)):
    scope = db.document_ids(library_owner(user_id)) if accounts_on() else None
    data = get_pipeline().graph_store.get_all_graph(limit=limit, doc_ids=scope)
    # Graphs built by older versions stored the internal file name as the title.
    titles = _doc_titles()
    for d in data.get("documents", []):
        d["title"] = titles.get(d["id"]) or d.get("title") or d["id"]
    return {"status": "success", **data}


@app.get("/api/graph/node/{node_id}")
def get_node_details(node_id: str, user_id: str = Depends(current_user_id)):
    found = get_pipeline().graph_store.get_node(node_id)
    if found and accounts_on() and found["node"].get("doc_id") not in set(db.document_ids(library_owner(user_id))):
        found = None
    if not found:
        raise HTTPException(status_code=404, detail="Entity not found")
    return {"node": found["node"], "connected_edges": found["edges"],
            "stats": {"degree": len(found["edges"]), "category": found["node"]["category"]}}


# ---------------------------------------------------------------------------
# Report export
# ---------------------------------------------------------------------------
def _export_messages(req: ExportRequest, user_id: str):
    title = req.title or "OmniDoc analysis"
    if req.chat_id:
        chat = owned_chat(req.chat_id, user_id)
        title = chat.get("title") or title
        messages = []
        for m in db.get_messages(req.chat_id):
            meta = m.get("metadata") if isinstance(m.get("metadata"), dict) else {}
            sources = [
                {**s, "source_type": s.get("source_type") or s.get("kind", "")}
                for s in (meta.get("sources") or []) if isinstance(s, dict)
            ]
            item = {
                "role": m["role"],
                "content": m["content"],
                "sources": sources,
                "conflicts": meta.get("conflicts", []),
                "graph_entities": meta.get("graph", {}).get("nodes", []) if isinstance(meta.get("graph"), dict) else meta.get("graph_entities", []),
                "math_results": meta.get("math_results", []),
                "visual_artifacts": meta.get("visual_artifacts", []),
            }
            if meta.get("math_results"):
                item["math_result"] = meta["math_results"][0]
            messages.append(item)
        scores = [
            (m.get("metadata") or {}).get("groundedness_score")
            for m in db.get_messages(req.chat_id) if isinstance(m.get("metadata"), dict)
        ]
        scores = [s for s in scores if isinstance(s, (int, float))]
        meta = {"model_name": current_model(), "groundedness_score": (sum(scores) / len(scores)) if scores else None}
        return title, messages, meta
    if req.messages:
        return title, req.messages, req.metadata or {"model_name": current_model()}
    raise HTTPException(status_code=400, detail="Either chat_id or messages must be provided")


def _attachment(title: str, ext: str) -> Dict[str, str]:
    """Content-Disposition that survives non-Latin titles (RFC 6266 / 5987)."""
    base = re.sub(r"\s+", "_", title.strip()) or "OmniDoc_analysis"
    ascii_name = re.sub(r"[^A-Za-z0-9_.-]", "", base)
    if not re.search(r"[A-Za-z0-9]", ascii_name):
        ascii_name = "OmniDoc_analysis"
    quoted = urllib.parse.quote(f"{base}.{ext}")
    return {"Content-Disposition": f"attachment; filename=\"{ascii_name}.{ext}\"; filename*=UTF-8''{quoted}"}


@app.post("/api/export/pdf")
def export_pdf(req: ExportRequest, user_id: str = Depends(current_user_id)):
    title, messages, meta = _export_messages(req, user_id)
    try:
        pdf_bytes = report_compiler.compile_pdf(title=title, messages=messages, metadata=meta)
    except Exception as e:
        logger.error(f"PDF compilation error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="PDF export failed. WeasyPrint needs Cairo and Pango installed (brew install pango).")
    return StreamingResponse(io.BytesIO(pdf_bytes), media_type="application/pdf", headers=_attachment(title, "pdf"))


@app.post("/api/export/docx")
def export_docx(req: ExportRequest, user_id: str = Depends(current_user_id)):
    title, messages, meta = _export_messages(req, user_id)
    try:
        docx_bytes = report_compiler.compile_docx(title=title, messages=messages, metadata=meta)
    except Exception as e:
        logger.error(f"DOCX compilation error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Word export failed")
    return StreamingResponse(
        io.BytesIO(docx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers=_attachment(title, "docx"),
    )


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Library views: every table, every extracted record and every dated statement in the library
# ---------------------------------------------------------------------------
def _my_documents(user_id: str) -> List[Dict[str, Any]]:
    return [dict(d) for d in db.get_all_documents(owner_id=library_owner(user_id))]


@app.get("/api/tables")
def library_tables(user_id: str = Depends(current_user_id)):
    """Every table found in the user's documents, with its document, page, columns and size."""
    docs = {d["id"]: d for d in _my_documents(user_id)}
    if not docs:
        return {"tables": []}
    entries = get_pipeline().table_store.tables_for(list(docs))
    return {"tables": [{
        "doc_id": t["doc_id"], "document": docs[t["doc_id"]].get("filename") or t["doc_id"], "table": t["table"],
        "table_id": t["table_id"], "title": t["title"], "page": t["page"], "n_rows": t["n_rows"],
        "columns": [c["name"] for c in t["columns"]],
    } for t in entries if t["doc_id"] in docs]}


@app.get("/api/records")
def library_records(user_id: str = Depends(current_user_id)):
    """The type detected for each document and the fields extracted from it, with the consistency checks."""
    out = []
    for d in _my_documents(user_id):
        meta = _doc_meta(d["id"])
        try:
            rec = json.loads((DATA_DIR / "records" / f"{d['id']}.json").read_text())
        except (OSError, ValueError):
            rec = None
        out.append({
            "doc_id": d["id"], "document": d.get("filename") or d["id"],
            "doc_type": meta.get("doc_type") or "other", "label": meta.get("doc_type_label") or "Document",
            "fields": [{k: f.get(k) for k in ("name", "label", "type", "value", "status", "page", "chunk_id", "quote")}
                       for f in (rec or {}).get("fields") or []],
            "checks": (rec or {}).get("validation") or [],
            "extracted": rec is not None,
        })
    return {"records": out}


# Two periods side by side ("FY2024 FY2023", "31 Mar 2024 31 Mar 2023") are the column headers of a table.
_PERIOD_COLUMNS = re.compile(r"(?:FY\s?\d{2,4}|(?:19|20)\d\d)\s+(?:\d{1,2}\s+[A-Za-z]{3,9}\.?\s+)?(?:FY\s?\d{2,4}|(?:19|20)\d\d)\b")
_FIGURE_PREFIX = re.compile(r"^Description of the pictures and charts on page \d+:\s*")


def _reads_as_a_statement(text: str, written: str = "") -> bool:
    """
    A sentence, not table cells read as text ("Balance sheet INR crore 31 Mar 2024 31 Mar 2023 412"):
    no columns of periods, and apart from its own date at most a quarter of its words carry figures.
    """
    if len(text.split()) < 5 or _PERIOD_COLUMNS.search(text):
        return False
    rest = text.replace(written, " ", 1).split() if written else text.split()
    return not rest or sum(1 for t in rest if any(ch.isdigit() for ch in t)) / len(rest) <= 0.25


@app.get("/api/timeline")
def library_timeline(doc_ids: Optional[str] = None, limit: int = 400, user_id: str = Depends(current_user_id)):
    """
    Dated statements across the library, oldest first: every sentence that mentions a date (found
    by the same rules the temporal-reasoning agent uses), with its document and page. No model call.
    """
    from agents.temporal_reasoning_agent import TemporalReasoningAgent
    docs = {d["id"]: d for d in _my_documents(user_id)}
    wanted = [i for i in (doc_ids or "").split(",") if i in docs] or list(docs)
    store = get_pipeline().lance_store
    # A scanned page's description (read by the vision model) keeps its text, without the label.
    chunks = [{"chunk_id": c.chunk_id, "doc_id": c.doc_id, "text": _FIGURE_PREFIX.sub("", c.text), "page_number": c.page_number}
              for d in wanted for c in store.get_document_chunks(d)]
    entries, _ = TemporalReasoningAgent._date_passages(chunks, None, None)
    seen, events = set(), []
    for e in sorted(entries, key=lambda e: e["date"]):
        if not _reads_as_a_statement(e["text"], e.get("written", "")):
            continue
        sig = (e["date"], e["text"][:80])
        if sig in seen:
            continue
        seen.add(sig)
        events.append({**e, "document": docs.get(e["doc_id"], {}).get("filename") or e["doc_id"]})
    limit = min(max(1, limit), 2000)
    return {"events": events[:limit], "total": len(events)}


# ---------------------------------------------------------------------------
# Personal API tokens (for the MCP server and scripts on a hosted server)
# ---------------------------------------------------------------------------
class TokenRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=40)


@app.post("/api/account/tokens")
def create_token(req: TokenRequest, user_id: str = Depends(account_user)):
    """A token that signs in as this account for a year; shown once, listed and revoked with the devices."""
    name = re.sub(r"\s+", " ", req.name).strip()
    token = db.create_session(user_id, ttl_days=365, device=f"API token: {name}")
    db.add_notice(user_id, "security", "A new API token was created", f"“{name}” can use your library for a year, until you revoke it under Devices.")
    return {"token": token, "name": name, "expires_in_days": 365}


# ---------------------------------------------------------------------------
# Administration
# ---------------------------------------------------------------------------
ADMIN_CODE_FILE = DATA_DIR / "admin_setup_code"


def admin_setup_code() -> str:
    """The code that makes a signed-in account an administrator: OMNIDOC_ADMIN_CODE, or one kept in the data folder."""
    configured = os.environ.get("OMNIDOC_ADMIN_CODE", "").strip()
    if configured:
        return configured
    try:
        return ADMIN_CODE_FILE.read_text().strip()
    except OSError:
        code = "-".join(secrets.token_hex(3) for _ in range(3))
        ADMIN_CODE_FILE.write_text(code)
        try:
            os.chmod(ADMIN_CODE_FILE, 0o600)
        except OSError:
            pass
        return code


def announce_setup_code() -> None:
    """At start-up, while nobody has claimed the role, print the code to the server log (the operator's eyes only)."""
    if accounts_on() and not db.list_admins():
        logger.warning("No administrator has claimed this server yet. Sign in, open Settings, choose "
                       f"'Administer this server', and enter: {admin_setup_code()}")


class AdminClaimRequest(BaseModel):
    code: str = Field(..., min_length=4, max_length=80)


@app.post("/api/admin/claim")
def claim_admin(req: AdminClaimRequest, request: Request, user_id: str = Depends(account_user)):
    _limit(request, "admin-claim", 5, 600)
    if not hmac.compare_digest(req.code.strip().lower().encode(), admin_setup_code().lower().encode()):
        raise HTTPException(status_code=403, detail="That code is not right. It is in the server's log, printed when it starts.")
    db.set_admin(user_id, True)
    db.add_notice(user_id, "security", "You are now an administrator of this server", "Claimed with the setup code.")
    return {"admin": True}


def _memory_limit_mb() -> Optional[int]:
    """The container's memory limit (cgroup v2 or v1), when the server runs in one."""
    for path in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            raw = Path(path).read_text().strip()
        except OSError:
            continue
        if raw.isdigit() and int(raw) < 1 << 50:
            return int(raw) // (1024 * 1024)
    return None


@app.get("/api/admin/overview")
def admin_overview(user_id: str = Depends(current_user_id)):
    require_admin(user_id)
    health = health_check()
    return {
        "health": {**health, "memory_limit_mb": _memory_limit_mb()},
        "stats": db.admin_stats(),
        "admins": db.list_admins(),
        "admin_emails": sorted(accounts._env_list("OMNIDOC_ADMIN_EMAILS")),
        "settings": {
            "accounts": accounts_on(), "demo": accounts.demo_enabled(), "trial_answers": accounts.trial_answers(),
            "default_model": current_model(), "version": VERSION,
        },
    }


class FeedbackRequest(BaseModel):
    message: str = Field(..., min_length=3, max_length=2000)
    rating: Optional[int] = Field(None, ge=1, le=5)
    contact: Optional[str] = Field(None, max_length=120)
    pow: Optional[Dict[str, Any]] = None


@app.post("/api/feedback")
def send_feedback(req: FeedbackRequest, request: Request):
    """Feedback from the product page, read by the administrator. No address or account is kept with it."""
    _limit(request, "feedback", 5, 3600)
    if accounts_on():
        _require_proof(req.pow)
    feedback_id = db.add_feedback(req.message.strip(), req.rating, (req.contact or "").strip() or None)
    return {"status": "success", "id": feedback_id}


@app.get("/api/admin/feedback")
def list_feedback(user_id: str = Depends(current_user_id)):
    require_admin(user_id)
    return {"feedback": db.list_feedback()}


@app.delete("/api/admin/feedback/{feedback_id}")
def delete_feedback(feedback_id: int, user_id: str = Depends(current_user_id)):
    require_admin(user_id)
    if not db.delete_feedback(feedback_id):
        raise HTTPException(status_code=404, detail="Not found")
    return {"status": "success"}


class AnnounceRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    body: str = Field("", max_length=2000)
    url: Optional[str] = Field(None, max_length=500)


@app.post("/api/admin/announce")
def announce(req: AnnounceRequest, user_id: str = Depends(current_user_id)):
    """A notice every account sees under Notifications (What's new, planned maintenance)."""
    require_admin(user_id)
    if req.url and not re.match(r"^https?://", req.url):
        raise HTTPException(status_code=400, detail="The link must start with http:// or https://")
    notice_id = db.add_notice(None, "announcement", req.title.strip(), req.body.strip(), req.url)
    return {"id": notice_id}


# The built web app (frontend/dist), served from the same address as the API
# ---------------------------------------------------------------------------
STATIC_DIR = Path(os.environ.get("OMNIDOC_STATIC_DIR") or Path(__file__).resolve().parent / "frontend" / "dist")
if (STATIC_DIR / "index.html").is_file():
    @app.get("/{path:path}", include_in_schema=False)
    def web_app(path: str):
        if path.startswith("api/") or path == "api":
            raise HTTPException(status_code=404, detail="Not found")
        target = (STATIC_DIR / path).resolve()
        if path and target.is_file() and STATIC_DIR.resolve() in target.parents:
            cache = "public, max-age=31536000, immutable" if path.startswith("assets/") else "no-cache"
            return FileResponse(target, headers={"Cache-Control": cache})
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})


if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("OMNIDOC_HOST", "127.0.0.1")
    port = int(os.environ.get("OMNIDOC_PORT", "8000"))
    logger.info(f"Starting OmniDoc API on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)
