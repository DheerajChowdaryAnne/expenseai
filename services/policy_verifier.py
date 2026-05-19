"""
services/policy_verifier.py — Agentic Policy Compliance Verification
======================================================================
Verifies each extracted expense against applicable policy limits using a
multi-turn Claude tool-use loop (the "agentic" part of ExpenseAI).

The agentic loop (max 6 iterations):
  1. Claude is given the expense details and two tools: rag_search + web_search
  2. Claude calls rag_search FIRST to check uploaded corporate policy PDFs
  3. If internal policy is found (relevance score >= 0.5), Claude uses it
     as the authoritative source and returns a JSON verdict
  4. If no internal policy exists, Claude calls web_search (Tavily) to look
     up live GSA per diem rates (meals/hotel) or IRS mileage rates
  5. Claude returns a structured JSON verdict with approved_amount, notes, etc.
  6. The loop is capped at MAX_TOOL_ITERATIONS=6 to prevent infinite loops

Policy override shortcircuit:
  If the user set org-specific caps (PolicyOverrides in the session), those
  caps are applied immediately without any Claude API calls — saving cost
  and ensuring consistent enforcement.
"""
from __future__ import annotations
import json, re
from decimal import Decimal
from typing import Optional
import anthropic
from config import settings
from models import ExtractedReceiptData, PolicyCheckResult, PolicyOverrides
from tools.web_search import WEB_SEARCH_TOOL_DEFINITION, execute_web_search
from tools.rag_search import RAG_SEARCH_TOOL_DEFINITION, execute_rag_search

# Async Claude client
client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

# Safety cap: prevent infinite loops in the agentic tool-use cycle
MAX_TOOL_ITERATIONS = 6

# ---------------------------------------------------------------------------
# System Prompt
# ---------------------------------------------------------------------------

# This system prompt is the "brain" of the policy verifier agent.
# It tells Claude:
#   - Which tool to call first (rag_search before web_search)
#   - What the confidence threshold is (0.5) for internal policy
#   - Exactly what JSON structure to return as the final verdict
SYSTEM_PROMPT = """You are an expert expense policy compliance officer.
Your task is to verify whether a travel expense is within the applicable policy limits.

IMPORTANT — Tool usage priority:
1. ALWAYS call rag_search FIRST (if available) to check the company's internal policy documents.
2. If rag_search returns results with found=true and relevance_score >= 0.5, use those as
   the authoritative source. Set policy_source to "Internal Policy: <doc_name>".
3. If rag_search finds nothing relevant (found=false or no high-scoring results), then
   call web_search to look up current GSA per diem or IRS rates.
4. After searching (typically 1-2 tool calls), return ONLY a JSON verdict.

The JSON verdict must have this exact structure:
{
  "policy_limit": <number or null if there is no specific limit>,
  "policy_source": "<source, e.g., 'Internal Policy: Employee Handbook 2025' or 'GSA Per Diem FY2025 Chicago IL'>",
  "is_compliant": <true if claimed_amount <= policy_limit, else false>,
  "approved_amount": <the lesser of claimed_amount and policy_limit, or claimed_amount if no limit>,
  "notes": "<1-2 sentence human-readable note for the expense report>",
  "search_query_used": "<the queries you used>"
}

Return ONLY the JSON object after you have finished searching. No other text."""


# ---------------------------------------------------------------------------
# Category-Specific Search Guidance
# ---------------------------------------------------------------------------

# These templates are injected into the user message to give Claude
# specific guidance on what to search for each expense category.
# {city}, {state}, {amount}, {month}, {year}, {description} are filled in
# from the actual expense data at runtime.
CATEGORY_HINTS: dict[str, str] = {
    "meals": (
        "Search for the GSA per diem M&IE (meals & incidental expenses) rate for "
        "{city}, {state} in {month} {year}. "
        "The M&IE rate is the daily meal allowance. "
        "If the trip is not overnight, apply 75% of the full day rate."
    ),
    "hotel": (
        "Search for the GSA per diem lodging rate for {city}, {state} in {month} {year}. "
        "GSA lodging rates vary by county and season."
    ),
    "taxi": (
        "Search for the typical taxi or rideshare fare from {city} {state} for a local trip. "
        "The claimed amount is ${amount}. Determine if this is reasonable."
    ),
    "airfare": (
        "Search for any federal or standard policy requiring economy/coach class airfare. "
        "The claimed airfare amount is ${amount}."
    ),
    "parking": (
        "Search for typical daily parking fees at {city}, {state} or airport parking "
        "policy limits. The claimed amount is ${amount}."
    ),
    "other": (
        "Search for any relevant federal travel policy that might apply to "
        "this expense of ${amount} described as '{description}'."
    ),
}

# Restrict web search to authoritative domains per category.
# This prevents Tavily from returning blog posts instead of official rates.
DOMAIN_HINTS: dict[str, list[str]] = {
    "meals":   ["gsa.gov"],
    "hotel":   ["gsa.gov"],
    "taxi":    [],          # No restriction — local fare data varies
    "airfare": ["gsa.gov"],
    "parking": [],          # No restriction
    "other":   [],
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def verify_expense_policy(
    expense: ExtractedReceiptData,
    trip_year: int,
    trip_month: str,
    policy_overrides: Optional[PolicyOverrides] = None,
    use_rag: bool = True,
) -> PolicyCheckResult:
    """
    Verify one expense against policy limits using the agentic tool-use loop.

    If policy_overrides provides a cap for this category, the cap is applied
    immediately without any API calls (cheaper and deterministic).

    Otherwise, Claude is invoked with rag_search + web_search tools and runs
    up to MAX_TOOL_ITERATIONS turns to find the applicable policy limit.

    Args:
        expense:          Extracted receipt data from Claude Vision.
        trip_year:        Year of travel (for IRS mileage rate lookup).
        trip_month:       Month of travel (for GSA seasonal rate lookup).
        policy_overrides: Optional org-specific caps to skip web/RAG search.
        use_rag:          Set False to skip internal policy search (testing only).

    Returns:
        PolicyCheckResult with approved_amount, compliance verdict, and notes.

    Raises:
        RuntimeError: If Claude doesn't return a verdict within MAX_TOOL_ITERATIONS.
    """
    # ── Shortcircuit: apply org override without any API calls ──────────────
    override_cap = _get_override_cap(expense.category, policy_overrides)
    if override_cap is not None:
        approved = min(expense.amount, override_cap)
        return PolicyCheckResult(
            category=expense.category,
            claimed_amount=expense.amount,
            policy_limit=override_cap,
            policy_source="Organization custom policy limit",
            is_compliant=expense.amount <= override_cap,
            approved_amount=approved,
            notes=(
                f"Checked against your organization's custom policy cap of ${override_cap}. "
                + ("Within limit." if expense.amount <= override_cap
                   else f"Claimed ${expense.amount} exceeds cap; approved ${approved}.")
            ),
            search_query_used="",
        )

    # ── Build user message with category-specific search guidance ───────────
    user_message = _build_user_message(expense, trip_year, trip_month)
    # Conversation history: starts with the user's expense verification request
    messages: list[dict] = [{"role": "user", "content": user_message}]

    # ── Determine available tools ─────────────────────────────────────────
    from services.rag_service import get_rag_service
    tools = []
    # Only add rag_search if policy documents have been uploaded to ChromaDB
    if use_rag and get_rag_service().has_documents():
        tools.append(RAG_SEARCH_TOOL_DEFINITION)
    # web_search is always available as fallback
    tools.append(WEB_SEARCH_TOOL_DEFINITION)

    # Domain hints make Tavily return authoritative sources (gsa.gov, irs.gov)
    allowed_domains = DOMAIN_HINTS.get(expense.category, [])

    # ── Agentic tool-use loop ──────────────────────────────────────────────
    for _ in range(MAX_TOOL_ITERATIONS):
        response = await client.messages.create(
            model=settings.claude_model,
            max_tokens=2048,    # More tokens than extraction — policy notes can be verbose
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=messages,
        )

        if response.stop_reason == "tool_use":
            # Claude wants to call one or more tools.
            # Find ALL tool_use blocks — Claude may call multiple tools at once.
            # IMPORTANT: Every tool_use block MUST receive a corresponding
            # tool_result, or the Anthropic API returns a 400 error.
            tool_blocks = [b for b in response.content if b.type == "tool_use"]

            tool_results = []
            for tool_block in tool_blocks:
                if tool_block.name == "rag_search":
                    # Query ChromaDB for internal policy excerpts
                    result = await execute_rag_search(**tool_block.input)
                else:
                    # web_search — add domain hints for authoritative sources
                    search_kwargs = dict(tool_block.input)
                    if allowed_domains and "allowed_domains" not in search_kwargs:
                        search_kwargs["allowed_domains"] = allowed_domains
                    result = await execute_web_search(**search_kwargs)

                # Package the tool result for the next conversation turn
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_block.id,  # Must match the tool_use block's id
                    "content": json.dumps(result),
                })

            # Append both Claude's response and our tool results to the conversation
            # so Claude has full context in the next iteration
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

        elif response.stop_reason == "end_turn":
            # Claude has finished searching and is returning the JSON verdict
            text_block = next(
                (b for b in response.content if hasattr(b, "text")), None
            )
            if not text_block:
                raise RuntimeError("Policy verifier: Claude returned no text content.")

            # Parse Claude's JSON verdict → build PolicyCheckResult
            raw = _strip_code_fences(text_block.text)
            verdict = json.loads(raw)

            return PolicyCheckResult(
                category=expense.category,
                claimed_amount=expense.amount,
                # policy_limit may be null if no specific limit applies
                policy_limit=Decimal(str(verdict["policy_limit"])) if verdict.get("policy_limit") else None,
                policy_source=verdict.get("policy_source", ""),
                is_compliant=verdict.get("is_compliant", True),
                # approved_amount = min(claimed, limit) as computed by Claude
                approved_amount=Decimal(str(verdict.get("approved_amount", expense.amount))),
                notes=verdict.get("notes", ""),
                search_query_used=verdict.get("search_query_used", ""),
            )

    # If we hit MAX_TOOL_ITERATIONS without an end_turn, something went wrong
    raise RuntimeError(
        f"Policy verification for {expense.category} did not complete within "
        f"{MAX_TOOL_ITERATIONS} tool call iterations."
    )


# ---------------------------------------------------------------------------
# Private Helpers
# ---------------------------------------------------------------------------

def _build_user_message(
    expense: ExtractedReceiptData,
    trip_year: int,
    trip_month: str,
) -> str:
    """
    Build the user message that starts the Claude tool-use conversation.

    Includes all expense details and a category-specific search hint
    telling Claude exactly what to look up and where.
    """
    # Get the search guidance template for this expense category
    hint_template = CATEGORY_HINTS.get(expense.category, CATEGORY_HINTS["other"])

    # Fill in the template placeholders with actual expense data
    hint = hint_template.format(
        city=expense.location_city or "unknown city",
        state=expense.location_state or "unknown state",
        amount=expense.amount,
        month=trip_month,
        year=trip_year,
        description=expense.description or "",
    )

    return (
        f"Verify the following expense for policy compliance:\n\n"
        f"Category: {expense.category}\n"
        f"Vendor: {expense.vendor}\n"
        f"Date: {expense.date}\n"
        f"Claimed Amount: ${expense.amount} {expense.currency}\n"
        f"Location: {expense.location_city or 'N/A'}, {expense.location_state or 'N/A'}\n"
        f"Description: {expense.description or 'N/A'}\n\n"
        f"Search guidance: {hint}\n\n"
        "Use the web_search tool to verify the applicable policy limit, "
        "then return your JSON verdict."
    )


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences from Claude's response if present."""
    text = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if match:
        return match.group(1).strip()
    return text


def _get_override_cap(
    category: str,
    overrides: Optional[PolicyOverrides],
) -> Optional[Decimal]:
    """
    Return the org-specific cap for a category, or None if not overridden.

    Only meals and hotel have overridable caps — mileage overrides are
    handled separately in mileage_calculator.py.
    """
    if not overrides:
        return None
    if category == "meals" and overrides.meal_daily_cap is not None:
        return overrides.meal_daily_cap
    if category == "hotel" and overrides.hotel_nightly_cap is not None:
        return overrides.hotel_nightly_cap
    return None
