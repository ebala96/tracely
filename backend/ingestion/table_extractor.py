"""
Table extraction from PDFs.
Primary: Camelot (lattice mode for bordered tables, stream for borderless).
Fallback 1: pdfplumber .extract_tables().
Fallback 2: text-line parsing for statements without structured tables.
"""
import logging
import re
from pathlib import Path

import pandas as pd
import pdfplumber

logger = logging.getLogger(__name__)

# Minimum table dimensions to be considered a transaction table
MIN_COLS = 4
MIN_ROWS = 3

# Regex to detect a line that starts with a date — used for text-line fallback
_DATE_LINE_RE = re.compile(
    r"^\s*(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}"        # DD/MM/YYYY or DD-MM-YYYY
    r"|\d{1,2}[\s\-](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\s\-]\d{2,4}"  # DD Mon YYYY
    r"|\d{4}[/\-]\d{2}[/\-]\d{2})",                 # YYYY-MM-DD
    re.I,
)
# Detect amount tokens: numbers with optional commas and 2 decimal places
_AMOUNT_RE = re.compile(r"\b\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?\b|\b\d{4,}(?:\.\d{1,2})?\b")


def extract(pdf_path: str | Path) -> list[pd.DataFrame]:
    """Return a list of DataFrames, one per detected transaction table."""
    tables = _try_camelot(pdf_path)
    if tables:
        return tables

    logger.info("Camelot found nothing, falling back to pdfplumber")
    tables = _try_pdfplumber(pdf_path)
    if tables:
        return tables

    logger.info("pdfplumber tables found nothing, falling back to text-line parser")
    return _try_text_lines(pdf_path)


def _try_camelot(pdf_path: str | Path) -> list[pd.DataFrame]:
    try:
        import camelot

        # Try lattice first (bordered tables)
        tables = camelot.read_pdf(str(pdf_path), pages="all", flavor="lattice")
        result = _filter_tables([t.df for t in tables])
        if result:
            return result

        # Try stream (borderless / whitespace-delimited)
        tables = camelot.read_pdf(str(pdf_path), pages="all", flavor="stream")
        return _filter_tables([t.df for t in tables])

    except Exception as e:
        logger.warning("Camelot failed: %s", e)
        return []


def _try_pdfplumber(pdf_path: str | Path) -> list[pd.DataFrame]:
    results: list[pd.DataFrame] = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                for raw in page.extract_tables():
                    if not raw:
                        continue
                    df = pd.DataFrame(raw[1:], columns=raw[0])
                    results.append(df)
        return _filter_tables(results)
    except Exception as e:
        logger.warning("pdfplumber table extraction failed: %s", e)
        return []


def _try_text_lines(pdf_path: str | Path) -> list[pd.DataFrame]:
    """
    Last-resort parser: scan each page's text line by line looking for
    lines that start with a date and contain at least one amount.
    Builds a DataFrame with columns: date, description, amount, balance.
    """
    rows: list[dict] = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                for line in text.splitlines():
                    line = line.strip()
                    if not _DATE_LINE_RE.match(line):
                        continue
                    amounts = _AMOUNT_RE.findall(line)
                    if not amounts:
                        continue

                    # Extract date token
                    date_m = _DATE_LINE_RE.match(line)
                    date_str = date_m.group(0).strip()

                    # Remove date from line to get description + amounts
                    rest = line[date_m.end():].strip()

                    # Last 1–2 numeric tokens are balance/amount; rest is description
                    # Remove all amount occurrences from rest to get description
                    desc = _AMOUNT_RE.sub("", rest).strip(" -/|,")

                    # Build row: take last two amounts as (amount, balance) or just (amount,)
                    clean_amounts = [a.replace(",", "") for a in amounts]
                    if len(clean_amounts) >= 2:
                        amount  = clean_amounts[-2]
                        balance = clean_amounts[-1]
                    else:
                        amount  = clean_amounts[-1]
                        balance = ""

                    rows.append({
                        "Date":        date_str,
                        "Description": desc or rest[:80],
                        "Amount":      amount,
                        "Balance":     balance,
                    })

    except Exception as e:
        logger.warning("Text-line fallback failed: %s", e)
        return []

    if len(rows) < MIN_ROWS:
        return []

    df = pd.DataFrame(rows)
    logger.info("Text-line parser extracted %d rows", len(df))
    return [df]


def _filter_tables(dfs: list[pd.DataFrame]) -> list[pd.DataFrame]:
    """Keep only tables large enough to plausibly contain transactions.
    Also removes repeated header rows that appear when a table spans pages."""
    kept = []
    for i, df in enumerate(dfs):
        df = df.dropna(how="all").reset_index(drop=True)
        df = _promote_header(df)
        df = _remove_duplicate_headers(df)
        logger.info("Table %d: shape=%s cols=%s", i, df.shape, list(df.columns))
        if df.shape[1] >= MIN_COLS and df.shape[0] >= MIN_ROWS:
            kept.append(df)
    return kept


def _remove_duplicate_headers(df: pd.DataFrame) -> pd.DataFrame:
    """
    Remove rows that repeat the column headers (happens when a table spans
    multiple pages and each page starts with a header row).
    """
    if df.empty:
        return df
    header_vals = {str(c).lower().strip() for c in df.columns}
    mask = df.apply(
        lambda row: not (
            sum(1 for v in row.values if str(v).lower().strip() in header_vals) >= len(df.columns) // 2
        ),
        axis=1,
    )
    return df[mask].reset_index(drop=True)


def _promote_header(df: pd.DataFrame) -> pd.DataFrame:
    """
    If columns are integers (Camelot didn't detect headers), scan rows to find
    the real header row — the first row where most cells are non-empty strings
    that look like column labels (not dates/amounts). Promote it and drop rows above it.
    """
    # If columns are already named strings, nothing to do
    if not all(isinstance(c, int) for c in df.columns):
        return df

    for i, row in df.iterrows():
        values = [str(v).strip() for v in row.values if str(v).strip()]
        # A header row has mostly short non-numeric strings
        if len(values) >= 3 and sum(1 for v in values if not _looks_like_data(v)) >= 2:
            df.columns = [str(v).strip() for v in row.values]
            df = df.iloc[i + 1:].reset_index(drop=True)
            return df

    return df


def _looks_like_data(val: str) -> bool:
    """Return True if value looks like transaction data (date or number), not a header label."""
    import re
    val = val.strip()
    # Looks like a number or amount
    if re.match(r'^[\d,\.+\-₹$]+$', val):
        return True
    # Looks like a date
    if re.match(r'\d{1,2}[\s\-/]\w+[\s\-/]\d{2,4}', val):
        return True
    if re.match(r'\d{2}[\-/]\d{2}[\-/]\d{2,4}', val):
        return True
    return False
