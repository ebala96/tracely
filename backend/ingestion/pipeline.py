"""
Full ingestion pipeline for one PDF bank statement.
Called by the NATS worker after a PDF is uploaded.
"""
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.models import Statement, StatementStatus, Transaction, Category
from db.postgres import AsyncSessionLocal
from db.qdrant_client import get_client as get_qdrant
from db.redis_client import get_redis
from ingestion import pdf_parser, table_extractor, transaction_parser, chunker, embedder
from ingestion.categoriser import load_taxonomy, categorise
from rag.llm_client import chat as llm_chat

logger = logging.getLogger(__name__)

QDRANT_COLLECTION = os.environ.get("QDRANT_COLLECTION", "spendly_chunks")
CATEGORIES_FILE   = Path(__file__).parent.parent.parent / "categories.yml"


async def run(pdf_path: str, statement_id: str) -> None:
    """Orchestrate the full ingestion pipeline for one statement."""
    async with AsyncSessionLocal() as session:
        # --- Mark as processing ---
        stmt = await _get_statement(session, statement_id)
        stmt.status = StatementStatus.processing
        await session.commit()

        try:
            await _process(session, pdf_path, statement_id, stmt)
            stmt.status     = StatementStatus.done
            stmt.processed_at = datetime.now(timezone.utc)
        except Exception as e:
            logger.exception("Pipeline failed for statement %s", statement_id)
            stmt.status    = StatementStatus.failed
            stmt.error_msg = str(e)
        finally:
            await session.commit()


async def _process(session, pdf_path: str, statement_id: str, stmt: Statement) -> None:
    # Step 1 — Parse PDF
    logger.info("[%s] Step 1: Parsing PDF", statement_id)
    parsed = pdf_parser.parse(pdf_path)

    if parsed.bank_name:
        stmt.bank_name = parsed.bank_name
    if parsed.period_start:
        stmt.period_start = parsed.period_start
    if parsed.period_end:
        stmt.period_end = parsed.period_end
    await session.commit()

    # Step 2 — Extract tables
    logger.info("[%s] Step 2: Extracting tables", statement_id)
    dfs = table_extractor.extract(pdf_path)
    if not dfs:
        raise ValueError("No transaction tables found in PDF")

    # Step 3 — Parse transactions
    logger.info("[%s] Step 3: Parsing transactions (bank=%s)", statement_id, parsed.bank_name)
    raw_txns = transaction_parser.parse(dfs, statement_id, bank_name=parsed.bank_name)
    if not raw_txns:
        raise ValueError("No transactions parsed from tables")
    logger.info("[%s] Parsed %d transactions", statement_id, len(raw_txns))

    # Step 4 — Categorise
    logger.info("[%s] Step 4: Categorising", statement_id)
    taxonomy = load_taxonomy(CATEGORIES_FILE)
    redis    = await get_redis()

    # Build slug → id map
    result = await session.execute(select(Category))
    slug_to_id = {c.slug: c.id for c in result.scalars()}

    for txn in raw_txns:
        parent_slug, sub_slug = await categorise(
            txn["description"], taxonomy, redis, _LLMWrapper(),
            merchant=txn.get("merchant"), db_session=session,
            txn_type=txn.get("txn_type", "debit"),
        )
        txn["category_id"]    = slug_to_id.get(parent_slug)
        txn["subcategory_id"] = slug_to_id.get(sub_slug) if sub_slug else None

    # Step 5 — Persist transactions (ON CONFLICT DO NOTHING makes this idempotent)
    logger.info("[%s] Step 5: Persisting to Postgres", statement_id)
    rows = [
        {
            "id":             txn["id"],
            "statement_id":   statement_id,
            "category_id":    txn["category_id"],
            "subcategory_id": txn.get("subcategory_id"),
            "date":           txn["date"],
            "description":    txn["description"],
            "merchant":       txn["merchant"],
            "amount":         txn["amount"],
            "txn_type":       txn["txn_type"],
            "balance":        txn.get("balance"),
            "ref_number":     txn.get("ref_number"),
            "raw_row":        txn.get("raw_row"),
        }
        for txn in raw_txns
    ]
    await session.execute(
        pg_insert(Transaction).values(rows).on_conflict_do_nothing(index_elements=["id"])
    )
    await session.commit()

    # Update statement period from actual transaction dates if not found in header
    if not stmt.period_start:
        stmt.period_start = min(t["date"] for t in raw_txns)
    if not stmt.period_end:
        stmt.period_end   = max(t["date"] for t in raw_txns)
    await session.commit()

    # Step 6 — Chunk + Embed
    logger.info("[%s] Step 6: Chunking and embedding", statement_id)
    chunks = chunker.build_chunks(
        raw_txns,
        statement_id,
        period_start=stmt.period_start,
        period_end=stmt.period_end,
    )
    qdrant = await get_qdrant()
    await embedder.embed_chunks(chunks, qdrant, QDRANT_COLLECTION)

    logger.info("[%s] Pipeline complete — %d txns, %d chunks", statement_id, len(raw_txns), len(chunks))

    # Bust query cache so new data shows up in chat immediately
    try:
        redis = await get_redis()
        keys = await redis.keys("query:*")
        if keys:
            await redis.delete(*keys)
    except Exception:
        pass


async def _get_statement(session, statement_id: str) -> Statement:
    result = await session.execute(
        select(Statement).where(Statement.id == statement_id)
    )
    stmt = result.scalar_one_or_none()
    if not stmt:
        raise ValueError(f"Statement {statement_id} not found")
    return stmt


class _LLMWrapper:
    """Thin wrapper so categoriser can call llm_client.chat()."""
    async def chat(self, messages: list[dict]) -> str:
        return await llm_chat(messages)
