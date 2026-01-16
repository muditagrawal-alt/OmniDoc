import ollama
import math

EMBED_MODEL = "nomic-embed-text"

def cosine_similarity(a, b):
    dot = sum(x*y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x*x for x in a))
    norm_b = math.sqrt(sum(x*x for x in b))
    return dot / (norm_a * norm_b)


class RAGPipeline:
    def __init__(self, chunk_size=500, overlap=100):
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.chunks = []
        self.embeddings = []

    def chunk_text(self, text: str):
        words = text.split()
        chunks = []

        i = 0
        while i < len(words):
            chunk = words[i:i+self.chunk_size]
            chunks.append(" ".join(chunk))
            i += self.chunk_size - self.overlap

        return chunks

    def embed(self, text: str):
        response = ollama.embeddings(
            model=EMBED_MODEL,
            prompt=text
        )
        return response["embedding"]

    def ingest(self, document_text: str):
        self.chunks = self.chunk_text(document_text)
        self.embeddings = [self.embed(c) for c in self.chunks]

    def retrieve(self, query: str, top_k=5):
        query_emb = self.embed(query)

        scores = [
            (cosine_similarity(query_emb, emb), chunk)
            for emb, chunk in zip(self.embeddings, self.chunks)
        ]

        scores.sort(reverse=True, key=lambda x: x[0])
        return [chunk for _, chunk in scores[:top_k]]