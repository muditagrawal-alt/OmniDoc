"""
Ingestion Engine for SOTA Agentic Graph RAG Benchmark Corpora.
Ingests:
1. MultiHop-RAG multi-document relational networks
2. FinanceBench audited SEC Form 10-K statements & tables
3. CRUD-RAG cross-document discrepancy audit reports
4. Microsoft GraphRAG / SOTA Architecture technical survey

Populates:
- LanceDB (.data/lancedb, table: document_chunks) with nomic-embed-text vectors
- Kùzu Graph (.data/kuzu_db/graph.kuzu) with Document, Chunk, and Entity nodes + RELATES_TO edges
"""
import os
import sys
import json
import logging
import uuid
from typing import List, Dict, Any

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.state import RetrievedChunk
from retrieval.embeddings import EmbeddingService
from retrieval.lancedb_store import LanceDBStore
from graph.store import KuzuGraphStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("OmniDoc.SOTABenchmarkIngester")


def ingest_all_sota_benchmarks():
    logger.info("==========================================================")
    logger.info("🚀 INGESTING SOTA AGENTIC GRAPH RAG BENCHMARK CORPORA")
    logger.info("==========================================================")

    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "benchmarks_data")
    corpus_files = [
        "multihop_rag_corpus.json",
        "financebench_corpus.json",
        "conflict_audit_corpus.json",
        "graphrag_sensemaking_corpus.json"
    ]

    embed_service = EmbeddingService()
    lance_store = LanceDBStore(db_dir=".data/lancedb", table_name="document_chunks")
    graph_store = KuzuGraphStore(db_path=".data/kuzu_db/graph.kuzu")

    total_docs = 0
    total_chunks = 0
    total_entities = 0
    total_relations = 0

    entity_id_cache = {}  # name_lower -> id

    for cfile in corpus_files:
        filepath = os.path.join(data_dir, cfile)
        if not os.path.exists(filepath):
            logger.warning(f"Corpus file not found: {filepath}")
            continue

        with open(filepath, "r", encoding="utf-8") as f:
            corpus_data = json.load(f)

        logger.info(f"\n📂 Ingesting corpus: {cfile} ({len(corpus_data)} document definitions)...")

        for doc in corpus_data:
            doc_id = doc["doc_id"]
            title = doc["title"]
            chunks_data = doc.get("chunks", [])

            total_docs += 1
            # 1. Register Document Node in Kùzu
            graph_store.add_document(
                doc_id=doc_id,
                title=title,
                doc_type="benchmark_doc",
                doc_hash=f"hash_{doc_id}"
            )

            # 2. Prepare chunks for vector embedding and LanceDB
            retrieved_chunks: List[RetrievedChunk] = []
            chunk_texts: List[str] = []

            for ch in chunks_data:
                cid = ch["chunk_id"]
                txt = ch["text"]
                pg = ch.get("page_number", 1)
                sec = ch.get("section", "General")

                retrieved_chunks.append(RetrievedChunk(
                    chunk_id=cid,
                    doc_id=doc_id,
                    text=txt,
                    score=1.0,
                    page_number=pg,
                    section_title=sec
                ))
                chunk_texts.append(txt)

            # 3. Compute Embeddings & Batch Add to LanceDB
            if chunk_texts:
                logger.info(f"  Embedding {len(chunk_texts)} chunks for document '{title[:45]}...'")
                embs = embed_service.embed_texts(chunk_texts)
                lance_store.add_chunks(retrieved_chunks, embs)
                total_chunks += len(retrieved_chunks)

            # 4. Populate Knowledge Graph (Entities, Relations, Mentions)
            for ch in chunks_data:
                cid = ch["chunk_id"]
                txt = ch["text"]
                pg = ch.get("page_number", 1)
                sec = ch.get("section", "General")

                # Register Chunk Node in Kùzu
                graph_store.add_chunk(
                    chunk_id=cid,
                    doc_id=doc_id,
                    page_number=pg,
                    section_title=sec,
                    text=txt
                )

                # Register Entities
                for ent in ch.get("entities", []):
                    ename = ent["name"].strip()
                    ecat = ent.get("category", "Concept")
                    edesc = ent.get("description", "")
                    
                    ename_l = ename.lower()
                    if ename_l not in entity_id_cache:
                        eid = f"ent_{uuid.uuid5(uuid.NAMESPACE_DNS, f'bench_{ename_l}').hex[:12]}"
                        entity_id_cache[ename_l] = eid
                        graph_store.add_entity(
                            entity_id=eid,
                            name=ename,
                            category=ecat,
                            description=edesc,
                            doc_id=doc_id
                        )
                        total_entities += 1
                    else:
                        eid = entity_id_cache[ename_l]

                    # Link Chunk -> Entity
                    graph_store.link_chunk_to_entity(cid, eid)

                # Register Relations
                for rel in ch.get("relations", []):
                    s_name_l = rel["source"].strip().lower()
                    t_name_l = rel["target"].strip().lower()
                    rel_type = rel.get("relation", "RELATES_TO")
                    r_desc = rel.get("description", "")
                    weight = rel.get("weight", 1.0)

                    s_id = entity_id_cache.get(s_name_l)
                    t_id = entity_id_cache.get(t_name_l)

                    if not s_id:
                        s_id = f"ent_{uuid.uuid5(uuid.NAMESPACE_DNS, f'bench_{s_name_l}').hex[:12]}"
                        entity_id_cache[s_name_l] = s_id
                        graph_store.add_entity(s_id, rel["source"], "Concept", "", doc_id)
                        total_entities += 1

                    if not t_id:
                        t_id = f"ent_{uuid.uuid5(uuid.NAMESPACE_DNS, f'bench_{t_name_l}').hex[:12]}"
                        entity_id_cache[t_name_l] = t_id
                        graph_store.add_entity(t_id, rel["target"], "Concept", "", doc_id)
                        total_entities += 1

                    graph_store.add_relation(
                        source_id=s_id,
                        target_id=t_id,
                        relation=rel_type,
                        description=r_desc,
                        weight=weight
                    )
                    total_relations += 1

    logger.info("==========================================================")
    logger.info("✅ SOTA BENCHMARK CORPORA INGESTION COMPLETE")
    logger.info(f"   • Total Documents Indexed:        {total_docs}")
    logger.info(f"   • Total Semantic Chunks Embedded: {total_chunks}")
    logger.info(f"   • Total Graph Entities (Nodes):   {total_entities}")
    logger.info(f"   • Total Graph Relations (Edges):  {total_relations}")
    logger.info("==========================================================")

    return {
        "total_docs": total_docs,
        "total_chunks": total_chunks,
        "total_entities": total_entities,
        "total_relations": total_relations
    }


if __name__ == "__main__":
    ingest_all_sota_benchmarks()
