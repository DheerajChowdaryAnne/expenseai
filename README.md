# ExpenseAI — AI-Powered Expense Report Automation

<div align="center">

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![Claude](https://img.shields.io/badge/Claude-Sonnet_4.6-D4A017?style=for-the-badge)
![ChromaDB](https://img.shields.io/badge/ChromaDB-RAG-8A2BE2?style=for-the-badge)
![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)

**Receipts In. Report Out.**

An agentic AI system that extracts receipt data via Claude Vision, verifies expenses against live GSA/IRS policy rates using Tavily web search, optionally checks your company's own uploaded policy PDFs (RAG via ChromaDB), and generates a professional PDF expense report — all automatically.

[Features](#-features) • [Architecture](#-architecture) • [Quick Start](#-quick-start) • [API Reference](#-api-reference) • [Project Structure](#-project-structure)

</div>

---

## ✨ Features

- **🔍 Claude Vision Receipt Extraction** — Reads JPEG, PNG, HEIC, WebP, and multi-page PDFs. Returns structured data (vendor, amount, date, category, location) with a confidence score.
- **🤖 Agentic Policy Verification** — A multi-turn Claude tool-use loop checks each expense against:
  1. Your company's internal policy PDFs (ChromaDB RAG) — always checked first
  2. Live U.S. government rates (Tavily → GSA per diem, IRS mileage) as fallback
- **📄 RAG Policy Engine** — Upload your company's expense policy PDF once. It's chunked, embedded (all-MiniLM-L6-v2, 384-dim, cosine similarity), and searched semantically on every verification.
- **🚗 IRS Mileage Rate Lookup** — Looks up the current IRS standard mileage rate via live web search for accurate reimbursement calculations.
- **📊 GSA Meal Cap Enforcement** — Applies daily GSA M&IE caps including the 75% first/last-day rule automatically.
- **⚡ Concurrent Processing** — All receipts are processed in parallel via `asyncio.gather()` with a `Semaphore(4)` rate limiter.
- **📡 Real-Time Progress** — WebSocket broadcasts live progress events to the frontend during processing. Falls back to polling.
- **👔 Human-in-the-Loop (HITL)** — Low-confidence items (score < 0.6) are flagged for manager review. Managers can approve, edit, or override any amount.
- **📑 Professional PDF Reports** — Jinja2 + WeasyPrint generates Letter-size PDFs with itemized table, compliance notes, summary box, and signature blocks.
- **📥 CSV Export** — Download all expense data as a spreadsheet.
- **🏛️ Session History** — All past reports are stored in SQLite and accessible from the history panel.
- **🎨 Dark Glassmorphism UI** — Single-file SPA with 4-step workflow, Chart.js donut chart, receipt lightbox preview, and animated progress terminal.

---

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    Frontend (SPA)                                 │
│              frontend/index.html — Dark Glassmorphism            │
│   Step 1: Trip Details → Step 2: Upload → Step 3: Process → Step 4: Results │
└─────────────────────────┬────────────────────────────────────────┘
                          │  REST API + WebSocket
┌─────────────────────────▼────────────────────────────────────────┐
│                    FastAPI Backend (main.py)                      │
│  • Session management  • WebSocket progress  • HITL review       │
│  • Policy document management  • Rate preview cache              │
└────┬─────────────────────────────────────────────┬───────────────┘
     │  Background Pipeline                         │
     ▼                                              ▼
┌────────────────┐    ┌───────────────────┐    ┌────────────────────┐
│ Claude Vision  │    │  Policy Verifier  │    │ Mileage Calculator │
│ (Extraction)   │    │  (Tool-Use Loop)  │    │ (Tool-Use Loop)    │
│                │    │                   │    │                    │
│ Receipt image  │    │  1. rag_search →  │    │ Claude searches    │
│ → JSON fields  │    │     ChromaDB RAG  │    │ irs.gov for        │
│ + confidence   │    │  2. web_search →  │    │ current rate       │
└────────────────┘    │     Tavily API    │    └────────────────────┘
                      └───────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │  services/          │
                    │  pdf_generator.py   │
                    │  Jinja2 + WeasyPrint│
                    └─────────────────────┘
```

### AI Agent Tool-Use Loop

```
Claude receives: expense details + [rag_search, web_search] tools
      │
      ▼
  stop_reason = "tool_use"?
      │
      ├─ YES → Execute tool (rag_search or web_search)
      │         Feed result back as tool_result message
      │         Loop again (max 6 iterations)
      │
      └─ NO (end_turn) → Parse JSON verdict → PolicyCheckResult
```

---

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- macOS: Homebrew with Pango/Cairo (for PDF rendering)
- API keys: [Anthropic](https://console.anthropic.com) + [Tavily](https://app.tavily.com)

### 1. Install system dependencies (macOS)

```bash
brew install pango cairo gobject-introspection poppler
```

### 2. Clone and set up Python environment

```bash
git clone https://github.com/your-username/expenseai.git
cd expenseai

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and add your API keys:

```env
ANTHROPIC_API_KEY=sk-ant-your-key-here
TAVILY_API_KEY=tvly-your-key-here
```

### 4. Start the server

```bash
bash run.sh
```

The app will be available at **http://localhost:8000**

> **Note:** The `run.sh` script sets `DYLD_LIBRARY_PATH=/opt/homebrew/lib` which is required for WeasyPrint to find the Pango/Cairo libraries on macOS Apple Silicon.

### 5. Generate test receipts (optional)

```bash
python create_test_receipts.py
```

---

## 🌍 Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | ✅ | — | Claude API key from [console.anthropic.com](https://console.anthropic.com) |
| `TAVILY_API_KEY` | ✅ | — | Tavily Search API key from [app.tavily.com](https://app.tavily.com) |
| `CLAUDE_MODEL` | ❌ | `claude-sonnet-4-6` | Which Claude model to use |
| `DATABASE_URL` | ❌ | `sqlite:///./expense_reports.db` | SQLAlchemy database URL |
| `MAX_FILE_SIZE` | ❌ | `20971520` (20 MB) | Max receipt upload size in bytes |
| `UPLOAD_DIR` | ❌ | `./uploads` | Where uploaded receipts are stored |
| `REPORTS_DIR` | ❌ | `./reports` | Where generated PDFs are saved |
| `CHROMA_DIR` | ❌ | `./chroma_db` | ChromaDB persistent storage directory |
| `POLICY_DOCS_DIR` | ❌ | `./policy_docs` | Where uploaded policy PDFs are stored |
| `POLICY_DOC_MAX_SIZE` | ❌ | `52428800` (50 MB) | Max policy PDF upload size in bytes |

---

## 📡 API Reference

### Session Lifecycle

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/sessions` | Create a new expense report session |
| `POST` | `/sessions/{id}/receipts` | Upload receipt files (multipart) |
| `POST` | `/sessions/{id}/process` | Start the AI processing pipeline |
| `GET` | `/sessions/{id}/status` | Poll processing status + progress % |
| `GET` | `/sessions/{id}/results` | Get full JSON results |
| `GET` | `/sessions/{id}/report` | Download the generated PDF |
| `GET` | `/sessions/{id}/export/csv` | Download results as CSV |
| `DELETE` | `/sessions/{id}` | Delete session, files, and PDF |
| `GET` | `/sessions` | List past sessions (history) |

### Real-Time Progress

| Method | Endpoint | Description |
|---|---|---|
| `WS` | `/ws/{session_id}` | WebSocket for real-time progress events |

### Manager Review (HITL)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/sessions/{id}/review-items` | Get items flagged for manager review |
| `PATCH` | `/sessions/{id}/items/{item_id}` | Approve or edit a flagged item |
| `POST` | `/sessions/{id}/regenerate-pdf` | Regenerate PDF after manager review |

### Policy Documents (RAG)

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/policy-documents` | Upload a corporate policy PDF (async ingest) |
| `GET` | `/policy-documents` | List all uploaded policy documents |
| `PATCH` | `/policy-documents/{doc_id}` | Update document metadata |
| `DELETE` | `/policy-documents/{doc_id}` | Delete document from DB + ChromaDB |
| `GET` | `/policy-documents/{doc_id}/preview` | Test-query the RAG index |

### Utilities

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | DB + model connectivity check |
| `GET` | `/policy-preview` | Live GSA/IRS rate lookup (cached) |
| `GET` | `/sessions/{id}/receipt-image/{filename}` | Serve uploaded receipt for preview |

---

## 📁 Project Structure

```
expenseai/
│
├── main.py                     # FastAPI app: all routes + background pipeline
├── models.py                   # Pydantic models (pipeline) + SQLAlchemy ORM
├── database.py                 # DB engine, session factory, migrations
├── config.py                   # Pydantic Settings (reads from .env)
│
├── services/
│   ├── receipt_extractor.py    # Claude Vision: image/PDF → structured JSON
│   ├── policy_verifier.py      # Agentic tool-use loop: RAG + web search
│   ├── rag_service.py          # ChromaDB manager: ingest, embed, query PDFs
│   ├── mileage_calculator.py   # IRS rate lookup + mileage reimbursement
│   └── pdf_generator.py        # Jinja2 + WeasyPrint PDF generation
│
├── tools/
│   ├── web_search.py           # Tavily API wrapper + Claude tool definition
│   └── rag_search.py           # ChromaDB search tool + Claude tool definition
│
├── frontend/
│   └── index.html              # Self-contained SPA (all CSS + JS inline)
│
├── templates/
│   └── expense_report.html     # Jinja2 template for PDF output
│
├── static/
│   └── styles.css              # WeasyPrint-optimized PDF stylesheet
│
├── requirements.txt            # Python dependencies
├── run.sh                      # Start script (sets DYLD_LIBRARY_PATH for macOS)
├── .env.example                # Environment variable template
├── .gitignore                  # Git ignore rules
│
└── create_test_receipts.py     # Generates synthetic receipt images for testing
```

---

## 🔑 Key Design Decisions

| Decision | Rationale |
|---|---|
| **All AI calls are `AsyncAnthropic`** | Prevents blocking FastAPI's async event loop during long Claude API calls |
| **`asyncio.gather` + `Semaphore(4)`** | Processes all receipts concurrently while respecting Claude API rate limits |
| **RAG before web search** | Internal company policy always takes precedence over public GSA/IRS rates |
| **Policy override shortcircuit** | Org-specific caps skip all API calls entirely — faster and deterministic |
| **ChromaDB cosine similarity** | Better than L2 distance for semantic text similarity in short policy excerpts |
| **400-word overlapping chunks** | Prevents policy rules that span page breaks from being split across chunks |
| **Session-based SQLite storage** | Simple, zero-config, and sufficient for the expected scale |
| **In-memory rate cache** | Avoids re-querying Tavily for the same city/year combination |
| **Confidence < 0.6 → HITL** | Blurry or ambiguous receipts get human review rather than wrong amounts |

---

## 📦 Dependencies

| Package | Purpose |
|---|---|
| `fastapi` | REST API framework |
| `uvicorn[standard]` | ASGI server with WebSocket support |
| `anthropic` | Claude API client (Vision + tool-use) |
| `httpx` | Async HTTP client for Tavily API calls |
| `chromadb` | Local vector database for policy RAG |
| `pypdf` | Extract text from uploaded policy PDFs |
| `pdf2image` | Convert PDF receipt pages to images for Claude Vision |
| `weasyprint` | HTML → PDF rendering engine |
| `jinja2` | HTML templating for PDF reports |
| `sqlalchemy` | ORM for SQLite session storage |
| `pydantic-settings` | Type-safe environment variable loading |
| `python-multipart` | Multipart form data for file uploads |
| `pillow` | Image processing for test receipt generation |

---

## 🧪 Running Tests

```bash
# End-to-end integration tests
python test_e2e.py

# Manual receipt extraction test
python create_test_receipts.py   # Generate test images first
```

---

## 📋 How to Upload a Corporate Policy PDF

1. Start the server: `bash run.sh`
2. Navigate to http://localhost:8000
3. In Step 1, find the **Policy Documents** section (or use the API directly)
4. Upload your company policy PDF via `POST /policy-documents`
5. Wait for status to become `"ready"` (check `GET /policy-documents`)
6. The policy will be automatically used for all future expense verifications

The policy verifier checks your internal documents first. If a relevant rule is found (relevance score ≥ 0.5), it's used as the authoritative source. Otherwise, it falls back to live GSA/IRS rates.

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Make your changes with appropriate comments/docstrings
4. Test thoroughly: `python test_e2e.py`
5. Submit a pull request

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

## 👤 Author

**Dheeraj Chowdary Anne, Pravallika Reddy Sabbasani**

Built as a capstone project demonstrating agentic AI patterns:
- Multi-modal Claude Vision for document understanding
- Multi-turn tool-use loops for autonomous policy research
- RAG (Retrieval-Augmented Generation) for grounding AI in enterprise knowledge
- Human-in-the-Loop (HITL) for handling uncertainty gracefully

---

<div align="center">

**ExpenseAI** — *True end-to-end automation. Receipts In. Report Out.*

</div>
