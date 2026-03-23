"""
Generate embeddings for text chunks using Ollama nomic-embed-text (768-dim).
"""
import logging
import os
import uuid
from typing import Any

import httpx

logger = logging.getLogger(__name__)

OLLAMA_URL   = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
EMBED_MODEL  = os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")


async def embed_text(text: str) -> list[float]:
    """Return a 768-dim embedding vector for the given text."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{OLLAMA_URL}/api/embeddings",
            json={"model": EMBED_MODEL, "prompt": text},
        )
        resp.raise_for_status()
        return resp.json()["embedding"]


async def embed_chunks(
    chunks: list[dict[str, Any]],
    qdrant_client,
    collection: str,
) -> None:
    """
    Embed all chunks and upsert into Qdrant.
    Each Qdrant point payload mirrors the chunk dict minus the text vector.
    """
    from qdrant_client.models import PointStruct

    points: list[PointStruct] = []

    for chunk in chunks:
        try:
            vector = await embed_text(chunk["text"])
        except Exception as e:
            logger.warning("Embedding failed for chunk: %s", e)
            continue

        point = PointStruct(
            id=str(uuid.uuid4()),
            vector=vector,
            payload={
                "statement_id":    chunk["statement_id"],
                "chunk_type":      chunk["chunk_type"],
                "period_start":    chunk["period_start"],
                "period_end":      chunk["period_end"],
                "text":            chunk["text"],
                "transaction_ids": chunk["transaction_ids"],
            },
        )
        points.append(point)

    if points:
        await qdrant_client.upsert(collection_name=collection, points=points)
        logger.info("Upserted %d chunks into Qdrant collection '%s'", len(points), collection)
