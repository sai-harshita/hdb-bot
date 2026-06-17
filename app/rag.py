import os

import httpx
from qdrant_client import QdrantClient

OLLAMA = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
COLLECTION = os.getenv("QDRANT_COLLECTION", "hdb_docs")
TOP_K = int(os.getenv("TOP_K", "4"))

qdrant = QdrantClient(url=QDRANT_URL)


def embed(text: str) -> list[float]:
    r = httpx.post(
        f"{OLLAMA}/api/embeddings",
        json={"model": EMBED_MODEL, "prompt": text},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["embedding"]


def retrieve(query: str, top_k: int = TOP_K) -> list[dict]:
    vec = embed(query)
    hits = qdrant.search(collection_name=COLLECTION, query_vector=vec, limit=top_k)
    return [
        {
            "text": h.payload.get("text", ""),
            "source": h.payload.get("source", ""),
            "score": h.score,
        }
        for h in hits
    ]


def format_context(chunks: list[dict]) -> str:
    # This string is fed to NeMo as relevant_chunks for grounding + fact check
    return "\n\n".join(f"[Source: {c['source']}]\n{c['text']}" for c in chunks)
