import ollama

EMBED_MODEL = "nomic-embed-text"

class EmbeddingModel:
    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for t in texts:
            res = ollama.embeddings(
                model=EMBED_MODEL,
                prompt=t
            )
            vectors.append(res["embedding"])
        return vectors