"""Semantic embeddings for Fylgja.

Providers supported:
- Ollama (default): local HTTP API, e.g. nomic-embed-text
- sentence-transformers: local Python package, optional

Fylgja stores vectors alongside memories and uses cosine similarity for retrieval.
"""
from __future__ import annotations
import json, math, os, urllib.request
from config import cfg


def _norm(v):
    return math.sqrt(sum(x*x for x in v)) or 1.0


def cosine(a, b):
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x*y for x,y in zip(a,b)) / (_norm(a)*_norm(b))


def embed(text: str):
    # Environment variables win when set (useful for quick overrides); otherwise
    # config.json's "embedding" section is now the real source of truth.
    provider = os.getenv("FYLGJA_EMBEDDING_PROVIDER", cfg("embedding","provider",default="ollama")).lower()
    if provider == "ollama":
        url = os.getenv("FYLGJA_OLLAMA_URL", cfg("embedding","url",default="http://127.0.0.1:11434/api/embeddings"))
        model = os.getenv("FYLGJA_EMBEDDING_MODEL", cfg("embedding","model",default="nomic-embed-text"))
        payload = json.dumps({"model": model, "prompt": text}).encode()
        req = urllib.request.Request(url, data=payload, headers={"Content-Type":"application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode())
        return data["embedding"]
    if provider in {"sentence_transformers", "sentence-transformers"}:
        from sentence_transformers import SentenceTransformer
        model_name = os.getenv("FYLGJA_EMBEDDING_MODEL", cfg("embedding","model",default="all-MiniLM-L6-v2"))
        model = SentenceTransformer(model_name)
        return model.encode(text, normalize_embeddings=False).tolist()
    raise ValueError(f"Unknown embedding provider: {provider}")
