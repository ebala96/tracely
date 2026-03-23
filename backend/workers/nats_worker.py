"""
NATS JetStream consumer — picks up ingestion jobs published by the upload route.
"""
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

# Ensure backend package root is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")

import nats
from nats.js.api import StreamConfig

from db.models import StatementStatus
from db.postgres import AsyncSessionLocal
from ingestion import pipeline

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

NATS_URL    = os.environ.get("NATS_URL", "nats://localhost:4222")
STREAM      = os.environ.get("NATS_STREAM", "SPENDLY")
SUBJECT     = os.environ.get("NATS_SUBJECT_INGEST", "spendly.ingest")
DURABLE     = "ingest-worker"


async def setup_stream(js):
    config = StreamConfig(
        name=STREAM,
        subjects=[SUBJECT],
        retention="workqueue",
    )
    try:
        await js.add_stream(config)
        logger.info("Stream '%s' created", STREAM)
    except Exception:
        # Stream exists — update it to ensure subjects are correct
        try:
            await js.update_stream(config)
            logger.info("Stream '%s' updated with subjects", STREAM)
        except Exception as e:
            logger.warning("Could not update stream: %s", e)


async def run_worker():
    nc = await nats.connect(NATS_URL)
    js = nc.jetstream()
    await setup_stream(js)

    sub = await js.pull_subscribe(SUBJECT, durable=DURABLE)
    logger.info("Worker listening on subject: %s", SUBJECT)

    while True:
        try:
            msgs = await sub.fetch(1, timeout=5)
            for msg in msgs:
                payload = json.loads(msg.data)
                statement_id = payload["statement_id"]
                pdf_path     = payload["pdf_path"]
                logger.info("Processing statement %s", statement_id)
                try:
                    await pipeline.run(pdf_path, statement_id)
                    await msg.ack()
                    logger.info("Done: %s", statement_id)
                except Exception as e:
                    logger.exception("Failed: %s — %s", statement_id, e)
                    await msg.nak()
        except nats.errors.TimeoutError:
            pass  # No messages — keep polling
        except Exception as e:
            logger.warning("Worker error: %s", e)
            await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(run_worker())
