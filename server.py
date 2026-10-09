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
import hashlib
import logging
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
from fastapi import FastAPI, HTTPException, UploadFile, File, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse

from db_store import OmniDocDB, LOCAL_USER_ID, DATA_DIR
from export.report_compiler import ReportCompiler
from core.pipeline import AgenticGraphRAGPipeline
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
    allow_headers=["Authorization", "X-OmniDoc-Token", "Content-Type", "Accept"],
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


def current_user_id(authorization: Optional[str] = Header(None), x_omnidoc_token: Optional[str] = Header(None)) -> str:
    token = _bearer(authorization, x_omnidoc_token)
    if not token:
        return LOCAL_USER_ID
    user_id = db.get_session_user_id(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Session expired. Sign in again.")
    return user_id


def owned_chat(chat_id: str, user_id: str) -> Dict[str, Any]:
    chat = db.get_chat(chat_id, user_id=user_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return chat


@app.post("/api/auth/login")
def login(req: LoginRequest):
    """Creates or reuses a local profile and returns a new session token."""
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
    return {"status": "success", "token": token, "user": user}


@app.get("/api/auth/me")
def get_current_user(authorization: Optional[str] = Header(None), x_omnidoc_token: Optional[str] = Header(None)):
    token = _bearer(authorization, x_omnidoc_token)
    if not token:
        raise HTTPException(status_code=401, detail="Not signed in")
    user_id = db.get_session_user_id(token)
    if user_id:
        user = db.get_user(user_id)
        if user:
            return {"user": user}
    raise HTTPException(status_code=401, detail="Session expired. Sign in again.")


@app.post("/api/auth/logout")
def logout(authorization: Optional[str] = Header(None), x_omnidoc_token: Optional[str] = Header(None)):
    token = _bearer(authorization, x_omnidoc_token)
    if token:
        db.delete_session(token)
    return {"status": "success"}


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------
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
        "timestamp": time.time(),
    }


@app.get("/api/models")
def list_models():
    models = available_models()
    if not models:
        raise HTTPException(status_code=503, detail="No model is available: add a free API key to .env (see .env.example) or start Ollama.")
    return {"models": models, "current": current_model()}


@app.put("/api/models/current")
def set_model(req: ModelRequest):
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


def _query_inputs(chat: Dict[str, Any], req: QueryRequest):
    history = [{"role": m["role"], "content": m["content"]} for m in db.get_messages(chat["id"])]
    doc_ids = [d for d in (req.document_ids or []) if DOC_ID_RE.match(d)]
    if not doc_ids and chat.get("document_id"):
        doc_ids = [chat["document_id"]]
    query_text = req.query.strip()
    if req.language and req.language in LANGUAGE_NAMES:
        query_text += (
            f"\n\n[Instruction: write the complete final answer in {LANGUAGE_NAMES[req.language]}, "
            "keeping numbers, formulas and names exact.]"
        )
    return history, doc_ids, query_text


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
def execute_chat_query(chat_id: str, req: QueryRequest, user_id: str = Depends(current_user_id)):
    """Runs the agent pipeline and returns the complete answer."""
    chat = owned_chat(chat_id, user_id)
    history, doc_ids, query_text = _query_inputs(chat, req)
    started = time.perf_counter()
    steps: List[Dict[str, Any]] = []
    state: Dict[str, Any] = {}
    try:
        for kind, data in get_pipeline().query_stream(
            user_query=query_text, document_ids=doc_ids, session_id=chat_id, conversation_history=history,
            web_mode=req.web or "auto",
        ):
            if kind == "step":
                steps.append(data)
            elif kind == "result":
                state = data
    except Exception as e:
        logger.error(f"Pipeline failed for chat {chat_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="The agent pipeline failed. Check that Ollama is running and try again.")
    payload = build_answer(state, steps, doc_ids, int((time.perf_counter() - started) * 1000))
    msg_id = _persist_turn(chat, req.query.strip(), payload, first_turn=not history)
    return {"status": "success", "message_id": msg_id, **payload}


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str, ensure_ascii=False)}\n\n"


@app.post("/api/chats/{chat_id}/query/stream")
def stream_chat_query(chat_id: str, req: QueryRequest, user_id: str = Depends(current_user_id)):
    """Runs the agent pipeline, streaming one `step` event per agent and a final `result`."""
    chat = owned_chat(chat_id, user_id)
    history, doc_ids, query_text = _query_inputs(chat, req)

    def events() -> Iterator[str]:
        started = time.perf_counter()
        steps: List[Dict[str, Any]] = []
        state: Dict[str, Any] = {}
        try:
            for kind, data in get_pipeline().query_stream(
                user_query=query_text, document_ids=doc_ids, session_id=chat_id, conversation_history=history,
                web_mode=req.web or "auto",
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
            payload = build_answer(state, steps, doc_ids, int((time.perf_counter() - started) * 1000))
            msg_id = _persist_turn(chat, req.query.strip(), payload, first_turn=not history)
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
def standalone_query(req: QueryRequest):
    """One-off agentic query without a stored conversation (used by scripts and evals)."""
    started = time.perf_counter()
    doc_ids = [d for d in (req.document_ids or []) if DOC_ID_RE.match(d)]
    steps: List[Dict[str, Any]] = []
    state: Dict[str, Any] = {}
    for kind, data in get_pipeline().query_stream(
        user_query=req.query, document_ids=doc_ids,
        session_id=req.session_id or f"session_{uuid.uuid4().hex[:8]}",
        web_mode=req.web or "auto",
    ):
        if kind == "step":
            steps.append(data)
        elif kind == "result":
            state = data
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
def list_documents():
    # Extraction progress lives in memory; after a restart fall back to what the graph holds.
    counts = _pipeline.graph_store.entity_counts_by_document() if _pipeline is not None else {}
    docs = []
    for d in db.get_all_documents():
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


def _ingest_bytes(contents: bytes, original_name: str, ext: str) -> Dict[str, Any]:
    """Stores and indexes a document's bytes (shared by uploads and URL imports)."""
    if not contents:
        raise HTTPException(status_code=400, detail="The file is empty")
    file_hash = hashlib.sha256(contents).hexdigest()
    existing = db.get_document_by_hash(file_hash)
    if existing:
        return {"status": "success", "doc_id": existing["id"], "filename": existing["filename"],
                "chunk_count": existing.get("chunk_count") or 0, "duplicate": True}

    doc_id = f"doc_{file_hash[:12]}"
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
                    size_bytes=len(contents), file_type=ext, chunk_count=chunk_count)
    get_pipeline().refresh_records()
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
def upload_document(file: UploadFile = File(...)):
    """Stores and indexes a document. Summaries, field extraction and the knowledge graph continue in the background."""
    original_name = Path(file.filename or "document").name or "document"
    ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail=f"Unsupported file type. Upload {', '.join(sorted(ALLOWED_EXTENSIONS))}.")
    contents = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"File is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    return _ingest_bytes(contents, original_name, ext)


class ImportUrlRequest(BaseModel):
    url: str = Field(..., min_length=8, max_length=2000)


@app.post("/api/documents/import-url")
def import_url(req: ImportUrlRequest):
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
        return {**_ingest_bytes(body, name, "pdf"), "url": final_url}
    if ctype.startswith("text/plain"):
        return {**_ingest_bytes(body, (path_name or "page") + ".txt", "txt"), "url": final_url}
    title = readable(body.decode("utf-8", errors="replace"), final_url).get("title") or final_url
    safe_title = re.sub(r"[\\/:*?\"<>|]+", " ", title).strip()[:90] or "Web page"
    return {**_ingest_bytes(body, f"{safe_title}.html", "html"), "url": final_url}


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: str):
    """Removes a document from SQLite, LanceDB, the knowledge graph and disk."""
    if not DOC_ID_RE.match(doc_id):
        raise HTTPException(status_code=400, detail="Invalid document id")
    doc = db.get_document(doc_id)
    try:
        get_pipeline().delete_document(doc_id)
        db.delete_document(doc_id)
        get_pipeline().refresh_records()
        if doc:
            for path in UPLOAD_DIR.glob(f"{doc_id}*"):
                path.unlink(missing_ok=True)
    except Exception as e:
        logger.error(f"Failed to delete document {doc_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not delete the document")
    return {"status": "success", "deleted_doc_id": doc_id}


class SummariesRequest(BaseModel):
    document_ids: Optional[List[str]] = Field(None, max_length=500)


@app.post("/api/documents/summaries")
def summarize_documents(req: Optional[SummariesRequest] = None):
    """Writes summaries, in the background, for documents (all by default) that have none yet."""
    doc_ids = [d for d in (req.document_ids or []) if DOC_ID_RE.match(d)] if req and req.document_ids else None
    queued = get_pipeline().summarize_missing(doc_ids)
    return {"status": "success", "queued": queued}


# ---------------------------------------------------------------------------
# Document viewer: the original file, page images, citation highlights, text, summary
# ---------------------------------------------------------------------------
_render_lock = threading.Lock()


def _stored_document(doc_id: str):
    """The library record and the stored upload of a document (404 when either is missing)."""
    if not DOC_ID_RE.match(doc_id):
        raise HTTPException(status_code=400, detail="Invalid document id")
    doc = db.get_document(doc_id)
    if not doc:
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
def document_file(doc_id: str):
    """The original uploaded file, shown inline by the browser where it can."""
    doc, path = _stored_document(doc_id)
    name = doc.get("filename") or path.name
    disposition = _attachment(name.rsplit(".", 1)[0], _file_type(path))["Content-Disposition"].replace("attachment", "inline", 1)
    return FileResponse(path, media_type=MEDIA_TYPES.get(_file_type(path), "application/octet-stream"),
                        headers={"Content-Disposition": disposition})


@app.get("/api/documents/{doc_id}/info")
def document_info(doc_id: str):
    """What the viewer needs: page sizes (with OCR language per page), tables and summary state."""
    doc, path = _stored_document(doc_id)
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
def document_page(doc_id: str, page_no: int, width: int = 1000):
    """One page as a PNG at the nearest standard width (cached on disk; ids are content hashes)."""
    _, path = _stored_document(doc_id)
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
def locate_citation(doc_id: str, req: LocateRequest):
    """
    Where a cited passage, and the sentence of it that supports the claim, sits in the
    document: normalised rectangles on a page for PDFs and images, or the chunk and quote to
    mark in the text of other documents.
    """
    from parsing.locate import locate, best_sentence
    _, path = _stored_document(doc_id)
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
def document_text(doc_id: str):
    """The document's text in reading order, as its indexed passages (overlaps removed)."""
    doc, _ = _stored_document(doc_id)
    chunks = get_pipeline().lance_store.get_document_chunks(doc_id)
    out, previous = [], ""
    for c in chunks:
        out.append({"chunk_id": c.chunk_id, "page": c.page_number, "section": c.section_title,
                    "text": _strip_overlap(previous, c.text) if previous else c.text})
        previous = c.text
    return {"doc_id": doc_id, "title": doc.get("filename") or doc_id, "chunks": out}


@app.get("/api/documents/{doc_id}/tables/{table}")
def document_table(doc_id: str, table: str, limit: int = 200):
    """Rows of one extracted table (for the viewer of spreadsheets and table citations)."""
    _stored_document(doc_id)
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
def document_summary(doc_id: str):
    _stored_document(doc_id)
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
def document_record(doc_id: str):
    """The document's detected type and the fields extracted from it, with consistency checks."""
    _stored_document(doc_id)
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
def extract_record(doc_id: str, req: RecordRequest):
    """(Re-)extracts the fields of the document's type; ``doc_type`` corrects a wrong detection."""
    from agents.extraction_agent import TYPE_PRESETS
    from agents.doc_classifier import LABELS
    doc, _ = _stored_document(doc_id)
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
def sensitive_data(doc_id: str):
    """Personal and financial identifiers found in the document (values masked), with where they are."""
    _, path = _stored_document(doc_id)
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
def redact_document(doc_id: str, req: RedactRequest):
    """A copy with the sensitive values removed: real PDF redactions for PDFs and scans, blacked-out text otherwise."""
    from parsing import pii
    doc, path = _stored_document(doc_id)
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
def compare_documents(req: CompareRequest):
    """Sentence-level comparison of two documents (modified, added, removed, changed figures); optional summary."""
    from agents.compare_agent import compare, summarize
    doc_a, _ = _stored_document(req.a)
    doc_b, _ = _stored_document(req.b)
    store = get_pipeline().lance_store
    result = compare(store.get_document_chunks(req.a), store.get_document_chunks(req.b))
    result["a"] = {"id": req.a, "title": doc_a.get("filename") or req.a}
    result["b"] = {"id": req.b, "title": doc_b.get("filename") or req.b}
    if req.summarize and result["changes"]:
        try:
            result["summary"] = summarize(current_model(), result["a"]["title"], result["b"]["title"], result["changes"])
        except Exception as e:
            logger.warning(f"Change summary failed: {e}")
            result["summary_error"] = "The summary could not be written (no model answered)."
    return result


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    document_ids: Optional[List[str]] = None
    top_k: int = Field(8, ge=1, le=30)


@app.post("/api/search")
def search_documents(req: SearchRequest):
    """Hybrid search (vectors + BM25, reranked) without a model call: the passages, with their document and page."""
    doc_ids = [d for d in (req.document_ids or []) if DOC_ID_RE.match(d)] or None
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
def extract_stream(req: ExtractRequest):
    """
    Fills the fields from each document, streaming `start`, then per document `doc_start`,
    `progress` and `doc_result` (or `doc_error`), and finally `done` with CSV rows.
    """
    from agents.extraction_agent import PRESETS, normalise_fields, results_to_csv_rows
    fields = normalise_fields(req.fields or (PRESETS.get(req.preset or "") or {}).get("fields") or [])
    if not fields:
        raise HTTPException(status_code=400, detail="Add at least one field to extract")
    titles = _doc_titles()
    doc_ids = [d for d in dict.fromkeys(req.document_ids) if DOC_ID_RE.match(d) and d in titles]
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
            threading.Thread(target=run_one, args=(doc_id, updates), name=f"extract-{doc_id}", daemon=True).start()
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
def get_knowledge_graph(limit: int = 2000):
    data = get_pipeline().graph_store.get_all_graph(limit=limit)
    # Graphs built by older versions stored the internal file name as the title.
    titles = _doc_titles()
    for d in data.get("documents", []):
        d["title"] = titles.get(d["id"]) or d.get("title") or d["id"]
    return {"status": "success", **data}


@app.get("/api/graph/node/{node_id}")
def get_node_details(node_id: str):
    found = get_pipeline().graph_store.get_node(node_id)
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
