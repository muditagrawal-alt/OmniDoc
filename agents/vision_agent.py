"""
Vision agent: reads the figures of the documents in scope with a vision-language model: a
hosted one when configured (OMNIDOC_VISION_MODEL="gemini:gemini-3.5-flash-lite", or the vision
model of the first configured provider that has one), else a local Ollama model, in which
case nothing leaves the machine.

For PDFs and images the agent looks at whole pages, rendered from the stored upload when the
question is asked: the best-matching pages that carry pictures or charts, and pages the question
names, so a figure is read together with its labels, legend and caption, as a person sees it.
Pages are read in parallel. It also runs without being asked when the best passages sit on
pages that are mostly pictures or charts (slides, brochures, infographics), whose content the
text layer misses.

At ingestion it also describes the pages that are mostly pictures or charts and carry
little text (``caption_pages``); the pipeline indexes those descriptions as passages, so a
question about a map, an infographic or a photo finds its page by text search.

Other formats fall back to the figures saved at ingestion, ``<images_dir>/<doc_id>/p<page>_img<k>.png``
(embedded images) and ``p<page>_page.png`` (pages dominated by vector charts). Either way the
analysis is cited with its page, next to the passages it explains.
"""
from concurrent.futures import ThreadPoolExecutor
import os
import re
import time
import logging
import threading
from typing import Any, Dict, List, Optional, Set, Tuple

from core.state import AgentWorkflowState
from agents.llm_utils import get_client, trace, vision_chat
from agents import llm_providers
from agents.document_intelligence_agent import DocumentIntelligenceAgent

logger = logging.getLogger("OmniDoc.VisionAgent")

# Vision-capable models tried in order after OMNIDOC_VISION_MODEL.
FALLBACK_VISION_MODELS = ("qwen3.5:9b", "gemma4:12b", "qwen2.5vl:7b", "llama3.2-vision:11b")
MAX_FIGURES = int(os.getenv("OMNIDOC_VISION_MAX_FIGURES", "2"))

# Rendered page size: the longer side in pixels.
RENDER_PX = int(os.getenv("OMNIDOC_VISION_RENDER_PX", "1600"))
# A page carries a real figure when images cover this share of it (small logos and banners
# stay below), or when it has a chart drawn as vectors: curves, or many lines. Rectangles do not
# count: financial statements and other tables are drawn with hundreds of filled cells.
VISUAL_IMAGE_SHARE = 0.2
CHART_CURVES = 5
CHART_LINES = 200
# A large picture (a full-page map, photo or chart), looked for when the text search missed it.
LARGE_IMAGE_SHARE = 0.35
# Retrieved pages checked for the automatic trigger.
TRIGGER_TOP_PAGES = 2
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp")
# Pages described at ingestion, per document (one vision call each).
CAPTION_MAX_PAGES = int(os.getenv("OMNIDOC_CAPTION_MAX_PAGES", "30"))
# A page whose text layer has more characters than this is described only when a picture or chart covers most of it.
CAPTION_TEXT_CHARS = 800

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

PAGE_PROMPT = """You are looking at page {page} of a document, rendered as an image, to help answer a question.

Question: {query}

Read what on this page is relevant to the question: figures, charts, maps, diagrams, photos,
tables and their titles, axis labels, legends, captions and annotations. Transcribe numbers,
names and labels exactly as printed; count items carefully when the question asks how many;
do not estimate values you cannot read. If nothing on the page is relevant, say so in one sentence.
Answer in plain prose, at most 180 words."""


CAPTION_PROMPT = """Describe page {page} of the document "{title}" for a search index.

Transcribe every title, heading, label, number, name and short text you can read on the page.
Describe each chart (type, axes, every series with its values), table (columns and the values in
each row), map (what places or areas it marks and what the colours mean), diagram and photo (what
it shows, how many of each thing). Do not add anything that is not visible on the page.
Plain text, at most 220 words."""


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
                 max_figures: int = MAX_FIGURES, files_dir: Optional[str] = None):
        self.images_dir = images_dir
        # The uploaded files sit next to the figures folder (<data>/uploads beside <data>/figures).
        self.files_dir = files_dir or os.path.join(os.path.dirname(os.path.abspath(images_dir)), "uploads")
        # Deliberately not called `model_name`: switching the text model must not
        # replace the vision model with one that cannot read images.
        self.vision_model = vision_model or os.getenv("OMNIDOC_VISION_MODEL", "")
        self.max_figures = max_figures
        self._resolved: Optional[str] = None
        self._resolve_lock = threading.Lock()

    def run(self, state: AgentWorkflowState) -> Dict[str, Any]:
        started = time.perf_counter()
        asked = bool((state.get("needs") or {}).get("figures"))
        figures = self._page_candidates(state, strict=not asked) or (self._candidate_figures(state) if asked else [])
        if not figures:
            return {"visual_context": [],
                    "agent_traces": [trace("vision_agent", "skipped", "No figures in the selected documents.", started)]}

        model = self._resolve_model()
        if not model:
            return {"visual_context": [],
                    "agent_traces": [trace("vision_agent", "skipped", "No local vision model is installed.", started)]}

        query = state.get("user_query", "")
        chosen = figures[: self.max_figures]
        with ThreadPoolExecutor(max_workers=max(1, len(chosen))) as pool:
            analyses = list(pool.map(lambda fig: self._analyze(model, fig, query), chosen))
        findings = [{**{k: v for k, v in fig.items() if k != "render"}, "analysis": a, "model": model}
                    for fig, a in zip(chosen, analyses) if a]
        kind = "pages" if any("render" in f for f in chosen) else "figures"
        detail = f"{len(findings)} of {len(chosen)} {kind} read with {model}" + ("" if asked else " (pages mostly pictures or charts)")
        return {"visual_context": findings, "agent_traces": [trace("vision_agent", "completed", detail, started)]}

    # ------------------------------------------------------------------ pages
    def _upload(self, doc_id: str) -> Optional[str]:
        """The stored upload of a document when it is a PDF or an image."""
        if not _DOC_ID_RE.match(doc_id or "") or not os.path.isdir(self.files_dir):
            return None
        for ext in (".pdf",) + IMAGE_EXTENSIONS:
            path = os.path.join(self.files_dir, doc_id + ext)
            if os.path.isfile(path):
                return path
        return None

    @staticmethod
    def _visual(page: Any) -> Tuple[float, float, bool]:
        """
        (share of the page covered by images, strength of a vector chart on it (0 = none, up to 1),
        whether one image is the whole page).
        """
        area = float(page.rect.width * page.rect.height) or 1.0
        covered, scan = 0.0, False
        try:
            for info in page.get_image_info():
                x0, y0, x1, y1 = info["bbox"]
                a = max(0.0, x1 - x0) * max(0.0, y1 - y0)
                covered += a
                scan = scan or a >= 0.9 * area
        except Exception:
            pass
        curves = lines = 0
        try:
            for d in page.get_drawings():
                for item in d.get("items") or []:
                    curves += item[0] == "c"
                    lines += item[0] == "l"
        except Exception:
            pass
        chart = min(1.0, curves / 100 + lines / 1000) if curves >= CHART_CURVES or lines >= CHART_LINES else 0.0
        return min(1.0, covered / area), chart, scan

    def _page_candidates(self, state: AgentWorkflowState, strict: bool) -> List[Dict[str, Any]]:
        """
        Pages worth looking at, best first. ``strict`` (the question did not ask about a figure)
        keeps only pages the question names and top retrieved pages that carry a real figure,
        never a whole-page scan (OCR read its text). When the question asks about a figure:
        named pages, retrieved pages with a real figure, then the largest pictures of the
        retrieved documents (a map or chart with no words around it is rarely found by the text
        search), then retrieved pages with any picture.
        """
        page_scores = _page_scores(state.get("chunk_context") or [])
        scores = sorted(page_scores.items(), key=lambda kv: -kv[1])
        if strict:
            scores = scores[:TRIGGER_TOP_PAGES]
        docs: Dict[str, Any] = {}
        chosen: List[Tuple[str, int]] = []
        weaker: List[Tuple[str, int]] = []
        # Pages the question names ("in page 47", "slide 12") come first: one that is a picture
        # or chart, or whose text was not retrieved (often a page with no text layer at all).
        scope = [str(d) for d in (state.get("document_ids") or []) if _DOC_ID_RE.match(str(d))]
        scope = (scope or list(dict.fromkeys(d for (d, _), _ in scores)))[:2]
        named = [n for k, n in DocumentIntelligenceAgent.references(state.get("user_query", "")) if k == "page"]

        def open_pdf(doc_id: str) -> Optional[Any]:
            if doc_id not in docs:
                path = self._upload(doc_id)
                docs[doc_id] = None
                if path and path.lower().endswith(".pdf"):
                    import fitz
                    docs[doc_id] = fitz.open(path)
            return docs[doc_id]

        out: List[Dict[str, Any]] = []
        try:
            for doc_id in scope:
                doc = open_pdf(doc_id)
                for name in named:
                    page_no = len(doc) if doc is not None and name == "last" else int(name) if name.isdigit() else 0
                    if doc is None or not 1 <= page_no <= len(doc):
                        continue
                    share, chart, _ = self._visual(doc[page_no - 1])
                    if not strict or share >= VISUAL_IMAGE_SHARE or chart \
                            or (doc_id, page_no) not in page_scores:
                        chosen.append((doc_id, page_no))
            for (doc_id, page_no), _ in scores:
                path = self._upload(doc_id)
                if not path or page_no < 1:
                    continue
                if path.lower().endswith(IMAGE_EXTENSIONS):
                    if not strict and not any(f["doc_id"] == doc_id for f in out):
                        out.append({"figure_id": f"{doc_id}_image", "doc_id": doc_id, "page": 1,
                                    "caption": "The uploaded image", "image_path": path})
                    continue
                doc = open_pdf(doc_id)
                if doc is None or page_no > len(doc):
                    continue
                share, chart, scan = self._visual(doc[page_no - 1])
                real = share >= VISUAL_IMAGE_SHARE or chart > 0
                if (doc_id, page_no) in chosen:
                    continue
                if real and not (strict and scan):
                    chosen.append((doc_id, page_no))
                elif not strict and share > 0:
                    weaker.append((doc_id, page_no))
            if not strict and len(chosen) < self.max_figures:
                large: List[Tuple[float, str, int]] = []
                for doc_id in list(dict.fromkeys(d for (d, _), _ in scores))[:2]:
                    doc = open_pdf(doc_id)
                    if doc is None:
                        continue
                    for page_no in self._figure_pages(doc_id):
                        if (doc_id, page_no) in chosen or page_no > len(doc):
                            continue
                        share, chart, _ = self._visual(doc[page_no - 1])
                        if share >= LARGE_IMAGE_SHARE or chart > 0:
                            large.append((-max(share, chart), doc_id, page_no))
                chosen += [(d, p) for _, d, p in sorted(large)]
            chosen += [w for w in weaker if w not in chosen] if not strict else []
            for doc_id, page_no in chosen[: max(0, self.max_figures - len(out))]:
                out.append({"figure_id": f"{doc_id}_p{page_no}_render", "doc_id": doc_id, "page": page_no,
                            "caption": f"Page {page_no}", "render": self._upload(doc_id)})
        except Exception as e:
            logger.warning(f"Could not choose pages to look at: {e}")
        finally:
            for doc in docs.values():
                if doc is not None:
                    doc.close()
        return out

    def _figure_pages(self, doc_id: str) -> List[int]:
        """Pages with a figure saved at ingestion (embedded images, chart pages)."""
        folder = os.path.join(self.images_dir, doc_id)
        if not _DOC_ID_RE.match(doc_id or "") or not os.path.isdir(folder):
            return []
        return sorted({int(m.group(1)) for m in (_FIGURE_RE.match(n) for n in os.listdir(folder)) if m})

    def visual_pages(self, state: AgentWorkflowState) -> bool:
        """True when the question names a page, or the best passages sit on pages with real figures."""
        return bool(self._page_candidates(state, strict=True))

    # ------------------------------------------------------------------ ingestion captions
    def caption_candidates(self, path: str, max_pages: int = CAPTION_MAX_PAGES) -> List[int]:
        """
        Pages of a PDF worth describing, in page order: mostly pictures or charts and little text,
        best first when there are more than ``max_pages``. An uploaded image is its own page 1.
        """
        if path.lower().endswith(IMAGE_EXTENSIONS):
            return [1]
        if not path.lower().endswith(".pdf"):
            return []
        import fitz
        ranked: List[Tuple[float, int]] = []
        with fitz.open(path) as doc:
            for i, page in enumerate(doc, 1):
                share, chart, _ = self._visual(page)
                if share < VISUAL_IMAGE_SHARE and not chart:
                    continue
                chars = len(page.get_text().strip())
                if chars > CAPTION_TEXT_CHARS and share < LARGE_IMAGE_SHARE and not chart:
                    continue  # a text page with a small picture: its words are already searchable
                weight = share + chart + 1 - min(chars, CAPTION_TEXT_CHARS) / CAPTION_TEXT_CHARS
                ranked.append((-weight, i))
        return sorted(page for _, page in sorted(ranked)[:max_pages])

    def caption_pages(self, path: str, title: str, progress: Optional[Any] = None) -> List[Tuple[int, str]]:
        """(page, description) for the pages chosen by ``caption_candidates``; empty without a vision model."""
        pages = self.caption_candidates(path)
        model = self._resolve_model() if pages else None
        if not model:
            return []
        out: List[Tuple[int, str]] = []
        for i, page_no in enumerate(pages, 1):
            try:
                if path.lower().endswith(IMAGE_EXTENSIONS):
                    with open(path, "rb") as f:
                        image = f.read()
                    mime = "image/jpeg" if path.lower().endswith((".jpg", ".jpeg")) else "image/png"
                else:
                    image, mime = self._render(path, page_no), "image/png"
                prompt = CAPTION_PROMPT.format(page=page_no, title=title[:120])
                if llm_providers.parse_spec(model)[0] != "ollama":
                    text = vision_chat(model, prompt, image, mime=mime, num_predict=500)
                else:
                    resp = get_client().chat(model=model, messages=[{"role": "user", "content": prompt, "images": [image]}],
                                             options={"temperature": 0.1, "num_predict": 500})
                    text = _field(_field(resp, "message"), "content") or ""
                if text and text.strip():
                    out.append((page_no, " ".join(text.split())))
            except Exception as e:
                logger.warning(f"Could not describe page {page_no} of {title}: {e}")
            if progress:
                progress(i, len(pages))
        return out

    @staticmethod
    def _render(path: str, page_no: int) -> bytes:
        import fitz
        with fitz.open(path) as doc:
            page = doc[page_no - 1]
            zoom = min(3.0, RENDER_PX / max(float(page.rect.width), float(page.rect.height), 1.0))
            return page.get_pixmap(matrix=fitz.Matrix(zoom, zoom)).tobytes("png")

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

    @classmethod
    def _analyze(cls, model: str, fig: Dict[str, Any], query: str) -> Optional[str]:
        try:
            if fig.get("render"):
                image, mime = cls._render(fig["render"], fig["page"]), "image/png"
                prompt = PAGE_PROMPT.format(query=query[:500], page=fig["page"])
            else:
                with open(fig["image_path"], "rb") as f:
                    image = f.read()
                mime = "image/jpeg" if fig["image_path"].lower().endswith((".jpg", ".jpeg")) else "image/png"
                prompt = PROMPT.format(query=query[:500], page=fig["page"], doc_id=fig["doc_id"])
            if llm_providers.parse_spec(model)[0] != "ollama":
                text = vision_chat(model, prompt, image, mime=mime, num_predict=500)
                return text.strip() or None
            request = {
                "model": model,
                "messages": [{
                    "role": "user",
                    "content": prompt,
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
            logger.warning(f"Figure analysis failed for {fig.get('render') or fig.get('image_path')} (page {fig.get('page')}): {e}")
            return None
