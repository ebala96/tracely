# Tracely — Self-Hosted Bank Statement Analyser

> **Privacy-first**: all LLM inference, embeddings, and data stay 100% local.
> No data leaves your machine. No external API calls. Ever.

Tracely parses bank statement PDFs, extracts and categorises every transaction, stores them locally, and lets you query your spending in plain English through a chat interface powered by a local LLM.

---

## Features

- **PDF ingestion** — upload any Indian bank statement PDF; Tracely extracts all transactions automatically
- **Smart categorisation** — keyword matching + LLM fallback assigns categories and subcategories to every transaction
- **User learning** — correct a category once, teach it to all similar transactions with one click
- **Natural language chat** — ask questions like *"How much did I spend on Swiggy in March?"* or *"Compare my food spending between February and March"*
- **Streaming responses** — LLM answers stream token-by-token in real time
- **Analytics dashboard** — monthly trend charts, category breakdowns (expenses & income), top merchants, recurring transaction detection, summary cards
- **Bulk category editing** — select multiple transactions and re-categorise in one action
- **Income categories** — salary, freelance, refunds, dividends, transfers received — separate from expenses
- **Universal bank support** — fuzzy column matching + per-bank overrides for 30+ Indian banks; text-line fallback for borderless PDFs
- **CSV export** — export any filtered view

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Browser (React)                          │
│   Dashboard  │  Transactions  │  Chat  │  Upload                │
└──────────────────────┬──────────────────────────────────────────┘
                       │ HTTP / SSE
┌──────────────────────▼──────────────────────────────────────────┐
│                    FastAPI Backend                               │
│                                                                  │
│  /api/upload   /api/transactions   /api/analytics   /api/query  │
└──────┬──────────────────────────────────────────┬───────────────┘
       │ NATS JetStream                            │
       ▼                                           ▼
┌─────────────┐                          ┌─────────────────────┐
│ NATS Worker │                          │    RAG Engine        │
│  (ingestion)│                          │                      │
└──────┬──────┘                          │  1. Classify intent  │
       │                                 │  2. Build context    │
       ▼                                 │     (SQL + Qdrant)   │
┌─────────────────────────────┐          │  3. Stream LLM reply │
│     Ingestion Pipeline       │          └──────────┬──────────┘
│                              │                     │
│  PDF → Tables → Transactions │          ┌──────────▼──────────┐
│  → Categorise → Persist      │          │      Ollama          │
│  → Chunk → Embed             │          │  qwen2.5 (LLM)       │
└──────┬──────────────────────┘          │  nomic-embed-text     │
       │                                 └─────────────────────┘
       ▼
┌──────────────────────────────────────────────────────────────┐
│                     Data Layer                                │
│                                                              │
│   PostgreSQL          Qdrant              Redis              │
│   (transactions,      (vector             (query cache,      │
│    categories,         chunks for          LLM category      │
│    statements,         RAG search)         cache)            │
│    user rules)                                               │
└──────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Concern | Choice | Why |
|---|---|---|
| Local LLM | **Ollama** + `qwen2.5:7b` | Runs locally, fast inference, great reasoning |
| Embeddings | **Ollama** + `nomic-embed-text` | Local, 768-dim, excellent semantic quality |
| Vector DB | **Qdrant** (Docker) | Self-hosted, Rust-based, fast Python client |
| Relational DB | **PostgreSQL 16** (Docker) | Transactions, categories, statement metadata |
| Cache | **Redis 7** (Docker) | Query result caching, LLM category cache |
| Message queue | **NATS JetStream** (Docker) | Async ingestion jobs with retry and backpressure |
| API framework | **FastAPI** | Async, typed, auto OpenAPI docs |
| PDF text extraction | **pdfplumber** | Best text + layout extraction |
| PDF table extraction | **Camelot** | Best structured table extraction; fallback to pdfplumber |
| RAG orchestration | **Custom** (no LangChain) | Simpler, more transparent, easier to debug |
| Frontend | **React 18 + TypeScript + Vite** | Component-based UI, fast dev server |
| Charts | **Recharts** | Simple, composable, works well with React |
| Containerisation | **Docker Compose** | All infrastructure declared, one command startup |

**Ollama model selection by available VRAM:**
- ~8GB VRAM: `qwen2.5:7b` (~4.7 GB) — good balance of speed and quality
- ~16GB VRAM: `qwen2.5:14b` or `llama3.1:13b` — better reasoning
- CPU only: `qwen2.5:3b` — slower but functional

---

## System Design

### Ingestion Pipeline

When a PDF is uploaded the following steps run asynchronously via a NATS worker:

```
1. PDF Parsing       — pdfplumber extracts full text, detects bank name (30+ banks)
                       and statement period from header patterns

2. Table Extraction  — Camelot lattice mode (bordered tables)
                     → Camelot stream mode (borderless)
                     → pdfplumber extract_tables()
                     → Text-line fallback (regex date+amount scan per line)

3. Column Mapping    — Bank-specific column overrides tried first (HDFC, ICICI, SBI,
                       Axis, Kotak, and 10+ more), then generic fuzzy matching via
                       rapidfuzz against known aliases for date/description/debit/
                       credit/balance/ref columns. Auto-detects Dr/Cr flag columns.

4. Transaction Parse — Normalises dates (DD/MM/YYYY, DD-Mon-YYYY, YYYY-MM-DD),
                       amounts (strips ₹/commas/Dr/Cr suffixes), determines txn_type.
                       Deterministic UUID per transaction (MD5 of natural key) makes
                       re-ingestion idempotent via ON CONFLICT DO NOTHING.

5. Categorisation    — Priority order:
                       a. User-learned rules (DB patterns from manual corrections)
                       b. Subcategory keyword substring match
                       c. Parent category keyword match
                       d. Fuzzy match (threshold 85 via rapidfuzz)
                       e. Redis-cached LLM result (24h TTL)
                       f. Ollama LLM call → cached in Redis
                       Income categories (salary, refunds, dividends…) only match
                       credit transactions; expense categories only match debits.

6. Persist           — Bulk insert transactions into PostgreSQL

7. Chunk + Embed     — Transactions grouped into weekly text chunks + one summary
                       chunk per statement. Each chunk embedded via nomic-embed-text
                       and stored in Qdrant with statement_id / period metadata.

8. Cache bust        — Redis query cache cleared so chat reflects new data immediately
```

### RAG Query Engine

```
User question
      │
      ▼
1. Intent Classification
   AGGREGATION  — "how much", "total", "sum"
   LISTING      — "list all", "show me", "what were"
   COMPARISON   — "compare", "vs", "difference between"
   SEMANTIC     — "any unusual", "what kind of"

      │
      ▼
2. Context Building
   SQL path (AGGREGATION/LISTING/COMPARISON):
     - Extract subcategory, merchant, category, date range, amount range
     - Income keywords (salary, refund, dividend…) auto-switch txn_type=credit
     - Build parameterised SQL → execute → format as table

   Vector path (SEMANTIC):
     - Embed question with nomic-embed-text
     - Search Qdrant top-5 chunks filtered by statement_ids
     - Return chunk texts as context

      │
      ▼
3. LLM Prompt
   System: "You are Tracely, a personal finance assistant…"
   User:   "Context:\n{sql or vector results}\n\nQuestion: {question}"

      │
      ▼
4. Streaming Response (SSE)
   - Metadata event first (sql_used, sources)
   - Token chunks as they arrive from Ollama
   - Full reply cached in Redis (1h TTL) for identical future questions
```

### User Learning System

When a user manually corrects a transaction's category:
1. The correction is saved to `UserCategoryRule` (merchant pattern + description keyword)
2. A **"Pattern saved"** badge appears with an **"Apply Pattern"** button
3. Clicking Apply runs `backfill_similar()` — updates all non-user-corrected transactions matching the same pattern

### Category Taxonomy

Categories are defined in `categories.yml` with a two-level hierarchy:

```
Parent category  (e.g. Food & Dining)
  └── Subcategory (e.g. Fast Food → Domino's, KFC, McDonald's)
  └── Subcategory (e.g. Coffee & Cafes → Starbucks, CCD)
```

Income categories are tagged `txn_type: credit` so they never contaminate expense categorisation.

---

## Project Structure

```
tracely/
├── .env.example                 # Environment variable template
├── .gitignore
├── categories.yml               # Full category + subcategory taxonomy
├── docker-compose.yml           # All infrastructure services
│
├── backend/                     # Python FastAPI service
│   ├── main.py                  # App entry point, router registration
│   ├── pyproject.toml           # uv-managed Python dependencies
│   │
│   ├── api/routes/
│   │   ├── upload.py            # POST /api/upload
│   │   ├── query.py             # POST /api/query, POST /api/query/stream
│   │   ├── transactions.py      # GET/PATCH /api/transactions
│   │   ├── analytics.py         # GET /api/analytics/*
│   │   └── categories.py        # GET/POST/PATCH/DELETE /api/categories
│   │
│   ├── ingestion/
│   │   ├── pipeline.py          # Orchestrates the full ingestion flow
│   │   ├── pdf_parser.py        # Bank name + period detection
│   │   ├── table_extractor.py   # Camelot + pdfplumber + text-line fallback
│   │   ├── transaction_parser.py# Column mapping, amount/date parsing, merchant normalisation
│   │   ├── categoriser.py       # Keyword + LLM category assignment
│   │   ├── rule_learner.py      # User-correction pattern learning
│   │   ├── chunker.py           # Weekly text chunks for RAG
│   │   └── embedder.py          # Ollama nomic-embed-text calls
│   │
│   ├── rag/
│   │   ├── query_engine.py      # answer() + stream_answer() entry points
│   │   ├── intent_classifier.py # Keyword + LLM intent detection
│   │   ├── context_builder.py   # SQL builder + Qdrant retrieval
│   │   ├── retriever.py         # Qdrant vector search
│   │   └── llm_client.py        # Ollama chat() + chat_stream()
│   │
│   ├── db/
│   │   ├── models.py            # SQLAlchemy ORM (Statement, Transaction, Category, UserCategoryRule)
│   │   ├── postgres.py          # Async engine + session factory
│   │   ├── qdrant_client.py     # Qdrant client + collection initialisation
│   │   └── redis_client.py      # Redis client + cache helpers
│   │
│   ├── workers/
│   │   └── nats_worker.py       # JetStream consumer — triggers ingestion pipeline
│   │
│   ├── schemas/models.py        # Pydantic request/response schemas
│   └── migrations/              # Alembic migration scripts
│
├── frontend/                    # React + TypeScript + Vite
│   └── src/
│       ├── api/client.ts        # Typed API wrappers for all endpoints
│       ├── components/
│       │   ├── ChatInterface.tsx    # Streaming chat UI
│       │   ├── TransactionTable.tsx # Paginated table with bulk edit + filters
│       │   ├── CategoryChart.tsx    # Donut chart — expenses / income toggle
│       │   ├── MonthlyTrend.tsx     # Area chart — debit vs credit by month
│       │   └── PdfUploader.tsx      # Drag-drop upload with status polling
│       └── pages/
│           ├── Dashboard.tsx    # Summary cards + charts + recurring + transactions
│           ├── Upload.tsx
│           └── Chat.tsx
│
└── scripts/
    ├── setup.sh                 # First-time setup (Docker, migrations, seed, Ollama)
    ├── start.sh                 # Start backend + worker + frontend
    ├── stop.sh                  # Stop all app processes
    ├── teardown.sh              # Stop app + Docker infrastructure
    ├── start-backend.sh
    ├── start-worker.sh
    ├── start-frontend.sh
    └── seed_categories.py       # Load categories.yml into PostgreSQL
```

---

## Setup

### Prerequisites

- **Docker + Docker Compose** — for PostgreSQL, Qdrant, Redis, NATS
- **Python 3.11+** with [uv](https://github.com/astral-sh/uv) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- **Node.js 18+** — for the frontend
- **Ollama** — install from [ollama.com](https://ollama.com) and pull models:
  ```bash
  ollama pull qwen2.5:7b
  ollama pull nomic-embed-text
  ```

> **WSL2 users**: Run Ollama natively on Windows (it auto-detects the GPU). Set `OLLAMA_BASE_URL=http://host.docker.internal:11434` in your `.env`.

### First-time setup

```bash
git clone <repo-url> tracely
cd tracely

# Run setup — creates .env, starts Docker, runs migrations, seeds categories
bash scripts/setup.sh
```

The script will pause after creating `.env` and ask you to set passwords. Edit `.env` then re-run:

```bash
# Edit passwords
nano .env

# Re-run to complete setup
bash scripts/setup.sh
```

### Start the application

```bash
bash scripts/start.sh
```

This starts three processes in the background:
- **Backend** → `http://localhost:8000` (logs: `logs/backend.log`)
- **Worker** → NATS JetStream consumer (logs: `logs/worker.log`)
- **Frontend** → `http://localhost:5173` (logs: `logs/frontend.log`)

### Stop

```bash
bash scripts/stop.sh          # Stop app processes only
bash scripts/teardown.sh      # Stop app + Docker (data preserved)
docker compose down -v        # Stop Docker + delete all data volumes
```

### After changing categories

Re-seed the category table and re-run categorisation on existing transactions:

```bash
uv run --project backend python scripts/seed_categories.py
curl -X POST http://localhost:8000/api/transactions/recategorize
```

---

## Environment Variables

Copy `.env.example` to `.env` and fill in your values:

```env
# PostgreSQL
POSTGRES_PASSWORD=your_strong_password
DATABASE_URL=postgresql+asyncpg://spendly:your_strong_password@localhost:5432/spendly

# Qdrant
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=spendly_chunks

# Redis
REDIS_PASSWORD=your_strong_password
REDIS_URL=redis://:your_strong_password@localhost:6379/0

# NATS
NATS_URL=nats://localhost:4222

# Ollama — all local, no API key needed
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_LLM_MODEL=qwen2.5:7b
OLLAMA_EMBED_MODEL=nomic-embed-text

# App
JWT_SECRET=a_very_long_random_secret_string
UPLOAD_DIR=/tmp/spendly_uploads
```

---

## Database Schema

```
statements          — one row per uploaded PDF
  id, filename, bank_name, period_start, period_end,
  status (pending/processing/done/failed), uploaded_at, error_msg

transactions        — one row per extracted transaction line
  id (deterministic UUID), statement_id, date, description,
  merchant, amount, txn_type (debit/credit), balance,
  category_id, subcategory_id, user_corrected, ref_number

categories          — two-level hierarchy loaded from categories.yml
  id, name, slug, icon, colour, parent_id (null = top-level)

user_category_rules — learned patterns from manual corrections
  id, merchant_pattern, description_keyword,
  category_id, subcategory_id, hit_count
```

---

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/upload` | Upload a PDF bank statement |
| GET | `/api/statements` | List all statements |
| GET | `/api/statements/{id}` | Get statement status |
| DELETE | `/api/statements/{id}` | Delete statement + its transactions |
| GET | `/api/transactions` | Paginated, filterable transaction list |
| PATCH | `/api/transactions/{id}/category` | Update category + save learned rule |
| POST | `/api/transactions/{id}/apply-pattern` | Apply learned pattern to all similar transactions |
| PATCH | `/api/transactions/bulk-category` | Update category for multiple transactions |
| POST | `/api/transactions/recategorize` | Re-run categorisation on all non-user-corrected transactions |
| GET | `/api/categories` | List all categories (hierarchical) |
| POST | `/api/query` | Ask a question — returns full answer |
| POST | `/api/query/stream` | Ask a question — streams tokens via SSE |
| POST | `/api/query/cache/clear` | Flush cached query results |
| GET | `/api/analytics/summary` | This month vs last month summary |
| GET | `/api/analytics/monthly` | Monthly debit/credit totals |
| GET | `/api/analytics/categories` | Per-category spend totals (debit or credit) |
| GET | `/api/analytics/merchants` | Top merchants by spend |
| GET | `/api/analytics/recurring` | Detected recurring / subscription transactions |

Full interactive docs available at `http://localhost:8000/docs` when the backend is running.

---

## Privacy

- All services run locally via Docker — nothing leaves your machine
- Ollama runs locally — no cloud LLM API calls
- PDF files stored in local filesystem only (`UPLOAD_DIR`)
- No analytics, no telemetry, no external network calls
