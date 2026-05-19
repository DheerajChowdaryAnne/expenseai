"""
services/pdf_generator.py — Jinja2 + WeasyPrint PDF Report Generation
======================================================================
Generates professional expense report PDFs from processed expense items.

Two public functions:
  - build_summary()              — Aggregates totals and metadata from all items
  - generate_expense_report_pdf() — Renders HTML template and converts to PDF

PDF rendering pipeline:
  1. build_summary() computes totals, counts flagged items, collects policy sources
  2. generate_expense_report_pdf() renders templates/expense_report.html using
     Jinja2 with the report data, expense items, and summary
  3. WeasyPrint converts the rendered HTML to a Letter-size PDF
  4. The PDF is saved to settings.reports_dir and the path is returned

macOS / WeasyPrint setup note:
  WeasyPrint requires Pango and Cairo for font rendering and PDF output.
  On macOS with Homebrew, these live in /opt/homebrew/lib which is not in
  the default dynamic linker search path. The DYLD_LIBRARY_PATH injection
  at the top of this file fixes that — it must happen before WeasyPrint
  is imported anywhere in the process.

Dependencies:
  - weasyprint  : HTML → PDF converter (install: pip install weasyprint)
  - jinja2      : Template engine for the HTML report
  - pango/cairo : System libraries (macOS: brew install pango cairo gobject-introspection)
"""
from __future__ import annotations
import os

# ── macOS Homebrew library path fix ───────────────────────────────────────
# WeasyPrint needs Pango and Cairo, which Homebrew installs to /opt/homebrew/lib.
# This path isn't in ctypes' default search paths on macOS, so we inject it
# into DYLD_LIBRARY_PATH BEFORE importing WeasyPrint or any of its dependencies.
# This block must run at module import time — placing it here ensures it happens
# before any other code in this module executes.
_brew_lib = "/opt/homebrew/lib"
if os.path.isdir(_brew_lib):
    _existing = os.environ.get("DYLD_LIBRARY_PATH", "")
    if _brew_lib not in _existing:
        os.environ["DYLD_LIBRARY_PATH"] = f"{_brew_lib}:{_existing}" if _existing else _brew_lib

from datetime import datetime
from decimal import Decimal
from typing import List
from jinja2 import Environment, FileSystemLoader
from models import ExpenseItem, ExpenseReportRequest, ExpenseReportSummary
from config import settings

# Jinja2 template environment — loads templates from the /templates directory
# autoescape=True prevents HTML injection in user-provided strings (e.g. vendor names)
_template_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
_jinja_env = Environment(loader=FileSystemLoader(_template_dir), autoescape=True)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_summary(expense_items: List[ExpenseItem]) -> ExpenseReportSummary:
    """
    Compute aggregate totals and collect metadata from all processed expense items.

    Called both after the initial processing pipeline and after manager review
    (PATCH /items endpoint) to keep the summary always up to date.

    Logic:
      - total_claimed = sum of all receipt amounts + mileage claimed amounts
      - total_approved = sum of all final_approved_amounts (after policy limits)
      - total_adjusted = total_claimed - total_approved (how much was cut)
      - items_requiring_review = count of items where requires_manager_review=True
      - policy_sources_referenced = deduplicated list of policy sources used

    Args:
        expense_items: List of fully-processed ExpenseItem objects.

    Returns:
        ExpenseReportSummary with all computed totals and metadata.
    """
    total_claimed = Decimal("0.00")
    total_approved = Decimal("0.00")
    sources: list[str] = []
    review_count = 0

    for item in expense_items:
        # For receipt items: claimed amount comes from Claude Vision extraction
        if item.extracted:
            total_claimed += item.extracted.amount
        # For mileage items: claimed amount is the calculated reimbursement
        elif item.mileage and item.policy_check:
            total_claimed += item.policy_check.claimed_amount

        # Approved amount is what gets reimbursed (may be less than claimed)
        total_approved += item.final_approved_amount

        # Collect unique policy sources for the "Sources Consulted" section
        if item.policy_check and item.policy_check.policy_source:
            src = item.policy_check.policy_source
            if src not in sources:
                sources.append(src)

        # Count items needing manager attention
        if item.requires_manager_review:
            review_count += 1

    return ExpenseReportSummary(
        total_claimed=total_claimed,
        total_approved=total_approved,
        total_adjusted=total_claimed - total_approved,
        items_requiring_review=review_count,
        policy_sources_referenced=sources,
        # Human-readable timestamp shown in the PDF report footer
        generated_at=datetime.now().strftime("%B %d, %Y at %I:%M %p"),
    )


async def generate_expense_report_pdf(
    report_request: ExpenseReportRequest,
    expense_items: List[ExpenseItem],
    summary: ExpenseReportSummary,
    output_filename: str,
) -> str:
    """
    Render the Jinja2 HTML template and convert it to a PDF using WeasyPrint.

    This function is called at the end of the background processing pipeline
    in main.py, and also by POST /sessions/{id}/regenerate-pdf after manager
    review is complete.

    Rendering pipeline:
      1. Build a list of `rendered_items` dicts that flatten nested Pydantic
         model fields into simple values the Jinja2 template can use directly
      2. Render templates/expense_report.html with Jinja2
      3. Use WeasyPrint's HTML() to convert the rendered HTML string to PDF
         (base_url=static_dir ensures WeasyPrint can find the CSS stylesheet)
      4. Write the PDF to settings.reports_dir/{output_filename}

    Args:
        report_request:  Trip details and submitter info (from the session).
        expense_items:   List of processed ExpenseItem objects.
        summary:         Pre-computed totals from build_summary().
        output_filename: The PDF filename (e.g. "expense_report_{session_id}.pdf").

    Returns:
        Absolute path to the generated PDF file.

    Raises:
        RuntimeError: If WeasyPrint is not installed.
    """
    try:
        from weasyprint import HTML, CSS
    except ImportError as e:
        raise RuntimeError(
            "WeasyPrint is required for PDF generation. "
            "Install: pip install weasyprint && brew install pango cairo gobject-introspection"
        ) from e

    template = _jinja_env.get_template("expense_report.html")

    # ── Flatten expense items into simple dicts for the template ────────────
    # Jinja2 templates work best with flat dicts rather than nested Pydantic models,
    # so we extract the fields the template needs into a simpler structure.
    rendered_items = []
    for idx, item in enumerate(expense_items, start=1):
        rendered_items.append(
            {
                "num":              idx,
                "id":               item.id,
                "receipt_filename": item.receipt_filename,
                # Date from extracted data; "—" for mileage items
                "date":             item.extracted.date if item.extracted else "—",
                # Category: prefer extracted, then policy_check, then mileage default
                "category": (
                    item.extracted.category if item.extracted and item.extracted.category
                    else item.policy_check.category if item.policy_check and item.policy_check.category
                    else "mileage" if item.mileage else "other"
                ).title(),
                # Vendor: receipt vendor name or "origin → destination" for mileage
                "vendor": (
                    item.extracted.vendor if item.extracted
                    else f"{item.mileage.origin} → {item.mileage.destination}" if item.mileage
                    else "—"
                ),
                # Claimed amount: from receipt or from mileage calculation
                "claimed": (
                    item.extracted.amount if item.extracted
                    else item.policy_check.claimed_amount if item.policy_check
                    else Decimal("0")
                ),
                "approved":       item.final_approved_amount,
                "is_compliant":   item.policy_check.is_compliant if item.policy_check else True,
                "requires_review": item.requires_manager_review,
                "policy_source":  item.policy_check.policy_source if item.policy_check else "",
                "policy_limit":   item.policy_check.policy_limit if item.policy_check else None,
                "notes":          item.policy_check.notes if item.policy_check else "",
                "search_query":   item.policy_check.search_query_used if item.policy_check else "",
            }
        )

    # Absolute path to the static directory — WeasyPrint needs this as base_url
    # so it can resolve relative paths in the HTML/CSS (e.g. font URLs)
    static_dir = os.path.abspath(
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
    )

    # Render the Jinja2 HTML template with all the data
    html_content = template.render(
        report=report_request,       # Trip details and submitter info
        items=rendered_items,        # Flattened expense item list
        summary=summary,             # Aggregate totals
        static_dir=static_dir,       # For any template-level static file references
    )

    # Ensure the output directory exists before writing the PDF
    os.makedirs(settings.reports_dir, exist_ok=True)
    output_path = os.path.join(settings.reports_dir, output_filename)

    # Convert HTML → PDF using WeasyPrint.
    # base_url=static_dir allows WeasyPrint to find relative CSS/font references.
    HTML(string=html_content, base_url=static_dir).write_pdf(output_path)

    return output_path
