import uuid
import enum
from datetime import datetime, timezone

from sqlalchemy import Column, String, Float, Date, DateTime, Integer, Text, Boolean, ForeignKey, Enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship, DeclarativeBase


class Base(DeclarativeBase):
    pass


class StatementStatus(str, enum.Enum):
    pending    = "pending"
    processing = "processing"
    done       = "done"
    failed     = "failed"


class Statement(Base):
    """One uploaded PDF bank statement."""
    __tablename__ = "statements"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename     = Column(String, nullable=False)
    bank_name    = Column(String)
    period_start = Column(Date)
    period_end   = Column(Date)
    status       = Column(Enum(StatementStatus), default=StatementStatus.pending)
    uploaded_at  = Column(DateTime(timezone=True))
    processed_at = Column(DateTime(timezone=True))
    error_msg    = Column(Text)

    transactions = relationship("Transaction", back_populates="statement")


class Category(Base):
    """Spending categories — top-level and subcategories (parent_id set for subs)."""
    __tablename__ = "categories"

    id        = Column(Integer, primary_key=True, autoincrement=True)
    name      = Column(String, unique=True, nullable=False)
    slug      = Column(String, unique=True, nullable=False)
    icon      = Column(String)
    colour    = Column(String)
    parent_id = Column(Integer, ForeignKey("categories.id"), nullable=True)

    parent       = relationship("Category", remote_side="Category.id", back_populates="subcategories")
    subcategories = relationship("Category", back_populates="parent")
    transactions = relationship("Transaction", foreign_keys="Transaction.category_id", back_populates="category")
    sub_transactions = relationship("Transaction", foreign_keys="Transaction.subcategory_id", back_populates="subcategory")


class Transaction(Base):
    """One normalised transaction row extracted from a statement."""
    __tablename__ = "transactions"

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    statement_id   = Column(UUID(as_uuid=True), ForeignKey("statements.id"), nullable=False)
    category_id    = Column(Integer, ForeignKey("categories.id"))     # parent category
    subcategory_id = Column(Integer, ForeignKey("categories.id"), nullable=True)  # leaf subcategory

    date           = Column(Date, nullable=False)
    description    = Column(Text, nullable=False)
    merchant       = Column(String)
    amount         = Column(Float, nullable=False)
    txn_type       = Column(String)        # "debit" | "credit"
    balance        = Column(Float)
    ref_number     = Column(String)
    raw_row        = Column(Text)
    user_corrected = Column(Boolean, default=False)  # True once user manually changed the category

    statement   = relationship("Statement", back_populates="transactions")
    category    = relationship("Category", foreign_keys=[category_id], back_populates="transactions")
    subcategory = relationship("Category", foreign_keys=[subcategory_id], back_populates="sub_transactions")


class UserCategoryRule(Base):
    """
    Learned pattern: when user manually recategorises a transaction,
    we extract a merchant/description pattern and save it here.
    Future ingestion checks these rules first before the default taxonomy.
    """
    __tablename__ = "user_category_rules"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    # What to match (at least one must be set)
    merchant_pattern    = Column(String, nullable=True, index=True)   # normalised merchant name
    description_keyword = Column(String, nullable=True, index=True)   # key token from description
    # What to assign
    category_id         = Column(Integer, ForeignKey("categories.id"), nullable=False)
    subcategory_id      = Column(Integer, ForeignKey("categories.id"), nullable=True)
    # Stats
    hit_count           = Column(Integer, default=1)
    created_at          = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at          = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    category    = relationship("Category", foreign_keys=[category_id])
    subcategory = relationship("Category", foreign_keys=[subcategory_id])
