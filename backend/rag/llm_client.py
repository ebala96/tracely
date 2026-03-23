"""
Ollama /api/chat wrapper — supports both blocking and streaming modes.
"""
import json
import logging
import os
from typing import AsyncGenerator

import httpx

logger = logging.getLogger(__name__)

OLLAMA_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
LLM_MODEL  = os.environ.get("OLLAMA_LLM_MODEL", "qwen2.5:3b")

_OPTIONS = {"temperature": 0.1, "num_predict": 512}


async def chat(messages: list[dict]) -> str:
    """Send a chat request to Ollama and return the assistant reply as a string."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{OLLAMA_URL}/api/chat",
            json={"model": LLM_MODEL, "messages": messages, "stream": False, "options": _OPTIONS},
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]


async def chat_stream(messages: list[dict]) -> AsyncGenerator[str, None]:
    """Async generator yielding text chunks from Ollama streaming API."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream(
            "POST",
            f"{OLLAMA_URL}/api/chat",
            json={"model": LLM_MODEL, "messages": messages, "stream": True, "options": _OPTIONS},
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                chunk = data.get("message", {}).get("content", "")
                if chunk:
                    yield chunk
                if data.get("done"):
                    break
