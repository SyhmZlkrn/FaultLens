"""Embed the manual and incident history for search.

    python -m scripts.build_index

Manual sections are split on '## [MAN-xx] Title' headings.
Incidents come from data/knowledge/incidents.jsonl, one record per line.
"""
from __future__ import annotations

import json
import re

import numpy as np

from app import config

HEADING = re.compile(r"^## \[(?P<id>[A-Z]+-\d+)\]\s*(?P<title>.+)$", re.M)


def manual_chunks() -> list[dict]:
    chunks = []
    for path in sorted(config.KNOWLEDGE_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        matches = list(HEADING.finditer(text))
        for i, m in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body = text[m.end():end].strip()
            chunks.append({"id": m["id"], "source": "manual", "title": m["title"].strip(), "text": body})
    return chunks


def incident_chunks() -> list[dict]:
    chunks = []
    path = config.KNOWLEDGE_DIR / "incidents.jsonl"
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        text = (f"Asset {r['asset']} on {r['date']}. Symptoms: {r['symptoms']} "
                f"Root cause: {r['root_cause']} Actions: {r['actions']} "
                f"Downtime: {r['downtime_hours']} h. Outcome: {r['outcome']}")
        chunks.append({"id": r["id"], "source": "incident", "title": r["title"], "text": text})
    return chunks


def main():
    import torch
    from sentence_transformers import SentenceTransformer

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print("Embedding on:", torch.cuda.get_device_name(0) if device == "cuda" else "CPU")
    chunks = manual_chunks() + incident_chunks()
    model = SentenceTransformer(config.EMBED_MODEL, device=device)
    emb = model.encode([f"{c['title']}. {c['text']}" for c in chunks],
                       normalize_embeddings=True, batch_size=64, show_progress_bar=True)
    config.ARTIFACTS.mkdir(exist_ok=True)
    np.savez(config.INDEX_PATH, embeddings=emb.astype(np.float32))
    with open(config.CHUNKS_PATH, "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c) + "\n")
    print(f"Indexed {len(chunks)} chunks -> {config.INDEX_PATH}")


if __name__ == "__main__":
    main()
