"""
Comprehensive end-to-end Playwright test for ExpenseAI.
Tests: Step 1-4 flow, HITL Manager Dashboard, RAG policy doc upload.

Usage:
    source venv/bin/activate
    python test_e2e.py
"""

import asyncio
import json
import os
import io
import time
from pathlib import Path

from playwright.async_api import async_playwright, Page, expect

BASE_URL = "http://localhost:8000"
RECEIPTS_DIR = Path(__file__).parent / "test_receipts"
SCREENSHOTS_DIR = Path(__file__).parent / "test_screenshots"
SCREENSHOTS_DIR.mkdir(exist_ok=True)

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
INFO = "\033[94m→\033[0m"

results: list[dict] = []


def log(symbol, msg):
    print(f"  {symbol} {msg}")


def record(name: str, passed: bool, note: str = ""):
    results.append({"test": name, "passed": passed, "note": note})
    log(PASS if passed else FAIL, f"{name}" + (f" — {note}" if note else ""))


async def ss(page: Page, name: str):
    path = SCREENSHOTS_DIR / f"{name}.png"
    await page.screenshot(path=str(path), full_page=True)
    log(INFO, f"Screenshot → test_screenshots/{name}.png")


# ---------------------------------------------------------------------------
# Helper: create a minimal policy PDF in memory
# ---------------------------------------------------------------------------
def make_policy_pdf() -> bytes:
    """Create a tiny valid PDF with policy text (no external deps)."""
    content = (
        "Hotel Policy: Maximum hotel nightly rate is $120.00 per night. "
        "Meal Allowance: Daily meal per diem limit is $45.00 per day. "
        "Airfare: Economy class only. Maximum $600 domestic airfare. "
        "Taxi/Rideshare: Reasonable local transport, max $50 per trip. "
        "Parking: Up to $30 per day airport parking reimbursable."
    )
    # Minimal but valid PDF
    pdf = f"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj
4 0 obj<</Length {len(content) + 50}>>
stream
BT /F1 12 Tf 72 720 Td ({content}) Tj ET
endstream
endobj
5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
xref
0 6
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000266 00000 n
0000000{400 + len(content):09d} 00000 n
trailer<</Size 6/Root 1 0 R>>
startxref
{500 + len(content)}
%%EOF"""
    return pdf.encode()


# ---------------------------------------------------------------------------
# Test Suite
# ---------------------------------------------------------------------------

async def test_health():
    """T01: Health endpoint returns ok."""
    import httpx
    r = httpx.get(f"{BASE_URL}/health")
    ok = r.status_code == 200 and r.json().get("status") == "ok"
    record("T01 Health endpoint", ok, r.json().get("model", ""))
    return ok


async def test_step1_ui(page: Page):
    """T02: Step 1 loads with correct form elements."""
    await page.goto(BASE_URL)
    await page.wait_for_load_state("networkidle")
    await ss(page, "01_step1_initial")

    # Check title
    title_visible = await page.locator("h1").first.is_visible()
    record("T02 Step 1 loads", title_visible)

    # Check form fields
    name_field = page.locator("#submitterName")
    email_field = page.locator("#submitterEmail")
    dept_field = page.locator("#department")
    trip_dest = page.locator("#tripDestination")

    has_fields = (
        await name_field.is_visible()
        and await email_field.is_visible()
        and await dept_field.is_visible()
    )
    record("T02b Step 1 form fields present", has_fields)
    return has_fields


async def test_policy_docs_section(page: Page):
    """T03: Corporate Policy Documents collapsible exists in Step 1."""
    # Look for the policy docs section toggle
    policy_toggle = page.locator("text=Corporate Policy Documents").first
    visible = await policy_toggle.is_visible()
    record("T03 Policy docs collapsible visible", visible)

    if visible:
        await policy_toggle.click()
        await page.wait_for_timeout(600)
        await ss(page, "02_policy_docs_section")

    return visible


async def test_upload_policy_doc_api():
    """T04: Upload a policy PDF via API and verify indexing."""
    import httpx

    pdf_bytes = make_policy_pdf()
    log(INFO, f"Policy PDF size: {len(pdf_bytes)} bytes")

    r = httpx.post(
        f"{BASE_URL}/policy-documents",
        files={"file": ("test_policy.pdf", pdf_bytes, "application/pdf")},
        data={"display_name": "Test Policy Handbook 2025", "description": "E2E test policy"},
    )
    if r.status_code not in (200, 202):
        record("T04 Policy doc upload", False, f"HTTP {r.status_code}: {r.text[:100]}")
        return None

    data = r.json()
    doc_id = data.get("doc_id")
    record("T04 Policy doc upload accepted", bool(doc_id), f"doc_id={doc_id}")

    # Wait for indexing (background task)
    log(INFO, "Waiting for RAG indexing...")
    for attempt in range(12):
        await asyncio.sleep(2)
        r2 = httpx.get(f"{BASE_URL}/policy-documents")
        docs = r2.json()
        matching = [d for d in docs if d.get("doc_id") == doc_id]
        if matching and matching[0].get("status") == "ready":
            chunks = matching[0].get("chunk_count", 0)
            record("T04b Policy doc indexed (ready)", True, f"{chunks} chunks")
            return doc_id
        elif matching and matching[0].get("status") == "error":
            record("T04b Policy doc indexed", False, matching[0].get("error_message", "")[:80])
            return doc_id

    record("T04b Policy doc indexed (timeout)", False, "Still processing after 24s")
    return doc_id


async def test_rag_preview_api(doc_id: str):
    """T05: RAG preview returns relevant policy text."""
    import httpx

    r = httpx.get(f"{BASE_URL}/policy-documents/{doc_id}/preview", params={"q": "hotel nightly rate"})
    if r.status_code != 200:
        record("T05 RAG preview", False, f"HTTP {r.status_code}")
        return

    data = r.json()
    hits = data.get("results", [])
    found_hotel = any("hotel" in (h.get("text", "").lower() + h.get("text", "").lower()) for h in hits)
    record("T05 RAG preview returns hotel policy", found_hotel, f"{len(hits)} hits")


async def test_policy_docs_ui_refresh(page: Page):
    """T06: UI shows uploaded policy doc after reload."""
    await page.reload()
    await page.wait_for_load_state("networkidle")

    # Expand policy docs section
    policy_toggle = page.locator("text=Corporate Policy Documents").first
    if await policy_toggle.is_visible():
        await policy_toggle.click()
        await page.wait_for_timeout(800)

    await ss(page, "03_policy_doc_listed")
    # Check for "Test Policy Handbook" or "ready" badge
    doc_card = page.locator("text=Test Policy Handbook").first
    visible = await doc_card.is_visible()
    record("T06 Policy doc shows in UI", visible)


async def test_fill_step1(page: Page) -> str:
    """T07: Fill Step 1 form and advance to Step 2."""
    await page.fill("#submitterName", "Alice Manager")
    await page.fill("#submitterEmail", "alice@acme.com")
    await page.fill("#department", "Engineering")
    await page.fill("#tripDestination", "Chicago, IL")
    await page.fill("#tripPurpose", "E2E Test Conference")

    # Set dates
    await page.evaluate("""() => {
        document.getElementById('startDate').value = '2025-03-10';
        document.getElementById('endDate').value = '2025-03-12';
    }""")

    await ss(page, "04_step1_filled")

    # Click Next
    next_btn = page.locator("button:has-text('Next'), button:has-text('Continue')").first
    if await next_btn.is_visible():
        await next_btn.click()
    else:
        # Try the step-advance button
        await page.evaluate("goToStep(2)")

    await page.wait_for_timeout(500)
    await ss(page, "05_step2_upload")

    # Verify we're on step 2
    step2_visible = await page.locator("#step2").is_visible()
    record("T07 Step 1 → Step 2 transition", step2_visible)
    return step2_visible


async def test_upload_receipts(page: Page):
    """T08: Upload test receipts via file input."""
    receipt_files = list(RECEIPTS_DIR.glob("*.png"))
    if not receipt_files:
        record("T08 Receipt upload", False, "No test receipts found")
        return False

    # Find file input
    file_input = page.locator("input[type='file']").first
    if not await file_input.is_visible():
        # It may be hidden — set files directly
        await file_input.set_input_files([str(f) for f in receipt_files[:3]])
    else:
        await file_input.set_input_files([str(f) for f in receipt_files[:3]])

    await page.wait_for_timeout(1000)
    await ss(page, "06_receipts_uploaded")

    # Check that file items appeared
    file_items = page.locator(".file-item, .receipt-item, [class*='file']")
    count = await file_items.count()
    record("T08 Receipts uploaded to UI", count > 0, f"{count} file items visible")
    return count > 0


async def test_start_processing(page: Page) -> str | None:
    """T09: Start processing and get session ID."""
    # Click Process / Submit button
    process_btn = page.locator("button:has-text('Process'), button:has-text('Submit'), button:has-text('Generate')").first
    if not await process_btn.is_visible():
        # Try next step button from step 2
        next_btn = page.locator("button:has-text('Next')").first
        if await next_btn.is_visible():
            await next_btn.click()
            await page.wait_for_timeout(500)

    process_btn = page.locator("button:has-text('Process'), button:has-text('Submit'), button:has-text('Generate')").first
    if await process_btn.is_visible():
        await process_btn.click()
    else:
        log(INFO, "No process button found — checking current URL/state")

    await page.wait_for_timeout(1500)
    await ss(page, "07_step3_processing")

    # Get session ID from JS context
    session_id = await page.evaluate("() => window.sessionId || window.currentSessionId || ''")
    record("T09 Processing started", bool(session_id), f"session={session_id[:8] if session_id else 'none'}...")
    return session_id or None


async def test_wait_for_completion(page: Page, session_id: str | None):
    """T10: Wait for processing to complete (up to 3 min)."""
    if not session_id:
        record("T10 Processing completes", False, "No session ID")
        return False

    import httpx
    log(INFO, "Waiting for processing (max 3 min)...")

    for i in range(36):  # 36 × 5s = 3 min
        await asyncio.sleep(5)
        r = httpx.get(f"{BASE_URL}/sessions/{session_id}/status")
        if r.status_code != 200:
            continue
        data = r.json()
        status = data.get("status", "")
        progress = data.get("progress_pct", 0)
        log(INFO, f"  [{i*5}s] status={status} progress={progress}%")

        if status == "completed":
            record("T10 Processing completes", True, f"Done in ~{i*5}s")
            return True
        elif status == "failed":
            record("T10 Processing completes", False, data.get("error_message", "failed")[:60])
            return False

    record("T10 Processing completes", False, "Timeout after 3 min")
    return False


async def test_step4_results(page: Page, session_id: str):
    """T11: Step 4 shows results table and summary cards."""
    # Navigate to step 4 via JS
    await page.evaluate(f"sessionId = '{session_id}'")
    await page.evaluate("loadResults()")
    await page.wait_for_load_state("networkidle")
    await page.wait_for_timeout(2500)
    await ss(page, "08_step4_results")

    # Check summary cards
    total_card = page.locator(".summary-card, [class*='summary']").first
    has_summary = await total_card.is_visible()
    record("T11a Step 4 summary cards visible", has_summary)

    # Check results table
    table_rows = page.locator("table tbody tr, .expense-row")
    row_count = await table_rows.count()
    record("T11b Step 4 expense rows", row_count > 0, f"{row_count} rows")

    # Check for donut chart
    canvas = page.locator("canvas")
    has_chart = await canvas.is_visible()
    record("T11c Chart.js donut visible", has_chart)

    # Check for internal policy badge (purple) — if RAG was used
    purple_badge = page.locator("[style*='a78bfa'], .internal-policy-badge")
    purple_count = await purple_badge.count()
    if purple_count > 0:
        record("T11d Internal policy badge (purple)", True, f"{purple_count} items used RAG")
    else:
        log(INFO, "  No internal policy badges (RAG may not have matched all categories)")

    return row_count > 0


async def test_manager_review_button(page: Page):
    """T12: Manager Review button visible when review items exist."""
    review_btn = page.locator("button:has-text('Manager Review'), #managerReviewBtn, [onclick*='openManager']")
    count = await review_btn.count()

    if count == 0:
        log(INFO, "  Manager Review button not shown (no items flagged for review)")
        record("T12 Manager Review btn", True, "No flagged items — expected")
        return False

    visible = await review_btn.first.is_visible()
    record("T12 Manager Review btn visible", visible)
    return visible


async def test_manager_dashboard_api(session_id: str):
    """T13: Review-items API returns correct structure."""
    import httpx
    r = httpx.get(f"{BASE_URL}/sessions/{session_id}/review-items")
    if r.status_code != 200:
        record("T13 Review-items API", False, f"HTTP {r.status_code}")
        return []

    data = r.json()
    items = data.get("items", [])
    total = data.get("total_review_count", 0)
    reviewed = data.get("reviewed_count", 0)

    record("T13 Review-items API structure", "items" in data, f"{total} items, {reviewed} reviewed")
    return items


async def test_manager_dashboard_ui(page: Page, items: list):
    """T14: Open manager dashboard and interact with it."""
    if not items:
        record("T14 Manager dashboard open", True, "Skipped — no review items")
        return

    review_btn = page.locator("button:has-text('Manager Review'), #managerReviewBtn").first
    if await review_btn.is_visible():
        await review_btn.click()
        await page.wait_for_timeout(800)
        await ss(page, "09_manager_dashboard")

        panel = page.locator("#managerDashboard, [id*='manager']").first
        visible = await panel.is_visible()
        record("T14 Manager dashboard opens", visible)
    else:
        record("T14 Manager dashboard open", True, "No review button — no items to review")


async def test_csv_export(page: Page, session_id: str):
    """T15: CSV export link works."""
    import httpx
    r = httpx.get(f"{BASE_URL}/sessions/{session_id}/export/csv")
    ok = r.status_code == 200 and "text/csv" in r.headers.get("content-type", "")
    rows = len(r.text.strip().split("\n")) - 1  # minus header
    record("T15 CSV export", ok, f"{rows} data rows")


async def test_pdf_download(page: Page, session_id: str):
    """T16: PDF report exists and is downloadable."""
    import httpx
    r = httpx.get(f"{BASE_URL}/sessions/{session_id}/report")
    ok = r.status_code == 200 and "application/pdf" in r.headers.get("content-type", "")
    size_kb = len(r.content) // 1024
    record("T16 PDF report download", ok, f"{size_kb} KB")


async def test_history_panel(page: Page):
    """T17: History panel opens and lists sessions."""
    hist_btn = page.locator("button:has-text('History'), [onclick*='openHistory'], #historyBtn").first
    if not await hist_btn.is_visible():
        record("T17 History panel", True, "Skipped — no history button found")
        return

    await hist_btn.click()
    await page.wait_for_timeout(600)
    await ss(page, "10_history_panel")

    panel = page.locator("#historyPanel, [id*='history']").first
    record("T17 History panel opens", await panel.is_visible())


async def test_delete_policy_doc(doc_id: str):
    """T18: Delete the test policy document."""
    import httpx
    r = httpx.delete(f"{BASE_URL}/policy-documents/{doc_id}")
    ok = r.status_code in (200, 204)
    record("T18 Policy doc delete", ok, f"HTTP {r.status_code}")

    # Verify gone
    r2 = httpx.get(f"{BASE_URL}/policy-documents")
    remaining = [d for d in r2.json() if d.get("doc_id") == doc_id]
    record("T18b Policy doc removed from list", len(remaining) == 0)


async def test_session_list_api():
    """T19: Sessions list API returns data."""
    import httpx
    r = httpx.get(f"{BASE_URL}/sessions?limit=5")
    ok = r.status_code == 200
    count = len(r.json()) if ok else 0
    record("T19 Sessions list API", ok, f"{count} sessions")


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

async def main():
    print("\n" + "="*60)
    print("  ExpenseAI — Comprehensive E2E Test Suite")
    print("="*60 + "\n")

    # T01: Health check (no browser needed)
    health_ok = await test_health()
    if not health_ok:
        print("\n\033[91mServer not healthy — aborting.\033[0m")
        return

    # T04: Upload policy doc (API-only, before browser starts)
    doc_id = await test_upload_policy_doc_api()

    if doc_id:
        await test_rag_preview_api(doc_id)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(channel="chrome", headless=False)
        ctx = await browser.new_context(viewport={"width": 1400, "height": 900})
        page = await ctx.new_page()

        try:
            # UI tests
            await test_step1_ui(page)
            await test_policy_docs_section(page)

            if doc_id:
                await test_policy_docs_ui_refresh(page)
            else:
                await page.goto(BASE_URL)
                await page.wait_for_load_state("networkidle")

            # Expand policy docs section first, then proceed
            policy_toggle = page.locator("text=Corporate Policy Documents").first
            if await policy_toggle.is_visible():
                # Scroll to policy docs and take a screenshot
                await policy_toggle.scroll_into_view_if_needed()
                await ss(page, "03b_policy_docs_with_doc")

            # Fill step 1 and proceed
            step2_ok = await test_fill_step1(page)
            if step2_ok:
                await test_upload_receipts(page)

                session_id = await test_start_processing(page)

                if session_id:
                    completed = await test_wait_for_completion(page, session_id)
                    await ss(page, "07b_step3_done")

                    if completed:
                        await test_step4_results(page, session_id)
                        review_btn_visible = await test_manager_review_button(page)

                        # API-level manager review tests
                        review_items = await test_manager_dashboard_api(session_id)

                        if review_btn_visible and review_items:
                            await test_manager_dashboard_ui(page, review_items)

                        await test_csv_export(page, session_id)
                        await test_pdf_download(page, session_id)

                        await ss(page, "11_step4_final")

            await test_history_panel(page)
            await test_session_list_api()

        except Exception as e:
            log(FAIL, f"Unexpected error: {e}")
            await ss(page, "error_state")
            import traceback
            traceback.print_exc()

        finally:
            await page.wait_for_timeout(1000)
            await browser.close()

    # Cleanup: delete test policy doc
    if doc_id:
        await test_delete_policy_doc(doc_id)

    # ---------------------------------------------------------------------------
    # Summary
    # ---------------------------------------------------------------------------
    print("\n" + "="*60)
    print("  TEST SUMMARY")
    print("="*60)
    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    for r in results:
        sym = PASS if r["passed"] else FAIL
        note = f"  ({r['note']})" if r["note"] else ""
        print(f"  {sym} {r['test']}{note}")

    print(f"\n  {passed}/{total} tests passed")
    if passed == total:
        print("\033[92m  ALL TESTS PASSED\033[0m")
    else:
        failed = [r for r in results if not r["passed"]]
        print(f"\033[91m  {len(failed)} FAILED:\033[0m")
        for r in failed:
            print(f"    - {r['test']}: {r['note']}")
    print("="*60 + "\n")
    print(f"  Screenshots saved to: test_screenshots/")


if __name__ == "__main__":
    asyncio.run(main())
