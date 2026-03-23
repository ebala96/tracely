"""
GET   /api/transactions                — paginated, filterable transaction list
GET   /api/transactions/{id}           — single transaction
PATCH /api/transactions/{id}/category  — update category + learn pattern
POST  /api/transactions/recategorize   — backfill categories for all uncategorized transactions
"""
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from db.models import Transaction, Category
from db.postgres import AsyncSessionLocal
from ingestion.categoriser import load_taxonomy, categorise
from ingestion.rule_learner import save_rule, backfill_similar
from schemas.models import TransactionOut, TransactionListResponse

router = APIRouter(prefix="/api", tags=["transactions"])


class CategoryUpdateRequest(BaseModel):
    category_id:    Optional[int] = None
    subcategory_id: Optional[int] = None


class RecategorizeResponse(BaseModel):
    updated: int
    skipped: int


class BulkCategoryRequest(BaseModel):
    transaction_ids: list[uuid.UUID]
    category_id:     Optional[int] = None
    subcategory_id:  Optional[int] = None


@router.patch("/transactions/bulk-category")
async def bulk_update_category(body: BulkCategoryRequest):
    """Update category for multiple transactions at once."""
    if not body.transaction_ids:
        return {"updated": 0}

    from sqlalchemy import update as sql_update
    async with AsyncSessionLocal() as session:
        await session.execute(
            sql_update(Transaction)
            .where(Transaction.id.in_(body.transaction_ids))
            .values(
                category_id    = body.category_id,
                subcategory_id = body.subcategory_id,
                user_corrected = True,
            )
        )
        await session.commit()

    return {"updated": len(body.transaction_ids)}


@router.post("/transactions/recategorize", response_model=RecategorizeResponse)
async def recategorize_all():
    """
    Fast-path re-categorization of all non-user-corrected transactions using
    the YAML taxonomy keyword matching only (no LLM, no Redis needed).
    Safe to run multiple times — skips user-corrected rows.
    """
    taxonomy = load_taxonomy()

    async with AsyncSessionLocal() as session:
        # Build slug → id map
        cats = (await session.execute(select(Category))).scalars().all()
        slug_to_id = {c.slug: c.id for c in cats}

        # Load all non-user-corrected transactions
        txns = (await session.execute(
            select(Transaction).where(Transaction.user_corrected.is_not(True))
        )).scalars().all()

        updated = skipped = 0

        # Use only fast keyword matching — no async LLM calls needed
        # Use txn_type-specific lookups so income categories only match credits
        for txn in txns:
            combined = f"{(txn.merchant or '').lower()} {txn.description.lower()}".strip()
            is_income = txn.txn_type == "credit"

            sub_lookup    = taxonomy["income_sub"]    if is_income else taxonomy["sub"]
            parent_lookup = taxonomy["income_parent"] if is_income else taxonomy["parent"]

            parent_slug = sub_slug = None

            # Subcategory first
            for keyword, (p_slug, s_slug) in sub_lookup.items():
                if keyword in combined:
                    parent_slug, sub_slug = p_slug, s_slug
                    break

            # Parent keywords fallback
            if not parent_slug:
                for keyword, p_slug in parent_lookup.items():
                    if keyword in combined:
                        parent_slug = p_slug
                        break

            if not parent_slug:
                skipped += 1
                continue

            new_cat_id = slug_to_id.get(parent_slug)
            new_sub_id = slug_to_id.get(sub_slug) if sub_slug else None

            if txn.category_id != new_cat_id or txn.subcategory_id != new_sub_id:
                txn.category_id    = new_cat_id
                txn.subcategory_id = new_sub_id
                updated += 1
            else:
                skipped += 1

        await session.commit()

    # Bust query cache so chat reflects the new categories immediately
    from db.redis_client import get_redis
    redis = await get_redis()
    keys = await redis.keys("query:*")
    if keys:
        await redis.delete(*keys)

    return RecategorizeResponse(updated=updated, skipped=skipped)


@router.get("/transactions", response_model=TransactionListResponse)
async def list_transactions(
    page:          int            = Query(1, ge=1),
    page_size:     int            = Query(50, ge=1, le=200),
    statement_id:  Optional[uuid.UUID] = None,
    category_id:   Optional[int]  = None,
    category_slug: Optional[str]  = None,
    merchant:      Optional[str]  = None,
    txn_type:      Optional[str]  = None,
    date_from:     Optional[str]  = None,
    date_to:       Optional[str]  = None,
    min_amount:    Optional[float] = None,
    max_amount:    Optional[float] = None,
    sort_by:       str            = Query("date", pattern="^(date|amount|merchant)$"),
    sort_dir:      str            = Query("desc", pattern="^(asc|desc)$"),
):
    async with AsyncSessionLocal() as session:
        q = select(Transaction).options(
            selectinload(Transaction.category),
            selectinload(Transaction.subcategory),
        )

        if statement_id:
            q = q.where(Transaction.statement_id == statement_id)
        if category_id:
            q = q.where(Transaction.category_id == category_id)
        if category_slug:
            q = q.join(Transaction.category).where(Category.slug == category_slug)
        if merchant:
            q = q.where(Transaction.merchant.ilike(f"%{merchant}%"))
        if txn_type:
            q = q.where(Transaction.txn_type == txn_type)
        if date_from:
            q = q.where(Transaction.date >= date_from)
        if date_to:
            q = q.where(Transaction.date <= date_to)
        if min_amount is not None:
            q = q.where(Transaction.amount >= min_amount)
        if max_amount is not None:
            q = q.where(Transaction.amount <= max_amount)

        # Total count
        count_q = select(func.count()).select_from(q.subquery())
        total = (await session.execute(count_q)).scalar_one()

        # Sort
        col = getattr(Transaction, sort_by, Transaction.date)
        q = q.order_by(col.desc() if sort_dir == "desc" else col.asc())

        # Paginate
        q = q.offset((page - 1) * page_size).limit(page_size)
        items = (await session.execute(q)).scalars().all()

    return TransactionListResponse(
        items     = items,
        total     = total,
        page      = page,
        page_size = page_size,
    )


@router.get("/transactions/{transaction_id}", response_model=TransactionOut)
async def get_transaction(transaction_id: uuid.UUID):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Transaction)
            .options(selectinload(Transaction.category), selectinload(Transaction.subcategory))
            .where(Transaction.id == transaction_id)
        )
        txn = result.scalar_one_or_none()
        if not txn:
            raise HTTPException(status_code=404, detail="Transaction not found")
        return txn


@router.patch("/transactions/{transaction_id}/category", response_model=TransactionOut)
async def update_transaction_category(transaction_id: uuid.UUID, body: CategoryUpdateRequest):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Transaction)
            .options(selectinload(Transaction.category), selectinload(Transaction.subcategory))
            .where(Transaction.id == transaction_id)
        )
        txn = result.scalar_one_or_none()
        if not txn:
            raise HTTPException(status_code=404, detail="Transaction not found")

        txn.category_id    = body.category_id
        txn.subcategory_id = body.subcategory_id
        txn.user_corrected = True

        # Save the learned rule (backfill is triggered separately via /apply-pattern)
        if body.category_id is not None:
            await save_rule(
                session,
                merchant       = txn.merchant,
                description    = txn.description,
                category_id    = body.category_id,
                subcategory_id = body.subcategory_id,
            )

        await session.commit()

        result = await session.execute(
            select(Transaction)
            .options(selectinload(Transaction.category), selectinload(Transaction.subcategory))
            .where(Transaction.id == transaction_id)
        )
        return result.scalar_one()


class ApplyPatternResponse(BaseModel):
    updated: int
    pattern: str


@router.post("/transactions/{transaction_id}/apply-pattern", response_model=ApplyPatternResponse)
async def apply_pattern(transaction_id: uuid.UUID):
    """
    Apply the learned category pattern from this transaction to all similar
    non-user-corrected transactions in the database.
    The transaction must have been manually categorised first (user_corrected=True).
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Transaction).where(Transaction.id == transaction_id)
        )
        txn = result.scalar_one_or_none()
        if not txn:
            raise HTTPException(status_code=404, detail="Transaction not found")
        if not txn.user_corrected or txn.category_id is None:
            raise HTTPException(status_code=400, detail="Transaction has no user-set category to apply")

        updated = await backfill_similar(
            session,
            merchant       = txn.merchant,
            description    = txn.description,
            category_id    = txn.category_id,
            subcategory_id = txn.subcategory_id,
        )
        await session.commit()

    from ingestion.rule_learner import extract_pattern
    merchant_pat, desc_kw = extract_pattern(txn.merchant, txn.description)
    pattern_label = merchant_pat or desc_kw or txn.description[:30]

    return ApplyPatternResponse(updated=updated, pattern=pattern_label)
