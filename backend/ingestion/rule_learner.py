"""
Learn category patterns from user corrections.

When a user manually changes a transaction's category:
  1. Extract a stable pattern from the merchant/description
  2. Upsert a UserCategoryRule with that pattern
  3. Backfill all similar non-user-corrected transactions in the DB
  4. Bust Redis cache keys for the affected pattern
"""
import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Transaction, UserCategoryRule

logger = logging.getLogger(__name__)

# Words that appear in bank descriptions but carry no merchant signal
_NOISE = {
    "upi", "neft", "imps", "rtgs", "transfer", "payment", "pay", "to", "from",
    "bank", "ac", "account", "ref", "no", "txn", "id", "dr", "cr", "via",
    "online", "pos", "atm", "ach", "nach", "auto", "debit", "credit", "chq",
    "cheque", "clearing", "mandate", "ecs", "si", "standing", "instruction",
    "mobile", "net", "banking", "utr", "the", "and", "for", "at",
}

_REF_PATTERN = re.compile(
    r"\b([A-Z]{2,}\d{6,}|\d{10,}|[A-Z0-9]{15,})\b"
)


def extract_pattern(merchant: Optional[str], description: str) -> tuple[Optional[str], Optional[str]]:
    """
    Returns (merchant_pattern, description_keyword).

    merchant_pattern   — normalised merchant name if meaningful
    description_keyword — most significant token from the description
    """
    merchant_pattern: Optional[str] = None
    description_keyword: Optional[str] = None

    # --- Merchant pattern ---
    if merchant:
        m = merchant.strip().lower()
        if len(m) >= 3 and m not in _NOISE:
            merchant_pattern = m

    # --- Description keyword ---
    # Strip reference numbers, then tokenise
    clean = _REF_PATTERN.sub(" ", description.lower())
    tokens = re.findall(r"\b[a-z][a-z0-9]{2,}\b", clean)
    meaningful = [t for t in tokens if t not in _NOISE]

    if meaningful:
        # Prefer the longest token — usually the merchant/service name
        description_keyword = max(meaningful, key=len)

    return merchant_pattern, description_keyword


async def save_rule(
    session: AsyncSession,
    merchant: Optional[str],
    description: str,
    category_id: int,
    subcategory_id: Optional[int],
) -> UserCategoryRule:
    """Upsert a UserCategoryRule for the extracted pattern."""
    merchant_pattern, description_keyword = extract_pattern(merchant, description)

    if not merchant_pattern and not description_keyword:
        logger.warning("No usable pattern for merchant=%r desc=%r — skipping rule", merchant, description)
        return None

    # Look for an existing rule with the same pattern
    q = select(UserCategoryRule)
    if merchant_pattern:
        q = q.where(UserCategoryRule.merchant_pattern == merchant_pattern)
    else:
        q = q.where(
            UserCategoryRule.merchant_pattern.is_(None),
            UserCategoryRule.description_keyword == description_keyword,
        )

    existing = (await session.execute(q)).scalar_one_or_none()

    if existing:
        existing.category_id    = category_id
        existing.subcategory_id = subcategory_id
        existing.hit_count      += 1
        existing.updated_at     = datetime.now(timezone.utc)
        logger.info("Updated rule id=%d pattern=%r→%r cat=%d", existing.id, merchant_pattern, description_keyword, category_id)
        return existing
    else:
        rule = UserCategoryRule(
            merchant_pattern    = merchant_pattern,
            description_keyword = description_keyword,
            category_id         = category_id,
            subcategory_id      = subcategory_id,
        )
        session.add(rule)
        await session.flush()
        logger.info("Created rule id=%d pattern=%r→%r cat=%d", rule.id, merchant_pattern, description_keyword, category_id)
        return rule


async def backfill_similar(
    session: AsyncSession,
    merchant: Optional[str],
    description: str,
    category_id: int,
    subcategory_id: Optional[int],
    redis=None,
) -> int:
    """
    Update all non-user-corrected transactions that match the same pattern.
    Returns the count of transactions updated.
    """
    merchant_pattern, description_keyword = extract_pattern(merchant, description)
    if not merchant_pattern and not description_keyword:
        return 0

    # Build filter — match on merchant OR description keyword
    from sqlalchemy import or_
    conditions = []
    if merchant_pattern:
        conditions.append(Transaction.merchant.ilike(f"%{merchant_pattern}%"))
    if description_keyword:
        conditions.append(Transaction.description.ilike(f"%{description_keyword}%"))

    result = await session.execute(
        update(Transaction)
        .where(Transaction.user_corrected.is_(False))
        .where(or_(*conditions))
        .values(category_id=category_id, subcategory_id=subcategory_id)
        .returning(Transaction.id)
    )
    updated_ids = result.fetchall()
    count = len(updated_ids)

    if count:
        logger.info("Backfilled %d transactions matching pattern=%r/%r", count, merchant_pattern, description_keyword)

    # Bust Redis cache for this pattern
    if redis and description_keyword:
        cache_key = f"cat2:{hashlib.md5(description_keyword.encode()).hexdigest()}"
        await redis.delete(cache_key)

    return count


async def apply_user_rules(
    session: AsyncSession,
    merchant: Optional[str],
    description: str,
) -> Optional[tuple[int, Optional[int]]]:
    """
    Check if any learned rule matches this transaction.
    Returns (category_id, subcategory_id) or None.
    """
    merchant_lower = (merchant or "").lower().strip()
    desc_lower     = description.lower()

    rules = (await session.execute(select(UserCategoryRule))).scalars().all()

    # Merchant pattern is more specific — check first
    for rule in rules:
        if rule.merchant_pattern and merchant_lower and rule.merchant_pattern in merchant_lower:
            return rule.category_id, rule.subcategory_id

    # Description keyword fallback
    for rule in rules:
        if rule.description_keyword and rule.description_keyword in desc_lower:
            return rule.category_id, rule.subcategory_id

    return None
