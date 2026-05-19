# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI-powered travel expense report automation system. Users upload receipts; the system extracts data via Claude Vision, verifies each expense against uploaded company policies (via ChromaDB RAG) and live U.S. government rates (Tavily web search) using Claude tool-use, then generates a PDF expense report.

**Version:** 2.0.0 — full async, concurrent processing, WebSocket progress, RAG policy engine, CSV export, session history.

## Setup & Running

**System dependencies (macOS):**
```bash
brew install pango cairo gobject-introspection poppler
```
(chromadb and sentence-transformers are handled via pip)

**Python environment:**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # then add ANTHROPIC_API_KEY and TAVILY_API_KEY
```

**Run the server:**
```bash
bash run.sh
# Equivalent to:
source venv/bin/activate && DYLD_LIBRARY_PATH=/opt/homebrew/lib uvicorn main:app --reload --port 8000
```

The `DYLD_LIBRARY_PATH` prefix is required on macOS for WeasyPrint to find Pango/Cairo Homebrew libraries.

**Generate test receipt images:**
```bash
python create_test_receipts.py
```

## Architecture

### Request Flow
1. Frontend (`frontend/index.html`) collects trip details and uploads receipts via REST API
2. `POST /sessions/{id}/process` triggers an async background task in `main.py`
3. Background pipeline: extract ALL receipts concurrently → verify policy concurrently → calculate mileage → generate PDF
4. Frontend receives real-time progress via **WebSocket** `/ws/{session_id}`; falls back to polling `GET /sessions/{id}/status` if WebSocket is unavailable

### AI Processing Pipeline (`main.py:_run_processing_pipeline`)
- **Receipt extraction** (`services/receipt_extractor.py`): Claude Vision (`AsyncAnthropic`) reads base64-encoded images, returns structured `ExtractedReceiptData`. PDFs are converted to PNG first via pdf2image.
- **Policy verification** (`services/policy_verifier.py`): Multi-turn Claude tool-use loop (`AsyncAnthropic`, max 6 iterations). Claude first calls `rag_search` (ChromaDB) to check internal company policy. If no policy exists or confidence is low (< 0.5 score), it falls back to `web_search` (Tavily) to fetch live GSA/IRS data. Returns a structured compliance verdict.
- **Mileage calculation** (`services/mileage_calculator.py`): Same Claude tool-use loop pattern (`AsyncAnthropic`) to look up the current IRS mileage rate, then applies it to user-provided miles.
- **PDF generation** (`services/pdf_generator.py`): Renders `templates/expense_report.html` (Jinja2) and converts to PDF via WeasyPrint.

### Key Design Patterns
- **All AI calls are async**: every service uses `anthropic.AsyncAnthropic` — never the sync `Anthropic` client — to avoid blocking the event loop.
- **Concurrent receipt processing**: receipts are extracted and policy-verified concurrently via `asyncio.gather` with a `asyncio.Semaphore(4)` to respect API rate limits.
- **Session-based state**: each user gets a UUID session stored in SQLite (`expense_reports` table). Files live in `uploads/{session_id}/`, PDFs in `reports/`.
- **WebSocket progress**: `ConnectionManager` in `main.py` broadcasts JSON events (`progress`, `status`, `completed`, `failed`) to connected clients during processing.
- **Policy rate cache**: `_policy_rate_cache` dict in `main.py` caches GSA/IRS rate lookups keyed by `(city, state, year, month)` — avoids redundant Tavily calls for the same destination.
- **Semantic RAG Retrieval**: `services/rag_service.py` manages a local persistent ChromaDB collection. Uploaded policy PDFs are chunked and embedded (384-dim, cosine similarity). Top-k=4 results are retrieved during verification.
- **Tool-use loop**: `policy_verifier.py` and `mileage_calculator.py` implement the same `for _ in range(MAX_ITERATIONS)` pattern — call Claude with tools, handle `tool_use` by executing `rag_search` or `web_search`, feed results back as `tool_result`, loop until `end_turn`.
- **Confidence flagging**: receipts with extraction confidence < 0.6 are flagged for manager review in the PDF.
- **Daily meal caps**: `_apply_daily_meal_caps()` in `main.py` groups meal items by date, applies the GSA 75% first/last-day rule, and proportionally scales down approved amounts when daily total exceeds the cap.
- **U.S. domestic only**: policy verification is scoped to GSA/IRS standards; international rates are not supported.

### Environment Variables (`.env`)
| Variable | Required | Default |
|----------|----------|---------|
| `ANTHROPIC_API_KEY` | Yes | — |
| `TAVILY_API_KEY` | Yes | — |
| `CLAUDE_MODEL` | No | `claude-sonnet-4-6` |
| `DATABASE_URL` | No | `sqlite:///./expense_reports.db` |
| `MAX_FILE_SIZE` | No | `20971520` (20 MB) |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Serve frontend SPA |
| `GET` | `/health` | DB + model connectivity check |
| `WS` | `/ws/{session_id}` | WebSocket for real-time processing progress |
| `GET` | `/sessions` | List recent sessions (history) — `?limit=&offset=` |
| `POST` | `/sessions` | Create new expense report session |
| `POST` | `/sessions/{id}/receipts` | Upload receipt files (multipart) |
| `POST` | `/sessions/{id}/process` | Start background processing pipeline |
| `GET` | `/sessions/{id}/status` | Poll processing status + progress % |
| `GET` | `/sessions/{id}/results` | Fetch full JSON results |
| `GET` | `/sessions/{id}/report` | Download generated PDF |
| `GET` | `/sessions/{id}/export/csv` | Download results as CSV |
| `GET` | `/sessions/{id}/receipt-image/{filename}` | Serve uploaded receipt file for preview |
| `GET` | `/policy-preview` | Live GSA/IRS rate lookup — `?city=&state=&start_date=` |
| `DELETE` | `/sessions/{id}` | Delete session + files + PDF |

## Key Files

| File | Role |
|------|------|
| `main.py` | FastAPI app, all endpoints, WebSocket manager, concurrent processing pipeline, rate cache |
| `services/receipt_extractor.py` | Claude Vision receipt parsing (`AsyncAnthropic`) |
| `services/policy_verifier.py` | Claude tool-use loop for internal policy + GSA/IRS compliance (`AsyncAnthropic`) |
| `services/mileage_calculator.py` | IRS mileage rate lookup + calculation (`AsyncAnthropic`) |
| `services/pdf_generator.py` | WeasyPrint + Jinja2 PDF generation |
| `services/rag_service.py` | ChromaDB collection manager for enterprise policy embeddings |
| `tools/web_search.py` | Tavily API wrapper + Claude tool definition |
| `tools/rag_search.py` | Semantic search over ChromaDB + Claude tool definition |
| `models.py` | Pydantic models (`ExtractedReceiptData`, `PolicyCheckResult`, `ExpenseItem`, etc.) and SQLAlchemy ORM |
| `frontend/index.html` | 4-step SPA — dark glassmorphism UI, WebSocket progress, Chart.js donut, receipt lightbox, history panel |
| `templates/expense_report.html` | Jinja2 template for PDF output (WeasyPrint-optimized) |
| `static/styles.css` | PDF stylesheet (WeasyPrint print CSS) |
| `database.py` | SQLAlchemy engine, session factory, schema migrations |
| `config.py` | Pydantic settings loaded from `.env` |

## Frontend Features (v2)

The single-page UI (`frontend/index.html`) implements:
- **Step 1** — Trip details form + live GSA/IRS rate preview (debounced, cached) + collapsible mileage modal + custom policy overrides
- **Step 2** — Drag-and-drop receipt upload with per-file category hint dropdowns
- **Step 3** — Real-time WebSocket progress bar + terminal-style live log + stage indicators; polling fallback
- **Step 4** — Summary cards, Chart.js donut chart by category, itemized expense table, expandable policy notes, receipt lightbox, CSV + PDF download buttons
- **History panel** — slide-in sidebar listing past sessions, "Open" to reload any completed report
