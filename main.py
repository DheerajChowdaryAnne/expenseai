"""
main.py — FastAPI Application: AI Expense Report Automation System
==================================================================
This is the main entry point for ExpenseAI. It defines all REST API
endpoints, the WebSocket real-time progress system, and the background
processing pipeline that orchestrates the three AI agents.

Key responsibilities:
  - REST API routes for session lifecycle (create → upload → process → results)
  - WebSocket endpoint for real-time progress updates to the frontend
  - Background processing pipeline (_run_processing_pipeline):
      1. Concurrent Claude Vision receipt extraction
      2. Concurrent Claude tool-use policy verification (RAG + web search)
      3. Daily meal cap enforcement (GSA 75% first/last-day rule)
      4. IRS mileage reimbursement calculation
      5. WeasyPrint PDF report generation
  - Human-in-the-Loop (HITL) manager review endpoints
  - Corporate policy document (RAG) management endpoints
  - Live GSA/IRS rate preview with in-memory cache

Version: 2.0.0 — full async, concurrent processing, WebSocket progress,
                 RAG policy engine, CSV export, session history.
"""

from __future__ import annotations

import asyncio
import csv
import datetime
import io
import json
import os
import shutil
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional

import anthropic as _anthropic
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from config import settings
from database import SessionLocal, get_db, init_database
from models import (
    ExpenseItem,
    ExpenseReport,
    ExpenseReportRequest,
    ManagerItemPatch,
    MileageEntry,
    PolicyCheckResult,
    PolicyDocument,
    PolicyOverrides,
)
from services.mileage_calculator import calculate_mileage_reimbursement
from services.pdf_generator import build_summary, generate_expense_report_pdf
from services.policy_verifier import verify_expense_policy
from services.receipt_extractor import extract_receipt_data
from tools.web_search import WEB_SEARCH_TOOL_DEFINITION, execute_web_search

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(title="AI Expense Report Automation", version="2.0.0")

# Mount the static files directory so WeasyPrint and the frontend can access CSS.
# Files are served at /static/* (e.g. /static/styles.css)
_static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")

# Only these MIME types are accepted for receipt uploads.
# Anything else is rejected with a 400 error before it reaches Claude.
ALLOWED_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/heic",
    "image/webp",
    "application/pdf",
}

# ---------------------------------------------------------------------------
# WebSocket connection manager
# ---------------------------------------------------------------------------

class ConnectionManager:
    """
    Manages active WebSocket connections grouped by session_id.

    Each session can have multiple connected clients (e.g. the user has
    multiple browser tabs open). broadcast() sends a JSON event to all
    of them simultaneously.

    WebSocket events sent during processing:
      {"type": "status",   "status": "processing",    "message": "..."}
      {"type": "progress", "done": N, "total": M,      "pct": 0-100, "message": "..."}
      {"type": "status",   "status": "generating_pdf", "message": "..."}
      {"type": "completed","status": "completed",      "total_approved": "$X.XX"}
      {"type": "failed",   "status": "failed",         "message": "error text"}
    """
    def __init__(self):
        # Maps session_id → list of active WebSocket connections for that session
        self.active: Dict[str, List[WebSocket]] = {}

    async def connect(self, session_id: str, ws: WebSocket):
        """Accept a new WebSocket connection and register it for the given session."""
        await ws.accept()
        self.active.setdefault(session_id, []).append(ws)

    def disconnect(self, session_id: str, ws: WebSocket):
        """Remove a disconnected WebSocket from the active connections list."""
        if session_id in self.active:
            self.active[session_id] = [w for w in self.active[session_id] if w is not ws]

    async def broadcast(self, session_id: str, data: dict):
        """
        Send a JSON event to all active WebSocket clients for this session.
        Silently ignores any connection errors (e.g. client disconnected mid-send).
        """
        for ws in self.active.get(session_id, []):
            try:
                await ws.send_json(data)
            except Exception:
                pass  # Client may have disconnected — safe to ignore

# Module-level singleton used by all routes and the background pipeline
ws_manager = ConnectionManager()

# ---------------------------------------------------------------------------
# In-memory policy rate cache  {(city, state, year, month) -> result}
# ---------------------------------------------------------------------------
# Caches the result of GET /policy-preview (GSA + IRS rate lookups) so that
# repeated lookups for the same destination and year don't hit Tavily again.
# Keyed by (city_lower, state_upper, year, month_name) — e.g.
# ("chicago", "IL", 2025, "October") → {meal_daily_rate, hotel_nightly_cap, ...}
_policy_rate_cache: dict = {}


@app.on_event("startup")
def startup():
    """
    Application startup hook — runs once when uvicorn starts the server.

    Responsibilities:
      1. Initialize the SQLite database (create tables, run migrations)
      2. Create all required directories if they don't exist yet
      3. Warm up ChromaDB and download the embedding model now so the first
         user request doesn't experience a cold-start delay
    """
    init_database()                                          # Create/migrate DB tables
    os.makedirs(settings.upload_dir, exist_ok=True)          # ./uploads/
    os.makedirs(settings.reports_dir, exist_ok=True)         # ./reports/
    os.makedirs(settings.policy_docs_dir, exist_ok=True)     # ./policy_docs/
    os.makedirs(settings.chroma_dir, exist_ok=True)          # ./chroma_db/
    # Eagerly initialize ChromaDB + download the sentence-transformer embedding model.
    # This happens at startup so the first actual policy search is fast.
    from services.rag_service import get_rag_service
    get_rag_service()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    """
    Serve the single-page application (SPA).

    Returns the contents of frontend/index.html as an HTML response.
    The frontend handles all routing client-side; this is the only HTML
    endpoint — all other routes are JSON REST APIs.
    """
    frontend_path = Path(__file__).parent / "frontend" / "index.html"
    return HTMLResponse(content=frontend_path.read_text(), status_code=200)


@app.get("/health")
async def health(db: Session = Depends(get_db)):
    """
    Basic health check endpoint.

    Verifies database connectivity by running a trivial SQL query.
    Returns model name so the frontend can confirm which Claude model is active.
    Used by monitoring tools and deployment readiness checks.
    """
    try:
        db.execute(__import__("sqlalchemy").text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    return {
        "status": "ok" if db_ok else "degraded",
        "database": "connected" if db_ok else "error",
        "model": settings.claude_model,
        "version": "2.0.0",
    }


# ---------------------------------------------------------------------------
# WebSocket — real-time progress updates
# ---------------------------------------------------------------------------


@app.websocket("/ws/{session_id}")
async def websocket_progress(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for real-time processing progress updates.

    The frontend connects here immediately after clicking "Process".
    The background pipeline broadcasts JSON events through ws_manager
    as each receipt is processed (see ConnectionManager above).

    The loop reads keep-alive pings from the client (we don't use the
    content, just stay alive). When the client disconnects, WebSocketDisconnect
    is raised and we clean up the connection.

    Fallback: if WebSocket is unavailable (e.g. proxy doesn't support it),
    the frontend falls back to polling GET /sessions/{id}/status every 2s.
    """
    await ws_manager.connect(session_id, websocket)
    try:
        while True:
            await websocket.receive_text()  # Absorb keep-alive pings from client
    except WebSocketDisconnect:
        ws_manager.disconnect(session_id, websocket)


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------


@app.get("/sessions")
async def list_sessions(
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """
    List recent expense report sessions for the history panel.

    Returns sessions ordered by creation date (newest first) with basic
    metadata for each. The frontend history panel calls this to populate
    the slide-in sidebar. Supports pagination via limit/offset.

    Query params:
        limit:  Maximum number of sessions to return (default 20)
        offset: Number of sessions to skip for pagination (default 0)
    """
    reports = (
        db.query(ExpenseReport)
        .order_by(ExpenseReport.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    total = db.query(ExpenseReport).count()

    return {
        "total": total,
        "sessions": [
            {
                "session_id":      r.session_id,
                "submitter_name":  r.submitter_name,
                "department":      r.department,
                "trip_purpose":    r.trip_purpose,
                "destination":     f"{r.destination_city}, {r.destination_state}",
                "trip_dates":      f"{r.trip_start_date} to {r.trip_end_date}",
                "status":          r.status,
                # total_approved is nested inside the JSON blob
                "total_approved":  r.report_summary_json.get("total_approved") if r.report_summary_json else None,
                "created_at":      r.created_at.isoformat() if r.created_at else None,
            }
            for r in reports
        ],
    }


@app.post("/sessions", status_code=201)
async def create_session(
    request: ExpenseReportRequest,
    db: Session = Depends(get_db),
):
    """
    Create a new expense report session (Step 1 of the UI flow).

    Stores the trip details and submitter info in the database and returns
    a session_id UUID. All subsequent API calls use this session_id.
    The session starts in "draft" status — no processing has occurred yet.

    Request body: ExpenseReportRequest (see models.py)
    Returns: {session_id: str, status: "draft"}
    """
    session_id = str(uuid.uuid4())  # Generate a new UUID for this session

    report = ExpenseReport(
        session_id=session_id,
        submitter_name=request.submitter_name,
        submitter_email=request.submitter_email,
        department=request.department,
        trip_purpose=request.trip_purpose,
        trip_start_date=str(request.trip_start_date),
        trip_end_date=str(request.trip_end_date),
        destination_city=request.destination_city,
        destination_state=request.destination_state,
        # Serialize Pydantic models to plain dicts for JSON column storage
        mileage_entries_json=[e.model_dump(mode="json") for e in request.mileage_entries],
        policy_overrides_json=request.policy_overrides.model_dump(mode="json") if request.policy_overrides else None,
        status="draft",
        expense_items_json=[],
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    return {"session_id": session_id, "status": "draft"}


@app.post("/sessions/{session_id}/receipts")
async def upload_receipts(
    session_id: str,
    files: List[UploadFile] = File(...),
    category_hints: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """
    Upload one or more receipt files to a session (Step 2 of the UI flow).

    Validates file type and size, saves files to disk under
    uploads/{session_id}/, and appends a pending ExpenseItem entry to
    the session's expense_items_json list. Sets session status to
    "receipts_uploaded" so the process endpoint can be called next.

    Args:
        files:          One or more uploaded receipt files (multipart form).
        category_hints: Optional JSON string mapping filename → category hint.
                        E.g. '{"hotel_receipt.jpg": "hotel"}'
                        Passed to Claude to improve extraction accuracy.

    Returns: {uploaded: [filenames], total_receipts: int}
    Raises:
        400: If session is already processing or completed.
        400: If a file's MIME type is not in ALLOWED_MIME_TYPES.
        413: If a file exceeds the 20 MB size limit.
    """
    report = _get_report_or_404(session_id, db)

    if report.status not in ("draft", "receipts_uploaded"):
        raise HTTPException(400, "Session is already being processed or completed.")

    # Parse category_hints JSON if provided (it's a form field, not JSON body)
    hints: dict = {}
    if category_hints:
        try:
            hints = json.loads(category_hints)
        except (json.JSONDecodeError, TypeError):
            hints = {}  # Invalid JSON — ignore and proceed without hints

    # Create the per-session upload directory if it doesn't exist
    upload_dir = Path(settings.upload_dir) / session_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    uploaded = []
    for f in files:
        # Reject unsupported file types before reading the full content
        if f.content_type not in ALLOWED_MIME_TYPES:
            raise HTTPException(
                400,
                f"Unsupported file type '{f.content_type}' for '{f.filename}'. "
                f"Accepted: JPEG, PNG, HEIC, WebP, PDF.",
            )

        content = await f.read()
        # Reject files that exceed the size limit
        if len(content) > settings.max_file_size:
            raise HTTPException(
                413, f"File '{f.filename}' exceeds the 20 MB size limit."
            )

        # Save the file to disk
        dest = upload_dir / f.filename
        dest.write_bytes(content)
        uploaded.append({"filename": f.filename, "content_type": f.content_type})

    # Append a "pending" ExpenseItem stub for each uploaded file.
    # The actual data extraction happens in the background pipeline.
    existing = report.expense_items_json or []
    for u in uploaded:
        item: dict = {
            "id":                    str(uuid.uuid4()),
            "receipt_filename":      u["filename"],
            "receipt_content_type":  u["content_type"],
            "status":                "pending",
        }
        # Attach the category hint if one was provided for this file
        hint = hints.get(u["filename"])
        if hint:
            item["category_hint"] = hint
        existing.append(item)

    report.expense_items_json = existing
    report.status = "receipts_uploaded"  # Advance session state
    db.commit()

    return {"uploaded": [u["filename"] for u in uploaded], "total_receipts": len(existing)}


@app.post("/sessions/{session_id}/process")
async def process_session(
    session_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Trigger the async AI processing pipeline (Step 3 of the UI flow).

    Sets session status to "processing", calculates the total number of
    items to process (for the progress bar), then hands off to FastAPI's
    BackgroundTasks. The actual work runs in _run_processing_pipeline()
    which is a long-running async function that doesn't block this response.

    Returns immediately with {status: "processing", total_items: N} so
    the frontend can connect to the WebSocket and show the progress bar.

    Raises:
        409: If the session is already processing or completed.
    """
    report = _get_report_or_404(session_id, db)

    if report.status == "processing":
        raise HTTPException(409, "Session is already being processed.")
    if report.status == "completed":
        raise HTTPException(409, "Session has already been completed.")

    # Count receipts + mileage entries to set up the progress bar total
    n_receipts = len(report.expense_items_json or [])
    n_mileage = len(report.mileage_entries_json or [])
    report.progress_total = n_receipts + n_mileage
    report.progress_current = 0
    report.status = "processing"
    db.commit()

    # Schedule the pipeline as a background task.
    # FastAPI runs this after sending the response, so the client
    # doesn't wait for processing to finish.
    background_tasks.add_task(_run_processing_pipeline, session_id)

    return {"status": "processing", "total_items": report.progress_total}


@app.get("/sessions/{session_id}/status")
async def get_status(session_id: str, db: Session = Depends(get_db)):
    """Poll processing status and progress."""
    report = _get_report_or_404(session_id, db)
    total = report.progress_total or 1
    pct = int((report.progress_current / total) * 100)

    return {
        "session_id": session_id,
        "status": report.status,
        "progress_pct": pct,
        "items_done": report.progress_current,
        "items_total": report.progress_total,
        "error": report.error_message,
    }


@app.get("/sessions/{session_id}/results")
async def get_results(session_id: str, db: Session = Depends(get_db)):
    """Return full JSON results once processing is complete."""
    report = _get_report_or_404(session_id, db)

    if report.status != "completed":
        raise HTTPException(
            400, f"Report is not ready yet. Current status: {report.status}"
        )

    return {
        "session_id": session_id,
        "expense_items": report.expense_items_json,
        "summary": report.report_summary_json,
    }


@app.get("/sessions/{session_id}/report")
async def download_report(session_id: str, db: Session = Depends(get_db)):
    """Download the generated PDF report."""
    report = _get_report_or_404(session_id, db)

    if report.status != "completed" or not report.pdf_path:
        raise HTTPException(400, "PDF report is not ready yet.")

    if not Path(report.pdf_path).exists():
        raise HTTPException(404, "PDF file not found on disk.")

    filename = f"expense_report_{session_id[:8]}.pdf"
    return FileResponse(
        report.pdf_path,
        media_type="application/pdf",
        filename=filename,
    )


@app.get("/sessions/{session_id}/export/csv")
async def export_csv(session_id: str, db: Session = Depends(get_db)):
    """Export expense items as CSV."""
    report = _get_report_or_404(session_id, db)

    if report.status != "completed":
        raise HTTPException(400, "Report is not ready yet.")

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "#", "Date", "Category", "Vendor", "Description",
        "Location", "Claimed ($)", "Approved ($)", "Policy Limit ($)",
        "Compliant", "Policy Source", "Notes",
    ])

    for i, item in enumerate(report.expense_items_json or [], start=1):
        ext = item.get("extracted") or {}
        pol = item.get("policy_check") or {}
        mil = item.get("mileage") or {}

        vendor = ext.get("vendor") or (
            f"{mil.get('origin', '')} → {mil.get('destination', '')}" if mil else "—"
        )
        location = f"{ext.get('location_city', '')}, {ext.get('location_state', '')}".strip(", ")

        writer.writerow([
            i,
            ext.get("date") or "—",
            (ext.get("category") or "mileage").title(),
            vendor,
            ext.get("description") or "—",
            location or "—",
            f"{float(ext.get('amount', pol.get('claimed_amount', 0))):.2f}",
            f"{float(item.get('final_approved_amount', 0)):.2f}",
            f"{float(pol.get('policy_limit', 0)):.2f}" if pol.get("policy_limit") else "No limit",
            "Yes" if pol.get("is_compliant") else "No",
            pol.get("policy_source") or "—",
            pol.get("notes") or "—",
        ])

    # Summary row
    s = report.report_summary_json or {}
    writer.writerow([])
    writer.writerow(["TOTAL", "", "", "", "", "",
                     f"{float(s.get('total_claimed', 0)):.2f}",
                     f"{float(s.get('total_approved', 0)):.2f}",
                     "", "", "", ""])

    output.seek(0)
    filename = f"expense_report_{session_id[:8]}.csv"
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/sessions/{session_id}/receipt-image/{filename}")
async def get_receipt_image(
    session_id: str,
    filename: str,
    db: Session = Depends(get_db),
):
    """Serve an uploaded receipt image for preview."""
    _get_report_or_404(session_id, db)  # verify session exists
    file_path = Path(settings.upload_dir) / session_id / filename
    if not file_path.exists():
        raise HTTPException(404, "File not found.")

    suffix = file_path.suffix.lower()
    mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".png": "image/png", ".webp": "image/webp",
                ".heic": "image/heic", ".pdf": "application/pdf"}
    media_type = mime_map.get(suffix, "application/octet-stream")
    return FileResponse(str(file_path), media_type=media_type)


@app.get("/policy-preview")
async def policy_preview(city: str, state: str, start_date: str):
    """
    Return applicable GSA meal/lodging per diem and IRS mileage rate
    for a given destination and travel year. Results are cached in-memory.
    """
    try:
        parsed = datetime.date.fromisoformat(start_date)
        year = parsed.year
        month = parsed.strftime("%B")
    except ValueError:
        raise HTTPException(400, "start_date must be YYYY-MM-DD.")

    cache_key = (city.lower(), state.upper(), year, month)
    if cache_key in _policy_rate_cache:
        return _policy_rate_cache[cache_key]

    _PREVIEW_SYSTEM = (
        "You are a travel policy researcher. "
        "Use web_search to look up three rates for the given destination and year, "
        "then return ONLY this JSON (no other text):\n"
        "{\n"
        '  "meal_daily_rate": <GSA M&IE rate in dollars, number>,\n'
        '  "hotel_nightly_cap": <GSA lodging per diem in dollars, number>,\n'
        '  "mileage_rate_per_mile": <IRS standard mileage rate, number>,\n'
        '  "source": "<brief citation e.g. GSA FY2025 / IRS Rev. Proc. 2025>"\n'
        "}\n"
        "Do 2–3 searches (GSA meals, GSA lodging, IRS mileage) then return the JSON."
    )

    user_msg = (
        f"Look up the following rates for {city}, {state} in {month} {year}:\n"
        f"1. GSA M&IE (meals & incidental expenses) per diem daily rate\n"
        f"2. GSA lodging per diem nightly cap\n"
        f"3. IRS standard mileage rate for {year}\n"
        "Search gsa.gov for #1 and #2, irs.gov for #3, then return the JSON."
    )

    aclient = _anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    messages: list[dict] = [{"role": "user", "content": user_msg}]

    try:
        for _ in range(6):
            resp = await aclient.messages.create(
                model=settings.claude_model,
                max_tokens=1024,
                system=_PREVIEW_SYSTEM,
                tools=[WEB_SEARCH_TOOL_DEFINITION],
                messages=messages,
            )
            if resp.stop_reason == "tool_use":
                tool_blocks = [b for b in resp.content if b.type == "tool_use"]
                tool_results = []
                for tb in tool_blocks:
                    result = await execute_web_search(**tb.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tb.id,
                        "content": json.dumps(result),
                    })
                messages.append({"role": "assistant", "content": resp.content})
                messages.append({"role": "user", "content": tool_results})
            elif resp.stop_reason == "end_turn":
                text = next((b.text for b in resp.content if hasattr(b, "text")), "")
                text = text.strip()
                m = __import__("re").search(r"```(?:json)?\s*([\s\S]*?)```", text)
                if m:
                    text = m.group(1).strip()
                data = json.loads(text)
                _policy_rate_cache[cache_key] = data  # cache it
                return data
    except Exception as exc:
        raise HTTPException(502, f"Policy preview lookup failed: {exc}")

    raise HTTPException(504, "Policy preview did not complete in time.")


@app.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str, db: Session = Depends(get_db)):
    """Delete session, uploaded files, and generated PDF."""
    report = _get_report_or_404(session_id, db)

    upload_dir = Path(settings.upload_dir) / session_id
    if upload_dir.exists():
        shutil.rmtree(upload_dir)

    if report.pdf_path and Path(report.pdf_path).exists():
        Path(report.pdf_path).unlink()

    db.delete(report)
    db.commit()


# ---------------------------------------------------------------------------
# HITL Manager Review endpoints
# ---------------------------------------------------------------------------


@app.get("/sessions/{session_id}/review-items")
async def get_review_items(session_id: str, db: Session = Depends(get_db)):
    """Return items flagged for manager review with receipt image URLs pre-computed."""
    report = _get_report_or_404(session_id, db)
    if report.status != "completed":
        raise HTTPException(400, f"Report is not ready yet. Current status: {report.status}")

    items = report.expense_items_json or []
    review_items = []
    total_flagged = 0
    reviewed_count = 0
    
    for idx, raw in enumerate(items):
        was_flagged = raw.get("requires_manager_review") or raw.get("manager_reviewed")
        if was_flagged:
            total_flagged += 1
            if raw.get("manager_reviewed"):
                reviewed_count += 1
                
            if raw.get("requires_manager_review"):
                item_out = dict(raw)
                item_out["index"] = idx
                fn = raw.get("receipt_filename")
                item_out["receipt_image_url"] = (
                    f"/sessions/{session_id}/receipt-image/{fn}" if fn else None
                )
                review_items.append(item_out)

    return {
        "session_id": session_id,
        "items_requiring_review": review_items,
        "total_review_count": total_flagged,
        "reviewed_count": reviewed_count,
    }


@app.patch("/sessions/{session_id}/items/{item_id}")
async def patch_expense_item(
    session_id: str,
    item_id: str,
    patch: ManagerItemPatch,
    db: Session = Depends(get_db),
):
    """Allow a manager to approve/edit an expense item and update the summary."""
    report = _get_report_or_404(session_id, db)
    if report.status != "completed":
        raise HTTPException(400, "Cannot edit items while report is not completed.")

    items = list(report.expense_items_json or [])
    target_idx = next(
        (i for i, it in enumerate(items) if it.get("id") == item_id), None
    )
    if target_idx is None:
        raise HTTPException(404, f"Item '{item_id}' not found.")

    item = dict(items[target_idx])

    # Apply field overrides
    if patch.manager_approved_amount is not None:
        amount_str = str(patch.manager_approved_amount)
        item["manager_approved_amount"] = amount_str
        item["final_approved_amount"] = amount_str
        if item.get("policy_check"):
            item["policy_check"]["approved_amount"] = amount_str
            if Decimal(str(item["policy_check"].get("claimed_amount", "0"))) == Decimal("0"):
                item["policy_check"]["claimed_amount"] = amount_str
    if patch.manager_notes is not None:
        item["manager_notes"] = patch.manager_notes
    if patch.vendor_override is not None and item.get("extracted"):
        item["extracted"]["vendor"] = patch.vendor_override
    if patch.amount_override is not None and item.get("extracted"):
        item["extracted"]["amount"] = str(patch.amount_override)

    # Mark as approved
    if patch.approve:
        item["requires_manager_review"] = False
        item["manager_reviewed"] = True
        item["reviewed_at"] = datetime.datetime.utcnow().isoformat()
        # If no explicit approved amount was provided, approve the claimed amount
        if patch.manager_approved_amount is None:
            claimed = Decimal("0.00")
            if item.get("extracted") and item["extracted"].get("amount"):
                claimed = Decimal(str(item["extracted"]["amount"]))
            item["final_approved_amount"] = str(claimed)
            item["manager_approved_amount"] = str(claimed)

    items[target_idx] = item
    report.expense_items_json = items

    # Recalculate summary
    parsed_items = [ExpenseItem(**it) for it in items]
    new_summary = build_summary(parsed_items)
    report.report_summary_json = new_summary.model_dump(mode="json")

    # Update review_status
    pending = [it for it in items if it.get("requires_manager_review")]
    report.review_status = "review_complete" if not pending else "pending_review"

    db.commit()

    return {
        "updated_item": item,
        "summary": report.report_summary_json,
        "remaining_review_count": len(pending),
    }


@app.post("/sessions/{session_id}/regenerate-pdf")
async def regenerate_pdf(session_id: str, db: Session = Depends(get_db)):
    """Regenerate the PDF after manager review is complete."""
    report = _get_report_or_404(session_id, db)
    if report.status != "completed":
        raise HTTPException(400, "Report is not ready.")

    items = [ExpenseItem(**it) for it in (report.expense_items_json or [])]
    summary = build_summary(items)

    req = ExpenseReportRequest(
        submitter_name=report.submitter_name,
        submitter_email=report.submitter_email,
        department=report.department,
        trip_purpose=report.trip_purpose,
        trip_start_date=datetime.date.fromisoformat(report.trip_start_date),
        trip_end_date=datetime.date.fromisoformat(report.trip_end_date),
        destination_city=report.destination_city,
        destination_state=report.destination_state,
    )

    pdf_filename = f"expense_report_{session_id}.pdf"
    pdf_path = await generate_expense_report_pdf(req, items, summary, pdf_filename)

    report.pdf_path = pdf_path
    report.report_summary_json = summary.model_dump(mode="json")
    report.review_status = "review_complete"
    db.commit()

    return {"status": "ok", "total_approved": str(summary.total_approved)}


# ---------------------------------------------------------------------------
# Corporate Policy Document endpoints (RAG)
# ---------------------------------------------------------------------------


@app.get("/policy-documents")
async def list_policy_documents(db: Session = Depends(get_db)):
    """List all uploaded corporate policy handbook PDFs."""
    docs = db.query(PolicyDocument).order_by(PolicyDocument.created_at.desc()).all()
    return {
        "documents": [
            {
                "doc_id": d.doc_id,
                "filename": d.filename,
                "display_name": d.display_name or d.filename,
                "description": d.description,
                "file_size_bytes": d.file_size_bytes,
                "chunk_count": d.chunk_count,
                "status": d.status,
                "is_active": bool(d.is_active),
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in docs
        ]
    }


@app.post("/policy-documents", status_code=202)
async def upload_policy_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    display_name: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Upload a corporate policy PDF and index it in ChromaDB (async)."""
    if file.content_type not in ("application/pdf", "application/octet-stream"):
        # Also allow generic binary in case browser doesn't detect mime correctly
        if not (file.filename or "").lower().endswith(".pdf"):
            raise HTTPException(400, "Only PDF files are accepted for policy documents.")

    doc_id = str(uuid.uuid4())
    dest_path = Path(settings.policy_docs_dir) / f"{doc_id}.pdf"

    content = await file.read()
    if len(content) > settings.policy_doc_max_size:
        raise HTTPException(413, f"File exceeds {settings.policy_doc_max_size // 1048576} MB limit.")

    dest_path.write_bytes(content)

    doc = PolicyDocument(
        doc_id=doc_id,
        filename=file.filename or "policy.pdf",
        display_name=display_name or file.filename or "policy.pdf",
        description=description,
        file_path=str(dest_path),
        file_size_bytes=len(content),
        status="processing",
    )
    db.add(doc)
    db.commit()

    async def _ingest(doc_id: str, file_path: str, doc_name: str):
        """Background task: chunk + embed + store in ChromaDB, then update DB."""
        _db = SessionLocal()
        try:
            from services.rag_service import get_rag_service
            svc = get_rag_service()
            loop = asyncio.get_event_loop()
            chunk_count = await loop.run_in_executor(
                None, svc.ingest_pdf, file_path, doc_id, doc_name
            )
            _doc = _db.query(PolicyDocument).filter_by(doc_id=doc_id).first()
            if _doc:
                _doc.chunk_count = chunk_count
                _doc.status = "ready"
                _db.commit()
        except Exception as exc:
            _doc = _db.query(PolicyDocument).filter_by(doc_id=doc_id).first()
            if _doc:
                _doc.status = "error"
                _doc.error_message = str(exc)
                _db.commit()
        finally:
            _db.close()

    background_tasks.add_task(
        _ingest, doc_id, str(dest_path), display_name or file.filename or "policy.pdf"
    )

    return {
        "doc_id": doc_id,
        "status": "processing",
        "message": "PDF uploaded. Indexing in background — check GET /policy-documents for status.",
    }


@app.patch("/policy-documents/{doc_id}")
async def update_policy_document(
    doc_id: str,
    display_name: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    is_active: Optional[bool] = Form(None),
    db: Session = Depends(get_db),
):
    """Update display name, description, or active status of a policy document."""
    doc = db.query(PolicyDocument).filter_by(doc_id=doc_id).first()
    if not doc:
        raise HTTPException(404, f"Policy document '{doc_id}' not found.")
    if display_name is not None:
        doc.display_name = display_name
    if description is not None:
        doc.description = description
    if is_active is not None:
        doc.is_active = 1 if is_active else 0
    db.commit()
    return {"doc_id": doc_id, "status": "updated"}


@app.delete("/policy-documents/{doc_id}", status_code=204)
async def delete_policy_document(doc_id: str, db: Session = Depends(get_db)):
    """Delete a policy document from the DB, ChromaDB, and disk."""
    doc = db.query(PolicyDocument).filter_by(doc_id=doc_id).first()
    if not doc:
        raise HTTPException(404, f"Policy document '{doc_id}' not found.")

    # Remove chunks from ChromaDB
    try:
        from services.rag_service import get_rag_service
        get_rag_service().delete_doc(doc_id)
    except Exception:
        pass  # ChromaDB removal failure is non-fatal

    # Remove file from disk
    if doc.file_path and Path(doc.file_path).exists():
        Path(doc.file_path).unlink(missing_ok=True)

    db.delete(doc)
    db.commit()


@app.get("/policy-documents/{doc_id}/preview")
async def preview_policy_document(
    doc_id: str,
    q: str = "expense policy limit",
    db: Session = Depends(get_db),
):
    """Test-query the RAG index for a specific document to verify indexing."""
    doc = db.query(PolicyDocument).filter_by(doc_id=doc_id).first()
    if not doc:
        raise HTTPException(404, f"Policy document '{doc_id}' not found.")
    if doc.status != "ready":
        raise HTTPException(400, f"Document is not ready yet (status: {doc.status}).")

    from services.rag_service import get_rag_service
    hits = get_rag_service().query(q, n_results=3)
    # Filter to only chunks from this doc
    hits = [h for h in hits if h.get("doc_id") == doc_id]
    return {"doc_id": doc_id, "query": q, "results": hits}


# ---------------------------------------------------------------------------
# Background processing pipeline
# ---------------------------------------------------------------------------

async def _run_processing_pipeline(session_id: str):
    """
    The core AI processing pipeline — runs in the background after POST /process.

    This function orchestrates all AI agents and produces the final expense report.
    It runs as a FastAPI BackgroundTask, meaning it executes after the HTTP
    response has been sent and does not block any other requests.

    Pipeline steps:
      1. CONCURRENT RECEIPT EXTRACTION:
         All receipts are processed concurrently via asyncio.gather().
         A Semaphore(4) limits simultaneous Claude API calls to avoid rate limits.
         Each receipt: Claude Vision extracts data → policy verifier checks compliance.

      2. DAILY MEAL CAP ENFORCEMENT:
         After all receipts are processed, meal items are grouped by date.
         GSA 75% first/last-day rule is applied to boundary days.
         If daily total exceeds the cap, all meals for that day are prorated.

      3. MILEAGE CALCULATION:
         Each mileage entry is processed sequentially (simpler, fewer items).
         Claude tool-use looks up the IRS mileage rate and multiplies by miles.

      4. SUMMARY BUILDING:
         Totals and policy sources are aggregated from all expense items.

      5. PDF GENERATION:
         Jinja2 renders the HTML template; WeasyPrint converts it to PDF.

    Throughout processing, JSON events are broadcast via WebSocket so the
    frontend can show a real-time progress bar and terminal log.

    On any unhandled exception, session status is set to "failed" and an
    error event is broadcast to the frontend.
    """
    db = SessionLocal()
    try:
        report = db.query(ExpenseReport).filter_by(session_id=session_id).first()
        if not report:
            return

        upload_dir = Path(settings.upload_dir) / session_id
        trip_year = int(report.trip_start_date[:4])
        trip_month = datetime.date.fromisoformat(report.trip_start_date).strftime("%B")

        policy_overrides: Optional[PolicyOverrides] = None
        if report.policy_overrides_json:
            policy_overrides = PolicyOverrides(**report.policy_overrides_json)

        # Notify via WebSocket
        await ws_manager.broadcast(session_id, {
            "type": "status", "status": "processing",
            "message": "Starting AI pipeline…"
        })

        # ---- Process receipts concurrently ----
        raw_items = list(report.expense_items_json or [])
        progress_lock = asyncio.Lock()
        progress_counter = [0]

        async def process_one_receipt(raw_item: dict) -> ExpenseItem:
            """
            Process a single receipt through the full AI pipeline.

            This inner function is the unit of work for asyncio.gather().
            It runs concurrently for all receipts, limited by the semaphore.

            Steps:
              1. Call Claude Vision to extract receipt data
              2. Fall back location to trip destination if Claude didn't find one
              3. Call the policy verifier to check compliance
              4. Set final_approved_amount from the policy verdict
              5. Flag for manager review if confidence < 0.6

            On any exception, the item is flagged for manager review with
            a zero-dollar amount and an error message in the policy notes.
            This ensures a single bad receipt doesn't abort the entire pipeline.
            """
            filename = raw_item.get("receipt_filename", "")
            mime = raw_item.get("receipt_content_type", "image/jpeg")
            file_path = str(upload_dir / filename)

            item = ExpenseItem(
                id=raw_item.get("id", str(uuid.uuid4())),
                receipt_filename=filename,
            )

            try:
                # Step 1: Claude Vision extraction
                extracted = await extract_receipt_data(
                    file_path, mime, category_hint=raw_item.get("category_hint")
                )
                item.extracted = extracted

                # Step 2: Flag low-confidence extractions for manager review
                if extracted.confidence_score < 0.6:
                    item.requires_manager_review = True

                # Step 3: Fall back location to trip destination if not on receipt
                if not extracted.location_city:
                    extracted.location_city = report.destination_city
                if not extracted.location_state:
                    extracted.location_state = report.destination_state

                # Step 4: Policy verification (RAG + web search)
                policy = await verify_expense_policy(
                    extracted, trip_year, trip_month, policy_overrides
                )
                item.policy_check = policy
                item.final_approved_amount = policy.approved_amount

            except Exception as exc:
                # On failure: flag for review, zero the amount, record the error
                item.requires_manager_review = True
                item.final_approved_amount = Decimal("0.00")
                item.policy_check = PolicyCheckResult(
                    category=raw_item.get("category_hint") or "other",
                    claimed_amount=Decimal("0.00"),
                    policy_source="Error during processing",
                    is_compliant=False,
                    approved_amount=Decimal("0.00"),
                    notes=f"Processing error: {exc}",
                    search_query_used="",
                )

            # Update progress counter (thread-safe via asyncio.Lock)
            async with progress_lock:
                progress_counter[0] += 1
                report.progress_current = progress_counter[0]
                db.commit()
                # Broadcast progress event to all connected WebSocket clients
                await ws_manager.broadcast(session_id, {
                    "type":    "progress",
                    "done":    progress_counter[0],
                    "total":   report.progress_total,
                    "pct":     int(progress_counter[0] / max(report.progress_total, 1) * 100),
                    "message": f"Processed receipt: {filename}",
                })

            return item

        # Run all receipts concurrently (up to 4 at a time to avoid rate limits)
        semaphore = asyncio.Semaphore(4)

        async def throttled_receipt(raw_item):
            async with semaphore:
                return await process_one_receipt(raw_item)

        expense_items: list[ExpenseItem] = list(
            await asyncio.gather(*[throttled_receipt(r) for r in raw_items])
        )

        # ---- Apply daily meal caps ----
        _apply_daily_meal_caps(expense_items, report.trip_start_date, report.trip_end_date)

        # ---- Process mileage entries ----
        for raw_mileage in (report.mileage_entries_json or []):
            entry = MileageEntry(**raw_mileage)
            item = ExpenseItem(
                id=str(uuid.uuid4()),
                mileage=entry,
            )
            try:
                policy = await calculate_mileage_reimbursement(
                    entry, trip_year,
                    rate_override=policy_overrides.mileage_rate_per_mile if policy_overrides else None,
                )
                item.policy_check = policy
                item.final_approved_amount = policy.approved_amount
            except Exception as exc:
                item.requires_manager_review = True
                item.final_approved_amount = Decimal("0.00")
                item.policy_check = PolicyCheckResult(
                    category="mileage",
                    claimed_amount=Decimal("0.00"),
                    policy_source="Error",
                    is_compliant=False,
                    approved_amount=Decimal("0.00"),
                    notes=f"Mileage calculation error: {exc}",
                    search_query_used="",
                )

            expense_items.append(item)
            progress_counter[0] += 1
            report.progress_current = progress_counter[0]
            db.commit()
            await ws_manager.broadcast(session_id, {
                "type": "progress",
                "done": progress_counter[0],
                "total": report.progress_total,
                "pct": int(progress_counter[0] / max(report.progress_total, 1) * 100),
                "message": f"Processed mileage: {entry.origin} → {entry.destination}",
            })

        # ---- Build summary ----
        summary = build_summary(expense_items)

        # ---- Generate PDF ----
        req = ExpenseReportRequest(
            submitter_name=report.submitter_name,
            submitter_email=report.submitter_email,
            department=report.department,
            trip_purpose=report.trip_purpose,
            trip_start_date=datetime.date.fromisoformat(report.trip_start_date),
            trip_end_date=datetime.date.fromisoformat(report.trip_end_date),
            destination_city=report.destination_city,
            destination_state=report.destination_state,
        )

        await ws_manager.broadcast(session_id, {
            "type": "status", "status": "generating_pdf",
            "message": "Generating PDF report…"
        })

        pdf_filename = f"expense_report_{session_id}.pdf"
        pdf_path = await generate_expense_report_pdf(req, expense_items, summary, pdf_filename)

        # ---- Persist results ----
        report.expense_items_json = [i.model_dump(mode="json") for i in expense_items]
        report.report_summary_json = summary.model_dump(mode="json")
        report.pdf_path = pdf_path
        report.status = "completed"
        db.commit()

        await ws_manager.broadcast(session_id, {
            "type": "completed",
            "status": "completed",
            "message": "Report ready!",
            "total_approved": str(summary.total_approved),
        })

    except Exception as exc:
        try:
            report.status = "failed"
            report.error_message = str(exc)
            db.commit()
            await ws_manager.broadcast(session_id, {
                "type": "failed",
                "status": "failed",
                "message": f"Processing failed: {exc}",
            })
        except Exception:
            pass
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Meal aggregation helpers
# ---------------------------------------------------------------------------

def _apply_daily_meal_caps(
    expense_items: list[ExpenseItem],
    trip_start_date: str,
    trip_end_date: str,
) -> None:
    """
    Enforce daily GSA M&IE (meals & incidental expenses) caps.

    This function is called AFTER all receipts have been individually verified.
    It aggregates all meal items by date and applies two rules:

    Rule 1 — Daily cap:
      If the sum of all meal items on a given day exceeds the GSA M&IE cap,
      each meal's approved_amount is prorated proportionally:
        approved_i = original_approved_i * (cap / daily_total)

    Rule 2 — 75% first/last-day rule (GSA Federal Travel Regulations):
      On the first and last day of travel, only 75% of the full daily M&IE
      rate is reimbursable (because the employee has partial-day meals at home).
      The effective cap is reduced: effective_cap = base_cap * 0.75

    Args:
        expense_items:   All processed expense items (mutated in place).
        trip_start_date: First day of travel in YYYY-MM-DD format.
        trip_end_date:   Last day of travel in YYYY-MM-DD format.
    """
    from collections import defaultdict

    start = datetime.date.fromisoformat(trip_start_date)
    end = datetime.date.fromisoformat(trip_end_date)

    # Group meal items by date (only items with extracted category="meals" and a date)
    by_date: dict[datetime.date, list[ExpenseItem]] = defaultdict(list)
    for item in expense_items:
        if (
            item.extracted
            and item.extracted.category == "meals"
            and item.extracted.date is not None
        ):
            by_date[item.extracted.date].append(item)

    for day, items in by_date.items():
        # Use the minimum policy_limit across all meal items for this day
        # (in case different items had different limits from different searches)
        limits = [
            item.policy_check.policy_limit
            for item in items
            if item.policy_check and item.policy_check.policy_limit is not None
        ]
        if not limits:
            continue  # No policy limits found — skip this day

        base_cap = min(limits)  # Use the most conservative limit

        # Apply 75% rule on first and last day of travel
        is_boundary_day = (day == start or day == end)
        effective_cap = (
            (base_cap * Decimal("0.75")).quantize(Decimal("0.01"))
            if is_boundary_day else base_cap
        )

        # Sum the currently approved amounts for all meals on this day
        daily_total = sum(item.final_approved_amount for item in items)
        if daily_total <= effective_cap:
            continue  # Already within the cap — nothing to adjust

        # Prorate each meal item proportionally to stay within the cap
        for item in items:
            share = (item.final_approved_amount / daily_total * effective_cap).quantize(Decimal("0.01"))
            item.final_approved_amount = share
            if item.policy_check:
                item.policy_check.approved_amount = share
                # Append a note explaining the cap adjustment
                day_note = (
                    f" [75% first/last-day rule applied; effective cap ${effective_cap}]"
                    if is_boundary_day
                    else f" [Daily meal total exceeded ${base_cap} GSA M&IE cap; prorated to ${share}]"
                )
                item.policy_check.notes = item.policy_check.notes.rstrip(".") + day_note


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_report_or_404(session_id: str, db: Session) -> ExpenseReport:
    """
    Fetch an ExpenseReport by session_id or raise a 404 HTTPException.

    Used as a DRY helper by every route that operates on a specific session.
    Centralises the "does this session exist?" check so routes don't repeat it.
    """
    report = db.query(ExpenseReport).filter_by(session_id=session_id).first()
    if not report:
        raise HTTPException(404, f"Session '{session_id}' not found.")
    return report


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
