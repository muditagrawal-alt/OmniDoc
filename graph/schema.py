"""
Knowledge Graph Schema definitions for Kùzu Property Graph.
Defines Node tables (Entity, Document, Chunk) and Relationship tables.
"""
from dataclasses import dataclass
from typing import List, Optional

# Kùzu Cypher DDL Statements for Schema Initialization
KUZU_NODE_SCHEMAS = [
    # Document Node
    """
    CREATE NODE TABLE IF NOT EXISTS Document (
        id STRING,
        title STRING,
        doc_type STRING,
        hash STRING,
        PRIMARY KEY (id)
    )
    """,
    # Chunk Node
    """
    CREATE NODE TABLE IF NOT EXISTS Chunk (
        id STRING,
        doc_id STRING,
        page_number INT64,
        section_title STRING,
        text STRING,
        PRIMARY KEY (id)
    )
    """,
    # Entity Node
    """
    CREATE NODE TABLE IF NOT EXISTS Entity (
        id STRING,
        name STRING,
        category STRING,
        description STRING,
        doc_id STRING,
        PRIMARY KEY (id)
    )
    """,
    # Community / Theme Node (for LightRAG high-level sensemaking)
    """
    CREATE NODE TABLE IF NOT EXISTS Community (
        id STRING,
        name STRING,
        summary STRING,
        level INT64,
        PRIMARY KEY (id)
    )
    """
]

KUZU_REL_SCHEMAS = [
    # Document -> Chunk
    """
    CREATE REL TABLE IF NOT EXISTS HAS_CHUNK (
        FROM Document TO Chunk
    )
    """,
    # Chunk -> Entity
    """
    CREATE REL TABLE IF NOT EXISTS MENTIONS (
        FROM Chunk TO Entity
    )
    """,
    # Entity -> Entity (Domain relations like USES, DEFINES, DEPENDS_ON)
    """
    CREATE REL TABLE IF NOT EXISTS RELATES_TO (
        FROM Entity TO Entity,
        relation STRING,
        description STRING,
        weight DOUBLE
    )
    """,
    # Community -> Entity (Cluster membership)
    """
    CREATE REL TABLE IF NOT EXISTS IN_COMMUNITY (
        FROM Entity TO Community
    )
    """
]
