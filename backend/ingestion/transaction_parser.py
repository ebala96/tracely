"""
Normalise raw DataFrame rows into Transaction-like dicts.
Handles varying column names across banks via fuzzy header matching.
"""
import hashlib
import re
import uuid
import logging
from datetime import date
from typing import Optional

import pandas as pd
from dateutil import parser as dateparser
from rapidfuzz import process, fuzz

logger = logging.getLogger(__name__)

# Known merchant normalizations (lowercase key → display name)
_MERCHANT_NORM: dict[str, str] = {
    "swiggy": "Swiggy",
    "zomato": "Zomato",
    "amazon": "Amazon",
    "flipkart": "Flipkart",
    "myntra": "Myntra",
    "netflix": "Netflix",
    "spotify": "Spotify",
    "hotstar": "Hotstar",
    "youtube": "YouTube",
    "uber": "Uber",
    "ola": "Ola",
    "rapido": "Rapido",
    "phonepe": "PhonePe",
    "gpay": "Google Pay",
    "paytm": "Paytm",
    "razorpay": "Razorpay",
    "irctc": "IRCTC",
    "bigbasket": "BigBasket",
    "blinkit": "Blinkit",
    "dunzo": "Dunzo",
    "zepto": "Zepto",
    "instamart": "Instamart",
    "jiomart": "JioMart",
    "nykaa": "Nykaa",
    "meesho": "Meesho",
    "airtel": "Airtel",
    "jio": "Jio",
    "bsnl": "BSNL",
    "act ": "ACT Broadband",
    "bescom": "BESCOM",
    "zerodha": "Zerodha",
    "groww": "Groww",
    "hdfc": "HDFC",
    "icici": "ICICI",
    "sbi": "SBI",
    "axis": "Axis Bank",
    "kotak": "Kotak",
    "1mg": "1mg",
    "apollo": "Apollo Pharmacy",
    "medplus": "MedPlus",
    "cult.fit": "Cult.fit",
    "cult fit": "Cult.fit",
    "domino": "Domino's",
    "pizza hut": "Pizza Hut",
    "kfc": "KFC",
    "mcdonalds": "McDonald's",
    "mcdonald": "McDonald's",
    "starbucks": "Starbucks",
}

# Strips common banking prefixes and noise from descriptions
_PREFIX_RE = re.compile(
    r"^(?:UPI[-/\s]?|NEFT[-/\s]?|IMPS[-/\s]?|RTGS[-/\s]?|POS[-/\s]?|"
    r"BIL[-/\s]?|INT[-/\s]?|TRF[-/\s]?|ACH[-/\s]?|ECS[-/\s]?|SI[-/\s]?|"
    r"CLG[-/\s]?|EMI[-/\s]?|CHQ[-/\s]?|ATM[-/\s]?|MMT[-/\s]?|FT[-/\s]?|"
    r"INB[-/\s]?|MB[-/\s]?|IB[-/\s]?|NB[-/\s]?|D[-/\s]?)",
    re.I,
)
# Strips long numeric IDs and timestamps after merchant name
_NOISE_RE = re.compile(r"[\s/|_-]+\d{6,}.*$|[\s/|_-]+\d{2}[-/]\d{2}[-/]\d{2,4}.*$")

# Canonical column roles and their common aliases (generic fallback)
_COL_ALIASES = {
    "date":        ["date", "txn date", "transaction date", "value date", "posting date", "trans date"],
    "description": ["description", "narration", "particulars", "details", "remarks",
                    "transaction details", "transaction remarks", "trans particulars"],
    "debit":       ["debit", "dr", "withdrawal", "withdrawals", "debit amount", "dr amount",
                    "withdrawal amt", "debit amt"],
    "credit":      ["credit", "cr", "deposit", "deposits", "credit amount", "cr amount",
                    "deposit amt", "credit amt"],
    "amount":      ["debit/credit", "amount", "debit / credit", "dr/cr", "dr / cr",
                    "transaction amount", "trans amount"],
    "balance":     ["balance", "closing balance", "running balance", "available balance", "bal"],
    "ref_number":  ["ref", "ref no", "reference", "chq no", "cheque no", "utr",
                    "transaction id", "chq / ref no", "chq./ref.no.", "tran. id", "trans id"],
    "txn_flag":    ["dr/cr", "type", "txn type", "cr/dr", "debit/credit flag", "d/c"],
}

# Per-bank column name hints — tried before generic aliases.
# Each role maps to a list of exact (or near-exact) column names that bank uses.
_BANK_OVERRIDES: dict[str, dict[str, list[str]]] = {
    "HDFC": {
        "date":        ["Date"],
        "description": ["Narration"],
        "debit":       ["Withdrawal Amt.", "Withdrawal Amt", "Debit"],
        "credit":      ["Deposit Amt.", "Deposit Amt", "Credit"],
        "balance":     ["Closing Balance"],
        "ref_number":  ["Chq./Ref.No.", "Chq./ Ref. No."],
    },
    "ICICI": {
        "date":        ["Transaction Date", "Value Date"],
        "description": ["Transaction Remarks", "Remarks"],
        "debit":       ["Withdrawal Amount (INR )", "Withdrawal Amount", "Debit"],
        "credit":      ["Deposit Amount (INR )", "Deposit Amount", "Credit"],
        "balance":     ["Balance (INR )", "Balance"],
    },
    "SBI": {
        "date":        ["Txn Date", "Value Date"],
        "description": ["Description"],
        "ref_number":  ["Ref No./Cheque No.", "Ref No. /Cheque No."],
        "debit":       ["Debit"],
        "credit":      ["Credit"],
        "balance":     ["Balance"],
    },
    "Axis": {
        "date":        ["Tran. Date", "Transaction Date"],
        "description": ["PARTICULARS", "Particulars", "Narration"],
        "debit":       ["DR", "Debit"],
        "credit":      ["CR", "Credit"],
        "balance":     ["BAL.", "Balance"],
        "ref_number":  ["Tran. Id", "Trans. Id", "Reference No"],
    },
    "Kotak": {
        "date":        ["Transaction Date", "Value Date"],
        "description": ["Description", "Narration"],
        "debit":       ["Debit", "DR"],
        "credit":      ["Credit", "CR"],
        "balance":     ["Balance"],
    },
    "Yes Bank": {
        "date":        ["Transaction Date", "Txn Date"],
        "description": ["Transaction Details", "Narration", "Remarks"],
        "debit":       ["Withdrawal", "Debit"],
        "credit":      ["Deposit", "Credit"],
        "balance":     ["Balance"],
    },
    "IndusInd": {
        "date":        ["Transaction Date", "Value Date"],
        "description": ["Narration", "Remarks", "Description"],
        "debit":       ["Debit", "Withdrawal"],
        "credit":      ["Credit", "Deposit"],
        "balance":     ["Balance"],
    },
    "IDFC First": {
        "date":        ["Transaction Date", "Date"],
        "description": ["Transaction Remarks", "Narration"],
        "debit":       ["Debit", "DR"],
        "credit":      ["Credit", "CR"],
        "balance":     ["Balance"],
    },
    "RBL": {
        "date":        ["Transaction Date", "Posting Date"],
        "description": ["Description", "Narration", "Particulars"],
        "debit":       ["Debit", "Withdrawal"],
        "credit":      ["Credit", "Deposit"],
        "balance":     ["Balance"],
    },
    "PNB": {
        "date":        ["Posting Date", "Transaction Date", "Txn Date"],
        "description": ["Particulars", "Description", "Narration"],
        "debit":       ["Debit", "Withdrawal"],
        "credit":      ["Credit", "Deposit"],
        "balance":     ["Balance"],
    },
    "Canara": {
        "date":        ["Date", "Transaction Date"],
        "description": ["Particulars", "Description"],
        "debit":       ["Debit", "DR"],
        "credit":      ["Credit", "CR"],
        "balance":     ["Balance"],
        "txn_flag":    ["Dr/Cr"],
    },
    "Bank of Baroda": {
        "date":        ["Transaction Date", "Value Date"],
        "description": ["Remarks", "Narration", "Particulars"],
        "debit":       ["Debit", "Withdrawal"],
        "credit":      ["Credit", "Deposit"],
        "balance":     ["Balance"],
    },
    "Federal": {
        "date":        ["Transaction Date", "Value Date"],
        "description": ["Particulars", "Narration"],
        "amount":      ["Transaction Amount"],
        "txn_flag":    ["Dr/Cr", "Type"],
        "balance":     ["Balance"],
    },
    "KVB": {
        "date":        ["Tran Date", "Transaction Date"],
        "description": ["Particulars", "Narration"],
        "amount":      ["Amount"],
        "txn_flag":    ["Dr/Cr"],
        "balance":     ["Balance"],
    },
}

_REF_RE = re.compile(
    r"(UTR\w+|NEFT[/\w]+|IMPS[/\w]+|UPI[/\w]+|[A-Z]{3}\d{10,})", re.I
)


def parse(
    dfs: list[pd.DataFrame],
    statement_id: str,
    bank_name: Optional[str] = None,
) -> list[dict]:
    """
    Parse a list of DataFrames into a flat list of transaction dicts.
    bank_name (e.g. "HDFC", "SBI") enables bank-specific column matching.
    """
    transactions: list[dict] = []
    for df in dfs:
        mapping = _map_columns(df, bank_name)
        logger.info("[%s] Column mapping: %s", bank_name or "unknown", mapping)
        if not mapping.get("date") or not mapping.get("description"):
            logger.warning(
                "Skipping table — could not map date/description. Bank: %s  Columns: %s",
                bank_name, list(df.columns),
            )
            continue

        for _, row in df.iterrows():
            txn = _parse_row(row, mapping, statement_id)
            if txn:
                transactions.append(txn)

    return transactions


def _map_columns(
    df: pd.DataFrame,
    bank_name: Optional[str] = None,
) -> dict[str, Optional[str]]:
    """
    Map DataFrame columns to canonical roles.
    Strategy:
      1. Exact match against bank-specific hints (if bank known)
      2. Fuzzy match against bank-specific hints
      3. Fuzzy match against generic aliases
    """
    cols_orig  = list(df.columns)
    cols_lower = [str(c).lower().strip() for c in cols_orig]

    bank_hints = _BANK_OVERRIDES.get(bank_name or "", {})
    mapping: dict[str, Optional[str]] = {}

    for role, generic_aliases in _COL_ALIASES.items():
        bank_specific = bank_hints.get(role, [])
        # Bank hints first, then generic aliases as fallback
        all_aliases = bank_specific + [a for a in generic_aliases if a not in bank_specific]

        best_col   = None
        best_score = 0

        for alias in all_aliases:
            alias_l = alias.lower().strip()

            # 1. Exact match
            if alias_l in cols_lower:
                best_col = cols_orig[cols_lower.index(alias_l)]
                best_score = 100
                break

            # 2. Fuzzy match (threshold higher for bank-specific, lower for generic)
            threshold = 80 if alias in bank_specific else 70
            match = process.extractOne(alias_l, cols_lower, scorer=fuzz.token_sort_ratio)
            if match and match[1] >= threshold and match[1] > best_score:
                best_score = match[1]
                best_col   = cols_orig[cols_lower.index(match[0])]

        mapping[role] = best_col

    # Auto-detect txn_flag: look for a column whose values are consistently Dr/Cr
    if not mapping.get("txn_flag"):
        mapping["txn_flag"] = _detect_flag_column(df, exclude=set(mapping.values()))

    return mapping


def _detect_flag_column(df: pd.DataFrame, exclude: set) -> Optional[str]:
    """
    Heuristic: if a column (not already mapped) has ≥80% of values matching
    Dr/Cr/D/C/debit/credit, treat it as the txn_flag column.
    """
    flag_re = re.compile(r"^\s*(dr?|cr?|debit|credit)\s*$", re.I)
    for col in df.columns:
        if col in exclude:
            continue
        vals = df[col].dropna().astype(str)
        if len(vals) == 0:
            continue
        if vals.apply(lambda v: bool(flag_re.match(v))).mean() >= 0.8:
            return col
    return None


def _parse_row(row: pd.Series, mapping: dict, statement_id: str) -> Optional[dict]:
    # --- Date ---
    raw_date = _cell(row, mapping.get("date"))
    if not raw_date:
        return None
    txn_date = _parse_date(raw_date)
    if not txn_date:
        return None

    # --- Description ---
    description = _cell(row, mapping.get("description"))
    if not description:
        return None

    # --- Amounts ---
    # Try separate debit/credit columns first
    debit_val  = _parse_amount(_cell(row, mapping.get("debit")))
    credit_val = _parse_amount(_cell(row, mapping.get("credit")))

    # Fall back to combined amount column
    if debit_val is None and credit_val is None and mapping.get("amount"):
        raw_amt = _cell(row, mapping.get("amount"))
        if raw_amt:
            s = raw_amt.strip()
            # Detect sign: +/- prefix, or Dr/Cr suffix
            upper = s.upper()
            if s.startswith("+") or upper.endswith("CR") or upper.endswith(" C"):
                credit_val = _parse_amount(s)
            elif s.startswith("-") or upper.endswith("DR") or upper.endswith(" D"):
                debit_val  = _parse_amount(s)
            else:
                # No sign indicator — defer to txn_flag column below
                debit_val  = _parse_amount(s)   # tentative; may be overridden

    if debit_val is None and credit_val is None:
        return None

    # --- txn_flag column overrides debit/credit assignment ---
    # e.g. a "Dr/Cr" column with value "Cr" means the amount is a credit
    txn_flag_val = _cell(row, mapping.get("txn_flag"))
    if txn_flag_val:
        flag = txn_flag_val.strip().upper()
        combined = debit_val or credit_val or 0.0
        if combined > 0:
            if flag in ("CR", "C", "CREDIT"):
                debit_val, credit_val = None, combined
            elif flag in ("DR", "D", "DEBIT"):
                debit_val, credit_val = combined, None

    if debit_val and debit_val > 0:
        amount   = debit_val
        txn_type = "debit"
    else:
        amount   = credit_val or 0.0
        txn_type = "credit"

    if amount == 0:
        return None

    # --- Balance ---
    balance = _parse_amount(_cell(row, mapping.get("balance")))

    # --- Ref number ---
    ref_cell = _cell(row, mapping.get("ref_number")) or description
    ref_match = _REF_RE.search(ref_cell)
    ref_number = ref_match.group(0) if ref_match else None

    return {
        "id":           str(_deterministic_uuid(statement_id, txn_date, description.strip(), round(amount, 2), txn_type)),
        "statement_id": statement_id,
        "date":         txn_date,
        "description":  description.strip(),
        "merchant":     _extract_merchant(description),
        "amount":       round(amount, 2),
        "txn_type":     txn_type,
        "balance":      balance,
        "ref_number":   ref_number,
        "raw_row":      str(row.to_dict()),
        "category_id":  None,
    }


def _deterministic_uuid(statement_id: str, txn_date: date, description: str, amount: float, txn_type: str) -> uuid.UUID:
    """Stable UUID derived from the transaction's natural key — makes ingestion idempotent."""
    key = f"{statement_id}|{txn_date}|{description}|{amount}|{txn_type}"
    return uuid.UUID(hashlib.md5(key.encode()).hexdigest())


def _cell(row: pd.Series, col: Optional[str]) -> Optional[str]:
    if col is None or col not in row.index:
        return None
    val = row[col]
    if pd.isna(val):
        return None
    return str(val).strip() or None


def _parse_date(raw: str) -> Optional[date]:
    raw = raw.strip()
    if not raw:
        return None
    try:
        return dateparser.parse(raw, dayfirst=True).date()
    except Exception:
        return None


def _parse_amount(raw: Optional[str]) -> Optional[float]:
    if not raw:
        return None
    # Strip commas, currency symbols, spaces
    cleaned = re.sub(r"[₹$£,\s]", "", raw)
    # Handle Dr/Cr suffixes
    cleaned = re.sub(r"(Dr|CR|dr|cr)$", "", cleaned, flags=re.I).strip()
    if not cleaned:
        return None
    try:
        val = float(cleaned)
        return abs(val) if val != 0 else None
    except ValueError:
        return None


def _extract_merchant(description: str) -> str:
    """
    Extract and normalize merchant name from raw bank description.
    Strips UPI/NEFT/IMPS prefixes, ref numbers, account numbers, timestamps.
    """
    cleaned = description.strip()

    # Remove ref numbers (UTR, IMPS IDs etc.)
    cleaned = _REF_RE.sub(" ", cleaned)

    # Remove UPI recipient handles like @okaxis, @ybl, @paytm
    cleaned = re.sub(r"@\S+", " ", cleaned)

    # Strip leading banking prefixes (UPI/, NEFT/, POS/ etc.)
    cleaned = _PREFIX_RE.sub("", cleaned).strip()

    # For UPI format "MerchantName/txnid" — take the part before first slash
    if "/" in cleaned:
        part = cleaned.split("/")[0].strip()
        if len(part) >= 3:
            cleaned = part

    # Strip trailing noise: long numeric IDs and dates
    cleaned = _NOISE_RE.sub("", cleaned).strip(" -/|")

    # Limit to 45 chars
    merchant = cleaned[:45].strip(" -/|") or description[:40]

    # Check known merchant normalizations (longest match wins)
    lower = merchant.lower()
    best_key = ""
    best_name = ""
    for key, name in _MERCHANT_NORM.items():
        if key in lower and len(key) > len(best_key):
            best_key, best_name = key, name

    if best_name:
        return best_name

    # Title-case the result if it looks ALL CAPS
    if merchant == merchant.upper() and len(merchant) > 3:
        merchant = merchant.title()

    return merchant
