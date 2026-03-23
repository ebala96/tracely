"""
POST /api/query        — natural language question → RAG answer.
POST /api/query/stream — same but streams tokens via SSE.
POST /api/query/cache/clear — flush all cached query results.
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from db.redis_client import get_redis
from rag import query_engine
from rag.query_engine import answer
from schemas.models import QueryRequest, QueryResponse

router = APIRouter(prefix="/api", tags=["query"])


@router.post("/query", response_model=QueryResponse)
async def query(request: QueryRequest):
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    statement_ids = (
        [str(sid) for sid in request.statement_ids]
        if request.statement_ids else None
    )

    result = await answer(request.question, statement_ids)
    return QueryResponse(
        answer   = result["answer"],
        sources  = result.get("sources", []),
        sql_used = result.get("sql_used"),
    )


@router.post("/query/stream")
async def query_stream(request: QueryRequest):
    """Stream LLM tokens via Server-Sent Events as they are generated."""
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    statement_ids = (
        [str(sid) for sid in request.statement_ids]
        if request.statement_ids else None
    )

    return StreamingResponse(
        query_engine.stream_answer(request.question, statement_ids),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/query/cache/clear")
async def clear_query_cache():
    """Flush all cached RAG query results from Redis."""
    redis = await get_redis()
    keys = await redis.keys("query:*")
    if keys:
        await redis.delete(*keys)
    return {"cleared": len(keys)}
