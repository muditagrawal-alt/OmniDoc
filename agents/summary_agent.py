"""
Summaries across documents.

After upload, every document gets a map-reduce summary in the background: consecutive
chunks are grouped into sections of roughly a thousand words, each section is summarised,
and the section summaries are reduced to an overview with key points and topics. The
result is stored as JSON next to the other document data.

Questions about a whole collection ("summarise everything", "what are the main themes
across my documents?") cannot be answered from a handful of retrieved chunks, so the
corpus agent answers them from these summaries instead, each citable to its document and
section pages.
"""
import os
import re
import json
import time
import logging
import threading
from typing import Any, Dict, List, Optional, Sequence

from core.state import AgentWorkflowState
from agents.llm_utils import chat, chat_json, trace

logger = logging.getLogger("OmniDoc.SummaryAgent")

SECTION_WORDS = int(os.getenv("OMNIDOC_SUMMARY_SECTION_WORDS", "1000"))
MAX_SECTIONS = int(os.getenv("OMNIDOC_SUMMARY_MAX_SECTIONS", "12"))
MAX_SECTION_CHARS = 9000
ON_THE_FLY_LIMIT = 2

SECTION_PROMPT = """Summarise this part of the document "{title}" in 2 to 4 sentences.
Keep the exact figures, names and dates that matter most. Write plainly, without a preamble.

TEXT (pages {pages}):
{text}"""

DOCUMENT_PROMPT = """These are the section summaries of the document "{title}":

{sections}

Return JSON only:
{{"summary": "an overview of the whole document in 4 to 6 sentences",
  "key_points": ["5 to 8 short key points, each ending with the section labels it comes from, e.g. (S2) or (S1, S4)"],
  "topics": ["3 to 8 short topic phrases"]}}"""

_CORPUS_RE = re.compile(
    r"\b(summari[sz]e|summary|summaries|overview|tl;?dr|gist|in a nutshell|main (themes?|points|ideas|topics|takeaways|arguments)|"
    r"key (themes?|points|ideas|takeaways|findings|topics)|common (themes?|threads?)|what (are|is) (these|the|my|all) "
    r"(documents?|files?|papers?|reports?) about|across (all |my |the |these )?(documents|files|papers|reports|sources)|"
    r"all (of )?(my |the |these )?(documents|files|papers|reports)|whole (document|collection|library)|everything)\b",
    re.IGNORECASE,
)


def is_corpus_question(query: str, primary_intent: Optional[str] = None) -> bool:
    """True for questions about whole documents or the whole collection."""
    if _CORPUS_RE.search(query or ""):
        return True
    return primary_intent == "summarization"


class DocumentSummarizer:
    """Builds, stores and loads map-reduce summaries of documents."""

    def __init__(self, store_dir: str, model_name: str = "qwen2.5:7b-instruct"):
        self.store_dir = store_dir
        self.model_name = model_name
        os.makedirs(store_dir, exist_ok=True)
        self._locks: Dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def _path(self, doc_id: str) -> str:
        return os.path.join(self.store_dir, f"{doc_id}.json")

    def load(self, doc_id: str) -> Optional[Dict[str, Any]]:
        if not re.match(r"^[A-Za-z0-9_\-.]+$", doc_id or ""):
            return None
        try:
            with open(self._path(doc_id), "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def has(self, doc_id: str) -> bool:
        return os.path.exists(self._path(doc_id))

    def delete(self, doc_id: str) -> None:
        if re.match(r"^[A-Za-z0-9_\-.]+$", doc_id or ""):
            try:
                os.remove(self._path(doc_id))
            except OSError:
                pass

    @staticmethod
    def _group(chunks: Sequence[Any]) -> List[List[Any]]:
        total = sum(len(c.text.split()) for c in chunks)
        target = max(SECTION_WORDS, total // MAX_SECTIONS + 1)
        groups: List[List[Any]] = []
        current: List[Any] = []
        words = 0
        for c in chunks:
            n = len(c.text.split())
            section_change = current and (c.section_title or "") != (current[-1].section_title or "")
            if current and (words + n > target or (section_change and words >= target // 2)):
                groups.append(current)
                current, words = [], 0
            current.append(c)
            words += n
        if current:
            groups.append(current)
        return groups

    def summarize(self, doc_id: str, title: str, chunks: Sequence[Any],
                  progress: Optional[Any] = None) -> Optional[Dict[str, Any]]:
        """Summarises a document from its chunks and stores the result. Returns it."""
        chunks = [c for c in chunks if (c.text or "").strip()]
        if not chunks:
            return None
        with self._guard:
            lock = self._locks.setdefault(doc_id, threading.Lock())
        with lock:
            existing = self.load(doc_id)
            if existing:
                return existing
            groups = self._group(chunks)
            sections = []
            for i, group in enumerate(groups, 1):
                pages = sorted({int(c.page_number or 1) for c in group})
                page_label = f"{pages[0]}" if len(pages) == 1 else f"{pages[0]}-{pages[-1]}"
                text = "\n\n".join(c.text for c in group)[:MAX_SECTION_CHARS]
                try:
                    summary = chat(self.model_name, [{"role": "user", "content": SECTION_PROMPT.format(
                        title=title, pages=page_label, text=text)}], num_predict=260, temperature=0.1, fast=True)
                except Exception as e:
                    logger.warning(f"Section summary failed for {doc_id} S{i}: {e}")
                    summary = ""
                sections.append({
                    "i": i,
                    "title": next((c.section_title for c in group if c.section_title), "") or f"Pages {page_label}",
                    "pages": [pages[0], pages[-1]],
                    "chunk_ids": [c.chunk_id for c in group],
                    "summary": re.sub(r"\s+", " ", summary).strip(),
                })
                if progress:
                    progress(i, len(groups) + 1)
            listing = "\n".join(f"S{s['i']} (pages {s['pages'][0]}-{s['pages'][1]}): {s['summary']}"
                                for s in sections if s["summary"])
            overview: Dict[str, Any] = {}
            if listing:
                try:
                    overview = chat_json(self.model_name, DOCUMENT_PROMPT.format(title=title, sections=listing),
                                         num_predict=700)
                except Exception as e:
                    logger.warning(f"Document summary failed for {doc_id}: {e}")
            key_points = []
            for point in (overview.get("key_points") or [] if isinstance(overview, dict) else []):
                text = str(point).strip()
                refs = [int(n) for n in re.findall(r"S(\d+)", text)]
                text = re.sub(r"\s*\((?:S\d+[,;\s]*)+\)\s*$", "", text).strip()
                if text:
                    key_points.append({"text": text, "sections": [n for n in refs if 1 <= n <= len(sections)]})
            result = {
                "doc_id": doc_id,
                "title": title,
                "created": time.time(),
                "model": self.model_name,
                "summary": str((overview or {}).get("summary") or " ".join(s["summary"] for s in sections[:3])).strip(),
                "key_points": key_points,
                "topics": [str(t).strip() for t in (overview or {}).get("topics") or [] if str(t).strip()][:8],
                "sections": sections,
            }
            if progress:
                progress(len(groups) + 1, len(groups) + 1)
            tmp = self._path(doc_id) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self._path(doc_id))
            return result


class CorpusSummaryAgent:
    """Supplies document and section summaries as evidence for whole-collection questions."""

    def __init__(self, summarizer: DocumentSummarizer, lance_store: Any = None,
                 doc_titles: Optional[Any] = None):
        self.summarizer = summarizer
        self.lance_store = lance_store
        self.doc_titles = doc_titles  # callable -> {doc_id: title}

    def _all_doc_ids(self) -> List[str]:
        try:
            return list((self.doc_titles() or {}).keys()) if self.doc_titles else []
        except Exception:
            return []

    def _title(self, doc_id: str) -> str:
        try:
            return (self.doc_titles() or {}).get(doc_id, doc_id) if self.doc_titles else doc_id
        except Exception:
            return doc_id

    def run(self, state: AgentWorkflowState) -> Dict[str, Any]:
        started = time.perf_counter()
        doc_ids = [d for d in (state.get("document_ids") or []) if d] or self._all_doc_ids()
        context: List[Dict[str, Any]] = []
        missing: List[str] = []
        computed = 0
        for doc_id in doc_ids[:20]:
            summary = self.summarizer.load(doc_id)
            if summary is None and computed < ON_THE_FLY_LIMIT and self.lance_store is not None:
                chunks = self.lance_store.get_document_chunks(doc_id)
                if chunks:
                    summary = self.summarizer.summarize(doc_id, self._title(doc_id), chunks)
                    computed += 1
            if summary is None:
                missing.append(doc_id)
                continue
            points = "\n".join(f"- {p['text']}" for p in summary.get("key_points", []))
            context.append({
                "kind": "document",
                "doc_id": doc_id,
                "title": f"Summary of {summary.get('title') or self._title(doc_id)}",
                "page": 1,
                "text": (summary.get("summary") or "") + ("\nKey points:\n" + points if points else ""),
            })
            # One document in scope: add its section summaries so the answer can be detailed.
            if len(doc_ids) == 1:
                for s in summary.get("sections", [])[:MAX_SECTIONS]:
                    if s.get("summary"):
                        context.append({
                            "kind": "section",
                            "doc_id": doc_id,
                            "title": f"{s.get('title') or 'Section'} (pp. {s['pages'][0]}-{s['pages'][1]})",
                            "page": s["pages"][0],
                            "chunk_ids": s.get("chunk_ids", []),
                            "text": s["summary"],
                        })
        detail = f"{sum(1 for c in context if c['kind'] == 'document')} document summaries"
        if computed:
            detail += f" ({computed} written now)"
        if missing:
            detail += f"; {len(missing)} not summarised yet"
        return {"summary_context": context, "agent_traces": [trace("corpus_summary", "completed", detail, started)]}
