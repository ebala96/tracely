"""
POST /api/upload  — receive a PDF, queue it for ingestion.
GET  /api/statements      — list all statements
GET  /api/statements/{id} — get one statement (used for polling status)
"""
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import nats
from fastapi import APIRouter, HTTPException, UploadFile, File
from sqlalchemy import select, delete

from db.models import Statement, StatementStatus, Transaction
from db.postgres import AsyncSessionLocal
from db.qdrant_client import get_client as get_qdrant, COLLECTION
from schemas.models import StatementOut, UploadResponse

router = APIRouter(prefix="/api", tags=["upload"])

UPLOAD_DIR  = Path(os.environ.get("UPLOAD_DIR", "/tmp/spendly_uploads"))
NATS_URL    = os.environ.get("NATS_URL", "nats://localhost:4222")
NATS_SUBJECT = os.environ.get("NATS_SUBJECT_INGEST", "spendly.ingest")


@router.post("/upload", response_model=UploadResponse)
async def upload_statement(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    statement_id = uuid.uuid4()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = UPLOAD_DIR / f"{statement_id}.pdf"

    # Save file to disk
    contents = await file.read()
    pdf_path.write_bytes(contents)

    # Create statement row
    async with AsyncSessionLocal() as session:
        stmt = Statement(
            id          = statement_id,
            filename    = file.filename,
            status      = StatementStatus.pending,
            uploaded_at = datetime.now(timezone.utc),
        )
        session.add(stmt)
        await session.commit()

    # Publish to NATS
    try:
        nc = await nats.connect(NATS_URL)
        js = nc.jetstream()
        payload = json.dumps({
            "statement_id": str(statement_id),
            "pdf_path":     str(pdf_path),
        }).encode()
        await js.publish(NATS_SUBJECT, payload)
        await nc.drain()
    except Exception as e:
        # Don't fail the upload if NATS is down — status stays pending
        # and can be retried manually
        pass

    return UploadResponse(statement_id=statement_id, status="pending")


@router.get("/statements", response_model=list[StatementOut])
async def list_statements():
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Statement).order_by(Statement.uploaded_at.desc())
        )
        return result.scalars().all()


@router.get("/statements/{statement_id}", response_model=StatementOut)
async def get_statement(statement_id: uuid.UUID):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Statement).where(Statement.id == statement_id)
        )
        stmt = result.scalar_one_or_none()
        if not stmt:
            raise HTTPException(status_code=404, detail="Statement not found")
        return stmt


@router.delete("/statements/{statement_id}", status_code=204)
async def delete_statement(statement_id: uuid.UUID):
    async with AsyncSessionLocal() as session:
        stmt = (await session.execute(
            select(Statement).where(Statement.id == statement_id)
        )).scalar_one_or_none()
        if not stmt:
            raise HTTPException(status_code=404, detail="Statement not found")

        # Delete transactions from Postgres
        await session.execute(delete(Transaction).where(Transaction.statement_id == statement_id))
        await session.delete(stmt)
        await session.commit()

    # Delete vectors from Qdrant
    try:
        qdrant = await get_qdrant()
        await qdrant.delete(
            collection_name=COLLECTION,
            points_selector={"filter": {"must": [{"key": "statement_id", "match": {"value": str(statement_id)}}]}},
        )
    except Exception:
        pass

    # Delete PDF from disk
    pdf_path = UPLOAD_DIR / f"{statement_id}.pdf"
    if pdf_path.exists():
        pdf_path.unlink()


@router.delete("/statements", status_code=204)
async def delete_all_statements():
    async with AsyncSessionLocal() as session:
        all_ids = (await session.execute(select(Statement.id))).scalars().all()
        await session.execute(delete(Transaction))
        await session.execute(delete(Statement))
        await session.commit()

    # Clear all Qdrant vectors
    try:
        qdrant = await get_qdrant()
        await qdrant.delete_collection(COLLECTION)
        from qdrant_client.models import Distance, VectorParams
        await qdrant.create_collection(
            collection_name=COLLECTION,
            vectors_config=VectorParams(size=768, distance=Distance.COSINE),
        )
    except Exception:
        pass

    # Delete all PDFs
    for pdf in UPLOAD_DIR.glob("*.pdf"):
        pdf.unlink(missing_ok=True)
