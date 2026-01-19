# rag.py
import os
import math
import json
import pickle
import numpy as np
import ollama

EMBED_MODEL = "nomic-embed-text"

def cosine_similarity(a, b):
    dot = sum(x*y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x*x for x in a))
    norm_b = math.sqrt(sum(x*x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)

class RAGPipeline:
    def __init__(self, chunk_size=500, overlap=100, top_k=5, cache_file="rag_cache.pkl"):
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.top_k = top_k
        self.chunks = []
        self.embeddings = []
        self.cache_file = cache_file
        self.index_built = False

        # Load from cache if exists
        if os.path.exists(self.cache_file):
            with open(self.cache_file, "rb") as f:
                cache = pickle.load(f)
                self.chunks = cache["chunks"]
                self.embeddings = cache["embeddings"]
                self.index_built = True

    def chunk_text(self, text: str):
        words = text.split()
        chunks = []
        i = 0
        while i < len(words):
            chunk = " ".join(words[i:i+self.chunk_size])
            chunks.append(chunk)
            i += self.chunk_size - self.overlap
        return chunks

    def embed_text(self, text: str):
        res = ollama.embeddings(model=EMBED_MODEL, prompt=text)
        return res["embedding"]

    def ingest(self, document_text: str, save_cache=True):
        # Chunk only if not loaded from cache
        if not self.index_built:
            self.chunks = self.chunk_text(document_text)
            self.embeddings = [self.embed_text(c) for c in self.chunks]
            self.index_built = True
            if save_cache:
                with open(self.cache_file, "wb") as f:
                    pickle.dump({"chunks": self.chunks, "embeddings": self.embeddings}, f)

    def retrieve(self, query: str, top_k=None, debug=False):
        if top_k is None:
            top_k = self.top_k
        query_emb = self.embed_text(query)

        scores = [
            (cosine_similarity(query_emb, emb), chunk)
            for emb, chunk in zip(self.embeddings, self.chunks)
        ]
        scores.sort(reverse=True, key=lambda x: x[0])

        if debug:
            print("Top retrieved chunk scores:")
            for score, chunk in scores[:top_k]:
                print(f"{score:.4f}: {chunk[:100]}...")

        return [chunk for _, chunk in scores[:top_k]]