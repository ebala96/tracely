import asyncio
import os

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, VectorParams

COLLECTION = os.environ.get("QDRANT_COLLECTION", "spendly_chunks")
_client: AsyncQdrantClient | None = None
_lock = asyncio.Lock()


async def get_client() -> AsyncQdrantClient:
    global _client
    if _client is not None:
        return _client
    async with _lock:
        if _client is None:
            client = AsyncQdrantClient(url=os.environ["QDRANT_URL"])
            response = await client.get_collections()
            existing = [c.name for c in response.collections]
            if COLLECTION not in existing:
                await client.create_collection(
                    collection_name=COLLECTION,
                    vectors_config=VectorParams(size=768, distance=Distance.COSINE),
                )
            _client = client
    return _client
