"""
Entity and Relationship Extractor for Graph RAG.
Uses structured LLM output to extract entity-relationship triples
and populate the embedded Kùzu property graph.
"""
import re
import json
import uuid
import logging
from typing import List, Dict, Any, Tuple
from pydantic import BaseModel, Field
import ollama

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
- Extract 3 to 10 meaningful entities per chunk.
- For each relationship, source_name and target_name MUST match one of the extracted entity names.
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


class GraphExtractor:
    """Extracts entity-relation subgraphs and populates Kùzu."""

    def __init__(self, graph_store: KuzuGraphStore, model_name: str = "qwen2.5:7b-instruct"):
        self.graph_store = graph_store
        self.model_name = model_name

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
        # Save chunk into Kùzu
        self.graph_store.add_chunk(
            chunk_id=chunk_id,
            doc_id=doc_id,
            page_number=page_number,
            section_title=section_title,
            text=chunk_text
        )

        try:
            response = ollama.chat(
                model=self.model_name,
                messages=[{"role": "user", "content": EXTRACTION_PROMPT.format(chunk_text=chunk_text[:3000])}],
                options={"temperature": 0.0, "num_predict": 1024},
                stream=False
            )
            raw = response["message"]["content"].strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```(?:json)?\s*", "", raw)
                raw = re.sub(r"\s*```$", "", raw)

            data = json.loads(raw)
            payload = ExtractionPayload(**data)
            
            created_entities = []
            entity_map = {}  # name -> id

            # Register Entities
            for ent in payload.entities:
                cleaned_name = ent.name.strip()
                if not cleaned_name:
                    continue
                ent_id = f"ent_{uuid.uuid5(uuid.NAMESPACE_DNS, f'{doc_id}_{cleaned_name}').hex[:12]}"
                entity_map[cleaned_name.lower()] = ent_id
                
                self.graph_store.add_entity(
                    entity_id=ent_id,
                    name=cleaned_name,
                    category=ent.category,
                    description=ent.description,
                    doc_id=doc_id
                )
                self.graph_store.link_chunk_to_entity(chunk_id, ent_id)
                
                created_entities.append(EntityNode(
                    id=ent_id,
                    name=cleaned_name,
                    category=ent.category,
                    description=ent.description,
                    doc_id=doc_id,
                    source_chunk_ids=[chunk_id]
                ))

            # Register Relationships
            created_relations = []
            for rel in payload.relationships:
                src_key = rel.source_name.strip().lower()
                tgt_key = rel.target_name.strip().lower()
                
                src_id = entity_map.get(src_key)
                tgt_id = entity_map.get(tgt_key)
                
                if src_id and tgt_id and src_id != tgt_id:
                    self.graph_store.add_relation(
                        source_id=src_id,
                        target_id=tgt_id,
                        relation=rel.relation.strip().upper(),
                        description=rel.description,
                        weight=rel.weight
                    )
                    created_relations.append(RelationshipEdge(
                        source_id=src_id,
                        target_id=tgt_id,
                        relation=rel.relation.strip().upper(),
                        description=rel.description,
                        weight=rel.weight,
                        doc_id=doc_id
                    ))

            return created_entities, created_relations

        except Exception as e:
            logger.warning(f"Graph extraction skipped for chunk {chunk_id}: {e}")
            return [], []
