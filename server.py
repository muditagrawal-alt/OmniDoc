"""
OmniDoc FastAPI backend.

Serves the React frontend's API:
1. Local profiles with opaque session tokens
2. Conversation sessions and message history (SQLite)
3. The multi-agent Graph RAG pipeline (LangGraph + LanceDB + Kùzu + Ollama),
   with Server-Sent Events streaming of per-agent progress
4. Document ingestion (Docling) with background knowledge-graph extraction
5. Knowledge-graph export for the 3D globe
6. PDF (WeasyPrint) and DOCX (python-docx) report export
"""
import os
import re
import io
import sys
import json
import time
import uuid
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
from fastapi.responses import StreamingResponse

from db_store import OmniDocDB, LOCAL_USER_ID, DATA_DIR
from export.report_compiler import ReportCompiler
from core.pipeline import AgenticGraphRAGPipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("OmniDoc.Server")

VERSION = "2.1.0"
OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
DEFAULT_MODEL = os.environ.get("OMNIDOC_MODEL", "qwen2.5:7b-instruct")
MAX_UPLOAD_BYTES = int(os.environ.get("OMNIDOC_MAX_UPLOAD_MB", "100")) * 1024 * 1024
ALLOWED_EXTENSIONS = {"pdf", "docx", "txt", "md"}
UPLOAD_DIR = DATA_DIR / "uploads"
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
    allow_headers=["Authorization", "Content-Type", "Accept"],
)

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
                _pipeline = AgenticGraphRAGPipeline(data_dir=str(DATA_DIR), model_name=model)
    return _pipeline


def current_model() -> str:
    if _pipeline is not None:
        return _pipeline.model_name
    return _load_settings().get("model") or DEFAULT_MODEL


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
def _bearer(authorization: Optional[str]) -> Optional[str]:
    if authorization and authorization.startswith("Bearer "):
        token = authorization[len("Bearer "):].strip()
        return token or None
    return None


def current_user_id(authorization: Optional[str] = Header(None)) -> str:
    token = _bearer(authorization)
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
def get_current_user(authorization: Optional[str] = Header(None)):
    token = _bearer(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Not signed in")
    user_id = db.get_session_user_id(token)
    if user_id:
        user = db.get_user(user_id)
        if user:
            return {"user": user}
    raise HTTPException(status_code=401, detail="Session expired. Sign in again.")


@app.post("/api/auth/logout")
def logout(authorization: Optional[str] = Header(None)):
    token = _bearer(authorization)
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
        "stores": stores,
        "timestamp": time.time(),
    }


@app.get("/api/models")
def list_models():
    models = ollama_models()
    if models is None:
        raise HTTPException(status_code=503, detail="Ollama is not reachable at " + OLLAMA_URL)
    return {"models": models, "current": current_model()}


@app.put("/api/models/current")
def set_model(req: ModelRequest):
    models = ollama_models()
    if models is None:
        raise HTTPException(status_code=503, detail="Ollama is not reachable")
    if req.model not in {m["name"] for m in models}:
        raise HTTPException(status_code=404, detail=f"Model {req.model} is not installed in Ollama")
    settings = _load_settings()
    settings["model"] = req.model
    _save_settings(settings)
    if _pipeline is not None:
        _pipeline.set_model(req.model)
    return {"current": req.model}


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
    if score is None or (score == 0 and supported == 0 and unsupported == 0):
        status = "unverified"
        score = None
    elif getattr(v, "is_grounded", False) and unsupported == 0:
        status = "verified"
    else:
        status = "partial"
    return {"status": status, "score": None if score is None else round(float(score), 3),
            "supported": supported, "unsupported": unsupported, "feedback": feedback}


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
        "visual_artifacts": to_jsonable(state.get("visual_artifacts") or []),
        "conflicts": to_jsonable(state.get("conflicts") or []),
        "graph": build_graph(state),
        "steps": visible_steps,
        "verification": build_verification(state),
        "model": current_model(),
        "elapsed_ms": elapsed_ms,
        "document_ids": doc_ids,
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
            user_query=query_text, document_ids=doc_ids, session_id=chat_id, conversation_history=history
        ):
            if kind == "step":
                steps.append(data)
            else:
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
                user_query=query_text, document_ids=doc_ids, session_id=chat_id, conversation_history=history
            ):
                if kind == "step":
                    steps.append(data)
                    if not data.get("skipped"):
                        yield _sse("step", {k: data[k] for k in ("node", "label", "detail", "duration_ms")})
                else:
                    state = data
            payload = build_answer(state, steps, doc_ids, int((time.perf_counter() - started) * 1000))
            msg_id = _persist_turn(chat, req.query.strip(), payload, first_turn=not history)
            yield _sse("result", {"status": "success", "message_id": msg_id, **payload})
        except Exception as e:
            logger.error(f"Streaming pipeline failed for chat {chat_id}: {e}", exc_info=True)
            yield _sse("error", {"message": "The agent pipeline failed. Check that Ollama is running and try again."})

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
    ):
        if kind == "step":
            steps.append(data)
        else:
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
        docs.append(d)
    return {"documents": docs}


@app.post("/api/documents/upload")
def upload_document(file: UploadFile = File(...)):
    """Stores and indexes a document. Knowledge-graph extraction continues in the background."""
    original_name = Path(file.filename or "document").name or "document"
    ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail=f"Unsupported file type. Upload {', '.join(sorted(ALLOWED_EXTENSIONS))}.")

    contents = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"File is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
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

    try:
        parsed = get_pipeline().ingest_document(
            file_path=str(saved_path), doc_id=doc_id, doc_hash=file_hash,
            fast_mode=True, background_graph=True, title=original_name,
        )
    except Exception as e:
        logger.error(f"Ingestion failed for {original_name}: {e}", exc_info=True)
        saved_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="Could not read this document. It may be scanned, encrypted or corrupted.")

    chunk_count = len(parsed.chunks)
    db.add_document(doc_id=doc_id, filename=original_name, file_hash=file_hash,
                    size_bytes=len(contents), file_type=ext, chunk_count=chunk_count)
    return {"status": "success", "doc_id": doc_id, "filename": original_name,
            "chunk_count": chunk_count, "duplicate": False,
            "visual_element_count": len(getattr(parsed, "visual_elements", []) or [])}


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: str):
    """Removes a document from SQLite, LanceDB, the knowledge graph and disk."""
    if not DOC_ID_RE.match(doc_id):
        raise HTTPException(status_code=400, detail="Invalid document id")
    doc = db.get_document(doc_id)
    try:
        get_pipeline().delete_document(doc_id)
        db.delete_document(doc_id)
        if doc:
            for path in UPLOAD_DIR.glob(f"{doc_id}*"):
                path.unlink(missing_ok=True)
    except Exception as e:
        logger.error(f"Failed to delete document {doc_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not delete the document")
    return {"status": "success", "deleted_doc_id": doc_id}


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


if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("OMNIDOC_HOST", "127.0.0.1")
    port = int(os.environ.get("OMNIDOC_PORT", "8000"))
    logger.info(f"Starting OmniDoc API on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)
