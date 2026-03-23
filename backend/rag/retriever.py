"""
Qdrant vector search — embed the query, retrieve top-k matching chunks.
"""
import logging
import os
from typing import Optional

from db.qdrant_client import get_client as get_qdrant
from ingestion.embedder import embed_text

logger = logging.getLogger(__name__)

COLLECTION = os.environ.get("QDRANT_COLLECTION", "spendly_chunks")
DEFAULT_TOP_K = 5


async def search(
    query: str,
    top_k: int = DEFAULT_TOP_K,
    statement_ids: Optional[list[str]] = None,
) -> list[dict]:
    """
    Embed query, search Qdrant, return list of chunk payloads.
    Optionally filter by statement_ids.
    """
    vector = await embed_text(query)
    client = await get_qdrant()

    query_filter = None
    if statement_ids:
        from qdrant_client.models import Filter, FieldCondition, MatchAny
        query_filter = Filter(
            must=[
                FieldCondition(
                    key="statement_id",
                    match=MatchAny(any=statement_ids),
                )
            ]
        )

    results = await client.search(
        collection_name=COLLECTION,
        query_vector=vector,
        limit=top_k,
        query_filter=query_filter,
        with_payload=True,
    )

    chunks = []
    for hit in results:
        payload = hit.payload or {}
        payload["score"] = hit.score
        chunks.append(payload)

    return chunks
