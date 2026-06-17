import json
import os

import httpx
from datasets import Dataset
from langchain_ollama import ChatOllama, OllamaEmbeddings
from ragas import evaluate
from ragas.metrics import answer_relevancy, context_precision, faithfulness

OLLAMA = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
API = os.getenv("API_URL", "http://localhost:8000")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:3b")

judge = ChatOllama(model=LLM_MODEL, base_url=OLLAMA, temperature=0)
judge_emb = OllamaEmbeddings(model=EMBED_MODEL, base_url=OLLAMA)


def get_token() -> str:
    r = httpx.post(f"{API}/auth/token",
                   data={"username": os.getenv("DEMO_USER", "demo"),
                         "password": os.getenv("DEMO_PASSWORD", "demo12345")})
    return r.json()["access_token"]


def ask(token: str, q: str) -> dict:
    r = httpx.post(f"{API}/chat", json={"message": q},
                   headers={"Authorization": f"Bearer {token}"}, timeout=120)
    return r.json()


def main() -> None:
    with open(os.path.join(os.path.dirname(__file__), "eval_set.json")) as f:
        gold = json.load(f)

    token = get_token()
    rows = {"question": [], "answer": [], "contexts": [], "ground_truth": []}
    for item in gold:
        resp = ask(token, item["question"])
        rows["question"].append(item["question"])
        rows["answer"].append(resp["answer"])
        rows["contexts"].append(resp.get("sources", []) or ["no context"])
        rows["ground_truth"].append(item["ground_truth"])

    ds = Dataset.from_dict(rows)
    result = evaluate(
        ds,
        metrics=[faithfulness, answer_relevancy, context_precision],
        llm=judge,
        embeddings=judge_emb,
    )
    print(result)
    os.makedirs("ragas_results", exist_ok=True)
    result.to_pandas().to_csv("ragas_results/scores.csv", index=False)


if __name__ == "__main__":
    main()
