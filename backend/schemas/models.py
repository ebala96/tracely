from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Statement
# ---------------------------------------------------------------------------

class StatementOut(BaseModel):
    id: uuid.UUID
    filename: str
    bank_name: Optional[str]
    period_start: Optional[date]
    period_end: Optional[date]
    status: str
    uploaded_at: Optional[datetime]
    processed_at: Optional[datetime]
    error_msg: Optional[str]

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Category
# ---------------------------------------------------------------------------

class CategoryOut(BaseModel):
    id: int
    name: str
    slug: str
    icon: Optional[str]
    colour: Optional[str]
    parent_id: Optional[int] = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Transaction
# ---------------------------------------------------------------------------

class TransactionOut(BaseModel):
    id: uuid.UUID
    statement_id: uuid.UUID
    category_id: Optional[int]
    subcategory_id: Optional[int] = None
    category: Optional[CategoryOut] = None
    subcategory: Optional[CategoryOut] = None
    date: date
    description: str
    merchant: Optional[str]
    amount: float
    txn_type: str
    balance: Optional[float]
    ref_number: Optional[str]
    user_corrected: Optional[bool] = False

    model_config = {"from_attributes": True}


class TransactionListResponse(BaseModel):
    items: list[TransactionOut]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

class UploadResponse(BaseModel):
    statement_id: uuid.UUID
    status: str


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

class QueryRequest(BaseModel):
    question: str
    statement_ids: Optional[list[uuid.UUID]] = None


class QueryResponse(BaseModel):
    answer: str
    sources: list[str] = []
    sql_used: Optional[str] = None


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

class MonthlyStats(BaseModel):
    month: str
    total_debit: float
    total_credit: float


class CategoryStats(BaseModel):
    category: str
    slug: str
    colour: str
    icon: str
    total: float
    count: int


class MerchantStats(BaseModel):
    merchant: str
    total: float
    count: int


class TimelinePoint(BaseModel):
    date: date
    amount: float
