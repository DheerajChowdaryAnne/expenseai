"""
services/mileage_calculator.py — IRS Mileage Rate Lookup & Reimbursement
=========================================================================
Calculates the approved mileage reimbursement amount for a MileageEntry.

Rate priority (highest to lowest):
  1. entry.rate_per_mile     — User explicitly provided a rate per mile
  2. rate_override           — Org-specific override from PolicyOverrides
  3. IRS live lookup         — Claude tool-use loop searches irs.gov for
                               the current year's standard mileage rate

IRS rate lookup uses a short Claude tool-use loop (max 4 iterations):
  - Claude calls web_search with allowed_domains=["irs.gov"]
  - Tavily returns the current IRS mileage rate from an official source
  - Claude extracts the rate and returns a JSON dict with {rate, source, url}
  - The rate is applied to total_miles (doubled for round trips)

Fallback:
  If the IRS lookup fails for any reason (network error, API error, etc.),
  FALLBACK_IRS_RATE (0.67 $/mile, the 2024 rate) is used instead. This
  ensures the pipeline never fails completely due to a web search issue.
"""
from __future__ import annotations
import json, re
from decimal import Decimal
from typing import Optional
import anthropic
from config import settings
from models import MileageEntry, PolicyCheckResult
from tools.web_search import WEB_SEARCH_TOOL_DEFINITION, execute_web_search

# Async Claude client
client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

# Fallback rate used if the IRS lookup fails (2024 IRS standard mileage rate)
FALLBACK_IRS_RATE = 0.67
FALLBACK_SOURCE = "IRS Standard Mileage Rate (fallback - verify at irs.gov)"

# System prompt for the IRS rate lookup loop.
# Instructs Claude to search and return a minimal JSON dict — no prose.
RATE_LOOKUP_SYSTEM = """You are a tax policy researcher.
Find the IRS standard mileage rate for business travel for the given year.
Use the web_search tool, then return ONLY a JSON object:
{
  "rate": <dollars per mile as a float, e.g. 0.67>,
  "source": "<brief description, e.g., 'IRS Rev. Proc. 2024-1, effective Jan 1 2024'>",
  "url": "<source URL if available>"
}
No other text."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def calculate_mileage_reimbursement(
    entry: MileageEntry,
    trip_year: int,
    rate_override: Optional[float] = None,
) -> PolicyCheckResult:
    """
    Compute the approved mileage reimbursement for a MileageEntry.

    Applies the rate from the highest-priority source available, then
    computes total_miles * rate and returns a PolicyCheckResult that
    integrates naturally with the rest of the expense pipeline.

    Args:
        entry:         MileageEntry with origin, destination, miles, and
                       is_round_trip. May include an explicit rate_per_mile.
        trip_year:     Year of travel — used to look up the correct IRS rate.
        rate_override: Optional org-specific rate (from PolicyOverrides).
                       Takes precedence over the IRS lookup but not over
                       an explicitly provided entry.rate_per_mile.

    Returns:
        PolicyCheckResult with category="mileage", is_compliant=True,
        and approved_amount = total_miles * rate.
    """
    # Calculate total miles: double if round trip
    total_miles = entry.miles * (2 if entry.is_round_trip else 1)

    # Determine the reimbursement rate (priority order)
    if entry.rate_per_mile:
        # User explicitly specified a rate — always highest priority
        rate = entry.rate_per_mile
        source = f"User-specified rate (${rate}/mile)"
        url = ""
    elif rate_override is not None:
        # Org policy override — skip IRS lookup
        rate = rate_override
        source = f"Organization custom mileage rate (${rate}/mile)"
        url = ""
    else:
        # Look up the current IRS rate via Claude + Tavily
        rate, source, url = await _lookup_irs_rate(trip_year)

    # Calculate the approved reimbursement amount
    approved = round(total_miles * rate, 2)

    # Build a human-readable description for the PDF policy notes
    trip_desc = (
        f"Round trip: {entry.origin} → {entry.destination}"
        if entry.is_round_trip
        else f"{entry.origin} → {entry.destination}"
    )
    notes = (
        f"{total_miles:.1f} miles × ${rate}/mile = ${approved:.2f}. "
        f"{trip_desc}."
    )
    if url:
        notes += f" Rate source: {url}"

    # Mileage reimbursements are always compliant (no upper cap)
    claimed = Decimal(str(approved))
    return PolicyCheckResult(
        category="mileage",
        claimed_amount=claimed,
        policy_limit=None,          # No cap on mileage reimbursements
        policy_source=source,
        is_compliant=True,          # Mileage claims are always approved
        approved_amount=claimed,
        notes=notes,
        search_query_used=f"IRS standard mileage rate {trip_year}",
    )


# ---------------------------------------------------------------------------
# Internal IRS Rate Lookup
# ---------------------------------------------------------------------------

async def _lookup_irs_rate(year: int) -> tuple[float, str, str]:
    """
    Use a short Claude tool-use loop to find the IRS mileage rate for `year`.

    Makes up to 4 iterations:
      1. Claude calls web_search for the IRS mileage rate
      2. Tavily returns results from irs.gov
      3. Claude extracts the rate and returns JSON
      4. We parse the JSON and return (rate, source, url)

    Falls back to FALLBACK_IRS_RATE if anything goes wrong (network error,
    unexpected Claude response, JSON parse error, etc.). This ensures the
    expense pipeline never fails just because of a web search hiccup.

    Args:
        year: The tax year to look up (e.g. 2025).

    Returns:
        Tuple of (rate_per_mile: float, source_description: str, source_url: str)
    """
    messages: list[dict] = [
        {
            "role": "user",
            "content": (
                f"What is the IRS standard mileage rate for business travel in {year}? "
                "Use web_search to find the authoritative answer, then return the JSON verdict."
            ),
        }
    ]

    try:
        for _ in range(4):  # Max 4 iterations for this simpler lookup
            response = await client.messages.create(
                model=settings.claude_model,
                max_tokens=512,           # Small response — just a JSON dict
                system=RATE_LOOKUP_SYSTEM,
                tools=[WEB_SEARCH_TOOL_DEFINITION],
                messages=messages,
            )

            if response.stop_reason == "tool_use":
                # Claude wants to search the web — execute all tool calls
                tool_blocks = [b for b in response.content if b.type == "tool_use"]
                tool_results = []
                for tool_block in tool_blocks:
                    # Restrict search to irs.gov for authoritative results
                    search_result = await execute_web_search(
                        **{**tool_block.input, "allowed_domains": ["irs.gov"]}
                    )
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_block.id,
                        "content": json.dumps(search_result),
                    })
                # Feed results back into the conversation for the next iteration
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})

            elif response.stop_reason == "end_turn":
                # Claude returned the JSON verdict — parse and return it
                text = next(
                    (b.text for b in response.content if hasattr(b, "text")), ""
                )
                text = _strip_fences(text)
                data = json.loads(text)
                return float(data["rate"]), data.get("source", "IRS.gov"), data.get("url", "")

    except Exception:
        pass  # Any error → fall through to the fallback rate below

    # Fallback: use the 2024 IRS rate if the lookup failed for any reason
    return FALLBACK_IRS_RATE, FALLBACK_SOURCE, ""


def _strip_fences(text: str) -> str:
    """Remove markdown code fences from Claude's response if present."""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    return m.group(1).strip() if m else text
