"""Search the manual and incident history. Embeddings are built on AMD GPU (amd/build_index.py)."""
from __future__ import annotations

import json

import numpy as np

from app import config


class Retriever:
    def __init__(self, index_path=config.INDEX_PATH, chunks_path=config.CHUNKS_PATH,
                 model_name: str = config.EMBED_MODEL, encoder=None):
        self.emb = np.load(index_path)["embeddings"]
        with open(chunks_path, encoding="utf-8") as f:
            self.chunks = [json.loads(line) for line in f]
        if encoder is None:
            from sentence_transformers import SentenceTransformer
            encoder = SentenceTransformer(model_name, device="cpu")
        self.encoder = encoder

    def search(self, query: str, k: int = 4, source: str | None = None) -> list[dict]:
        q = self.encoder.encode([query], normalize_embeddings=True)[0]
        scores = self.emb @ q
        hits = []
        for i in np.argsort(-scores):
            c = self.chunks[i]
            if source and c["source"] != source:
                continue
            hits.append({**c, "score": round(float(scores[i]), 3)})
            if len(hits) == k:
                break
        return hits
