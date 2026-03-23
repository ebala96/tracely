"""
Main RAG entry point: user question → answer.

Flow:
  1. Classify intent
  2. Build context (SQL or vector search)
  3. Assemble prompt
  4. Call Ollama LLM
  5. Cache result in Redis
  6. Return answer + metadata
"""
import hashlib
import json
import logging
from typing import Optional

from db.redis_client import cache_get, cache_set
from rag import llm_client, intent_classifier, context_builder

logger = logging.getLogger(__name__)

CACHE_TTL = 3600  # 1 hour

_SYSTEM_PROMPT = """\
You are Spendly, a personal finance assistant.
Answer questions about the user's bank transactions.
Use ONLY the context provided — do not invent transactions or amounts.
Format all amounts in Indian Rupees (₹).
If you cannot answer from the context, say so clearly and briefly.

Formatting rules:
- Use a markdown table when listing multiple transactions or rows of data.
- Use bullet points for short summaries or comparisons.
- Bold key figures like totals and amounts.
- Keep responses concise — no unnecessary filler text."""


async def answer(
    question: str,
    statement_ids: Optional[list[str]] = None,
) -> dict:
    """
    Returns:
      {
        answer:    str,
        sources:   list[str],   # chunk period labels
        sql_used:  str | None,
        intent:    str,
      }
    """
    # --- Cache check ---
    cache_key = _make_cache_key(question, statement_ids)
    cached = await cache_get(cache_key)
    if cached:
        logger.debug("Cache hit for query: %s", question[:60])
        return json.loads(cached)

    # --- Step 1: Classify intent ---
    intent = await intent_classifier.classify(question)
    logger.info("Intent: %s | Query: %s", intent.value, question[:80])

    # --- Step 2: Build context ---
    context_text, sql_used = await context_builder.build(question, intent, statement_ids)

    # --- Step 3: Assemble prompt ---
    user_message = f"Context:\n{context_text}\n\nQuestion: {question}"

    # --- Step 4: LLM call ---
    reply = await llm_client.chat([
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user",   "content": user_message},
    ])

    # --- Step 5: Build sources list ---
    sources = _extract_sources(context_text, intent)

    result = {
        "answer":   reply.strip(),
        "sources":  sources,
        "sql_used": sql_used,
        "intent":   intent.value,
    }

    # --- Step 6: Cache (skip on SQL errors) ---
    if not context_text.startswith("SQL error"):
        await cache_set(cache_key, json.dumps(result), ttl=CACHE_TTL)

    return result


async def stream_answer(
    question: str,
    statement_ids: Optional[list[str]] = None,
):
    """
    Async generator yielding SSE-formatted strings.
    Emits: metadata event first, then token chunks, then done.
    """
    # --- Cache hit: stream cached answer in one shot ---
    cache_key = _make_cache_key(question, statement_ids)
    cached = await cache_get(cache_key)
    if cached:
        data = json.loads(cached)
        yield f"data: {json.dumps({'meta': {'sql_used': data.get('sql_used'), 'sources': data.get('sources', [])}})}\n\n"
        yield f"data: {json.dumps({'chunk': data['answer']})}\n\n"
        yield "data: {\"done\": true}\n\n"
        return

    # --- Steps 1-2: classify + build context (fast, no streaming needed) ---
    intent = await intent_classifier.classify(question)
    context_text, sql_used = await context_builder.build(question, intent, statement_ids)

    sources = _extract_sources(context_text, intent)
    yield f"data: {json.dumps({'meta': {'sql_used': sql_used, 'sources': sources}})}\n\n"

    # --- Step 3: stream LLM response ---
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user",   "content": f"Context:\n{context_text}\n\nQuestion: {question}"},
    ]

    full_reply = ""
    async for chunk in llm_client.chat_stream(messages):
        full_reply += chunk
        yield f"data: {json.dumps({'chunk': chunk})}\n\n"

    yield "data: {\"done\": true}\n\n"

    # Cache the completed reply
    if not context_text.startswith("SQL error"):
        result = {
            "answer":  full_reply.strip(),
            "sources": sources,
            "sql_used": sql_used,
            "intent":  intent.value,
        }
        await cache_set(cache_key, json.dumps(result), ttl=CACHE_TTL)


def _make_cache_key(question: str, statement_ids: Optional[list[str]]) -> str:
    ids_str = ",".join(sorted(statement_ids)) if statement_ids else ""
    raw = f"{question.lower().strip()}|{ids_str}"
    return f"query:{hashlib.md5(raw.encode()).hexdigest()}"


def _extract_sources(context_text: str, intent) -> list[str]:
    """Pull chunk period labels from semantic context for display."""
    import re
    return re.findall(r"\[Chunk \d+ — [^\]]+\]", context_text)
