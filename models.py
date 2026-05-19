"""
models.py — Pydantic Data Models & SQLAlchemy ORM Models
=========================================================
This file defines two categories of models:

  1. PYDANTIC MODELS — Data structures that flow through the AI processing
     pipeline. These are used for validation, serialization, and as the
     typed interface between services. They are NOT stored directly in the
     database; instead they are serialized to JSON and stored in JSON columns.

  2. SQLALCHEMY ORM MODELS — Database table definitions for persistent
     session storage. Each session represents one expense report submission
     and stores all data as JSON blobs in a single table row.

Data flow overview:
  Request body → ExpenseReportRequest
  Claude Vision output → ExtractedReceiptData
  Policy verification output → PolicyCheckResult
  Combined per-receipt result → ExpenseItem
  All items combined → ExpenseReportSummary
  Persisted in database → ExpenseReport (ORM)
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional, List

from pydantic import BaseModel, Field
from sqlalchemy import Column, Integer, String, DateTime, Text, JSON
from sqlalchemy.sql import func

from database import Base


# ---------------------------------------------------------------------------
# Expense Category Type Alias
# ---------------------------------------------------------------------------

# The exact set of category strings the system recognises.
# Claude Vision is instructed to return exactly one of these strings.
# The `Literal` type causes Pydantic to raise a validation error if any
# other string is returned (e.g. "food" instead of "meals").
ExpenseCategory = Literal["airfare", "hotel", "taxi", "meals", "parking", "mileage", "other"]


# ===========================================================================
# PYDANTIC MODELS — Pipeline data structures
# ===========================================================================

class ExtractedReceiptData(BaseModel):
    """
    Structured output from the Claude Vision receipt extraction step.

    Claude reads the receipt image and returns a JSON object that Pydantic
    validates into this model. Every field that Claude couldn't determine
    from the image is set to null (None).

    Fields:
        amount:           The final total paid (after tax and tip). Stored as
                          Decimal for precise financial arithmetic.
        currency:         3-letter ISO currency code. Defaults to "USD".
        date:             Date the expense was incurred (YYYY-MM-DD).
        vendor:           Business name on the receipt.
        category:         One of the ExpenseCategory literals above.
        description:      Optional brief description of what was purchased.
        location_city:    City where the expense occurred (for GSA rate lookup).
        location_state:   2-letter US state code (for GSA rate lookup).
        confidence_score: How confident Claude is in the extraction (0.0–1.0).
                          Receipts below 0.6 are flagged for manager review.
    """
    amount: Decimal
    currency: str = "USD"
    date: date
    vendor: str
    category: ExpenseCategory
    description: Optional[str] = None
    location_city: Optional[str] = None
    location_state: Optional[str] = None
    # ge=0.0, le=1.0 means Pydantic enforces the range [0.0, 1.0]
    confidence_score: float = Field(ge=0.0, le=1.0)


class PolicyCheckResult(BaseModel):
    """
    Structured output from the Claude policy verification step.

    Claude runs a multi-turn tool-use loop (searching internal ChromaDB
    policies and/or live GSA/IRS rates via Tavily), then returns a JSON
    verdict that Pydantic validates into this model.

    Fields:
        category:         The expense category being verified.
        claimed_amount:   What the employee claimed on the receipt.
        policy_limit:     The maximum allowed amount per policy. None means
                          no specific limit applies (expense is fully approved).
        policy_source:    Where the policy limit came from — either an internal
                          doc name or a GSA/IRS citation.
        is_compliant:     True if claimed_amount <= policy_limit.
        approved_amount:  min(claimed_amount, policy_limit). This is the amount
                          that will actually be reimbursed.
        notes:            1–2 sentence human-readable explanation for the report.
        search_query_used:The exact search queries Claude used (for transparency).
    """
    category: ExpenseCategory
    claimed_amount: Decimal
    policy_limit: Optional[Decimal] = None   # None = no specific limit
    policy_source: str
    is_compliant: bool
    approved_amount: Decimal
    notes: str
    search_query_used: str


class MileageEntry(BaseModel):
    """
    A single mileage reimbursement claim entered by the user in Step 1.

    Instead of uploading a receipt, users fill in trip details and the
    system calculates reimbursement using the current IRS mileage rate.

    Fields:
        origin:          Starting address or description (e.g. "Home - Austin, TX")
        destination:     Ending address or description (e.g. "Austin-Bergstrom Airport")
        miles:           One-way distance in miles. Must be > 0 (enforced by Field gt=0).
        is_round_trip:   If True, the total distance is doubled (miles * 2).
        rate_per_mile:   Optional override. If None, the current IRS rate is
                         looked up dynamically via Claude + Tavily.
    """
    origin: str
    destination: str
    miles: float = Field(gt=0)              # Must be positive
    is_round_trip: bool = True
    rate_per_mile: Optional[float] = None   # None → look up IRS rate


class ExpenseItem(BaseModel):
    """
    Represents a single processed expense — either a receipt or a mileage entry.

    This is the central data structure that combines raw extraction output,
    policy verification results, and manager review fields into one object.
    A list of ExpenseItems is stored as a JSON array in the ExpenseReport DB row.

    Fields:
        id:                     UUID for this specific item (for PATCH endpoints).
        receipt_filename:       Original uploaded filename (None for mileage items).
        extracted:              Claude Vision output (None for mileage items).
        mileage:                Mileage entry (None for receipt items).
        policy_check:           Compliance verdict from the policy verifier.
        final_approved_amount:  The final amount to reimburse. Starts as
                                policy_check.approved_amount, but can be
                                overridden by a manager via the PATCH endpoint.
        requires_manager_review:True if extraction confidence < 0.6 OR if
                                 an exception occurred during processing.
        manager_reviewed:       True once a manager has acted on this item.
        manager_approved_amount:Amount the manager manually approved (overrides AI).
        manager_notes:          Manager's comment on why they made changes.
        reviewed_at:            ISO timestamp of when the manager reviewed.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    receipt_filename: Optional[str] = None
    extracted: Optional[ExtractedReceiptData] = None
    mileage: Optional[MileageEntry] = None
    policy_check: Optional[PolicyCheckResult] = None
    final_approved_amount: Decimal = Decimal("0.00")
    requires_manager_review: bool = False

    # Human-in-the-loop (HITL) manager review fields
    manager_reviewed: bool = False
    manager_approved_amount: Optional[Decimal] = None
    manager_notes: Optional[str] = None
    reviewed_at: Optional[str] = None  # ISO datetime string


class ManagerItemPatch(BaseModel):
    """
    Request body for PATCH /sessions/{session_id}/items/{item_id}.

    Used by accounting managers to override AI decisions on flagged items.
    All fields are optional — only send what you want to change.

    Fields:
        manager_approved_amount: Override the AI-approved dollar amount.
        manager_notes:           Reason for the override (stored in the report).
        approve:                 Set to True to clear the review flag and mark
                                 this item as approved.
        vendor_override:         Correct a misread vendor name.
        amount_override:         Correct a misread receipt amount.
    """
    manager_approved_amount: Optional[Decimal] = None
    manager_notes: Optional[str] = None
    approve: bool = False
    vendor_override: Optional[str] = None
    amount_override: Optional[Decimal] = None


class PolicyOverrides(BaseModel):
    """
    Optional organization-specific policy caps that override GSA/IRS defaults.

    Set these in Step 1 of the UI to apply your company's stricter (or more
    generous) expense limits. When a cap is set, the policy verifier skips
    the AI tool-use loop entirely and applies the cap directly — saving
    API calls and ensuring consistent enforcement of company policy.

    Fields:
        meal_daily_cap:       Max daily meal allowance (e.g. Decimal("75.00"))
        hotel_nightly_cap:    Max nightly hotel rate (e.g. Decimal("150.00"))
        mileage_rate_per_mile:Custom mileage rate in $/mile (e.g. 0.50)
    """
    meal_daily_cap: Optional[Decimal] = None
    hotel_nightly_cap: Optional[Decimal] = None
    mileage_rate_per_mile: Optional[float] = None


class ExpenseReportRequest(BaseModel):
    """
    Request body for POST /sessions — creates a new expense report session.

    Captures all the trip details needed to look up location-specific GSA
    per diem rates and identify the correct IRS mileage year.

    Fields:
        submitter_name:    Employee's full name.
        submitter_email:   Employee's email (appears on the PDF report).
        department:        Department name (for routing/accounting).
        trip_purpose:      Why the trip was taken (appears on the PDF report).
        trip_start_date:   First day of travel (used for 75% first-day meal rule).
        trip_end_date:     Last day of travel (used for 75% last-day meal rule).
        destination_city:  Primary destination city (for GSA rate lookup).
        destination_state: 2-letter state code (for GSA rate lookup).
        mileage_entries:   Zero or more mileage claims to calculate.
        policy_overrides:  Optional org-specific caps that override GSA/IRS defaults.
    """
    submitter_name: str
    submitter_email: str
    department: str
    trip_purpose: str
    trip_start_date: date
    trip_end_date: date
    destination_city: str
    destination_state: str
    mileage_entries: List[MileageEntry] = []
    policy_overrides: Optional[PolicyOverrides] = None


class ExpenseReportSummary(BaseModel):
    """
    Aggregate totals and metadata for a completed expense report.

    Built by services/pdf_generator.py's build_summary() function after
    all items have been processed. Stored as JSON in the DB and also
    rendered in the PDF report and dashboard UI.

    Fields:
        total_claimed:             Sum of all claimed amounts.
        total_approved:            Sum of all approved amounts (after policy limits).
        total_adjusted:            total_claimed - total_approved (how much was cut).
        items_requiring_review:    Count of items flagged for manager attention.
        policy_sources_referenced: Deduplicated list of policy sources used
                                   (e.g. "GSA Per Diem FY2025 Chicago, IL").
        generated_at:              Human-readable timestamp for the report footer.
    """
    total_claimed: Decimal
    total_approved: Decimal
    total_adjusted: Decimal
    items_requiring_review: int
    policy_sources_referenced: List[str]
    generated_at: str   # e.g. "May 18, 2025 at 06:45 PM"


# ===========================================================================
# SQLALCHEMY ORM MODELS — Database tables
# ===========================================================================

class PolicyDocument(Base):
    """
    Database record for an uploaded corporate policy handbook PDF.

    When a PDF is uploaded via POST /policy-documents:
      1. A PolicyDocument row is created with status="processing"
      2. A background task chunks + embeds the PDF into ChromaDB
      3. The row is updated to status="ready" with chunk_count filled in

    The doc_id is also used as the ChromaDB metadata key so chunks from
    this document can be found and deleted when the doc is removed.
    """
    __tablename__ = "policy_documents"

    id = Column(Integer, primary_key=True, index=True)
    # UUID string — used as the ChromaDB document identifier
    doc_id = Column(String(36), unique=True, index=True, default=lambda: str(uuid.uuid4()))
    filename = Column(String(255), nullable=False)           # Original filename
    display_name = Column(String(255), nullable=True)        # User-friendly label
    description = Column(Text, nullable=True)                # Optional description
    file_path = Column(String(500), nullable=False)          # Absolute path on disk
    file_size_bytes = Column(Integer, nullable=True)
    chunk_count = Column(Integer, default=0)                 # Number of ChromaDB chunks
    # Status lifecycle: "processing" → "ready" (or "error" on failure)
    status = Column(String(50), default="processing")
    error_message = Column(Text, nullable=True)              # Set if status="error"
    is_active = Column(Integer, default=1)                   # 1=active, 0=disabled
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class ExpenseReport(Base):
    """
    Database record for a single expense report session.

    One row is created when a user clicks "Start New Report". The row
    accumulates data through the multi-step flow:
      draft → receipts_uploaded → processing → completed (or failed)

    JSON columns store nested Pydantic model data. This avoids complex
    relational joins and keeps the schema simple — the full expense data
    can be loaded with a single SELECT query.
    """
    __tablename__ = "expense_reports"

    id = Column(Integer, primary_key=True, index=True)
    # UUID used in all API URLs — e.g. /sessions/{session_id}/results
    session_id = Column(String(36), unique=True, index=True, default=lambda: str(uuid.uuid4()))

    # ── Submitter & trip details ────────────────────────────────────────────
    submitter_name = Column(String(255))
    submitter_email = Column(String(255))
    department = Column(String(255))
    trip_purpose = Column(Text)
    trip_start_date = Column(String(10))    # "YYYY-MM-DD" string
    trip_end_date = Column(String(10))      # "YYYY-MM-DD" string
    destination_city = Column(String(255))
    destination_state = Column(String(10))

    # ── JSON blobs — serialized Pydantic model data ─────────────────────────
    mileage_entries_json = Column(JSON, default=list)   # List[MileageEntry.dict()]
    expense_items_json = Column(JSON, default=list)     # List[ExpenseItem.dict()]
    report_summary_json = Column(JSON, nullable=True)   # ExpenseReportSummary.dict()
    policy_overrides_json = Column(JSON, nullable=True) # PolicyOverrides.dict()

    # ── Processing state ────────────────────────────────────────────────────
    # Lifecycle: "draft" → "receipts_uploaded" → "processing" → "completed"/"failed"
    status = Column(String(50), default="draft")
    pdf_path = Column(String(500), nullable=True)       # Absolute path to generated PDF
    error_message = Column(Text, nullable=True)          # Set if status="failed"

    # ── Progress tracking (for real-time WebSocket progress bar) ────────────
    progress_current = Column(Integer, default=0)       # Items processed so far
    progress_total = Column(Integer, default=0)         # Total items to process

    # ── Manager review state ────────────────────────────────────────────────
    # "pending_review" → "review_complete" (updated by PATCH /items endpoint)
    review_status = Column(String(50), nullable=True)

    # ── Timestamps ──────────────────────────────────────────────────────────
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
