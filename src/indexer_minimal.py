# src/indexer_minimal.py
"""
Minimal indexer using SentenceTransformers + chromadb (no llama-index).
- Builds a persistent Chroma collection from data/products/*.json
- Provides: build_index(), semantic_search(), upsert_product_file()
"""

import json
from pathlib import Path
from sentence_transformers import SentenceTransformer
import chromadb
import numpy as np

# paths
BASE_DIR = Path(__file__).resolve().parent.parent
PRODUCTS_DIR = BASE_DIR / "data" / "products"
CHROMA_DIR = BASE_DIR / "chroma_db_minimal"

# init embedding model
embed_model = SentenceTransformer("all-MiniLM-L6-v2")

# Persistent chroma client
chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))

COLLECTION_NAME = "products_minimal"
try:
    collection = chroma_client.get_collection(COLLECTION_NAME)
except Exception:
    collection = chroma_client.create_collection(name=COLLECTION_NAME)

def _build_text_from_json(data: dict) -> str:
    title = data.get("name", "") or data.get("title", "") or ""
    desc = data.get("description", "") or ""
    reviews = data.get("reviews", []) or []
    price = ""
    try:
        price = data.get("offers", {}).get("price") or data.get("price") or ""
    except Exception:
        price = ""
    url = data.get("source_url", "") or ""
    text = f"TITLE: {title}\n\nDESCRIPTION: {desc}\n\nPRICE: {price}\n\nREVIEWS:\n" + "\n".join(reviews) + f"\n\nURL: {url}"
    return text.strip()

def build_index():
    ids, metadatas, documents, embeddings = [], [], [], []
    for jfile in PRODUCTS_DIR.glob("*.json"):
        try:
            data = json.loads(jfile.read_text(encoding="utf-8"))
        except Exception:
            continue
        pid = jfile.stem
        text = _build_text_from_json(data)
        emb = embed_model.encode(text, convert_to_numpy=True).tolist()
        ids.append(pid)
        metadatas.append({"url": data.get("source_url",""), "title": data.get("name","")})
        documents.append(text)
        embeddings.append(emb)

    if ids:
        collection.upsert(ids=ids, metadatas=metadatas, documents=documents, embeddings=embeddings)
    print(f"[indexer_minimal] Indexed {len(ids)} documents into Chroma collection '{COLLECTION_NAME}'.")

def semantic_search(query: str, top_k: int = 5):
    qemb = embed_model.encode(query, convert_to_numpy=True).tolist()
    result = collection.query(query_embeddings=[qemb], n_results=top_k, include=["documents","metadatas","distances"])
    items = []
    docs = result.get("documents", [[]])[0]
    metas = result.get("metadatas", [[]])[0]
    dists = result.get("distances", [[]])[0]
    for doc, meta, dist in zip(docs, metas, dists):
        items.append({"document": doc, "metadata": meta, "distance": dist})
    return items

def upsert_product_file(json_path: Path):
    """
    Upsert one product JSON file into the chroma collection.
    This function reads the JSON, builds a text and embedding, then upserts with id=json filename stem.
    """
    if isinstance(json_path, str):
        json_path = Path(json_path)
    if not json_path.exists():
        raise FileNotFoundError(f"{json_path} not found")

    data = json.loads(json_path.read_text(encoding="utf-8"))
    pid = json_path.stem
    text = _build_text_from_json(data)
    emb = embed_model.encode(text, convert_to_numpy=True).tolist()
    meta = {"url": data.get("source_url",""), "title": data.get("name","")}
    collection.upsert(ids=[pid], metadatas=[meta], documents=[text], embeddings=[emb])
    print(f"[indexer_minimal] Upserted {pid} into collection '{COLLECTION_NAME}'.")

if __name__ == "__main__":
    # convenience: build all
    build_index()
    print("Test search result:")
    res = semantic_search("good headphones for commuting", top_k=3)
    for i,r in enumerate(res,1):
        print(i, "title:", r["metadata"].get("title"), "dist:", r["distance"])
