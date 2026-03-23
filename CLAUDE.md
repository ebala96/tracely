# Spendly — Self-Hosted Bank Statement RAG

> **Privacy-first**: All LLM inference, embeddings, and data stay 100% local.
> No data leaves the machine. No external API calls ever.

---

## What This Is

Spendly parses bank statement PDFs, extracts and categorises transactions,
stores them in a local vector database + PostgreSQL, and lets you query your
spending in plain English via a chat interface powered by a local LLM.

Example queries:
- "How much did I spend on Swiggy in March?"
- "List all subscriptions this month"
- "Compare my food spending between February and March"
- "What were my top 5 merchants last quarter?"

---

## Core Tech Decisions

| Concern              | Choice                      | Reason                                               |
|----------------------|-----------------------------|------------------------------------------------------|
| Local LLM            | **Ollama** + `qwen2.5:7b`   | Runs locally, fast inference, great reasoning           |
| Embeddings           | **Ollama** + `nomic-embed-text` | Local, 768-dim, excellent semantic quality       |
| Vector DB            | **Qdrant** (Docker)         | Self-hosted, Rust-based, fast, great Python client   |
| Structured DB        | **PostgreSQL 16** (Docker)  | Transactions, categories, users, statement metadata  |
| Cache                | **Redis 7** (Docker)        | Query result caching, session store                  |
| Message queue        | **NATS JetStream** (Docker) | Async ingestion jobs, retry, backpressure            |
| API framework        | **FastAPI**                 | Async, typed, auto OpenAPI                           |
| PDF text extraction  | **pdfplumber**              | Best text + layout extraction for statements         |
| PDF table extraction | **Camelot**                 | Best table extraction; fallback to pdfplumber        |
| RAG orchestration    | **Custom** (no LangChain)   | Simpler, more transparent, easier to debug           |
| Frontend             | **React 18 + TypeScript + Vite** | Component-based UI, fast dev server             |
| Charts               | **Recharts**                | Simple, composable, works well with React            |
| Containerisation     | **Docker Compose**          | All services declared, one command startup           |

**Ollama model selection by available VRAM:**
- ~8GB VRAM: use `qwen2.5:7b` (~4.7 GB) — good balance of speed and quality
- ~16GB VRAM: use `qwen2.5:14b` or `llama3.1:13b` — better reasoning
- CPU only: use `qwen2.5:3b` — slower but functional

---

## Monorepo Structure

```
spendly/
├── CLAUDE.md                        # ← this file
├── docker-compose.yml               # All infrastructure services
├── .env                             # Environment variables (gitignored)
├── .env.example                     # Template to commit
├── categories.yml                   # Merchant → category taxonomy
│
├── backend/                         # Python FastAPI service
│   ├── pyproject.toml               # uv-managed dependencies
│   ├── main.py                      # FastAPI app entry point
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes/
│   │   │   ├── upload.py            # POST /api/upload — receive PDF
│   │   │   ├── query.py             # POST /api/query — chat queries
│   │   │   ├── transactions.py      # GET /api/transactions — CRUD
│   │   │   └── analytics.py         # GET /api/analytics — aggregations
│   │   └── middleware/
│   │       └── auth.py              # JWT verification
│   │
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── pipeline.py              # Orchestrates full ingestion flow
│   │   ├── pdf_parser.py            # pdfplumber text + metadata extraction
│   │   ├── table_extractor.py       # Camelot table extraction + fallback
│   │   ├── transaction_parser.py    # Row normalisation → Transaction objects
│   │   ├── chunker.py               # Semantic chunking for RAG
│   │   ├── embedder.py              # Ollama nomic-embed-text calls
│   │   └── categoriser.py           # Merchant → category (YAML + LLM fallback)
│   │
│   ├── rag/
│   │   ├── __init__.py
│   │   ├── query_engine.py          # Main entry: user query → answer
│   │   ├── intent_classifier.py     # Detects aggregation vs semantic queries
│   │   ├── retriever.py             # Qdrant vector search
│   │   ├── context_builder.py       # Combines vector + SQL results
│   │   └── llm_client.py            # Ollama /api/chat wrapper
│   │
│   ├── db/
│   │   ├── __init__.py
│   │   ├── postgres.py              # SQLAlchemy async engine + session
│   │   ├── qdrant_client.py         # Qdrant client + collection setup
│   │   ├── redis_client.py          # Redis client + cache helpers
│   │   └── models.py                # SQLAlchemy ORM models
│   │
│   ├── workers/
│   │   ├── __init__.py
│   │   └── nats_worker.py           # NATS JetStream consumer for ingestion jobs
│   │
│   └── schemas/
│       ├── __init__.py
│       └── models.py                # Pydantic request/response schemas
│
├── frontend/                        # React + TypeScript + Vite
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── api/
│       │   └── client.ts            # Typed fetch wrappers for all endpoints
│       ├── components/
│       │   ├── ChatInterface.tsx     # Main query chat UI
│       │   ├── PdfUploader.tsx       # Drag-drop upload with progress
│       │   ├── TransactionTable.tsx  # Paginated, filterable tx list
│       │   ├── CategoryChart.tsx     # Recharts pie/bar charts
│       │   └── MonthlyTrend.tsx      # Recharts line chart by month
│       └── pages/
│           ├── Dashboard.tsx
│           ├── Upload.tsx
│           └── Chat.tsx
│
└── scripts/
    ├── setup.sh                     # Pull Ollama models, init DBs
    └── seed_categories.py           # Load categories.yml into Postgres
```

---

## Docker Compose — All Services

**File: `docker-compose.yml`**

```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: spendly
      POSTGRES_USER: spendly
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U spendly"]
      interval: 5s
      timeout: 5s
      retries: 5

  qdrant:
    image: qdrant/qdrant:latest
    volumes:
      - qdrant_data:/qdrant/storage
    ports:
      - "6333:6333"   # HTTP API
      - "6334:6334"   # gRPC

  redis:
    image: redis:7-alpine
    command: redis-server --requirepass ${REDIS_PASSWORD}
    volumes:
      - redis_data:/data
    ports:
      - "6379:6379"

  nats:
    image: nats:latest
    command: "-js -m 8222"   # Enable JetStream + monitoring
    volumes:
      - nats_data:/data
    ports:
      - "4222:4222"   # Client connections
      - "8222:8222"   # HTTP monitoring

  ollama:
    image: ollama/ollama:latest
    volumes:
      - ollama_models:/root/.ollama
    ports:
      - "11434:11434"
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    environment:
      - OLLAMA_KEEP_ALIVE=24h   # Keep model loaded in VRAM

volumes:
  postgres_data:
  qdrant_data:
  redis_data:
  nats_data:
  ollama_models:
```

> **WSL2 GPU note**: For Ollama GPU passthrough in Docker on WSL2, ensure
> `nvidia-container-toolkit` is installed. Alternatively run Ollama natively
> on Windows (it auto-detects the GPU) and point the backend at
> `http://host.docker.internal:11434`.

---

## Environment Variables

**File: `.env.example`**

```env
# PostgreSQL
POSTGRES_PASSWORD=changeme
DATABASE_URL=postgresql+asyncpg://spendly:changeme@localhost:5432/spendly

# Qdrant
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=spendly_chunks

# Redis
REDIS_PASSWORD=changeme
REDIS_URL=redis://:changeme@localhost:6379/0

# NATS
NATS_URL=nats://localhost:4222
NATS_STREAM=SPENDLY
NATS_SUBJECT_INGEST=spendly.ingest

# Ollama (all local, no API key needed)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_LLM_MODEL=qwen2.5:7b
OLLAMA_EMBED_MODEL=nomic-embed-text

# App
JWT_SECRET=changeme_very_long_secret
UPLOAD_DIR=/tmp/spendly_uploads
```

---

## Database Schema (PostgreSQL)

**File: `backend/db/models.py`**

```python
from sqlalchemy import Column, String, Float, Date, DateTime, Integer, Text, ForeignKey, Enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship, DeclarativeBase
import uuid, enum

class Base(DeclarativeBase):
    pass

class StatementStatus(str, enum.Enum):
    pending    = "pending"
    processing = "processing"
    done       = "done"
    failed     = "failed"

class Statement(Base):
    """One uploaded PDF bank statement."""
    __tablename__ = "statements"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename     = Column(String, nullable=False)
    bank_name    = Column(String)               # "HDFC", "SBI", etc — parsed from PDF
    period_start = Column(Date)                 # Statement period start
    period_end   = Column(Date)                 # Statement period end
    status       = Column(Enum(StatementStatus), default=StatementStatus.pending)
    uploaded_at  = Column(DateTime(timezone=True))
    processed_at = Column(DateTime(timezone=True))
    error_msg    = Column(Text)                 # Set on failure

    transactions = relationship("Transaction", back_populates="statement")


class Category(Base):
    """Top-level spending categories loaded from categories.yml."""
    __tablename__ = "categories"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    name         = Column(String, unique=True, nullable=False)  # "Food & Dining"
    slug         = Column(String, unique=True, nullable=False)  # "food_dining"
    icon         = Column(String)                               # emoji or icon name
    colour       = Column(String)                               # hex colour for charts

    transactions = relationship("Transaction", back_populates="category")


class Transaction(Base):
    """One normalised transaction row extracted from a statement."""
    __tablename__ = "transactions"

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    statement_id   = Column(UUID(as_uuid=True), ForeignKey("statements.id"), nullable=False)
    category_id    = Column(Integer, ForeignKey("categories.id"))

    date           = Column(Date, nullable=False)
    description    = Column(Text, nullable=False)    # Raw description from statement
    merchant       = Column(String)                  # Normalised merchant name
    amount         = Column(Float, nullable=False)   # Always positive
    txn_type       = Column(String)                  # "debit" | "credit"
    balance        = Column(Float)                   # Running balance if available
    ref_number     = Column(String)                  # UTR/ref from bank
    raw_row        = Column(Text)                    # Original CSV row for debugging

    statement = relationship("Statement", back_populates="transactions")
    category  = relationship("Category", back_populates="transactions")
```

---

## categories.yml — Merchant Taxonomy

**File: `categories.yml`**

```yaml
categories:
  - name: Food & Dining
    slug: food_dining
    icon: "🍔"
    colour: "#F97316"
    merchants:
      - swiggy
      - zomato
      - dunzo
      - blinkit
      - uber eats
      - dominos
      - pizza hut
      - mcdonalds
      - kfc
      - starbucks

  - name: Transport
    slug: transport
    icon: "🚗"
    colour: "#3B82F6"
    merchants:
      - uber
      - ola
      - rapido
      - namma yatri
      - yulu
      - metro
      - irctc
      - redbus
      - makemytrip flights

  - name: Subscriptions
    slug: subscriptions
    icon: "📺"
    colour: "#8B5CF6"
    merchants:
      - netflix
      - spotify
      - amazon prime
      - hotstar
      - zee5
      - sonyliv
      - youtube premium
      - apple music
      - notion
      - github

  - name: Shopping
    slug: shopping
    icon: "🛍️"
    colour: "#EC4899"
    merchants:
      - amazon
      - flipkart
      - myntra
      - ajio
      - nykaa
      - meesho
      - snapdeal

  - name: Utilities
    slug: utilities
    icon: "⚡"
    colour: "#EAB308"
    merchants:
      - bescom
      - tata power
      - airtel
      - jio
      - bsnl
      - vi
      - act broadband
      - bbmp

  - name: Health
    slug: health
    icon: "🏥"
    colour: "#10B981"
    merchants:
      - apollo pharmacy
      - medplus
      - netmeds
      - 1mg
      - pharmeasy
      - cult fit
      - healthkart

  - name: Finance
    slug: finance
    icon: "🏦"
    colour: "#6B7280"
    merchants:
      - lic
      - hdfc life
      - icici prudential
      - sip
      - mutual fund
      - zerodha
      - groww
      - nps

  - name: Groceries
    slug: groceries
    icon: "🛒"
    colour: "#84CC16"
    merchants:
      - bigbasket
      - grofers
      - jiomart
      - dmmart
      - reliance fresh
      - more supermarket
      - licious

  - name: Other
    slug: other
    icon: "📦"
    colour: "#9CA3AF"
    merchants: []   # catch-all; LLM assigns this when uncertain
```

---

## Ingestion Pipeline Detail

### 1. Upload → NATS

**File: `backend/api/routes/upload.py`**

```python
"""
POST /api/upload
- Accepts multipart PDF upload
- Saves to UPLOAD_DIR/{statement_id}.pdf
- Creates Statement row in Postgres (status=pending)
- Publishes ingestion job to NATS JetStream
- Returns {statement_id, status} immediately — ingestion is async
"""
```

### 2. NATS Worker — consumes job

**File: `backend/workers/nats_worker.py`**

```python
"""
JetStream consumer on subject: spendly.ingest

On message received:
  payload = {statement_id: uuid, pdf_path: str}

Steps:
  1. Update statement status → processing
  2. Call ingestion.pipeline.run(pdf_path, statement_id)
  3. Update statement status → done (or failed + error_msg)
  4. Ack the message

Use push-based consumer with AckExplicit.
Retry up to 3 times on failure (JetStream handles redelivery).
"""
```

### 3. Ingestion Pipeline

**File: `backend/ingestion/pipeline.py`**

```python
"""
Full pipeline for one PDF:

Step 1 — PDF parsing (pdf_parser.py)
  - Open PDF with pdfplumber
  - Extract: full text, page count, metadata
  - Detect bank name from header text (regex patterns per bank)
  - Detect statement period from header

Step 2 — Table extraction (table_extractor.py)
  PRIMARY: Try Camelot (lattice mode for bordered tables, stream for borderless)
    - Returns list[DataFrame], one per detected table
    - Filter: keep only tables with 4+ columns and 3+ rows
  FALLBACK: pdfplumber .extract_tables() if Camelot finds nothing
  OUTPUT: List of raw DataFrames

Step 3 — Transaction parsing (transaction_parser.py)
  For each DataFrame row:
    - Detect column mapping: date, description, debit, credit, balance
      (column names vary per bank — use fuzzy matching on headers)
    - Parse date (handle DD/MM/YYYY, DD-MMM-YYYY, YYYY-MM-DD)
    - Parse amount (strip commas, handle Dr/Cr suffixes)
    - Determine txn_type: debit if debit col has value, else credit
    - Extract ref number with regex (UTR\d+, NEFT/\w+, etc.)
  OUTPUT: List[Transaction] (Pydantic objects, not yet in DB)

Step 4 — Categorisation (categoriser.py)
  For each transaction:
    - Lowercase the description
    - Check against categories.yml merchant list (substring match)
    - If match found → assign category
    - If no match → call Ollama LLM with:
        system: "You are a financial transaction categoriser."
        user: f"Transaction: '{description}'. 
               Categories: {category_list}.
               Reply with ONLY the category slug."
    - Cache LLM category results in Redis (key: hash of description)
  OUTPUT: Transactions with category_id assigned

Step 5 — Persist to PostgreSQL
  - Bulk insert all Transaction rows
  - Update Statement.period_start, period_end, status=done

Step 6 — Chunk + Embed for RAG (chunker.py + embedder.py)
  Chunking strategy:
    - Group transactions by week (7-day windows)
    - Each chunk = one week's transactions as structured text block:
        "Transactions 01-Mar to 07-Mar 2025:
         - 02-Mar | Swiggy | Food & Dining | ₹340.00 (debit)
         - 04-Mar | Uber | Transport | ₹120.00 (debit)
         ..."
    - Also create one chunk per statement summary (totals per category)
  
  Embedding:
    - Call Ollama nomic-embed-text for each chunk
    - Returns 768-dim vector
  
  Qdrant payload per point:
    {
      id: uuid,
      vector: [768 floats],
      payload: {
        statement_id: str,
        chunk_type: "weekly" | "summary",
        period_start: "2025-03-01",
        period_end: "2025-03-07",
        text: "<the full chunk text>",
        transaction_ids: [list of tx UUIDs in this chunk]
      }
    }
"""
```

---

## RAG Query Engine Detail

**File: `backend/rag/query_engine.py`**

```python
"""
POST /api/query
Body: {question: str, statement_ids: list[str] | None}

Full flow:

Step 1 — Intent Classification (intent_classifier.py)
  Classify the query into one of:
    A) AGGREGATION  — needs SQL: "how much", "total", "sum", "count"
    B) LISTING      — needs SQL + format: "list all", "show me", "what were"
    C) SEMANTIC     — needs vector search: "what kind of", "any unusual"
    D) COMPARISON   — needs SQL across periods: "compare", "vs", "difference"
  
  Use simple keyword rules first.
  If ambiguous, call Ollama with a classification prompt.

Step 2 — Context Building (context_builder.py)
  
  For AGGREGATION / LISTING / COMPARISON:
    - Build parameterised SQL query directly from intent
    - Execute against PostgreSQL
    - Format result as structured text for LLM context
    Example SQL for "swiggy spend in march":
      SELECT SUM(amount), COUNT(*) FROM transactions
      WHERE LOWER(description) LIKE '%swiggy%'
        AND date BETWEEN '2025-03-01' AND '2025-03-31'
        AND txn_type = 'debit'
  
  For SEMANTIC:
    - Embed the query with Ollama nomic-embed-text
    - Search Qdrant: top_k=5, filter by statement_ids if provided
    - Retrieve chunk texts
    - Also run a broad SQL to get supporting transaction rows

Step 3 — Prompt Assembly
  System prompt:
    "You are Spendly, a personal finance assistant. 
     Answer questions about the user's bank transactions.
     Use ONLY the context provided. Do not invent transactions.
     Format amounts in Indian Rupees (₹). 
     If you cannot answer from the context, say so clearly."
  
  User message:
    f"Context:\n{context_text}\n\nQuestion: {question}"

Step 4 — Ollama LLM Call (llm_client.py)
  POST http://localhost:11434/api/chat
  {
    "model": "qwen2.5:7b",
    "messages": [system_msg, user_msg],
    "stream": false,
    "options": {
      "temperature": 0.1,    # Low temp for factual financial answers
      "num_predict": 512
    }
  }

Step 5 — Cache + Return
  - Cache response in Redis: key = hash(question + statement_ids), TTL = 1 hour
  - Return: {answer: str, sources: [chunk refs], sql_used: str | None}
"""
```

---

## Analytics Endpoints

**File: `backend/api/routes/analytics.py`**

```python
"""
All endpoints return pre-aggregated data — no LLM involved.

GET /api/analytics/monthly
  Query: ?year=2025&statement_id=...
  Returns: [{month: "Jan", total_debit: 12000, total_credit: 5000}, ...]

GET /api/analytics/categories
  Query: ?from=2025-01-01&to=2025-03-31&statement_id=...
  Returns: [{category: "Food & Dining", total: 4500, count: 23}, ...]

GET /api/analytics/merchants
  Query: ?limit=10&statement_id=...
  Returns top merchants by total spend: [{merchant: "Swiggy", total: 3200, count: 14}]

GET /api/analytics/timeline
  Query: ?merchant=swiggy&statement_id=...
  Returns daily spend for a specific merchant: [{date: "2025-03-05", amount: 340}]
"""
```

---

## Frontend Component Responsibilities

**`PdfUploader.tsx`**
- Drag-and-drop zone (react-dropzone)
- Multi-file queue, one at a time
- Poll `GET /api/statements/{id}` every 3 seconds until `status === "done"`
- Show progress: Uploading → Parsing → Embedding → Done

**`ChatInterface.tsx`**
- Textarea for natural language input
- Statement selector (filter queries to specific uploads)
- Message history with user/assistant bubbles
- Show `sql_used` in a collapsible "How I answered" section

**`TransactionTable.tsx`**
- Server-side pagination (page, page_size, sort, filter params)
- Column filters: date range, category, merchant, min/max amount
- Inline category badge with colour from categories.yml
- CSV export button

**`CategoryChart.tsx`**
- Recharts `PieChart` + `Legend`
- Date range picker to re-fetch
- Click a slice → filters TransactionTable to that category

**`MonthlyTrend.tsx`**
- Recharts `AreaChart` or `BarChart`
- Two series: Total Debit, Total Credit
- Toggle individual categories on/off

---

## Python Dependencies

**File: `backend/pyproject.toml`**

```toml
[project]
name = "spendly-backend"
version = "0.1.0"
requires-python = ">=3.11"

dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.30",
  "sqlalchemy[asyncio]>=2.0",
  "asyncpg>=0.30",           # async PostgreSQL driver
  "alembic>=1.13",           # DB migrations
  "pydantic>=2.0",
  "pydantic-settings>=2.0",
  "pdfplumber>=0.11",
  "camelot-py[cv]>=0.11",    # needs ghostscript + opencv
  "pandas>=2.0",
  "qdrant-client>=1.9",
  "nats-py>=2.7",
  "redis[hiredis]>=5.0",
  "httpx>=0.27",             # for Ollama HTTP calls
  "python-multipart>=0.0.9", # for file upload
  "python-jose[cryptography]>=3.3",  # JWT
  "pyyaml>=6.0",
  "rapidfuzz>=3.0",          # fuzzy merchant matching
  "python-dateutil>=2.9",    # flexible date parsing
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

---

## Frontend Dependencies

**File: `frontend/package.json`** (key deps)

```json
{
  "dependencies": {
    "react": "^18.3",
    "react-dom": "^18.3",
    "typescript": "^5.5",
    "vite": "^5.4",
    "recharts": "^2.12",
    "react-dropzone": "^14.2",
    "date-fns": "^3.6",
    "zustand": "^4.5",
    "axios": "^1.7",
    "@tanstack/react-query": "^5.0",
    "clsx": "^2.1",
    "tailwindcss": "^3.4"
  }
}
```

---

## Setup Script

**File: `scripts/setup.sh`**

```bash
#!/bin/bash
set -e

echo "=== Spendly Setup ==="

# 1. Copy env
cp .env.example .env
echo "→ Edit .env and set strong passwords, then re-run this script"

# 2. Start infrastructure
docker compose up -d postgres qdrant redis nats

# 3. Wait for postgres
echo "→ Waiting for PostgreSQL..."
until docker compose exec postgres pg_isready -U spendly; do sleep 2; done

# 4. Run migrations
cd backend
pip install uv
uv sync
uv run alembic upgrade head
cd ..

# 5. Seed categories
uv run python scripts/seed_categories.py

# 6. Pull Ollama models (run Ollama natively or in Docker)
echo "→ Pulling Ollama models (this will take a while)..."
ollama pull qwen2.5:7b
ollama pull nomic-embed-text

echo "=== Setup complete ==="
echo "Start backend: cd backend && uv run uvicorn main:app --reload"
echo "Start worker:  cd backend && uv run python -m workers.nats_worker"
echo "Start frontend: cd frontend && npm install && npm run dev"
```

---

## Build Order for Claude Code

Implement in this exact sequence to avoid broken dependencies:

1. **`docker-compose.yml`** — infrastructure first, start it up
2. **`backend/db/models.py`** — ORM models
3. **`backend/db/postgres.py`** — async SQLAlchemy engine
4. **`backend/db/qdrant_client.py`** — Qdrant client + create collection
5. **`backend/db/redis_client.py`** — Redis client + cache helpers
6. **`backend/schemas/models.py`** — Pydantic schemas (request/response)
7. **`categories.yml`** — merchant taxonomy
8. **`scripts/seed_categories.py`** — loads YAML into Category table
9. **`backend/ingestion/pdf_parser.py`** — pdfplumber wrapper
10. **`backend/ingestion/table_extractor.py`** — Camelot + fallback
11. **`backend/ingestion/transaction_parser.py`** — normalise rows
12. **`backend/ingestion/categoriser.py`** — YAML match + Ollama fallback
13. **`backend/ingestion/chunker.py`** — weekly chunk builder
14. **`backend/ingestion/embedder.py`** — Ollama nomic-embed-text calls
15. **`backend/ingestion/pipeline.py`** — orchestrates 9–14
16. **`backend/rag/llm_client.py`** — Ollama /api/chat wrapper
17. **`backend/rag/intent_classifier.py`** — keyword + LLM classify
18. **`backend/rag/retriever.py`** — Qdrant vector search
19. **`backend/rag/context_builder.py`** — SQL + vector context merge
20. **`backend/rag/query_engine.py`** — orchestrates 17–19
21. **`backend/workers/nats_worker.py`** — JetStream consumer
22. **`backend/api/routes/upload.py`** — upload endpoint
23. **`backend/api/routes/query.py`** — query endpoint
24. **`backend/api/routes/transactions.py`** — CRUD endpoints
25. **`backend/api/routes/analytics.py`** — aggregation endpoints
26. **`backend/main.py`** — FastAPI app wiring
27. **`frontend/`** — React app, implement pages in order: Upload → Transactions → Chat → Dashboard

---

## Key Implementation Notes

### Ollama LLM Client — no streaming for now

```python
# backend/rag/llm_client.py
import httpx, os

OLLAMA_URL = os.environ["OLLAMA_BASE_URL"]
LLM_MODEL  = os.environ["OLLAMA_LLM_MODEL"]

async def chat(messages: list[dict]) -> str:
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": LLM_MODEL,
                "messages": messages,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 512}
            }
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]
```

### Qdrant Collection Setup

```python
# backend/db/qdrant_client.py
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, VectorParams

COLLECTION = "spendly_chunks"

async def get_client() -> AsyncQdrantClient:
    client = AsyncQdrantClient(url=os.environ["QDRANT_URL"])
    
    existing = [c.name for c in await client.get_collections()]
    if COLLECTION not in existing:
        await client.create_collection(
            collection_name=COLLECTION,
            vectors_config=VectorParams(size=768, distance=Distance.COSINE)
        )
    return client
```

### Categoriser — YAML match then LLM fallback

```python
# backend/ingestion/categoriser.py
import yaml, hashlib
from rapidfuzz import fuzz

def load_taxonomy(path="categories.yml") -> dict:
    with open(path) as f:
        data = yaml.safe_load(f)
    # Build: {merchant_keyword → category_slug}
    lookup = {}
    for cat in data["categories"]:
        for merchant in cat["merchants"]:
            lookup[merchant.lower()] = cat["slug"]
    return lookup

async def categorise(description: str, taxonomy: dict, redis, llm_client) -> str:
    desc_lower = description.lower()
    
    # 1. Exact / substring match
    for keyword, slug in taxonomy.items():
        if keyword in desc_lower:
            return slug
    
    # 2. Fuzzy match (threshold 85)
    for keyword, slug in taxonomy.items():
        if fuzz.partial_ratio(keyword, desc_lower) >= 85:
            return slug
    
    # 3. Redis cache for LLM results
    cache_key = f"cat:{hashlib.md5(desc_lower.encode()).hexdigest()}"
    cached = await redis.get(cache_key)
    if cached:
        return cached.decode()
    
    # 4. LLM fallback
    slugs = list(set(taxonomy.values()))
    slug = await llm_client.chat([
        {"role": "system", "content": "You classify bank transactions. Reply with ONLY the category slug, nothing else."},
        {"role": "user", "content": f"Transaction: '{description}'\nCategories: {slugs}\nReply with one slug:"}
    ])
    slug = slug.strip().lower()
    
    await redis.setex(cache_key, 86400, slug)  # Cache 24h
    return slug
```

### NATS JetStream — stream + consumer setup

```python
# backend/workers/nats_worker.py
import nats, json, asyncio
from nats.js.api import StreamConfig, ConsumerConfig, AckPolicy

STREAM  = "SPENDLY"
SUBJECT = "spendly.ingest"

async def setup_stream(js):
    try:
        await js.add_stream(StreamConfig(
            name=STREAM,
            subjects=[SUBJECT],
            retention="workqueue",  # Message deleted after ack
            max_deliver=3           # Retry 3 times on failure
        ))
    except Exception:
        pass  # Stream already exists

async def run_worker():
    nc = await nats.connect(os.environ["NATS_URL"])
    js = nc.jetstream()
    await setup_stream(js)
    
    sub = await js.pull_subscribe(SUBJECT, durable="ingest-worker")
    
    while True:
        try:
            msgs = await sub.fetch(1, timeout=5)
            for msg in msgs:
                payload = json.loads(msg.data)
                try:
                    await pipeline.run(
                        payload["pdf_path"],
                        payload["statement_id"]
                    )
                    await msg.ack()
                except Exception as e:
                    await msg.nak()  # JetStream will redeliver
        except Exception:
            await asyncio.sleep(1)
```

---

## Privacy Guarantees

- **No data leaves localhost**: Ollama, Qdrant, PostgreSQL, Redis, NATS all run locally via Docker
- **No Ollama cloud**: `ollama serve` runs in Docker with no outbound telemetry
- **No embedding API**: `nomic-embed-text` runs locally via Ollama
- **PDF uploads**: stored in local filesystem only, never uploaded to cloud storage
- **Zero analytics/telemetry**: all Docker images run airgapped; add `--network=none` to Qdrant/NATS in docker-compose if you want full network isolation

---

*Spendly — your money, your machine.*