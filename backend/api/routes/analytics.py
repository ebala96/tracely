"""
Pre-aggregated analytics endpoints — no LLM involved.

GET /api/analytics/monthly    — monthly debit/credit totals
GET /api/analytics/categories — per-category spend totals
GET /api/analytics/merchants  — top merchants by spend
GET /api/analytics/timeline   — daily spend for a specific merchant
GET /api/analytics/recurring  — detect recurring/subscription transactions
"""
import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select, func, text
from sqlalchemy.orm import selectinload

from db.models import Transaction, Category
from db.postgres import AsyncSessionLocal
from schemas.models import MonthlyStats, CategoryStats, MerchantStats, TimelinePoint


class RecurringTransaction(BaseModel):
    merchant:      str
    frequency:     str        # "monthly" | "weekly" | "irregular"
    avg_amount:    float
    occurrences:   int
    last_date:     date
    next_expected: Optional[date] = None

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/summary")
async def summary(statement_id: Optional[uuid.UUID] = None):
    """
    Returns debit/credit totals and transaction count for this period and last period.
    - No statement_id: uses current calendar month vs previous calendar month.
    - With statement_id: uses the statement's period_end month as reference,
      so the cards always reflect the statement you're looking at.
    """
    from datetime import date, timedelta
    from db.models import Statement as StatementModel

    async with AsyncSessionLocal() as session:
        # Determine reference date: end of statement period, or today
        ref_date = date.today()
        if statement_id:
            stmt_row = await session.get(StatementModel, statement_id)
            if stmt_row and stmt_row.period_end:
                ref_date = stmt_row.period_end

        this_start = ref_date.replace(day=1)
        last_end   = this_start - timedelta(days=1)
        last_start = last_end.replace(day=1)

        async def _period_stats(start: date, end: date) -> dict:
            q = """
                SELECT
                    SUM(CASE WHEN txn_type = 'debit'  THEN amount ELSE 0 END),
                    SUM(CASE WHEN txn_type = 'credit' THEN amount ELSE 0 END),
                    COUNT(*)
                FROM transactions
                WHERE date BETWEEN :start AND :end
                  {stmt_filter}
            """
            params: dict = {"start": start, "end": end}
            stmt_filter = "AND statement_id = :statement_id" if statement_id else ""
            if statement_id:
                params["statement_id"] = str(statement_id)
            row = (await session.execute(text(q.format(stmt_filter=stmt_filter)), params)).fetchone()
            return {
                "debit":  float(row[0] or 0),
                "credit": float(row[1] or 0),
                "count":  int(row[2] or 0),
            }

        this_period = await _period_stats(this_start, ref_date)
        last_period = await _period_stats(last_start, last_end)

    change_pct = None
    if last_period["debit"] > 0:
        change_pct = round(
            (this_period["debit"] - last_period["debit"]) / last_period["debit"] * 100, 1
        )

    savings = this_period["credit"] - this_period["debit"]
    savings_rate = round(savings / this_period["credit"] * 100, 1) if this_period["credit"] > 0 else None

    return {
        "this_month":   this_period,
        "last_month":   last_period,
        "change_pct":   change_pct,
        "savings":      round(savings, 2),
        "savings_rate": savings_rate,
        "period_label": this_start.strftime("%b %Y"),
        "prev_label":   last_start.strftime("%b %Y"),
    }


@router.get("/monthly", response_model=list[MonthlyStats])
async def monthly(
    year:         Optional[int]       = None,
    statement_id: Optional[uuid.UUID] = None,
):
    async with AsyncSessionLocal() as session:
        q = """
            SELECT
                TO_CHAR(date, 'Mon') AS month,
                EXTRACT(MONTH FROM date) AS month_num,
                SUM(CASE WHEN txn_type = 'debit'  THEN amount ELSE 0 END) AS total_debit,
                SUM(CASE WHEN txn_type = 'credit' THEN amount ELSE 0 END) AS total_credit
            FROM transactions
            WHERE 1=1
              {year_filter}
              {stmt_filter}
            GROUP BY TO_CHAR(date, 'Mon'), EXTRACT(MONTH FROM date)
            ORDER BY month_num
        """
        params: dict = {}
        year_filter = "AND EXTRACT(YEAR FROM date) = :year" if year else ""
        stmt_filter = "AND statement_id = :statement_id" if statement_id else ""
        if year:
            params["year"] = year
        if statement_id:
            params["statement_id"] = str(statement_id)

        rows = (await session.execute(
            text(q.format(year_filter=year_filter, stmt_filter=stmt_filter)),
            params,
        )).fetchall()

    return [
        MonthlyStats(month=r[0], total_debit=r[2] or 0, total_credit=r[3] or 0)
        for r in rows
    ]


@router.get("/categories", response_model=list[CategoryStats])
async def categories(
    date_from:    Optional[str]       = None,
    date_to:      Optional[str]       = None,
    statement_id: Optional[uuid.UUID] = None,
    txn_type:     Optional[str]       = Query("debit", pattern="^(debit|credit)$"),
):
    async with AsyncSessionLocal() as session:
        q = select(
            Category.name,
            Category.slug,
            Category.colour,
            Category.icon,
            func.sum(Transaction.amount).label("total"),
            func.count(Transaction.id).label("count"),
        ).join(Transaction, Transaction.category_id == Category.id)\
         .where(Transaction.txn_type == txn_type)

        if date_from:
            q = q.where(Transaction.date >= date_from)
        if date_to:
            q = q.where(Transaction.date <= date_to)
        if statement_id:
            q = q.where(Transaction.statement_id == statement_id)

        q = q.group_by(Category.name, Category.slug, Category.colour, Category.icon)\
             .order_by(func.sum(Transaction.amount).desc())
        rows = (await session.execute(q)).fetchall()

    return [
        CategoryStats(
            category=r[0], slug=r[1], colour=r[2] or "#9CA3AF",
            icon=r[3] or "📦", total=r[4] or 0, count=r[5],
        )
        for r in rows
    ]


@router.get("/merchants", response_model=list[MerchantStats])
async def merchants(
    limit:        int                 = Query(10, ge=1, le=50),
    statement_id: Optional[uuid.UUID] = None,
):
    async with AsyncSessionLocal() as session:
        q = select(
            Transaction.merchant,
            func.sum(Transaction.amount).label("total"),
            func.count(Transaction.id).label("count"),
        ).where(
            Transaction.txn_type == "debit",
            Transaction.merchant.isnot(None),
        )

        if statement_id:
            q = q.where(Transaction.statement_id == statement_id)

        q = q.group_by(Transaction.merchant)\
             .order_by(func.sum(Transaction.amount).desc())\
             .limit(limit)
        rows = (await session.execute(q)).fetchall()

    return [MerchantStats(merchant=r[0], total=r[1] or 0, count=r[2]) for r in rows]


@router.get("/timeline", response_model=list[TimelinePoint])
async def timeline(
    merchant:     str,
    statement_id: Optional[uuid.UUID] = None,
):
    async with AsyncSessionLocal() as session:
        q = select(
            Transaction.date,
            func.sum(Transaction.amount).label("amount"),
        ).where(
            Transaction.txn_type == "debit",
            Transaction.merchant.ilike(f"%{merchant}%"),
        )

        if statement_id:
            q = q.where(Transaction.statement_id == statement_id)

        q = q.group_by(Transaction.date).order_by(Transaction.date)
        rows = (await session.execute(q)).fetchall()

    return [TimelinePoint(date=r[0], amount=r[1] or 0) for r in rows]


@router.get("/recurring", response_model=list[RecurringTransaction])
async def recurring(statement_id: Optional[uuid.UUID] = None):
    """
    Detect recurring transactions — merchants that appear 2+ times
    at roughly consistent intervals (monthly ±5 days, weekly ±2 days).
    """
    from datetime import timedelta

    async with AsyncSessionLocal() as session:
        q = select(
            Transaction.merchant,
            Transaction.date,
            Transaction.amount,
        ).where(
            Transaction.txn_type == "debit",
            Transaction.merchant.isnot(None),
        )
        if statement_id:
            q = q.where(Transaction.statement_id == statement_id)
        q = q.order_by(Transaction.merchant, Transaction.date)
        rows = (await session.execute(q)).fetchall()

    # Group by merchant
    from collections import defaultdict
    by_merchant: dict[str, list] = defaultdict(list)
    for merchant, txn_date, amount in rows:
        by_merchant[merchant].append((txn_date, amount))

    results: list[RecurringTransaction] = []
    today = date.today()

    for merchant, entries in by_merchant.items():
        if len(entries) < 2:
            continue

        dates   = [e[0] for e in entries]
        amounts = [e[1] for e in entries]

        # Calculate gaps between consecutive occurrences
        gaps = [(dates[i+1] - dates[i]).days for i in range(len(dates) - 1)]
        avg_gap = sum(gaps) / len(gaps)
        avg_amt = sum(amounts) / len(amounts)

        if 25 <= avg_gap <= 35:
            frequency = "monthly"
            next_exp  = dates[-1] + timedelta(days=30)
        elif 5 <= avg_gap <= 9:
            frequency = "weekly"
            next_exp  = dates[-1] + timedelta(days=7)
        elif len(entries) >= 3 and max(gaps) - min(gaps) <= 10:
            frequency = "irregular"
            next_exp  = dates[-1] + timedelta(days=int(avg_gap))
        else:
            continue  # Not regular enough

        results.append(RecurringTransaction(
            merchant      = merchant,
            frequency     = frequency,
            avg_amount    = round(avg_amt, 2),
            occurrences   = len(entries),
            last_date     = dates[-1],
            next_expected = next_exp if next_exp > today else None,
        ))

    # Sort: monthly first, then by avg amount desc
    order = {"monthly": 0, "weekly": 1, "irregular": 2}
    results.sort(key=lambda r: (order[r.frequency], -r.avg_amount))
    return results
