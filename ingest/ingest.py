import os
import tempfile
import uuid

import httpx
from bs4 import BeautifulSoup
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

OLLAMA = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
COLLECTION = os.getenv("QDRANT_COLLECTION", "hdb_docs")
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/137.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-SG,en;q=0.9",
    "Referer": "https://www.google.com/",
    "Cache-Control": "no-cache",
}

splitter = RecursiveCharacterTextSplitter(chunk_size=900, chunk_overlap=120)
qdrant = QdrantClient(url=QDRANT_URL)


def fetch_text(url: str) -> str:
    r = httpx.get(url, timeout=60, follow_redirects=True, headers=REQUEST_HEADERS)
    r.raise_for_status()
    if url.lower().endswith(".pdf") or "application/pdf" in r.headers.get("content-type", ""):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
            handle.write(r.content)
            path = handle.name
        try:
            reader = PdfReader(path)
            return "\n".join((p.extract_text() or "") for p in reader.pages)
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    return soup.get_text(separator=" ", strip=True)


def embed(text: str) -> list[float]:
    r = httpx.post(f"{OLLAMA}/api/embeddings",
                   json={"model": EMBED_MODEL, "prompt": text}, timeout=120)
    r.raise_for_status()
    return r.json()["embedding"]


def main() -> None:
    with open(os.path.join(os.path.dirname(__file__), "sources.txt")) as f:
        urls = [u.strip() for u in f if u.strip() and not u.startswith("#")]

    dim = len(embed("dimension probe"))
    qdrant.recreate_collection(
        collection_name=COLLECTION,
        vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
    )

    points = []
    for url in urls:
        try:
            text = fetch_text(url)
        except Exception as e:  # noqa: BLE001
            print(f"skip {url}: {e}")
            continue
        chunks = splitter.split_text(text)
        print(f"{url} -> {len(chunks)} chunks")
        for chunk in chunks:
            points.append(
                PointStruct(
                    id=str(uuid.uuid4()),
                    vector=embed(chunk),
                    payload={"text": chunk, "source": url},
                )
            )
    if points:
        qdrant.upsert(collection_name=COLLECTION, points=points)
    print(f"ingested {len(points)} chunks into {COLLECTION}")


if __name__ == "__main__":
    main()
