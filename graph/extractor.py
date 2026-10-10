"""
Entity and Relationship Extractor for Graph RAG.
Uses structured LLM output to extract entity-relationship triples
and populate the embedded Kùzu property graph.
"""
import re
import uuid
import logging
from typing import List, Dict, Any, Tuple, Optional
from pydantic import BaseModel, Field

from core.state import EntityNode, RelationshipEdge
from graph.store import KuzuGraphStore

logger = logging.getLogger("OmniDoc.GraphExtractor")


class ExtractedEntity(BaseModel):
    name: str = Field(description="Name of the concept, component, method, or entity")
    category: str = Field(description="Type: e.g. Concept, Component, Method, Organization, Metric, Regulation")
    description: str = Field(default="", description="Brief definition or context from text")


class ExtractedRelation(BaseModel):
    source_name: str = Field(description="Exact name of the source entity")
    target_name: str = Field(description="Exact name of the target entity")
    relation: str = Field(description="Relationship verb: e.g. USES, DEFINES, CONFLICTS_WITH, DEPENDS_ON, EVALUATES")
    description: str = Field(default="", description="Explanation of how they are related")
    weight: float = Field(default=1.0, description="Strength of relationship (0.1 to 1.0)")


class ExtractionPayload(BaseModel):
    entities: List[ExtractedEntity] = Field(default_factory=list)
    relationships: List[ExtractedRelation] = Field(default_factory=list)


EXTRACTION_PROMPT = """You are an expert Knowledge Graph Extraction Agent.
Your job is to extract prominent domain entities and directional relationships from the provided document chunk.

Focus on:
1. Core technical concepts, architectural components, methods, definitions, and algorithms.
2. Direct relationships between these concepts (e.g. A USES B, C DEFINES D, E DEPENDS_ON F).

Rules:
- Extract 3 to 10 meaningful entities per chunk, using the names exactly as written in the chunk.
- Do not invent entities, facts or numbers that are not in the chunk.
- For each relationship, source_name and target_name MUST match one of the extracted entity names.
- "relation" is a short UPPER_SNAKE_CASE verb phrase (e.g. USES, PART_OF, PRODUCES).
- Output ONLY valid JSON matching this schema:
{{
    "entities": [
        {{"name": "...", "category": "...", "description": "..."}}
    ],
    "relationships": [
        {{"source_name": "...", "target_name": "...", "relation": "...", "description": "...", "weight": 1.0}}
    ]
}}

DOCUMENT CHUNK:
{chunk_text}
"""


BATCH_PROMPT = """You are an expert Knowledge Graph Extraction Agent.
Extract prominent domain entities and directional relationships from EACH numbered document chunk below, separately.

Rules:
- 3 to 10 meaningful entities per chunk (concepts, components, methods, organisations, people, places, metrics), named exactly as written in that chunk.
- Keep every description under 15 words.
- Do not invent entities, facts or numbers that are not in the chunk.
- Relationship source_name and target_name MUST be entities of the same chunk; "relation" is a short UPPER_SNAKE_CASE verb (USES, PART_OF, PRODUCES).
- Output ONLY valid JSON:
{{"chunks": [{{"id": "C1", "entities": [{{"name": "...", "category": "...", "description": "..."}}],
  "relationships": [{{"source_name": "...", "target_name": "...", "relation": "...", "description": "...", "weight": 1.0}}]}}]}}

{chunks}
"""
# Chunks per extraction call, and the text budget of one call.
BATCH_CHUNKS = 4
BATCH_CHARS = 7000

_REL_RE = re.compile(r"[^A-Z0-9]+")
_WORD_RE = re.compile(r"[a-z0-9]+")


def clean_text(value: Any, max_len: int) -> str:
    """Single-line, backslash-free text safe for the graph store's Cypher literals."""
    text = str(value or "")
    text = text.replace("\\", "/").replace("\"", "'").replace("`", "'")
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", text)
    text = " ".join(text.split())
    return text[:max_len].strip()


def clean_relation(value: Any) -> str:
    rel = _REL_RE.sub("_", str(value or "").upper()).strip("_")
    rel = re.sub(r"_+", "_", rel)[:48]
    return rel or "RELATED_TO"


def _weight(value: Any) -> float:
    try:
        w = float(value)
    except (TypeError, ValueError):
        return 1.0
    return max(0.1, min(1.0, w))


def grounded_in(name: str, chunk_text: str) -> bool:
    """The entity (or its distinctive words) must occur in the chunk; filters invented entities."""
    low_chunk = chunk_text.lower()
    low = name.lower()
    if low in low_chunk:
        return True
    words = [w for w in _WORD_RE.findall(low) if len(w) >= 4 or w.isdigit()]
    if not words:
        return False
    hits = sum(1 for w in words if w in low_chunk)
    return hits / len(words) >= 0.5


def coerce_payload(data: Any) -> ExtractionPayload:
    """Builds a payload from imperfect LLM JSON, skipping malformed items instead of failing."""
    if isinstance(data, list):
        data = {"entities": data}
    if not isinstance(data, dict):
        return ExtractionPayload()
    entities, relations = [], []
    for e in data.get("entities") or data.get("nodes") or []:
        if isinstance(e, str):
            e = {"name": e}
        if not isinstance(e, dict):
            continue
        name = clean_text(e.get("name") or e.get("entity"), 120)
        if not name:
            continue
        entities.append(ExtractedEntity(
            name=name,
            category=clean_text(e.get("category") or e.get("type") or "Concept", 40) or "Concept",
            description=clean_text(e.get("description"), 400),
        ))
    for r in data.get("relationships") or data.get("relations") or data.get("edges") or []:
        if not isinstance(r, dict):
            continue
        src = clean_text(r.get("source_name") or r.get("source"), 120)
        tgt = clean_text(r.get("target_name") or r.get("target"), 120)
        if not src or not tgt:
            continue
        relations.append(ExtractedRelation(
            source_name=src,
            target_name=tgt,
            relation=clean_relation(r.get("relation") or r.get("type")),
            description=clean_text(r.get("description"), 400),
            weight=_weight(r.get("weight", 1.0)),
        ))
    return ExtractionPayload(entities=entities, relationships=relations)


class GraphExtractor:
    """Extracts entity-relation subgraphs and populates Kùzu."""

    def __init__(self, graph_store: KuzuGraphStore, model_name: str = "qwen2.5:7b-instruct"):
        self.graph_store = graph_store
        self.model_name = model_name

    @staticmethod
    def _entity_id(doc_id: str, name: str) -> str:
        return f"ent_{uuid.uuid5(uuid.NAMESPACE_DNS, f'{doc_id}_{name.lower()}').hex[:12]}"

    def extract_and_index_chunk(
        self,
        doc_id: str,
        chunk_id: str,
        chunk_text: str,
        page_number: int = 1,
        section_title: str = "General"
    ) -> Tuple[List[EntityNode], List[RelationshipEdge]]:
        """
        Extracts triples from a chunk and registers them into Kùzu.
        """
        self.graph_store.add_chunk(
            chunk_id=chunk_id,
            doc_id=doc_id,
            page_number=page_number,
            section_title=clean_text(section_title, 200) or "General",
            text=chunk_text
        )

        try:
            from agents.llm_utils import chat_json  # local import avoids an import cycle via agents/__init__
            data = chat_json(self.model_name, EXTRACTION_PROMPT.format(chunk_text=chunk_text[:3000]), num_predict=1024,
                             fast=True)
            payload = coerce_payload(data)
        except Exception as e:
            logger.warning(f"Graph extraction skipped for chunk {chunk_id}: {e}")
            return [], []
        return self._index_payload(doc_id, chunk_id, chunk_text, payload)

    def extract_batch(self, doc_id: str, chunks: List[Any], progress: Optional[Any] = None) -> int:
        """
        Extracts entities and relations from several chunks per model call (up to
        BATCH_CHUNKS chunks / BATCH_CHARS characters), which cuts the calls for a document to
        about a quarter. Returns the number of entities created.
        """
        batches: List[List[Any]] = []
        for ch in chunks:
            if batches and len(batches[-1]) < BATCH_CHUNKS and sum(len(c.text[:2500]) for c in batches[-1]) + len(ch.text[:2500]) <= BATCH_CHARS:
                batches[-1].append(ch)
            else:
                batches.append([ch])
        created = 0
        done = 0
        for batch in batches:
            for ch in batch:
                self.graph_store.add_chunk(chunk_id=ch.chunk_id, doc_id=doc_id, page_number=ch.page_number,
                                           section_title=clean_text(ch.section_title, 200) or "General", text=ch.text)
            answers = self._ask_batch(doc_id, batch)
            results = {ch.chunk_id: answers.get(f"C{i}") for i, ch in enumerate(batch, 1)}
            # A reply cut off by the token limit keeps the chunks before the cut: ask again for the rest.
            missing = [ch for ch in batch if not results[ch.chunk_id]]
            if missing and len(missing) < len(batch):
                again = self._ask_batch(doc_id, missing)
                for i, ch in enumerate(missing, 1):
                    results[ch.chunk_id] = again.get(f"C{i}")
            for ch in batch:
                payload = coerce_payload(results[ch.chunk_id] or {})
                entities, _ = self._index_payload(doc_id, ch.chunk_id, ch.text, payload)
                created += len(entities)
            done += len(batch)
            if progress:
                progress(done, len(chunks))
        return created

    def _ask_batch(self, doc_id: str, batch: List[Any]) -> Dict[str, Any]:
        """The model's entities and relations per chunk ("C1", "C2", ...) of one batch; {} on failure."""
        from agents.llm_utils import chat_json
        listing = "\n\n".join(f"[C{i}] {ch.text[:2500]}" for i, ch in enumerate(batch, 1))
        try:
            data = chat_json(self.model_name, BATCH_PROMPT.format(chunks=listing), num_predict=750 * len(batch), fast=True)
        except Exception as e:
            logger.warning(f"Graph extraction skipped for {len(batch)} chunk(s) of {doc_id}: {e}")
            return {}
        return {str(item.get("id") or "").strip().upper(): item
                for item in (data.get("chunks") or [] if isinstance(data, dict) else []) if isinstance(item, dict)}

    def _index_payload(self, doc_id: str, chunk_id: str, chunk_text: str,
                       payload: ExtractionPayload) -> Tuple[List[EntityNode], List[RelationshipEdge]]:
        """Registers a chunk's extracted entities (those found in its text) and relations."""
        created_entities: List[EntityNode] = []
        entity_map: Dict[str, str] = {}  # lower(name) -> id
        meta: Dict[str, Tuple[str, str]] = {}
        skipped: List[str] = []

        def register(name: str, category: str = "Concept", description: str = "") -> Optional[str]:
            key = name.lower()
            if key in entity_map:
                return entity_map[key]
            if not grounded_in(name, chunk_text):
                if name not in skipped:
                    skipped.append(name)
                return None
            ent_id = self._entity_id(doc_id, name)
            entity_map[key] = ent_id
            meta[key] = (name, category)
            self.graph_store.add_entity(entity_id=ent_id, name=name, category=category,
                                        description=description, doc_id=doc_id)
            self.graph_store.link_chunk_to_entity(chunk_id, ent_id)
            created_entities.append(EntityNode(id=ent_id, name=name, category=category, description=description,
                                               doc_id=doc_id, source_chunk_ids=[chunk_id]))
            return ent_id

        for ent in payload.entities:
            register(ent.name, ent.category, ent.description)

        created_relations: List[RelationshipEdge] = []
        seen_rel = set()
        for rel in payload.relationships:
            src_id = entity_map.get(rel.source_name.lower()) or register(rel.source_name)
            tgt_id = entity_map.get(rel.target_name.lower()) or register(rel.target_name)
            if not src_id or not tgt_id or src_id == tgt_id:
                continue
            key = (src_id, rel.relation, tgt_id)
            if key in seen_rel:
                continue
            seen_rel.add(key)
            self.graph_store.add_relation(source_id=src_id, target_id=tgt_id, relation=rel.relation,
                                          description=rel.description, weight=rel.weight)
            created_relations.append(RelationshipEdge(
                source_id=src_id, target_id=tgt_id,
                source_name=meta.get(rel.source_name.lower(), (rel.source_name, ""))[0],
                target_name=meta.get(rel.target_name.lower(), (rel.target_name, ""))[0],
                relation=rel.relation, description=rel.description, weight=rel.weight, doc_id=doc_id,
            ))

        if skipped:
            logger.info(f"Chunk {chunk_id}: skipped {len(skipped)} entity name(s) not found in the chunk text: {skipped[:5]}")
        return created_entities, created_relations
