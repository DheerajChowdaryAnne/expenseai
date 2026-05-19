"""
tools/rag_search.py — ChromaDB RAG Search Tool for Claude
==========================================================
Provides two things:

  1. RAG_SEARCH_TOOL_DEFINITION — A Claude tool schema that tells Claude
     about the internal policy document search capability. Claude is
     instructed (via the system prompt in policy_verifier.py) to call
     this tool FIRST before falling back to web_search.

  2. execute_rag_search() — Performs a semantic similarity search over
     the ChromaDB collection of uploaded corporate policy PDFs and returns
     the most relevant text excerpts to Claude.

RAG (Retrieval-Augmented Generation) flow:
  1. Corporate policy PDFs are uploaded via POST /policy-documents
  2. Each PDF is chunked into ~400-word segments and embedded by ChromaDB
     using the all-MiniLM-L6-v2 sentence transformer model
  3. When verifying an expense, Claude calls rag_search with a natural
     language query (e.g. "hotel nightly rate limit")
  4. ChromaDB finds the most semantically similar chunks using cosine
     similarity and returns them
  5. If the results are relevant (score >= 0.5), Claude uses the internal
     policy as the authoritative source. Otherwise, it falls back to
     web_search (Tavily) to look up GSA/IRS rates.

This ensures company-specific policies always take precedence over
generic government standards.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Claude Tool Definition
# ---------------------------------------------------------------------------

RAG_SEARCH_TOOL_DEFINITION = {
    # Tool name — used by Claude to identify this tool in tool_use blocks
    "name": "rag_search",

    # Description tells Claude when to use this tool.
    # Key instruction: use this FIRST, before web_search.
    # The relevance_score threshold (0.5) is mentioned so Claude knows
    # when to trust the results vs. fall back to web search.
    "description": (
        "Search the company's internal employee handbook and expense policy documents. "
        "Use this FIRST before web_search to find any internal rules about expense limits, "
        "approved vendors, reimbursement procedures, or policy exceptions. "
        "If you find a relevant internal policy rule (relevance_score >= 0.5), use it as "
        "the authoritative source and set policy_source to 'Internal Policy: <doc_name>'. "
        "Only call web_search if rag_search returns found=false or no relevant excerpts."
    ),

    # JSON Schema for the tool's input parameters
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "A specific natural-language query about an expense policy rule. "
                    "Examples: 'maximum hotel nightly rate', 'meal allowance per diem', "
                    "'airfare class of service policy', 'rideshare reimbursement limit'."
                ),
            },
            "n_results": {
                "type": "integer",
                "description": "Number of policy excerpts to return (1–4). Default 3.",
                "default": 3,
            },
        },
        # Only 'query' is required; n_results defaults to 3
        "required": ["query"],
    },
}


# ---------------------------------------------------------------------------
# ChromaDB Query Executor
# ---------------------------------------------------------------------------

async def execute_rag_search(query: str, n_results: int = 3) -> dict:
    """
    Perform a semantic search over the enterprise policy document collection.

    This function is called when Claude decides to use the rag_search tool.
    It queries the ChromaDB vector store for chunks of uploaded policy PDFs
    that are semantically similar to the query, then returns them to Claude
    as a tool_result.

    The function intentionally returns found=False (not an error) when:
      - No policy documents have been uploaded yet
      - ChromaDB finds no chunks above the minimum similarity threshold

    This "not found" signal tells Claude to fall back to web_search for
    live GSA/IRS rates instead of making up an answer.

    Args:
        query:     Natural language question about an expense policy rule.
        n_results: Maximum number of policy excerpts to return (clamped to 1–4).

    Returns:
        A dict with:
          - "found":   bool — True if relevant policy excerpts were found
          - "message": str  — Human-readable status description
          - "results": list — Each item has {text, doc_name, relevance_score}
                              relevance_score is cosine similarity (0.0 to 1.0)
                              Higher score = more semantically similar to query
    """
    # Import here to avoid circular imports at module load time.
    # rag_service.py is the actual ChromaDB manager.
    from services.rag_service import get_rag_service

    svc = get_rag_service()

    # Guard: if no policy PDFs have been uploaded, tell Claude gracefully
    if not svc.has_documents():
        return {
            "found": False,
            "message": "No internal policy documents have been uploaded.",
            "results": [],
        }

    # Query ChromaDB for semantically similar chunks.
    # n_results is clamped to max 4 to match MAX_RAG_RESULTS in rag_service.py
    hits = svc.query(query, n_results=min(max(n_results, 1), 4))

    # If ChromaDB returned nothing (empty collection edge case), return not-found
    if not hits:
        return {
            "found": False,
            "message": "No relevant internal policy found for this query.",
            "results": [],
        }

    # Return the found excerpts in a format Claude can easily parse.
    # Claude reads 'relevance_score' to decide if the policy is authoritative
    # (the system prompt says score >= 0.5 means use it as the primary source).
    return {
        "found": True,
        "message": f"Found {len(hits)} relevant policy excerpt(s).",
        "results": [
            {
                "text":            h["text"],       # The policy text chunk
                "doc_name":        h["doc_name"],   # Name of the source document
                "relevance_score": h["score"],      # Cosine similarity (0.0–1.0)
            }
            for h in hits
        ],
    }
