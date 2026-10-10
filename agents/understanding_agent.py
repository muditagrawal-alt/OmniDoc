"""
Question understanding in (at most) one model call.

Earlier versions spent five or six model calls before searching anything (context
resolution, semantic analysis, intent classification, planning, entity resolution, query
expansion), about half the time of an answer. This agent asks one structured question of
the fast model instead, and only when it helps:

* the question refers back to the conversation ("it", "that report", "the second one"),
* the question is not in English (the documents are searched with English queries),
* the question has several parts or is long.

Simple questions are understood with deterministic rules, without a model call. The
result (resolved question, language, English search queries, sub-questions, entities,
intent, needs, time range) is then turned into the structures the other agents use by the
context-memory, semantic-NLU, intent, entity-resolution and query-expansion agents, which
now run deterministically on it.
"""
import os
import re
import logging
from typing import Any, Dict, List, Optional, Tuple

from agents.llm_utils import chat_json, as_str_list

logger = logging.getLogger("OmniDoc.Understanding")

MODE = os.getenv("OMNIDOC_UNDERSTANDING", "auto").strip().lower()  # auto | llm | rules

INTENTS = ("factual", "comparison", "summary", "calculation", "timeline", "table", "relationship", "exploration", "library")
NEEDS = ("calculation", "chart", "figures", "tables", "graph", "timeline", "whole_documents", "library", "web")

PROMPT = """Read a user's question about their documents and describe it for a search system. Do not answer it.

CONVERSATION (most recent last):
{history}

QUESTION: {query}

Return JSON only:
{{"resolved_query": "the question rewritten to stand on its own: replace references such as 'it', 'they', 'that report', 'the second one' with what they mean in the conversation; otherwise copy it unchanged",
  "language": "ISO 639-1 code of the question's language, e.g. en, hi, mr, ta",
  "search_queries": ["1 to 3 short ENGLISH search queries that would find the answer in the documents (translate if needed; keep exact names, numbers and terms)"],
  "sub_questions": ["each separate thing the question asks, as a short question; one item for a simple question"],
  "entities": ["names of people, organisations, products, places, documents, tables, figures or sections mentioned"],
  "intent": "one of: factual, comparison, summary, calculation, timeline, table, relationship, exploration, library",
  "needs": {{"calculation": false, "chart": false, "figures": false, "tables": false, "graph": false, "timeline": false, "whole_documents": false, "library": false, "web": false}},
  "time_range": null}}

needs: calculation = arithmetic must be done; chart = the user asks for a chart, plot or graph; figures = about images, diagrams or charts inside the documents; tables = about values in tables or spreadsheets; graph = how entities are related; timeline = dates or the order of events; whole_documents = a summary or overview of whole documents or the collection; library = about the set of documents itself (how many, which ones, totals across all invoices or contracts); web = needs current events or general information from the internet, or the user asks to search the web.
time_range: {{"start": "YYYY or YYYY-MM-DD", "end": "YYYY or YYYY-MM-DD"}} only if the question limits a period."""

SCHEMA = {
    "type": "object",
    "properties": {
        "resolved_query": {"type": "string"},
        "language": {"type": "string"},
        "search_queries": {"type": "array", "items": {"type": "string"}},
        "sub_questions": {"type": "array", "items": {"type": "string"}},
        "entities": {"type": "array", "items": {"type": "string"}},
        "intent": {"type": "string", "enum": list(INTENTS)},
        "needs": {"type": "object", "properties": {n: {"type": "boolean"} for n in NEEDS}},
        "time_range": {"type": ["object", "null"], "properties": {"start": {"type": "string"}, "end": {"type": "string"}}},
    },
    "required": ["resolved_query", "language", "search_queries", "sub_questions", "intent", "needs"],
}

# The interface appends this to the question when the user picks an answer language.
_LANG_INSTRUCTION = re.compile(r"\n*\[Instruction: write the complete final answer in ([^.\]]+?)(?:\s*\([^)]*\))?[,.].*?\]\s*$", re.S)
_LANGUAGE_CODES = {"hindi": "hi", "marathi": "mr", "tamil": "ta", "telugu": "te", "kannada": "kn", "assamese": "as",
                   "bengali": "bn", "gujarati": "gu", "english": "en"}

_REFERENCE = re.compile(r"\b(it|its|they|them|their|this|that|these|those|he|she|his|her|same|above|previous|former|latter|"
                        r"the (first|second|third|last|other) (one|document|report|file|item)|that (report|document|company|file|year)|"
                        r"then|there|both)\b", re.I)
_WORD = re.compile(r"[\w'’-]+", re.UNICODE)
_STOP = {"the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "is", "are", "was", "were", "be", "what", "which",
         "who", "whom", "when", "where", "why", "how", "does", "do", "did", "can", "could", "would", "should", "about",
         "with", "from", "by", "as", "at", "this", "that", "these", "those", "it", "its", "my", "me", "i", "you", "your",
         "please", "tell", "give", "show", "list", "explain", "describe", "document", "documents", "there", "any", "all",
         "much", "many", "between", "than", "into", "per", "has", "have", "had", "will", "shall", "may"}

_RULES: Dict[str, re.Pattern] = {
    "calculation": re.compile(r"\b(calculat|comput|how much (more|less|higher|lower)|difference|ratio|percent(age)? (change|of)|"
                              r"growth|cagr|average|mean|median|sum of|total of|add up|multiply|divide|per cent|increase|decrease|"
                              r"times (more|larger|bigger)|what fraction|proportion)\w*", re.I),
    # A request to make a chart ("plot it", "show this as a bar chart"), not a question about one in the document.
    "chart": re.compile(r"\b(plot(?!s?\b (in|on|of) (the|this|page))|graph it|chart it|visuali[sz]e|draw|histogram|"
                        r"(make|create|generate|build|give me|show me|produce|render|prepare)( me)? (a |an )?"
                        r"((bar|line|pie|scatter|column|area|stacked) )?(chart|graph|plot)|"
                        r"(as|in|into) (a |an )?((bar|line|pie|scatter|column|area) )?(chart|graph|plot)\b)\w*", re.I),
    "figures": re.compile(r"\b(figure|fig\.|diagram|image|picture|photo|illustration|infographic|maps?\b|logo|icon|"
                         r"screenshot|slide|colou?r|drawing|shown|depicted|pictured|look(s|ed)? like|visual|"
                         r"charts?|graphs?(?! database| of relationships)|plots?\b|pie|histograms?)\w*", re.I),
    "tables": re.compile(r"\b(table|spreadsheet|sheet|row|column|cell|csv|excel|xlsx)s?\b", re.I),
    "graph": re.compile(r"\b(relat(ed|ion|ionship)|connect(ed|ion)|link(ed)?|network|depend(s|ency|encies)?|who works with|"
                        r"associated with|between .{2,40} and)\b", re.I),
    "timeline": re.compile(r"\b(when|timeline|chronolog\w*|before|after|since|until|history|histor\w+|sequence|dated?|"
                           r"(19|20)\d\d|year|month|deadline|expir\w+|due date)\b", re.I),
    "library": re.compile(r"\b(how many (documents|files|invoices|contracts|reports|papers)|which (documents|files|invoices|contracts|reports)|"
                          r"all (my |the )?(invoices|contracts|receipts|resumes|reports|statements)|across (all )?(invoices|contracts|receipts)|"
                          r"total (amount|due|value|spend) (of|across|for) (all|my)|list (my|the|all) (documents|files|invoices|contracts))\b", re.I),
}
_COMPARE = re.compile(r"\b(compare|comparison|versus|vs\.?|differ(ence|ent)?|contrast|better|worse|than)\b", re.I)
_SCRIPTS: List[Tuple[str, str, str]] = [
    ("ऀ", "ॿ", "hi"), ("ঀ", "৿", "bn"), ("਀", "੿", "pa"), ("઀", "૿", "gu"),
    ("଀", "୿", "or"), ("஀", "௿", "ta"), ("ఀ", "౿", "te"), ("ಀ", "೿", "kn"),
    ("ഀ", "ൿ", "ml"), ("؀", "ۿ", "ur"), ("Ѐ", "ӿ", "ru"), ("一", "鿿", "zh"),
    ("぀", "ヿ", "ja"), ("가", "힯", "ko"),
]


def split_language_instruction(query: str) -> Tuple[str, Optional[str]]:
    """Removes the interface's answer-language instruction; returns (question, language code or None)."""
    m = _LANG_INSTRUCTION.search(query or "")
    if not m:
        return query, None
    name = m.group(1).strip().lower()
    return query[:m.start()].rstrip(), _LANGUAGE_CODES.get(name.split()[0], None)


def detect_script_language(text: str) -> str:
    """Language guessed from the writing system (Latin script counts as English)."""
    counts: Dict[str, int] = {}
    for ch in text or "":
        for lo, hi, code in _SCRIPTS:
            if lo <= ch <= hi:
                counts[code] = counts.get(code, 0) + 1
                break
    letters = sum(1 for ch in text or "" if ch.isalpha())
    if counts and letters:
        code, n = max(counts.items(), key=lambda kv: kv[1])
        if n >= 0.3 * letters:
            return code
    return "en"


def content_words(text: str) -> List[str]:
    return [w for w in _WORD.findall(text or "") if w.lower() not in _STOP and len(w) > 2]


def _entities(text: str) -> List[str]:
    out: List[str] = []
    for m in re.finditer(r"[\"“'‘]([^\"”'’]{2,60})[\"”'’]", text):
        out.append(m.group(1).strip())
    for m in re.finditer(r"\b(?:Table|Figure|Fig\.|Section|Chapter|Appendix|Clause|Slide|Page)\s+[\w.]+", text, re.I):
        out.append(m.group(0))
    # Capitalised phrases not at the start of the question, and acronyms.
    for m in re.finditer(r"(?<![.?!]\s)(?<!^)\b([A-Z][\w&.-]*(?:\s+(?:of|and|for|the|de)?\s*[A-Z][\w&.-]*)*)", text):
        phrase = m.group(1).strip()
        if len(phrase) > 2 and phrase.lower() not in _STOP:
            out.append(phrase)
    out.extend(re.findall(r"\b[A-Z]{2,}[0-9]*\b", text))
    seen, unique = set(), []
    for e in out:
        key = e.lower()
        if key not in seen:
            seen.add(key)
            unique.append(e)
    return unique[:10]


def _sub_questions(text: str) -> List[str]:
    parts = [p.strip() for p in re.split(r"\?\s+(?=\S)|,?\s+and\s+(?=(?:what|which|who|when|where|why|how|is|are|does|do|did|can)\b)",
                                          text, flags=re.I) if p and p.strip()]
    parts = [p if p.endswith("?") else p + "?" for p in parts if len(p.split()) >= 3]
    return parts[:5] or [text]


def _years(text: str) -> List[str]:
    return re.findall(r"\b(1[89]\d\d|20\d\d)\b", text or "")


def _time_range(text: str) -> Optional[Dict[str, str]]:
    years = _years(text)
    if not years:
        return None
    low = text.lower()
    if len(years) >= 2 and re.search(r"\b(between|from|to|through|until|-|–)\b", low):
        return {"start": min(years), "end": max(years)}
    if re.search(r"\b(since|after|from)\s+(in\s+)?(1[89]|20)\d\d", low):
        return {"start": years[0], "end": ""}
    if re.search(r"\b(before|until|by)\s+(in\s+)?(1[89]|20)\d\d", low):
        return {"start": "", "end": years[0]}
    if re.search(r"\b(in|during|of|for)\s+(1[89]|20)\d\d\b", low) and len(years) == 1:
        return {"start": years[0], "end": years[0]}
    return None


def rules(query: str, corpus_question: bool = False) -> Dict[str, Any]:
    """Understanding without a model: language, needs, intent, entities, sub-questions, search queries."""
    needs = {n: bool(p.search(query)) for n, p in _RULES.items()}
    needs["whole_documents"] = corpus_question
    needs.setdefault("graph", False)
    from agents.web_search_agent import wants_web
    needs["web"] = wants_web(query)
    if needs["library"]:
        needs["tables"] = True
    intent = "factual"
    if needs["library"]:
        intent = "library"
    elif corpus_question:
        intent = "summary"
    elif _COMPARE.search(query):
        intent = "comparison"
    elif needs["calculation"]:
        intent = "calculation"
    elif needs["tables"]:
        intent = "table"
    elif needs["graph"]:
        intent = "relationship"
    elif needs["timeline"] and re.search(r"\b(when|timeline|chronolog|sequence|history)\b", query, re.I):
        intent = "timeline"
    words = content_words(query)
    queries = [query]
    if len(words) >= 3:
        queries.append(" ".join(words[:12]))
    return {
        "resolved_query": query,
        "language": detect_script_language(query),
        "search_queries": queries,
        "sub_questions": _sub_questions(query),
        "entities": _entities(query),
        "intent": intent,
        "needs": needs,
        "time_range": _time_range(query),
    }


def wants_model(query: str, history: List[Dict[str, Any]], language: str) -> Tuple[bool, str]:
    """Whether the model call is worth it for this question (MODE=auto)."""
    if MODE == "llm":
        return True, "always on"
    if MODE == "rules":
        return False, "rules only"
    if history and _REFERENCE.search(query):
        return True, "refers to the conversation"
    if language != "en":
        return True, "not in English"
    parts = len(_sub_questions(query))
    if parts >= 2 or len(query.split()) >= 28:
        return True, "several parts" if parts >= 2 else "long question"
    return False, "simple question"


class QueryUnderstandingAgent:
    """Understands a question with rules, or with one fast-model call when that helps."""

    def __init__(self, model_name: str = "qwen2.5:7b-instruct"):
        self.model_name = model_name

    @staticmethod
    def _history_text(history: List[Dict[str, Any]]) -> str:
        lines = []
        for turn in (history or [])[-6:]:
            if not isinstance(turn, dict):
                continue
            role = str(turn.get("role", "user")).capitalize()
            content = " ".join(str(turn.get("content", "")).split())
            lines.append(f"{role}: {content[:300 if role == 'User' else 500]}")
        return "\n".join(lines) or "(none)"

    def understand(self, query: str, history: Optional[List[Dict[str, Any]]] = None,
                   corpus_question: bool = False) -> Dict[str, Any]:
        """Returns the understanding dict plus "used_model" and "why"."""
        base = rules(query, corpus_question)
        use_model, why = wants_model(query, history or [], base["language"])
        base.update(used_model=False, why=why)
        if not use_model:
            return base
        try:
            parsed = chat_json(self.model_name, PROMPT.format(history=self._history_text(history or []), query=query[:2000]),
                               num_predict=500, fast=True, schema=SCHEMA)
        except Exception as e:
            logger.warning(f"Understanding call failed ({e}); using rules.")
            base["why"] = f"{why}; model unavailable"
            return base
        if not isinstance(parsed, dict):
            return base
        return self._merge(base, parsed, query, why)

    @staticmethod
    def _merge(base: Dict[str, Any], parsed: Dict[str, Any], query: str, why: str) -> Dict[str, Any]:
        out = dict(base)
        resolved = str(parsed.get("resolved_query") or "").strip()
        # A rewrite far longer than the question is usually an answer, not a question.
        if resolved and len(resolved) <= max(3 * len(query), len(query) + 250):
            out["resolved_query"] = resolved
        lang = str(parsed.get("language") or "").strip().lower()[:5]
        if re.fullmatch(r"[a-z]{2,3}", lang):
            # The script tells non-Latin languages apart reliably; trust the model for Latin ones.
            out["language"] = base["language"] if base["language"] != "en" else lang
        queries = as_str_list(parsed.get("search_queries"), max_items=3, max_len=200)
        out["search_queries"] = list(dict.fromkeys(queries + base["search_queries"]))[:4]
        subs = as_str_list(parsed.get("sub_questions"), max_items=5, max_len=240)
        if subs:
            out["sub_questions"] = subs
        ents = as_str_list(parsed.get("entities"), max_items=10, max_len=120)
        if ents:
            out["entities"] = list(dict.fromkeys(ents + base["entities"]))[:12]
        intent = str(parsed.get("intent") or "").strip().lower()
        if intent in INTENTS:
            out["intent"] = intent
        needs = parsed.get("needs") if isinstance(parsed.get("needs"), dict) else {}
        merged = dict(base["needs"])
        for n in NEEDS:
            if isinstance(needs.get(n), bool):
                # A chart needs an explicit request; keep the rules' "no" when the model says yes without one.
                merged[n] = needs[n] if n != "chart" else (needs[n] and base["needs"]["chart"])
        merged["whole_documents"] = merged.get("whole_documents") or base["needs"]["whole_documents"]
        out["needs"] = merged
        tr = parsed.get("time_range")
        if isinstance(tr, dict) and (tr.get("start") or tr.get("end")):
            out["time_range"] = {"start": str(tr.get("start") or "")[:10], "end": str(tr.get("end") or "")[:10]}
        out.update(used_model=True, why=why)
        return out
