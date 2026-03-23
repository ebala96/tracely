"""
Classify a user query into one of four intent types.

  AGGREGATION  — "how much", "total", "sum", "average"
  LISTING      — "list", "show", "what were", "give me", "top N"
  COMPARISON   — "compare", "vs", "versus", "difference"
  SEMANTIC     — open-ended / pattern recognition
"""
import logging
import re
from enum import Enum

from rag.llm_client import chat as llm_chat

logger = logging.getLogger(__name__)


class Intent(str, Enum):
    AGGREGATION = "aggregation"
    LISTING     = "listing"
    COMPARISON  = "comparison"
    SEMANTIC    = "semantic"


_RULES: list[tuple[re.Pattern, Intent]] = [
    (re.compile(r"\b(compare|vs\.?|versus|difference|more than|less than|higher|lower)\b", re.I), Intent.COMPARISON),
    (re.compile(r"\b(how much|total|sum|count|average|avg|spent|spend)\b", re.I),                 Intent.AGGREGATION),
    (re.compile(r"\b(list|show|give me|what were|what are|display|all|every|top\s+\d+|highest|largest|recent|latest)\b", re.I), Intent.LISTING),
]

_LLM_PROMPT = """\
Classify the following user question about their bank transactions into ONE of these intents:
- aggregation  (needs totals / sums / counts)
- listing      (needs a list of transactions or merchants)
- comparison   (compares two time periods or merchants)
- semantic     (open-ended / pattern recognition)

Reply with ONLY the intent word, nothing else.

Question: {question}"""


async def classify(question: str) -> Intent:
    for pattern, intent in _RULES:
        if pattern.search(question):
            return intent

    try:
        reply = await llm_chat([
            {"role": "user", "content": _LLM_PROMPT.format(question=question)}
        ])
        label = reply.strip().lower()
        return Intent(label)
    except Exception as e:
        logger.warning("Intent classification failed: %s — defaulting to listing", e)
        return Intent.LISTING
