import os

import httpx
from mcp.server.fastmcp import FastMCP
from qdrant_client import QdrantClient

OLLAMA = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
COLLECTION = os.getenv("QDRANT_COLLECTION", "hdb_docs")

qdrant = QdrantClient(url=QDRANT_URL)
mcp = FastMCP("hdb-tools", host="0.0.0.0", port=9000)


def _embed(text: str) -> list[float]:
    r = httpx.post(f"{OLLAMA}/api/embeddings",
                   json={"model": EMBED_MODEL, "prompt": text}, timeout=60)
    r.raise_for_status()
    return r.json()["embedding"]


@mcp.tool()
def search_hdb_docs(query: str, top_k: int = 4) -> list[dict]:
    """Search official HDB documents and return relevant passages with sources."""
    hits = qdrant.search(collection_name=COLLECTION, query_vector=_embed(query), limit=top_k)
    return [{"text": h.payload.get("text", ""), "source": h.payload.get("source", "")} for h in hits]


@mcp.tool()
def list_hdb_topics() -> list[str]:
    """Return the HDB topics this assistant can help with."""
    return ["BTO flats", "resale flats", "eligibility", "grants", "HDB loans",
            "renting a flat", "HDB services and appointments"]


if __name__ == "__main__":
    mcp.run(transport="sse")
