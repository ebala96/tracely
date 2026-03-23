import os

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, VectorParams

COLLECTION = os.environ.get("QDRANT_COLLECTION", "spendly_chunks")
_client: AsyncQdrantClient | None = None


async def get_client() -> AsyncQdrantClient:
    global _client
    if _client is None:
        _client = AsyncQdrantClient(url=os.environ["QDRANT_URL"])
        response = await _client.get_collections()
        existing = [c.name for c in response.collections]
        if COLLECTION not in existing:
            await _client.create_collection(
                collection_name=COLLECTION,
                vectors_config=VectorParams(size=768, distance=Distance.COSINE),
            )
    return _client
