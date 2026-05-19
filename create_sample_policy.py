import weasyprint

html_content = """
<!DOCTYPE html>
<html>
<head>
<style>
    body { font-family: 'Helvetica', sans-serif; line-height: 1.6; color: #333; margin: 40px; }
    h1 { color: #2c3e50; border-bottom: 2px solid #eee; padding-bottom: 10px; }
    h2 { color: #34495e; margin-top: 30px; }
    .important { background-color: #fff3cd; border-left: 4px solid #ffeeba; padding: 10px; }
</style>
</head>
<body>
    <h1>Acme Corp - Global Travel & Expense Policy</h1>
    <p><em>Effective Date: January 1, 2024</em></p>

    <h2>1. General Principles</h2>
    <p>All employees are expected to exercise good judgment and prudence when incurring business expenses. Acme Corp will reimburse employees for reasonable, necessary, and properly authorized business expenses.</p>

    <h2>2. Airfare</h2>
    <p>Employees must book the lowest logical airfare available. <strong>First-class and business-class travel are strictly prohibited</strong> for all domestic flights. For international flights exceeding 8 hours, business class is permitted with prior VP approval.</p>
    <div class="important">
        <strong>Strict Cap:</strong> Domestic round-trip flights must not exceed $500.00 without written justification.
    </div>

    <h2>3. Lodging (Hotel)</h2>
    <p>Acme Corp uses standard negotiated rates. If a preferred hotel is not available, the maximum nightly rate for any US city is <strong>$150.00 per night</strong>, except in "High Cost Locations" (e.g., New York, San Francisco, Chicago) where the cap is <strong>$250.00 per night</strong>.</p>

    <h2>4. Meals</h2>
    <p>Employees are granted a daily meal allowance of <strong>$75.00 per day</strong>. Alcohol cannot be expensed unless entertaining a client, in which case it must be categorized under "Client Entertainment".</p>

    <h2>5. Taxi & Rideshare</h2>
    <p>Standard rideshare (e.g., UberX, Lyft Standard) is the preferred method of ground transportation. Premium rides (e.g., Uber Black) are <strong>not reimbursable</strong>. All rides between an airport and a hotel should not exceed $60.00.</p>
</body>
</html>
"""

weasyprint.HTML(string=html_content).write_pdf("Acme_Corp_Travel_Policy.pdf")
print("Successfully generated Acme_Corp_Travel_Policy.pdf")
