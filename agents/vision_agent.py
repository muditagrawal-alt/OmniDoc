"""
Vision agent: reads the figures of the documents in scope with a vision-language model: a
hosted one when configured (OMNIDOC_VISION_MODEL="gemini:gemini-3.5-flash-lite", or the vision
model of the first configured provider that has one), else a local Ollama model, in which
case nothing leaves the machine.

Figures are saved at ingestion as ``<images_dir>/<doc_id>/p<page>_img<k>.png`` (embedded
images) and ``p<page>_page.png`` (whole pages dominated by vector charts or diagrams). The
agent prefers figures on the pages the retriever already found relevant, so the analysis can
be cited next to the passages it explains.
"""
import os
import re
import time
import logging
import threading
from typing import Any, Dict, List, Optional, Set, Tuple

from core.state import AgentWorkflowState
from agents.llm_utils import get_client, trace, vision_chat
from agents import llm_providers

logger = logging.getLogger("OmniDoc.VisionAgent")

# Vision-capable models tried in order after OMNIDOC_VISION_MODEL.
FALLBACK_VISION_MODELS = ("qwen3.5:9b", "gemma4:12b", "qwen2.5vl:7b", "llama3.2-vision:11b")
MAX_FIGURES = int(os.getenv("OMNIDOC_VISION_MAX_FIGURES", "2"))

_FIGURE_RE = re.compile(r"^p(\d+)_(?:img(\d+)|page)\.(?:png|jpe?g)$", re.IGNORECASE)
_DOC_ID_RE = re.compile(r"^[A-Za-z0-9_\-.]+$")

PROMPT = """You are reading a figure from a document to help answer a question.

Question: {query}
Figure location: page {page} of document {doc_id}

Describe what the figure shows that is relevant to the question: its type (chart, table,
diagram, photo...), axis titles, legend entries, labels and every number you can read.
Transcribe numbers and labels exactly as printed; do not estimate values you cannot read.
If the figure is unrelated to the question, say so in one sentence.
Answer in plain prose, at most 150 words."""


def _field(obj: Any, key: str) -> Any:
    return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)


def _page_scores(chunks: List[Any]) -> Dict[Tuple[str, int], float]:
    """Best retrieval score per (doc_id, page) among the retrieved passages."""
    scores: Dict[Tuple[str, int], float] = {}
    for ch in chunks or []:
        if not isinstance(ch, dict):
            continue
        try:
            key = (str(ch.get("doc_id") or ""), int(ch.get("page_number") or 0))
            score = float(ch.get("score") or 0.0)
        except (TypeError, ValueError):
            continue
        scores[key] = max(scores.get(key, 0.0), score)
    return scores


class VisionAgent:
    """Analyses document figures with a local Ollama vision model."""

    def __init__(self, images_dir: str = "extracted_images", vision_model: Optional[str] = None,
                 max_figures: int = MAX_FIGURES):
        self.images_dir = images_dir
        # Deliberately not called `model_name`: switching the text model must not
        # replace the vision model with one that cannot read images.
        self.vision_model = vision_model or os.getenv("OMNIDOC_VISION_MODEL", "")
        self.max_figures = max_figures
        self._resolved: Optional[str] = None
        self._resolve_lock = threading.Lock()

    def run(self, state: AgentWorkflowState) -> Dict[str, Any]:
        started = time.perf_counter()
        figures = self._candidate_figures(state)
        if not figures:
            return {"visual_context": [],
                    "agent_traces": [trace("vision_agent", "skipped", "No figures in the selected documents.", started)]}

        model = self._resolve_model()
        if not model:
            return {"visual_context": [],
                    "agent_traces": [trace("vision_agent", "skipped", "No local vision model is installed.", started)]}

        query = state.get("user_query", "")
        findings: List[Dict[str, Any]] = []
        for fig in figures[: self.max_figures]:
            analysis = self._analyze(model, fig, query)
            if analysis:
                findings.append({**fig, "analysis": analysis, "model": model})
        detail = f"{len(findings)} of {min(len(figures), self.max_figures)} figures read with {model}"
        return {"visual_context": findings, "agent_traces": [trace("vision_agent", "completed", detail, started)]}

    def _scope_doc_ids(self, state: AgentWorkflowState) -> List[str]:
        doc_ids = [str(d) for d in (state.get("document_ids") or []) if _DOC_ID_RE.match(str(d))]
        if doc_ids:
            return doc_ids
        return [d for d in os.listdir(self.images_dir)
                if _DOC_ID_RE.match(d) and os.path.isdir(os.path.join(self.images_dir, d))]

    def _candidate_figures(self, state: AgentWorkflowState) -> List[Dict[str, Any]]:
        """Figures of in-scope documents, best-matching pages first, then in page order."""
        if not os.path.isdir(self.images_dir):
            return []
        page_score = _page_scores(state.get("chunk_context") or [])
        ranked: List[Tuple[Tuple[float, int, int], Dict[str, Any]]] = []
        for doc_id in self._scope_doc_ids(state):
            folder = os.path.join(self.images_dir, doc_id)
            if not os.path.isdir(folder):
                continue
            for name in os.listdir(folder):
                m = _FIGURE_RE.match(name)
                if not m:
                    continue
                page = int(m.group(1))
                # A whole-page render (k = -1) shows a chart with its labels; prefer it.
                k = int(m.group(2)) if m.group(2) is not None else -1
                ranked.append(((-page_score.get((doc_id, page), -1.0), page, k), {
                    "figure_id": f"{doc_id}_p{page}_" + (f"img{k}" if k >= 0 else "page"),
                    "doc_id": doc_id,
                    "page": page,
                    "caption": f"Figure on page {page}" if k >= 0 else f"Page {page} (charts or diagrams)",
                    "image_path": os.path.join(folder, name),
                }))
        ranked.sort(key=lambda t: t[0])
        return [fig for _, fig in ranked]

    def _installed_models(self) -> Set[str]:
        try:
            listed = get_client().list()
        except Exception as e:
            logger.warning(f"Could not list Ollama models: {e}")
            return set()
        return {_field(m, "model") or _field(m, "name") for m in (_field(listed, "models") or [])}

    @staticmethod
    def _hosted_model() -> Optional[str]:
        """A hosted vision model: the configured spec if it names a provider, else the first provider with one."""
        configured = os.getenv("OMNIDOC_VISION_MODEL", "").strip()
        kind, name = llm_providers.parse_spec(configured) if configured else ("", "")
        if kind and kind != "ollama":
            p = llm_providers.REGISTRY.get(kind)
            return f"{kind}:{name or p.vision_model}" if p and p.configured else None
        for p in llm_providers.chat_providers():
            if p.vision_model:
                return f"{p.name}:{p.vision_model}"
        return None

    def _resolve_model(self) -> Optional[str]:
        """A hosted vision model, else the first installed local model that reports the vision capability."""
        hosted = self._hosted_model()
        if hosted:
            return hosted
        with self._resolve_lock:
            if self._resolved is None:
                self._resolved = ""
                installed = self._installed_models()
                preferred = [self.vision_model] if self.vision_model else []
                for name in preferred + [m for m in FALLBACK_VISION_MODELS if m not in preferred]:
                    if name in installed and self._supports_vision(name):
                        self._resolved = name
                        break
                if not self._resolved:
                    logger.warning("No local vision model is installed; figure analysis is disabled.")
            return self._resolved or None

    @staticmethod
    def _supports_vision(name: str) -> bool:
        try:
            caps = _field(get_client().show(name), "capabilities")
        except Exception:
            return False
        # Older Ollama servers do not report capabilities; trust the curated list then.
        return caps is None or "vision" in caps

    @staticmethod
    def _analyze(model: str, fig: Dict[str, Any], query: str) -> Optional[str]:
        try:
            with open(fig["image_path"], "rb") as f:
                image = f.read()
            if llm_providers.parse_spec(model)[0] != "ollama":
                mime = "image/jpeg" if fig["image_path"].lower().endswith((".jpg", ".jpeg")) else "image/png"
                text = vision_chat(model, PROMPT.format(query=query[:500], page=fig["page"], doc_id=fig["doc_id"]), image, mime=mime)
                return text.strip() or None
            request = {
                "model": model,
                "messages": [{
                    "role": "user",
                    "content": PROMPT.format(query=query[:500], page=fig["page"], doc_id=fig["doc_id"]),
                    "images": [image],
                }],
                "options": {"temperature": 0.1, "num_predict": 400},
            }
            try:
                # Thinking-capable VLMs answer much faster with thinking off.
                resp = get_client().chat(think=False, **request)
            except TypeError:
                resp = get_client().chat(**request)
            content = _field(_field(resp, "message"), "content") or ""
            return content.strip() or None
        except Exception as e:
            logger.warning(f"Figure analysis failed for {fig.get('image_path')}: {e}")
            return None
