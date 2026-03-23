"""
PDF parsing — extract raw text, metadata, bank name, and statement period.
"""
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

import pdfplumber


# Bank name detection patterns: search first 3 pages of text.
# Order matters — more specific patterns first to avoid false matches.
_BANK_PATTERNS = [
    # Private sector
    (re.compile(r"\bHDFC\s*Bank\b", re.I),                     "HDFC"),
    (re.compile(r"\bICICI\s*Bank\b", re.I),                    "ICICI"),
    (re.compile(r"\bAxis\s*Bank\b", re.I),                     "Axis"),
    (re.compile(r"\bKotak\s*Mahindra\b|\bKotak\s*Bank\b", re.I), "Kotak"),
    (re.compile(r"\bYes\s*Bank\b", re.I),                      "Yes Bank"),
    (re.compile(r"\bIndusInd\s*Bank\b", re.I),                 "IndusInd"),
    (re.compile(r"\bIDFC\s*FIRST\s*Bank\b|\bIDFC\s*Bank\b", re.I), "IDFC First"),
    (re.compile(r"\bRBL\s*Bank\b|\bRatnakar\s*Bank\b", re.I),  "RBL"),
    (re.compile(r"\bFederal\s*Bank\b", re.I),                  "Federal"),
    (re.compile(r"\bDCB\s*Bank\b", re.I),                      "DCB"),
    (re.compile(r"\bAU\s*Small\s*Finance\b", re.I),            "AU Small Finance"),
    (re.compile(r"\bBandhan\s*Bank\b", re.I),                  "Bandhan"),
    (re.compile(r"\bSouth\s*Indian\s*Bank\b", re.I),           "South Indian"),
    (re.compile(r"\bKarnataka\s*Bank\b", re.I),                "Karnataka"),
    (re.compile(r"\bKarur\s*Vysya\b|\bKVB\b", re.I),          "KVB"),
    # New-age / payments banks
    (re.compile(r"\bFi\s*Money\b|\bepifi\.in\b", re.I),        "Fi Money"),
    (re.compile(r"\bJupiter\b.*bank\b", re.I),                 "Jupiter"),
    (re.compile(r"\bSlice\b.*(?:bank|card)\b", re.I),          "Slice"),
    (re.compile(r"\bPaytm\s*Payments\s*Bank\b", re.I),         "Paytm Payments"),
    (re.compile(r"\bAirtel\s*Payments\s*Bank\b", re.I),        "Airtel Payments"),
    # Public sector
    (re.compile(r"\bState\s*Bank\s*of\s*India\b|\bSBI\b", re.I), "SBI"),
    (re.compile(r"\bPunjab\s*National\s*Bank\b|\bPNB\b", re.I),  "PNB"),
    (re.compile(r"\bCanara\s*Bank\b", re.I),                   "Canara"),
    (re.compile(r"\bBank\s*of\s*Baroda\b", re.I),              "Bank of Baroda"),
    (re.compile(r"\bBank\s*of\s*India\b", re.I),               "Bank of India"),
    (re.compile(r"\bUnion\s*Bank\s*of\s*India\b", re.I),       "Union Bank"),
    (re.compile(r"\bIndian\s*Bank\b", re.I),                   "Indian Bank"),
    (re.compile(r"\bCentral\s*Bank\s*of\s*India\b", re.I),     "Central Bank"),
    (re.compile(r"\bIDBI\s*Bank\b", re.I),                     "IDBI"),
    # Catch-all for HDFC without "Bank" suffix (e.g. credit card statements)
    (re.compile(r"\bHDFC\b", re.I),                            "HDFC"),
    (re.compile(r"\bICICI\b", re.I),                           "ICICI"),
]

# Statement period patterns
_PERIOD_PATTERNS = [
    # "01 Jan 2025 to 31 Jan 2025" or "01-Jan-2025 to 31-Jan-2025"
    re.compile(
        r"(\d{1,2}[\s\-/](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\s\-/]\d{4})"
        r"\s*(?:to|-)\s*"
        r"(\d{1,2}[\s\-/](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\s\-/]\d{4})",
        re.I,
    ),
    # "01/01/2025 to 31/01/2025"
    re.compile(
        r"(\d{1,2}[/\-]\d{1,2}[/\-]\d{4})\s*(?:to|-)\s*(\d{1,2}[/\-]\d{1,2}[/\-]\d{4})"
    ),
]


@dataclass
class ParsedPDF:
    full_text: str
    page_count: int
    bank_name: Optional[str]
    period_start: Optional[date]
    period_end: Optional[date]
    raw_pages: list[str] = field(default_factory=list)


def parse(pdf_path: str | Path) -> ParsedPDF:
    pages_text: list[str] = []

    with pdfplumber.open(pdf_path) as pdf:
        page_count = len(pdf.pages)
        for page in pdf.pages:
            text = page.extract_text() or ""
            pages_text.append(text)

    full_text = "\n".join(pages_text)
    header_text = "\n".join(pages_text[:3])  # bank/period usually in first 3 pages

    bank_name = _detect_bank(header_text)
    period_start, period_end = _detect_period(header_text)

    return ParsedPDF(
        full_text=full_text,
        page_count=page_count,
        bank_name=bank_name,
        period_start=period_start,
        period_end=period_end,
        raw_pages=pages_text,
    )


def _detect_bank(text: str) -> Optional[str]:
    for pattern, name in _BANK_PATTERNS:
        if pattern.search(text):
            return name
    return None


def _detect_period(text: str) -> tuple[Optional[date], Optional[date]]:
    from dateutil import parser as dateparser

    for pattern in _PERIOD_PATTERNS:
        m = pattern.search(text)
        if m:
            try:
                start = dateparser.parse(m.group(1), dayfirst=True).date()
                end = dateparser.parse(m.group(2), dayfirst=True).date()
                return start, end
            except Exception:
                continue
    return None, None
