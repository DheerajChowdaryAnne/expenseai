# 🔴 Live Demo Cue Sheet

**Prerequisites Before Pressing "Share Screen":**
1. Have your screen split perfectly in half:
   - **Right Side:** Terminal window running `sh run.sh` (make the text big!).
   - **Left Side:** Google Chrome at `http://127.0.0.1:8000`.
2. Have a folder open with your `airfare_receipt.png`, `hotel_receipt.png`, and `taxi_receipt.png` ready to be dragged and dropped.

---

### ACT 1: The Setup & Web Search (~ 25 Seconds)
**[ACTION]** Point to the Chrome window on the left. Type in a name (e.g., "Sarah") and a Destination ("Chicago"). Leave the mileage box empty or at 0 miles (this intentionally creates the $0.00 error for later!). Drag your 3 receipts into the upload box.

**[SPEAK]** *"Welcome to our live dashboard. On the left is our Employee view, and on the right is our Developer terminal so you can see the AI agents working. Let's process a typical business trip to Chicago. As soon as I enter these dates and this destination, our Tavily Web Search agent prepares to scrape the live internet for benchmark rates—like the current IRS mileage limits for this specific region—so it doesn't rely on stale, hard-coded rules. I’ll also leave an unverified mileage claim blank to test our safety nets, and now I will upload these three messy receipts."*

---

### ACT 2: The Agentic Pipeline (~ 25 Seconds)
**[ACTION]** Click the **"Process Documents"** button. Immediately move your mouse to the Terminal window on the right side of the screen as the logs start scrolling rapidly.

**[SPEAK]** *"I’ve hit process, and our multi-agent pipeline takes over. Watch the terminal here on the right: Right now, our FastAPI server is firing off async requests to the Claude Vision model, mathematically mapping the unstructured images into JSON. In parallel, our vector search is actively querying ChromaDB, pulling out exactly what the company rule limits are for Chicago hotels and domestic flights so it can run the math against Claude's extraction."*

---

### ACT 3: The Results & The Catch (~ 20 Seconds)
**[ACTION]** The dashboard loading completes. Move your mouse over the big green Total Approved box showing $521.72. Then explicitly circle your mouse around the red flagged Mileage item.

**[SPEAK]** *"In under a minute, the pipeline finished. It successfully parsed, verified against policy, and auto-approved $521 across complex Airfare, Hotel, and Taxi receipts without human intervention. However, remember that unverified mileage claim I entered? Because it lacked data, its Agentic Confidence Score dropped. Instead of breaking the app or approving bad math, the system safely trapped it in this red 'Review' state."*

---

### ACT 4: The Manager Override (~ 20 Seconds)
**[ACTION]** Click the red 'Manager Review' banner to open the side panel. 

**[SPEAK]** *"In a production environment, this side-panel uses Role-Based Access Control so only Accounting Managers can access it. For this demo, we combined it into a single view so you can watch me quickly resolve the red flag without logging out. The Manager can see what the AI flagged, recognize that the employee forgot to enter their mileage drive to the airport, and manually input the correction—say, $15.50."*

**[ACTION]** Type `$15.50` into the Manager panel and hit **Approve**.

---

### ACT 5: The Finale (~ 20 Seconds)
**[ACTION]** The dashboard turns fully green. Click **Regenerate PDF**. The file downloads. Open the PDF and drag it exactly to the center of your screen for the judges to see.

**[SPEAK]** *"Now that the exception is cleared, we trigger the final automated phase. Our Python engine instantly compiles the AI's JSON data, the Tavily market rates, the manager's override, and the original receipt images into a perfectly formatted, standardized PDF report ready to be paid out. True, end-to-end automation. Thank you!"*
