"""
Assign a category (and optional subcategory) to each transaction description.
Returns (parent_slug, subcategory_slug | None).

Order of precedence:
  1. Substring match against subcategory keywords
  2. Substring match against parent-level keywords
  3. Fuzzy match (threshold 85) — subcategories first, then parents
  4. Redis-cached LLM result
  5. Ollama LLM call (result cached for 24h)
"""
import hashlib
import json
import logging
from pathlib import Path
from typing import Optional

import yaml
from rapidfuzz import fuzz

logger = logging.getLogger(__name__)

CATEGORIES_FILE = Path(__file__).parent.parent.parent / "categories.yml"
FALLBACK_SLUG   = "other"
FUZZY_THRESHOLD = 85


def load_taxonomy(path: str | Path = CATEGORIES_FILE) -> dict:
    """
    Returns a taxonomy dict with separate lookups for debit (expense) and
    credit (income) categories so that income categories never accidentally
    match expense transactions and vice-versa.

    Shape:
        {
          "sub":         {kw → (parent_slug, sub_slug)},   # expense subcategories
          "parent":      {kw → parent_slug},                # expense parent keywords
          "income_sub":  {kw → (parent_slug, sub_slug)},   # income subcategories
          "income_parent":{kw → parent_slug},               # income parent keywords
          "slugs":       {parent_slug → [sub_slugs]},       # all, for LLM prompt
          "income_slugs":{parent_slug → [sub_slugs]},       # income only, for LLM
        }
    """
    with open(path) as f:
        data = yaml.safe_load(f)

    sub_lookup:        dict[str, tuple[str, str]] = {}
    parent_lookup:     dict[str, str]             = {}
    income_sub:        dict[str, tuple[str, str]] = {}
    income_parent:     dict[str, str]             = {}
    slugs:             dict[str, list[str]]       = {}
    income_slugs:      dict[str, list[str]]       = {}

    for cat in data["categories"]:
        p_slug   = cat["slug"]
        is_income = cat.get("txn_type") == "credit"

        target_sub    = income_sub    if is_income else sub_lookup
        target_parent = income_parent if is_income else parent_lookup
        target_slugs  = income_slugs  if is_income else slugs

        target_slugs[p_slug] = []

        for kw in cat.get("keywords") or []:
            target_parent[kw.lower()] = p_slug

        for sub in cat.get("subcategories") or []:
            s_slug = sub["slug"]
            target_slugs[p_slug].append(s_slug)
            for kw in sub.get("keywords") or []:
                target_sub[kw.lower()] = (p_slug, s_slug)

    return {
        "sub":           sub_lookup,
        "parent":        parent_lookup,
        "income_sub":    income_sub,
        "income_parent": income_parent,
        "slugs":         slugs,
        "income_slugs":  income_slugs,
    }


async def categorise(
    description: str,
    taxonomy: dict,
    redis,
    llm_client,
    merchant: Optional[str] = None,
    db_session=None,
    txn_type: str = "debit",
) -> tuple[str, Optional[str]]:
    """
    Return (parent_slug, subcategory_slug | None).
    Uses income-specific lookups for credit transactions so income categories
    never bleed into expense transactions and vice-versa.
    """
    desc_lower     = description.lower()
    merchant_lower = (merchant or "").lower()
    combined       = f"{merchant_lower} {desc_lower}".strip()

    is_income = txn_type == "credit"

    # 0. User-learned rules (highest priority)
    if db_session is not None:
        from ingestion.rule_learner import apply_user_rules
        from db.models import Category
        from sqlalchemy import select
        rule_match = await apply_user_rules(db_session, merchant, description)
        if rule_match:
            cat_id, sub_id = rule_match
            cat = (await db_session.execute(
                select(Category).where(Category.id == cat_id)
            )).scalar_one_or_none()
            sub = (await db_session.execute(
                select(Category).where(Category.id == sub_id)
            )).scalar_one_or_none() if sub_id else None
            if cat:
                return cat.slug, (sub.slug if sub else None)

    # Select the right lookups based on txn_type
    sub_lookup    = taxonomy["income_sub"]    if is_income else taxonomy["sub"]
    parent_lookup = taxonomy["income_parent"] if is_income else taxonomy["parent"]

    # 1. Substring — subcategories first
    for keyword, (p_slug, s_slug) in sub_lookup.items():
        if keyword in combined:
            return p_slug, s_slug

    # 2. Substring — parent keywords
    for keyword, p_slug in parent_lookup.items():
        if keyword in combined:
            return p_slug, None

    # 3. Fuzzy — subcategories
    for keyword, (p_slug, s_slug) in sub_lookup.items():
        if fuzz.partial_ratio(keyword, combined) >= FUZZY_THRESHOLD:
            return p_slug, s_slug

    # 4. Fuzzy — parent keywords
    for keyword, p_slug in parent_lookup.items():
        if fuzz.partial_ratio(keyword, combined) >= FUZZY_THRESHOLD:
            return p_slug, None

    # 5. Redis cache (keyed by txn_type to avoid cross-contamination)
    cache_key = f"cat2:{txn_type}:{hashlib.md5(combined.encode()).hexdigest()}"
    cached = await redis.get(cache_key)
    if cached:
        raw = cached.decode() if isinstance(cached, bytes) else cached
        parts = json.loads(raw)
        return parts[0], parts[1]

    # 6. LLM fallback
    result = await _llm_categorise(description, merchant, taxonomy, llm_client, is_income)
    await redis.setex(cache_key, 86400, json.dumps(result))
    return result


async def _llm_categorise(
    description: str,
    merchant: Optional[str],
    taxonomy: dict,
    llm_client,
    is_income: bool = False,
) -> tuple[str, Optional[str]]:
    slugs_map = taxonomy["income_slugs"] if is_income else taxonomy["slugs"]

    lines = []
    for p_slug, sub_slugs in slugs_map.items():
        if sub_slugs:
            lines.append(f"{p_slug} → subcategories: {', '.join(sub_slugs)}")
        else:
            lines.append(p_slug)
    category_guide = "\n".join(lines)

    merchant_line = f"Merchant: '{merchant}'\n" if merchant else ""

    try:
        result = await llm_client.chat([
            {
                "role": "system",
                "content": (
                    "You are an expert at categorising Indian bank transactions. "
                    "Given a transaction, pick the best parent category and, if applicable, the best subcategory. "
                    "Reply with ONLY a JSON object: {\"category\": \"slug\", \"subcategory\": \"slug_or_null\"}. "
                    "No explanation."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"{merchant_line}"
                    f"Description: '{description}'\n\n"
                    f"Available categories and subcategories:\n{category_guide}\n\n"
                    "Reply with JSON:"
                ),
            },
        ])

        parsed = json.loads(result.strip())
        p_slug = parsed.get("category", FALLBACK_SLUG).strip().lower()
        s_slug = (parsed.get("subcategory") or "").strip().lower() or None

        all_parent_slugs = list(slugs_map.keys())
        all_sub_slugs    = [s for subs in slugs_map.values() for s in subs]

        if p_slug not in all_parent_slugs:
            p_slug = FALLBACK_SLUG
            s_slug = None
        if s_slug and s_slug not in all_sub_slugs:
            s_slug = None

        return p_slug, s_slug

    except Exception as e:
        logger.warning("LLM categorisation failed for '%s': %s", description, e)
        return FALLBACK_SLUG, None
