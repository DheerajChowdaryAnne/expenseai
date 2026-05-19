"""
services/receipt_extractor.py — Claude Vision Receipt Data Extraction
======================================================================
Sends receipt images or PDFs to Claude's vision model and returns a
structured ExtractedReceiptData Pydantic model.

Supported file types:
  - JPEG, PNG, HEIC, WebP  → sent as base64 image blocks
  - PDF                    → pages converted to PNG via pdf2image (needs poppler)

Multi-page PDFs:
  All pages (up to MAX_PDF_PAGES=10) are sent to Claude simultaneously.
  Claude returns the grand total from the final summary page.

Confidence scoring:
  Claude returns a confidence_score (0.0–1.0). Receipts below 0.6 are
  flagged for manager review in main.py.
"""
from __future__ import annotations
import base64, io, json, re
from typing import Optional
import anthropic
from config import settings
from models import ExtractedReceiptData

# Async client — required so Claude calls don't block FastAPI's event loop
client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

# Safety cap: never send more than 10 PDF pages to Claude at once
MAX_PDF_PAGES = 10

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

# System prompt: instructs Claude on its role and output format.
# "Return valid JSON only" is critical — it prevents Claude from
# wrapping the output in explanation text.
SYSTEM_PROMPT = """You are an expert receipt OCR and data extraction specialist.
Your job is to extract structured expense information from receipt images with high accuracy.
Always return valid JSON only — no markdown, no explanation text, nothing else.
If a field is unclear or absent, use null.
For amounts, extract the final total paid (after tax and tip), not subtotals.
If you receive multiple pages of the same receipt, use the grand total from the final summary page.
For the category field, choose from exactly: airfare, hotel, taxi, meals, parking, other.
Assign a confidence_score from 0.0 to 1.0 based on image clarity and data completeness."""

# User prompt: the exact JSON schema Claude must return.
# Keeping the schema explicit and small reduces token usage and errors.
USER_PROMPT = """Extract all expense data from this receipt image (or multi-page receipt).

Return ONLY a JSON object with this exact structure:
{
  "amount": <number>,
  "currency": "<3-letter ISO code, default USD>",
  "date": "<YYYY-MM-DD>",
  "vendor": "<business name>",
  "category": "<airfare|hotel|taxi|meals|parking|other>",
  "description": "<brief description or null>",
  "location_city": "<city or null>",
  "location_state": "<2-letter state code or null>",
  "confidence_score": <0.0 to 1.0>
}"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def extract_receipt_data(
    file_path: str,
    mime_type: str,
    category_hint: Optional[str] = None,
) -> ExtractedReceiptData:
    """
    Send a receipt file to Claude Vision and return structured expense data.

    Called by the background processing pipeline for every uploaded receipt.

    Args:
        file_path:     Absolute path to the uploaded file on disk.
        mime_type:     MIME type (e.g. "image/jpeg", "application/pdf").
                       Used to route PDF vs. image handling.
        category_hint: Optional user-provided category (e.g. "meals").
                       Prepended to the prompt to help Claude when the
                       receipt is ambiguous or low quality.

    Returns:
        ExtractedReceiptData — validated Pydantic model.

    Raises:
        json.JSONDecodeError: If Claude's response isn't valid JSON.
        pydantic.ValidationError: If JSON fields don't match the schema.
        RuntimeError: If pdf2image/poppler is missing for PDF files.
    """
    # Convert the file to Anthropic-format image content blocks.
    # PDFs return one block per page; images return a single block.
    image_blocks = _prepare_image_blocks(file_path, mime_type)

    # If the user gave a category hint, prepend it to guide Claude
    user_text = USER_PROMPT
    if category_hint:
        user_text = (
            f"The user believes this is a '{category_hint}' expense. "
            f"Use this as guidance but verify from the receipt.\n\n"
            + USER_PROMPT
        )

    # Call Claude Vision: image blocks first, then the text prompt.
    # max_tokens=1024 is sufficient for the small JSON response.
    response = await client.messages.create(
        model=settings.claude_model,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": image_blocks + [{"type": "text", "text": user_text}],
            }
        ],
    )

    # Parse Claude's text response → strip code fences → parse JSON → validate
    raw = response.content[0].text.strip()
    raw = _strip_code_fences(raw)
    data = json.loads(raw)
    return ExtractedReceiptData(**data)


# ---------------------------------------------------------------------------
# Private Helpers
# ---------------------------------------------------------------------------

def _prepare_image_blocks(file_path: str, mime_type: str) -> list:
    """
    Convert a receipt file into a list of Anthropic image content blocks.

    The Anthropic API expects image content in this format:
        {"type": "image", "source": {"type": "base64", "media_type": ..., "data": ...}}

    For PDFs, each page becomes a separate block so Claude can read all pages.
    For image files, there is only one block.
    """
    if mime_type == "application/pdf":
        return _pdf_to_image_blocks(file_path)

    # Read image file and base64-encode it for the Anthropic API
    with open(file_path, "rb") as f:
        return [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": mime_type,
                    "data": base64.standard_b64encode(f.read()).decode(),
                },
            }
        ]


def _pdf_to_image_blocks(file_path: str) -> list:
    """
    Convert PDF pages to Claude image blocks using pdf2image (poppler).

    Rasterizes at 200 DPI for sharp text that Claude can read accurately.
    Pages beyond MAX_PDF_PAGES are dropped to keep token usage reasonable.

    Raises:
        RuntimeError: If pdf2image or poppler is not installed.
    """
    try:
        from pdf2image import convert_from_path
    except ImportError as e:
        raise RuntimeError(
            "pdf2image is required for PDF receipts. "
            "Install: pip install pdf2image && brew install poppler"
        ) from e

    # Rasterize PDF pages at 200 DPI → list of PIL Image objects
    pages = convert_from_path(file_path, dpi=200)
    pages = pages[:MAX_PDF_PAGES]  # Enforce page limit

    blocks = []
    for page in pages:
        # Save each PIL Image to an in-memory buffer as PNG
        buf = io.BytesIO()
        page.save(buf, format="PNG")
        blocks.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": base64.standard_b64encode(buf.getvalue()).decode(),
                },
            }
        )
    return blocks


def _strip_code_fences(text: str) -> str:
    """
    Remove markdown code fences if Claude accidentally wraps JSON in them.

    Handles both ```json ... ``` and plain ``` ... ``` fences.
    Returns the original text unchanged if no fences are found.
    """
    text = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if match:
        return match.group(1).strip()
    return text
