# rag.py - Enhanced RAG Pipeline with persistent storage
import math
import os
import pickle
from pathlib import Path
import ollama
import numpy as np

EMBED_MODEL = "nomic-embed-text"
CACHE_DIR = Path(".cache/embeddings")
CACHE_DIR.mkdir(exist_ok=True, parents=True)

def cosine_similarity(a, b):
    """Compute cosine similarity between two vectors."""
    dot = sum(x*y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x*x for x in a))
    norm_b = math.sqrt(sum(x*x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0
    return dot / (norm_a * norm_b)


class RAGPipeline:
    """Enhanced RAG pipeline with persistent embedding cache."""
    
    def __init__(self, chunk_size=500, overlap=100, cache_key=None):
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.chunks = []
        self.embeddings = []
        self.cache_key = cache_key
        self.metadata = {}

    def chunk_text(self, text: str) -> list:
        """Split text into overlapping chunks."""
        words = text.split()
        chunks = []
        
        i = 0
        while i < len(words):
            chunk = words[i:i+self.chunk_size]
            chunks.append(" ".join(chunk))
            i += self.chunk_size - self.overlap
        
        return chunks if chunks else [text]

    def embed(self, text: str) -> list:
        """Get embedding for text from Ollama."""
        try:
            response = ollama.embeddings(
                model=EMBED_MODEL,
                prompt=text
            )
            return response.get("embedding", [])
        except Exception as e:
            print(f"⚠️ Embedding error: {e}")
            return []

    def ingest(self, document_text: str, document_hash: str = None) -> bool:
        """
        Ingest document - chunks and embeds.
        Checks cache first if hash provided.
        """
        self.chunks = self.chunk_text(document_text)
        
        # Try loading from cache
        if document_hash:
            cache_file = CACHE_DIR / f"{document_hash}.pkl"
            if cache_file.exists():
                try:
                    with open(cache_file, 'rb') as f:
                        data = pickle.load(f)
                        self.embeddings = data['embeddings']
                        self.metadata = data.get('metadata', {})
                    print(f"✓ Loaded cached embeddings for {document_hash}")
                    return True
                except Exception as e:
                    print(f"⚠️ Cache load failed: {e}")
        
        # Generate new embeddings
        print(f"Generating embeddings for {len(self.chunks)} chunks...")
        self.embeddings = []
        for i, chunk in enumerate(self.chunks):
            emb = self.embed(chunk)
            if emb:
                self.embeddings.append(emb)
            if (i + 1) % 10 == 0:
                print(f"  {i + 1}/{len(self.chunks)} chunks embedded")
        
        # Cache embeddings
        if document_hash and self.embeddings:
            try:
                cache_file = CACHE_DIR / f"{document_hash}.pkl"
                with open(cache_file, 'wb') as f:
                    pickle.dump({
                        'embeddings': self.embeddings,
                        'chunks': self.chunks,
                        'metadata': self.metadata
                    }, f)
                print(f"✓ Cached embeddings")
            except Exception as e:
                print(f"⚠️ Cache save failed: {e}")
        
        return len(self.embeddings) > 0

    def retrieve(self, query: str, top_k: int = 5) -> list:
        """Retrieve top-k most relevant chunks."""
        if not self.embeddings:
            return []
        
        query_emb = self.embed(query)
        if not query_emb:
            return []
        
        scores = [
            (cosine_similarity(query_emb, emb), i, chunk)
            for i, (emb, chunk) in enumerate(zip(self.embeddings, self.chunks))
            if emb  # Skip empty embeddings
        ]
        
        scores.sort(reverse=True, key=lambda x: x[0])
        return [(idx, chunk, score) for score, idx, chunk in scores[:top_k]]

    def clear_cache(self):
        """Clear all cached embeddings."""
        import shutil
        if CACHE_DIR.exists():
            shutil.rmtree(CACHE_DIR)
            CACHE_DIR.mkdir(exist_ok=True, parents=True)