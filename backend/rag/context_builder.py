"""
Build the context string passed to the LLM.

- AGGREGATION / LISTING / COMPARISON  → SQL query against Postgres
- SEMANTIC                             → Qdrant vector search + supporting SQL
"""
import calendar
import logging
import re
from datetime import date
from typing import Optional

from sqlalchemy import text

from db.postgres import AsyncSessionLocal
from rag.intent_classifier import Intent
from rag.retriever import search as vector_search

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Category / subcategory slug → generic keywords in a question
# Keep merchant names OUT of here — they go through _extract_merchant instead.
# ---------------------------------------------------------------------------
_CATEGORY_KEYWORDS = {
    # Expense categories
    "online_food_order": ["online food", "food order", "food ordering"],
    "food_dining":    ["food", "dining", "eating", "meal", "meals"],
    "transport":      ["transport", "travel", "commute", "commuting", "cab", "taxi", "fuel", "petrol"],
    "subscriptions":  ["subscription", "subscriptions", "streaming", "ott", "saas"],
    "shopping":       ["shopping", "purchase", "bought", "retail", "ecommerce"],
    "utilities":      ["utilities", "utility", "electricity", "internet", "broadband", "recharge", "bill"],
    "health":         ["health", "medical", "medicine", "doctor", "hospital", "fitness"],
    "finance":        ["finance", "investment", "insurance", "loan", "emi"],
    "groceries":      ["groceries", "grocery", "vegetables", "supermarket"],
    "entertainment":  ["entertainment", "movies", "cinema", "gaming", "concert", "leisure"],
    "transfers":      ["transfer", "sent to", "send money", "transferred"],
    "other":          ["other", "miscellaneous"],
    # Income categories
    "salary_income":       ["salary", "sal", "payroll", "wages", "stipend", "pay"],
    "freelance_business":  ["freelance", "consulting income", "invoice", "client payment"],
    "investment_returns":  ["dividend", "interest income", "fd interest", "rd maturity", "mf redemption", "redemption"],
    "refunds_cashbacks":   ["refund", "cashback", "cash back", "reversal", "chargeback"],
    "income_transfer":     ["received from", "money received", "transfer received"],
}

# Subcategory slug → keywords (merchant names live here so they get a precise sub-filter)
_SUBCATEGORY_KEYWORDS: dict[str, tuple[str, list[str]]] = {
    # slug → (parent_slug, [keywords])
    # Always include the human-readable subcategory name as the first keyword
    # so natural language queries like "fast food in March" resolve correctly.
    "swiggy":           ("online_food_order", ["swiggy"]),
    "zomato":           ("online_food_order", ["zomato"]),
    "other_delivery":   ("online_food_order", ["uber eats", "dunzo", "blinkit food", "food delivery", "online food order"]),
    "fast_food":        ("food_dining",    ["fast food", "fastfood", "dominos", "pizza hut", "mcdonalds", "kfc", "burger king", "subway"]),
    "coffee_cafes":     ("food_dining",    ["coffee", "cafe", "cafes", "starbucks", "cafe coffee day", "ccd", "barista"]),
    "breakfast":        ("food_dining",    ["breakfast"]),
    "lunch":            ("food_dining",    ["lunch"]),
    "dinner":           ("food_dining",    ["dinner", "restaurant", "dining out"]),
    "cab_auto":         ("transport",      ["cab", "auto ride", "uber", "ola", "rapido", "namma yatri"]),
    "bike_scooter":     ("transport",      ["bike rental", "scooter", "yulu", "bounce"]),
    "public_transport": ("transport",      ["public transport", "metro", "bmtc", "ksrtc", "bus pass"]),
    "intercity_travel": ("transport",      ["intercity", "flight", "train ticket", "irctc", "redbus", "indigo", "spicejet", "air india", "makemytrip"]),
    "fuel":             ("transport",      ["fuel", "petrol", "diesel", "petrol pump", "hp petrol", "indian oil", "bharat petroleum"]),
    "streaming_video":  ("subscriptions",  ["streaming", "video streaming", "netflix", "hotstar", "amazon prime", "zee5", "sonyliv"]),
    "streaming_music":  ("subscriptions",  ["music streaming", "spotify", "youtube premium", "apple music", "jiosaavn"]),
    "saas_apps":        ("subscriptions",  ["saas", "app subscription", "notion", "github", "figma", "dropbox", "adobe", "microsoft 365"]),
    "ecommerce":        ("shopping",       ["ecommerce", "online shopping", "amazon", "flipkart", "meesho", "snapdeal"]),
    "fashion":          ("shopping",       ["fashion", "clothing", "clothes", "myntra", "ajio", "zara", "h&m", "westside"]),
    "beauty":           ("shopping",       ["beauty", "skincare", "cosmetics", "nykaa", "purplle", "mamaearth"]),
    "electricity_water":("utilities",      ["electricity", "water bill", "bescom", "tata power", "bwssb", "bbmp"]),
    "mobile_internet":  ("utilities",      ["mobile bill", "phone bill", "broadband", "airtel", "jio", "bsnl", "act broadband", "vi recharge"]),
    "pharmacy":         ("health",         ["pharmacy", "medicine", "medicines", "apollo pharmacy", "medplus", "netmeds", "1mg", "pharmeasy"]),
    "fitness":          ("health",         ["fitness", "gym", "workout", "cult fit", "gold's gym", "crossfit"]),
    "doctor_lab":       ("health",         ["doctor", "hospital", "lab test", "practo", "apollo hospital", "thyrocare", "lal path"]),
    "insurance":        ("finance",        ["insurance", "lic", "hdfc life", "icici prudential", "star health"]),
    "investments":      ("finance",        ["investment", "investments", "mutual fund", "sip", "zerodha", "groww", "nps", "smallcase"]),
    "loan_emi":         ("finance",        ["loan", "emi", "home loan", "bajaj finance"]),
    "online_groceries": ("groceries",      ["online groceries", "bigbasket", "blinkit", "jiomart", "zepto", "swiggy instamart"]),
    "supermarket":      ("groceries",      ["supermarket", "hypermarket", "dmart", "reliance fresh", "more supermarket", "star bazaar"]),
    "meat_seafood":     ("groceries",      ["meat", "seafood", "fish", "chicken", "licious", "freshtohome"]),
    "movies_cinema":    ("entertainment",  ["movie", "movies", "cinema", "theatre", "multiplex", "bookmyshow", "pvr", "inox", "cinepolis"]),
    "gaming":           ("entertainment",  ["gaming", "game", "steam", "playstation", "xbox", "epic games"]),
    "events_concerts":  ("entertainment",  ["concert", "event", "paytm insider", "zomato live"]),
    "family_relatives": ("transfers",      ["family", "relative", "relatives", "send home", "home transfer",
                                            "father", "mother", "brother", "sister", "wife", "husband", "son", "daughter", "parents"]),
    "friends_transfer": ("transfers",      ["friend", "friends", "lend", "borrow", "split"]),
    "rent":             ("transfers",      ["rent", "landlord", "house rent", "pg rent", "room rent"]),
    "self_transfer":    ("transfers",      ["self transfer", "own account", "sweep"]),
    # Income subcategories
    "salary":           ("salary_income",      ["salary", "sal cr", "monthly salary", "payroll credit"]),
    "bonus_incentive":  ("salary_income",      ["bonus", "incentive", "performance pay", "variable pay"]),
    "freelance":        ("freelance_business", ["freelance", "gig payment", "upwork", "fiverr"]),
    "interest_income":  ("investment_returns", ["interest credit", "fd interest", "savings interest", "int cr", "int paid"]),
    "dividends":        ("investment_returns", ["dividend", "div credit"]),
    "mf_redemption":    ("investment_returns", ["mf redemption", "mutual fund credit", "fund redemption", "redemption credit"]),
    "refund":           ("refunds_cashbacks",  ["refund", "reversal", "chargeback", "amount reversed"]),
    "cashback":         ("refunds_cashbacks",  ["cashback", "cash back", "reward credit"]),
    "received_family":  ("income_transfer",    ["received from family", "family transfer received"]),
    "received_friends": ("income_transfer",    ["received from friend", "split received", "splitwise"]),
}

_COMMON_WORDS = {
    "how", "much", "did", "i", "spend", "spending", "on", "in", "the", "last", "this",
    "month", "year", "all", "list", "show", "me", "my", "total", "transactions", "transaction",
    "what", "were", "are", "compare", "vs", "between", "and", "for", "from", "to",
    "give", "top", "recent", "latest", "above", "below", "over", "under",
    "rupees", "inr", "amount", "spent", "per", "during", "any", "every", "each",
    "highest", "largest", "biggest", "merchants", "merchant", "categories", "category",
    "breakdown", "wise", "expense", "expenses", "payment", "payments",
    "debit", "credit", "bank", "statement", "versus", "difference",
    # subcategory / category name words — prevent these being picked up as merchant names
    "food", "fast", "dining", "delivery", "cafe", "coffee", "breakfast", "lunch", "dinner",
    "transport", "cab", "auto", "fuel", "petrol", "metro", "travel", "flight", "train",
    "subscription", "streaming", "music", "video", "saas",
    "shopping", "fashion", "beauty", "ecommerce",
    "utilities", "electricity", "broadband", "mobile",
    "health", "pharmacy", "fitness", "doctor", "medicine",
    "finance", "insurance", "investment", "loan", "emi",
    "groceries", "grocery", "supermarket", "meat", "seafood",
    "entertainment", "movie", "movies", "cinema", "gaming", "concert",
    "transfer", "rent", "family", "friend", "friends",
    "swiggy", "zomato",
    # Income-related words — must not become merchant filters
    "salary", "sal", "payroll", "wages", "stipend", "income", "earnings",
    "bonus", "incentive", "commission", "variable",
    "freelance", "consulting", "invoice",
    "dividend", "dividends", "interest", "redemption", "maturity",
    "refund", "refunds", "cashback", "reversal", "chargeback",
    "received", "credited", "got", "earn", "earned",
}

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


async def build(
    question: str,
    intent: Intent,
    statement_ids: Optional[list[str]] = None,
) -> tuple[str, Optional[str]]:
    if intent == Intent.SEMANTIC:
        return await _semantic_context(question, statement_ids)
    else:
        return await _sql_context(question, intent, statement_ids)


# ---------------------------------------------------------------------------
# SQL-based context
# ---------------------------------------------------------------------------

async def _sql_context(
    question: str,
    intent: Intent,
    statement_ids: Optional[list[str]],
) -> tuple[str, str]:
    sql, params = _build_sql(question, intent, statement_ids)
    logger.info("SQL: %s | params: %s", sql, params)

    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(text(sql), params)
            rows = result.fetchall()
            cols = list(result.keys())
    except Exception as e:
        logger.exception("SQL execution failed: %s", e)
        return f"SQL error: {e}", sql

    if not rows:
        return "No transactions found matching your query.", sql

    # Build a human-readable filter summary so the LLM knows what the numbers represent
    filter_parts = []
    if params.get("sub_slug"):
        filter_parts.append(f"subcategory={params['sub_slug'].replace('_', ' ')}")
    if params.get("cat_slug"):
        filter_parts.append(f"category={params['cat_slug'].replace('_', ' ')}")
    if params.get("merchant"):
        filter_parts.append(f"merchant LIKE {params['merchant']}")
    if params.get("date_from") and params.get("date_to"):
        filter_parts.append(f"period={params['date_from']} to {params['date_to']}")
    if "txn_type = 'credit'" in sql:
        filter_parts.append("type=credit (income/received)")

    header = f"[Filters: {', '.join(filter_parts)}]\n" if filter_parts else ""

    lines = [" | ".join(cols)]
    lines += [" | ".join(str(v) if v is not None else "—" for v in row) for row in rows[:100]]
    context = header + "\n".join(lines)
    return context, sql


def _build_sql(
    question: str,
    intent: Intent,
    statement_ids: Optional[list[str]],
) -> tuple[str, dict]:
    q_lower = question.lower()
    params: dict = {}

    # --- Subcategory filter (checked before merchant/category — most specific) ---
    subcategory_filter = ""
    sub_result = _extract_subcategory(q_lower)
    if sub_result:
        sub_slug, parent_slug_from_sub = sub_result
        params["sub_slug"] = sub_slug
        subcategory_filter = "AND sc.slug = :sub_slug"

    # --- Merchant filter (only when no subcategory matched and query is merchant-specific) ---
    merchant_filter = ""
    if not subcategory_filter:
        merchant = _extract_merchant(q_lower)
        if merchant:
            params["merchant"] = f"%{merchant}%"
            merchant_filter = "AND (LOWER(t.description) LIKE :merchant OR LOWER(t.merchant) LIKE :merchant)"

    # --- Category filter (parent level — skip if subcategory already narrows it) ---
    category_filter = ""
    if not subcategory_filter:
        category_slug = _extract_category(q_lower)
        if category_slug:
            params["cat_slug"] = category_slug
            category_filter = "AND c.slug = :cat_slug"

    # --- Date filter ---
    date_filter = ""
    date_range = _extract_date_range(q_lower)
    if date_range:
        params["date_from"] = date.fromisoformat(date_range[0])
        params["date_to"] = date.fromisoformat(date_range[1])
        date_filter = "AND t.date BETWEEN :date_from AND :date_to"

    # --- Amount filter ---
    amount_filter = ""
    amount_range = _extract_amount_range(q_lower)
    if amount_range:
        lo, hi = amount_range
        if lo is not None:
            params["amount_min"] = lo
            amount_filter += " AND t.amount >= :amount_min"
        if hi is not None:
            params["amount_max"] = hi
            amount_filter += " AND t.amount <= :amount_max"

    # --- Statement filter ---
    stmt_filter = ""
    if statement_ids:
        safe_ids = ", ".join(f"'{sid}'" for sid in statement_ids if _is_uuid(sid))
        if safe_ids:
            stmt_filter = f"AND t.statement_id IN ({safe_ids})"

    # --- txn_type filter ---
    _income_words = {
        "credit", "credited", "received", "income", "salary", "sal",
        "payroll", "wages", "dividend", "dividends", "interest income",
        "refund", "cashback", "reversal", "redemption", "freelance",
        "earned", "got paid", "bonus received",
    }
    _both_words = {"all transaction", "both", "total transaction", "all txn"}
    txn_filter = "AND t.txn_type = 'debit'"
    if any(w in q_lower for w in _income_words):
        txn_filter = "AND t.txn_type = 'credit'"
    if any(w in q_lower for w in _both_words):
        txn_filter = ""  # No type filter

    # --- Top N ---
    top_n = _extract_top_n(q_lower)

    joins = """
        LEFT JOIN categories c  ON c.id  = t.category_id
        LEFT JOIN categories sc ON sc.id = t.subcategory_id
    """

    where = f"""
        WHERE 1=1
          {subcategory_filter}
          {merchant_filter}
          {category_filter}
          {date_filter}
          {amount_filter}
          {stmt_filter}
          {txn_filter}
    """

    if intent == Intent.AGGREGATION:
        sql = f"""
            SELECT
                COUNT(*)        AS txn_count,
                SUM(t.amount)   AS total_amount,
                AVG(t.amount)   AS avg_amount,
                MIN(t.amount)   AS min_amount,
                MAX(t.amount)   AS max_amount,
                MIN(t.date)     AS from_date,
                MAX(t.date)     AS to_date
            FROM transactions t {joins}
            {where}
        """

    elif intent == Intent.COMPARISON:
        sql = f"""
            SELECT
                TO_CHAR(t.date, 'Mon YYYY')      AS month,
                COUNT(*)                          AS txn_count,
                ROUND(SUM(t.amount)::numeric, 2)  AS total_amount
            FROM transactions t {joins}
            {where}
            GROUP BY TO_CHAR(t.date, 'Mon YYYY'), DATE_TRUNC('month', t.date)
            ORDER BY DATE_TRUNC('month', t.date)
        """

    elif _is_merchant_ranking_query(q_lower):
        # "top 5 merchants", "highest spending merchants"
        limit = top_n or 10
        sql = f"""
            SELECT
                COALESCE(t.merchant, t.description) AS merchant,
                COUNT(*)                             AS txn_count,
                ROUND(SUM(t.amount)::numeric, 2)     AS total_spent
            FROM transactions t {joins}
            {where}
            GROUP BY COALESCE(t.merchant, t.description)
            ORDER BY total_spent DESC
            LIMIT {limit}
        """

    elif _is_category_breakdown_query(q_lower):
        sql = f"""
            SELECT
                COALESCE(c.name, 'Uncategorised') AS category,
                COUNT(*)                           AS txn_count,
                ROUND(SUM(t.amount)::numeric, 2)   AS total_spent
            FROM transactions t {joins}
            {where}
            GROUP BY c.name
            ORDER BY total_spent DESC
        """

    else:
        # LISTING
        limit = top_n or 50
        sql = f"""
            SELECT
                t.date,
                COALESCE(t.merchant, t.description)  AS merchant,
                t.description,
                ROUND(t.amount::numeric, 2)           AS amount,
                t.txn_type,
                COALESCE(c.name, 'Uncategorised')     AS category,
                sc.name                               AS subcategory
            FROM transactions t {joins}
            {where}
            ORDER BY t.amount DESC, t.date DESC
            LIMIT {limit}
        """

    return sql.strip(), params


# ---------------------------------------------------------------------------
# Semantic context
# ---------------------------------------------------------------------------

async def _semantic_context(
    question: str,
    statement_ids: Optional[list[str]],
) -> tuple[str, None]:
    chunks = await vector_search(question, top_k=5, statement_ids=statement_ids)
    if not chunks:
        return "No relevant transaction data found.", None

    parts = []
    for i, chunk in enumerate(chunks, 1):
        parts.append(f"[Chunk {i} — {chunk.get('chunk_type','?')} "
                     f"{chunk.get('period_start','')} to {chunk.get('period_end','')}]")
        parts.append(chunk.get("text", ""))
        parts.append("")

    return "\n".join(parts), None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_subcategory(q: str) -> Optional[tuple[str, str]]:
    """Return (subcategory_slug, parent_slug) if a subcategory keyword appears in the question."""
    for sub_slug, (parent_slug, keywords) in _SUBCATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in q:
                return sub_slug, parent_slug
    return None


def _extract_merchant(q: str) -> Optional[str]:
    """Extract a specific merchant name — only when query is clearly about one merchant."""
    # Only extract if the question is merchant-specific (not "top merchants" type)
    if _is_merchant_ranking_query(q):
        return None
    if _is_category_breakdown_query(q):
        return None

    tokens = re.findall(r"\b[a-z0-9]+\b", q)
    candidates = [
        t for t in tokens
        if t not in _COMMON_WORDS
        and t not in _MONTHS
        and len(t) > 2
        and not re.match(r"^\d+$", t)
        and t not in _CATEGORY_KEYWORDS  # exclude generic category words only
    ]
    return candidates[0] if candidates else None


def _extract_category(q: str) -> Optional[str]:
    """Return a category slug if the question mentions a spending category."""
    for slug, keywords in _CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in q:
                return slug
    return None


def _extract_date_range(q: str) -> Optional[tuple[str, str]]:
    """
    Extract a date range from the question.
    Handles relative terms (last month, this week, yesterday, last 30 days, etc.)
    as well as explicit month/year references.
    """
    from datetime import timedelta
    today = date.today()

    # --- Relative date terms (checked before explicit months) ---
    if re.search(r"\b(today)\b", q):
        return (today.isoformat(), today.isoformat())

    if re.search(r"\b(yesterday)\b", q):
        d = today - timedelta(days=1)
        return (d.isoformat(), d.isoformat())

    if re.search(r"\bthis\s+week\b", q):
        start = today - timedelta(days=today.weekday())  # Monday
        return (start.isoformat(), today.isoformat())

    if re.search(r"\blast\s+week\b", q):
        start = today - timedelta(days=today.weekday() + 7)
        end   = start + timedelta(days=6)
        return (start.isoformat(), end.isoformat())

    if re.search(r"\bthis\s+month\b", q):
        start = today.replace(day=1)
        return (start.isoformat(), today.isoformat())

    if re.search(r"\blast\s+month\b", q):
        first_this = today.replace(day=1)
        last_prev  = first_this - timedelta(days=1)
        start      = last_prev.replace(day=1)
        return (start.isoformat(), last_prev.isoformat())

    if re.search(r"\blast\s+30\s+days?\b|\bpast\s+month\b", q):
        start = today - timedelta(days=30)
        return (start.isoformat(), today.isoformat())

    if re.search(r"\blast\s+7\s+days?\b|\bpast\s+week\b", q):
        start = today - timedelta(days=7)
        return (start.isoformat(), today.isoformat())

    if re.search(r"\blast\s+90\s+days?\b|\blast\s+3\s+months?\b|\blast\s+quarter\b", q):
        start = today - timedelta(days=90)
        return (start.isoformat(), today.isoformat())

    if re.search(r"\blast\s+6\s+months?\b", q):
        start = today - timedelta(days=180)
        return (start.isoformat(), today.isoformat())

    if re.search(r"\bthis\s+year\b", q):
        return (f"{today.year}-01-01", today.isoformat())

    if re.search(r"\blast\s+year\b", q):
        y = today.year - 1
        return (f"{y}-01-01", f"{y}-12-31")

    # Q1 / Q2 / Q3 / Q4
    q_match = re.search(r"\bq([1-4])\b", q, re.I)
    if q_match:
        quarter = int(q_match.group(1))
        year_match = re.search(r"\b(20\d{2})\b", q)
        yr = int(year_match.group(1)) if year_match else today.year
        start_month = (quarter - 1) * 3 + 1
        end_month   = start_month + 2
        last_day    = calendar.monthrange(yr, end_month)[1]
        return (f"{yr}-{start_month:02d}-01", f"{yr}-{end_month:02d}-{last_day:02d}")

    # --- Explicit month references ---
    year_match = re.search(r"\b(20\d{2})\b", q)
    year = int(year_match.group(1)) if year_match else today.year

    month_pattern = r"\b(" + "|".join(_MONTHS.keys()) + r")\b"
    found_months = [_MONTHS[m.group(1)] for m in re.finditer(month_pattern, q)]

    if len(found_months) >= 2:
        m1, m2 = min(found_months), max(found_months)
        last_day = calendar.monthrange(year, m2)[1]
        return (f"{year}-{m1:02d}-01", f"{year}-{m2:02d}-{last_day:02d}")

    if len(found_months) == 1:
        m = found_months[0]
        last_day = calendar.monthrange(year, m)[1]
        return (f"{year}-{m:02d}-01", f"{year}-{m:02d}-{last_day:02d}")

    return None


def _extract_amount_range(q: str) -> Optional[tuple[Optional[float], Optional[float]]]:
    """Extract amount bounds from queries like 'above 5000', 'below ₹1000'."""
    lo: Optional[float] = None
    hi: Optional[float] = None

    above = re.search(r"\b(?:above|over|more than|greater than|exceeding)[^\d]*(\d[\d,]*)", q)
    below = re.search(r"\b(?:below|under|less than)[^\d]*(\d[\d,]*)", q)

    if above:
        lo = float(above.group(1).replace(",", ""))
    if below:
        hi = float(below.group(1).replace(",", ""))

    return (lo, hi) if (lo is not None or hi is not None) else None


def _extract_top_n(q: str) -> Optional[int]:
    m = re.search(r"\btop\s+(\d+)\b", q, re.I)
    return int(m.group(1)) if m else None


def _is_merchant_ranking_query(q: str) -> bool:
    return bool(re.search(r"\b(top\s+\d+\s+merchant|highest.*merchant|most.*spent|merchant.*rank|where.*most)\b", q, re.I)) \
        or ("merchant" in q and any(w in q for w in ["top", "highest", "most", "rank", "list"]))


def _is_category_breakdown_query(q: str) -> bool:
    return bool(re.search(r"\b(breakdown|by category|category.*wise|each category|per category|which categor)\b", q, re.I))


def _is_uuid(val: str) -> bool:
    return bool(re.match(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        val, re.I,
    ))
