"""
Build RAG chunks from a list of transaction dicts.
Two chunk types:
  - "weekly"  : one chunk per 7-day window of transactions
  - "summary" : one chunk with per-category totals for the whole statement
"""
from datetime import date, timedelta
from typing import Any


def build_chunks(
    transactions: list[dict],
    statement_id: str,
    period_start: date | None = None,
    period_end:   date | None = None,
) -> list[dict[str, Any]]:
    """
    Return a list of chunk dicts ready for embedding + Qdrant upsert.
    Each chunk dict:
      {
        chunk_type:      "weekly" | "summary",
        period_start:    ISO date str,
        period_end:      ISO date str,
        text:            str,
        statement_id:    str,
        transaction_ids: [str, ...],
      }
    """
    if not transactions:
        return []

    sorted_txns = sorted(transactions, key=lambda t: t["date"])

    chunks: list[dict] = []
    chunks.extend(_weekly_chunks(sorted_txns, statement_id))
    chunks.append(_summary_chunk(sorted_txns, statement_id, period_start, period_end))
    return chunks


def _weekly_chunks(txns: list[dict], statement_id: str) -> list[dict]:
    if not txns:
        return []

    chunks = []
    week_start = txns[0]["date"]
    week_end   = week_start + timedelta(days=6)
    bucket: list[dict] = []

    for txn in txns:
        if txn["date"] <= week_end:
            bucket.append(txn)
        else:
            if bucket:
                chunks.append(_format_weekly(bucket, statement_id, week_start, week_end))
            # Advance week window
            week_start = txn["date"]
            week_end   = week_start + timedelta(days=6)
            bucket     = [txn]

    if bucket:
        chunks.append(_format_weekly(bucket, statement_id, week_start, week_end))

    return chunks


def _format_weekly(
    txns: list[dict],
    statement_id: str,
    week_start: date,
    week_end: date,
) -> dict:
    lines = [f"Transactions {week_start.strftime('%d-%b')} to {week_end.strftime('%d-%b %Y')}:"]
    for t in txns:
        category = t.get("category_slug") or "other"
        lines.append(
            f"  - {t['date'].strftime('%d-%b')} | {t['merchant'] or t['description'][:40]} "
            f"| {category} | ₹{t['amount']:,.2f} ({t['txn_type']})"
        )

    return {
        "chunk_type":      "weekly",
        "period_start":    week_start.isoformat(),
        "period_end":      week_end.isoformat(),
        "text":            "\n".join(lines),
        "statement_id":    statement_id,
        "transaction_ids": [t["id"] for t in txns],
    }


def _summary_chunk(
    txns: list[dict],
    statement_id: str,
    period_start: date | None,
    period_end:   date | None,
) -> dict:
    # Aggregate by category
    totals: dict[str, float] = {}
    for t in txns:
        if t["txn_type"] == "debit":
            slug = t.get("category_slug") or "other"
            totals[slug] = totals.get(slug, 0.0) + t["amount"]

    total_debit  = sum(t["amount"] for t in txns if t["txn_type"] == "debit")
    total_credit = sum(t["amount"] for t in txns if t["txn_type"] == "credit")

    p_start = (period_start or txns[0]["date"]).isoformat()
    p_end   = (period_end   or txns[-1]["date"]).isoformat()

    lines = [f"Statement Summary ({p_start} to {p_end}):"]
    lines.append(f"  Total Debit:  ₹{total_debit:,.2f}")
    lines.append(f"  Total Credit: ₹{total_credit:,.2f}")
    lines.append(f"  Transactions: {len(txns)}")
    lines.append("  By Category:")
    for slug, total in sorted(totals.items(), key=lambda x: -x[1]):
        lines.append(f"    {slug}: ₹{total:,.2f}")

    return {
        "chunk_type":      "summary",
        "period_start":    p_start,
        "period_end":      p_end,
        "text":            "\n".join(lines),
        "statement_id":    statement_id,
        "transaction_ids": [t["id"] for t in txns],
    }
