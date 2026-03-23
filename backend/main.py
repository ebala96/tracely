"""
Spendly FastAPI application entry point.
"""
import os
import sys
from pathlib import Path

# Ensure the backend directory is on the path when run directly
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import upload, query, transactions, analytics, categories
from db.postgres import create_tables

app = FastAPI(
    title="Spendly API",
    description="Privacy-first bank statement RAG — 100% local",
    version="0.1.0",
)

# CORS — allow the Vite dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Vite
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(upload.router)
app.include_router(query.router)
app.include_router(transactions.router)
app.include_router(analytics.router)
app.include_router(categories.router)


@app.on_event("startup")
async def startup():
    await create_tables()
    # Ensure upload directory exists
    upload_dir = os.environ.get("UPLOAD_DIR", "/tmp/spendly_uploads")
    Path(upload_dir).mkdir(parents=True, exist_ok=True)


@app.get("/health")
async def health():
    return {"status": "ok"}
