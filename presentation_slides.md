---
title: "ExpenseAI — Agentic AI for Expense Automation"
---

# Slide 1 – Title Slide
## ExpenseAI
**Receipts In. Report Out.**

- Team: Dheeraj Chowdary Anne, [Partner Name]
- Course: [Course Number]
- Instructor: [Instructor Name]

> **Visual:** Dark background. "ExpenseAI" in large bold type, centered.
> Animated: a crumpled receipt icon → arrow → clean PDF icon.

---

# Slide 2 – Roadmap
## Today's Story

| Act | Topic |
|-----|-------|
| 01 | The Broken System |
| 02 | Our Architecture |
| 03 | The Intelligence |
| 04 | Live Demo |

> **Visual:** Four horizontal nodes connected by animated arrows.
> Each node lights up sequentially as you speak.

---

# Slide 3 – Problem & Contribution
## Expense Reports Are Broken.

**The Problem** *(red section — left half)*
- Templates fail messy receipts
- Rules coded. Always stale.
- Humans review everything.

**→ We Fixed All Three.** *(green section — right half, revealed on click)*
- Vision AI. Zero templates.
- Live web search. Always current.
- RAG learns your policies.

**Novelty callouts** *(colored badges)*
- 🔴 Zero-template extraction
- 🔵 Real-time rate lookup
- 🟢 Instant policy ingestion

> **Visual:** Split-screen layout. Left side: crumpled receipt + red ✗ boxes.
> Right side: clean dashboard + green ✓ boxes. Animate right side in on click.

---

# Slide 4 – Technical Content: Architecture
## Three Agents. One Pipeline.

```
Receipt Upload
    │
    ▼
[🔴 Claude Vision]  ──→  Extract: amount, date, vendor, category
    │                     Confidence Score: 0.0 – 1.0
    ▼
[🔵 ChromaDB RAG]   ──→  Query: internal company policy
    │                     "Internal Policy: Employee Handbook"
    ▼
[🟢 Tavily Search]  ──→  Fetch: live GSA/IRS rates (fallback)
    │                     Domain: gsa.gov, irs.gov
    ▼
Concurrent asyncio.gather (4 receipts at once)
    │
    ▼
PDF + CSV Report
```

| Agent | Role | Technology |
|-------|------|------------|
| 🔴 Vision | Reads any receipt | Claude Vision |
| 🔵 Policy | Knows your rules | ChromaDB + sentence-transformers |
| 🟢 Search | Finds live rates | Tavily API |

> **Visual:** Horizontal flowchart. Red transparent box around Claude Vision node.
> Blue transparent box around ChromaDB node. Green box around Tavily node.
> Use pointer to trace the data path left → right.

---

# Slide 5 – Technical Content: Algorithms
## The 60% Rule.

**Confidence Gate** *(core safety algorithm)*

```
confidence_score = Claude's certainty (0.0 → 1.0)

IF confidence_score ≥ 0.6:
    → Auto-approve  ✓  (green path)
ELSE:
    → Flag for manager ⚠  (red path)
```

**GSA Meal Cap Formula**

```
approved = min(claimed_amount, GSA_rate × day_multiplier)

day_multiplier:
    0.75  →  first day of travel
    1.00  →  full travel days
    0.75  →  last day of travel
```

**RAG Priority Chain**

```
Internal Policy (ChromaDB, score ≥ 0.5)
    → if found: policy_source = "Internal Policy: [doc name]"
    → if not:   fall back to web_search (gsa.gov / irs.gov)
```

> **Visual:** Decision tree diagram. Red box on the < 0.6 branch.
> Green box on the ≥ 0.6 branch. Formula displayed as a styled equation block.
> Point to the decision node — "This is Node 7 in our architecture."

---

# Slide 6 – Key Takeaways
## It Just Works.

**Three things to remember:**

1. No templates. Ever.
2. Always current rates.
3. Humans only when needed.

> **Visual (top half):** Dashboard screenshot.
> 🟢 Green annotation box: "$521.72 Auto-Approved — airfare + hotel"
> 🔴 Red annotation box: "Flagged for Review — $0.00 Mileage (incomplete)"

**Re-emphasizing novelty:**
- Vision beats OCR
- Live search beats hard-coded rules
- RAG makes policy instant

> Final line on slide (large, centered): **"Thank you."**
