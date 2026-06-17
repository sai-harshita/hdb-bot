import os
import re

import httpx
from qdrant_client import QdrantClient

OLLAMA = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
COLLECTION = os.getenv("QDRANT_COLLECTION", "hdb_docs")
TOP_K = int(os.getenv("TOP_K", "4"))
TOKEN_RE = re.compile(r"[a-z0-9]+")

qdrant = QdrantClient(url=QDRANT_URL)


def embed(text: str) -> list[float]:
    r = httpx.post(
        f"{OLLAMA}/api/embeddings",
        json={"model": EMBED_MODEL, "prompt": text},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["embedding"]


def _tokenize(text: str) -> set[str]:
    return set(TOKEN_RE.findall((text or "").lower()))


def _topic_boost(query: str, source: str) -> float:
    low_query = query.lower()
    low_source = source.lower()
    boost = 0.0
    asks_eligibility = any(term in low_query for term in ["eligible", "eligibility", "who can buy"])
    asks_priority = any(term in low_query for term in ["priority", "scheme", "ballot", "first-timer"])

    if any(term in low_query for term in ["family", "families", "married", "spouse", "parent"]):
        if "couples-and-families" in low_source:
            boost += 0.35 if asks_eligibility else 0.25

    if any(term in low_query for term in ["bto", "new flat", "sbf", "ballot"]):
        if "bto-sbf-and-open-booking-of-flats" in low_source:
            boost += 0.20

    if "priority-schemes" in low_source:
        if asks_priority:
            boost += 0.20
        elif asks_eligibility:
            boost -= 0.15

    if any(term in low_query for term in ["grant", "grants"]):
        if "grant" in low_source:
            boost += 0.20

    if any(term in low_query for term in ["loan", "hfe", "financing"]):
        if "housing-loan" in low_source or "hfe" in low_source:
            boost += 0.20

    if any(term in low_query for term in ["single", "singles"]):
        if "/singles" in low_source:
            boost += 0.25

    if any(term in low_query for term in ["rent", "rental", "tenant"]):
        if "renting" in low_source or "public-rental-scheme" in low_source:
            boost += 0.20

    if "resale" in low_query and "resale" in low_source:
        boost += 0.20

    if any(term in low_query for term in ["renovation", "contractor", "building works"]):
        if "renovation" in low_source:
            boost += 0.20

    if low_source.endswith(".pdf"):
        boost -= 0.05

    return boost


def retrieve(query: str, top_k: int = TOP_K) -> list[dict]:
    vec = embed(query)
    hits = qdrant.search(collection_name=COLLECTION, query_vector=vec, limit=max(top_k * 4, 12))
    query_tokens = _tokenize(query)
    candidates = []
    for hit in hits:
        text = hit.payload.get("text", "")
        source = hit.payload.get("source", "")
        doc_tokens = _tokenize(f"{source} {text}")
        lexical_overlap = len(query_tokens & doc_tokens) * 0.015
        hybrid_score = hit.score + lexical_overlap + _topic_boost(query, source)
        candidates.append(
            {
                "text": text,
                "source": source,
                "score": hit.score,
                "hybrid_score": hybrid_score,
            }
        )

    candidates.sort(key=lambda item: item["hybrid_score"], reverse=True)

    selected = []
    source_counts: dict[str, int] = {}
    max_per_source = 1 if top_k <= 4 else 2

    for candidate in candidates:
        source = candidate["source"]
        if source_counts.get(source, 0) >= max_per_source:
            continue
        selected.append(candidate)
        source_counts[source] = source_counts.get(source, 0) + 1
        if len(selected) == top_k:
            return selected

    for candidate in candidates:
        if candidate in selected:
            continue
        selected.append(candidate)
        if len(selected) == top_k:
            break

    return selected


def format_context(chunks: list[dict]) -> str:
    # This string is fed to NeMo as relevant_chunks for grounding + fact check
    return "\n\n".join(f"[Source: {c['source']}]\n{c['text']}" for c in chunks)
