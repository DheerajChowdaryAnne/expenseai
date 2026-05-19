# Speaker Script — Steve Jobs Style

---

## Slide 1: Title (ExpenseAI)
*[Walk to center. Pause. Look at audience.]*

"My name is Dheeraj, and along with Pravallika, we're the team behind ExpenseAI."

*(pause)*

"Receipts in. Report out."

"That's it."

*(~15 seconds)*

---

## Slide 2: Today's Story
"Here's our story today."

"First — why the current system is broken."

"Then — how we architected something better."

"Then — the intelligence we built inside it."

"And then — a live demo."

*(~10 seconds)*

---

## Slide 3: The Broken System (and Our Fix)
*[Point to left / problem side]*

"Here's the world we live in right now."

"Your accounting software runs on templates. What happens when a receipt is messy? Hand-written? Real-world?"

*(pause)*

"It fails."

"And your company's compliance rules? Hard-coded into software. They go stale the moment they're written. Humans are forced to review everything — even the obvious."

*[Click — reveal right side]*

"We fixed all three."

"Vision AI — zero templates required, any format."

"Live web search — always-current GSA and IRS rates."

"And a RAG policy engine — learns your company policies instantly."

*(pause)*

"Think about that."

*(~35 seconds)*

---

## Slide 4: Our Architecture (Three Agents. One Pipeline.)
*[Point to Claude Vision node]*

"Three agents. One pipeline."

"Agent one: Claude Vision. It reads the receipt — JPEG, PNG, HEIC, PDF, it doesn't matter. It outputs structured data and assigns a confidence score."

*(pause)*

*[Point to Policy Verification node]*

"Step two: The Policy Verification Loop. The AI iterates up to six times. It queries your company policy using RAG and ChromaDB. If the score is low, it falls back to Tavily for a live web search."

*[Point to Report Generator node]*

"Step three: The Report Generator. It takes the verified data, saves it to an SQLite session store, and pushes live WebSocket updates before compiling the HTML into a perfect PDF via WeasyPrint and Jinja2."

*(~40 seconds)*

---

## Slide 5: The Intelligence Layer (How Decisions Are Made)
*[Point to Confidence Gate]*

"Now — the intelligence layer. How decisions are made."

"First: the HITL Confidence Gate. Every receipt gets a score. Above 0.6?"

*(pause)*

"Auto-approved. Pushed to PDF. Done."

"Drop below 0.6? It stops. It flags for a human manager review — catching low clarity, ambiguous fields, and missing location data."

*(pause)*

*[Point to GSA Compliance]*

"Next: Always-Current Compliance. We pull live GSA M&IE rates at processing time and apply a strict 75% proration cap on the first and last travel days. No stale lookup tables."

*[Point to Semantic RAG and Loop]*

"And powering it all? Our Semantic RAG retrieval and Agentic Tool-Use loop. The AI navigates 384-dimensional embeddings, iterating up to six times to make absolutely sure a claim is valid."

*(~35 seconds)*

---

## Transition to Live Demo
*[Pause. Look at audience.]*

"Let me leave you with three things before we see it in action."

*(pause)*

"No templates. Ever."

"Always current rates."

"Humans — only when the AI isn't certain."

*(pause)*

"That's intelligent automation."

*(pause)*

"Let's look at the demo."

*(~20 seconds)*

---
---

# 🔴 DEMO NARRATION (1.5 Minutes)

*Fast, confident cadence. No hesitation.*

**[Beat 1 — Upload]**
"Here's the employee experience. Drag and drop the receipts — just like attaching files to an email."
*[Upload 3–4 receipts]*
"Hit Submit. Our agents take it from here."

**[Beat 2 — Watch it run]**
*[Point to terminal / progress log]*
"Developers — look at this. That's Claude Vision pinging the receipt. There's ChromaDB returning a policy match. There's the GSA rate being fetched live. All async. All concurrent."

**[Beat 3 — Manager flag]**
*[Point to red flagged item]*
"Notice this. The system caught a $0.00 mileage entry — incomplete data, confidence below threshold. Flagged automatically. I can approve, edit, or reject right here, without logging out."

**[Beat 4 — Regenerate]**
*[Fix the item, click Regenerate PDF]*
"Fix it. One click. The PDF rebuilds instantly — standardized, audit-ready, compliant."

*(pause)*

"That's ExpenseAI. Thank you."
