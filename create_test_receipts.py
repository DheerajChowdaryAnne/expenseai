"""
Generates sample receipt images for testing the expense report system.
Run: python create_test_receipts.py
Creates 4 receipts in ./test_receipts/
"""

from PIL import Image, ImageDraw, ImageFont
import os

OUTPUT_DIR = "./test_receipts"
os.makedirs(OUTPUT_DIR, exist_ok=True)


def make_receipt(filename, lines, width=400, bg="#ffffff"):
    """Draw a simple text-based receipt image."""
    line_height = 22
    padding = 24
    height = padding * 2 + len(lines) * line_height + 10
    img = Image.new("RGB", (width, height), color=bg)
    draw = ImageDraw.Draw(img)

    try:
        # Try system fonts
        font_bold = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 15)
        font_reg  = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 13)
    except Exception:
        font_bold = ImageFont.load_default()
        font_reg  = font_bold

    y = padding
    for text, bold, center in lines:
        font = font_bold if bold else font_reg
        color = "#000000"
        if center:
            bbox = draw.textbbox((0, 0), text, font=font)
            x = (width - (bbox[2] - bbox[0])) // 2
        else:
            x = padding
        if text.startswith("---"):
            draw.line([(padding, y + 8), (width - padding, y + 8)], fill="#aaaaaa", width=1)
        else:
            draw.text((x, y), text, fill=color, font=font)
        y += line_height

    path = os.path.join(OUTPUT_DIR, filename)
    img.save(path)
    print(f"  Created: {path}")
    return path


# ── Receipt 1: Hotel ──────────────────────────────────────────────────────────
make_receipt("hotel_receipt.png", [
    ("MARRIOTT CHICAGO DOWNTOWN",        True,  True),
    ("333 N Michigan Ave, Chicago, IL",   False, True),
    ("Tel: (312) 540-0100",               False, True),
    ("---",                               False, False),
    ("Guest:  John Smith",                False, False),
    ("Check-in:   Oct 14, 2024",          False, False),
    ("Check-out:  Oct 16, 2024",          False, False),
    ("Room:       King Standard",         False, False),
    ("---",                               False, False),
    ("Room Rate (1 night)   $189.00",     False, False),
    ("City Tax (4.5%)         $8.51",     False, False),
    ("Hotel Tax (5%)          $9.45",     False, False),
    ("---",                               False, False),
    ("TOTAL CHARGED:        $206.96",     True,  False),
    ("Payment: Visa ****4321",            False, False),
    ("---",                               False, False),
    ("Thank you for staying with us!",    False, True),
])

# ── Receipt 2: Restaurant / Meals ─────────────────────────────────────────────
make_receipt("meal_receipt.png", [
    ("THE PURPLE PIG",                    True,  True),
    ("500 N Michigan Ave, Chicago, IL",   False, True),
    ("---",                               False, False),
    ("Date: October 15, 2024",            False, False),
    ("Table: 12   Server: Maria",         False, False),
    ("---",                               False, False),
    ("Charcuterie Board        $22.00",   False, False),
    ("Grilled Salmon           $28.00",   False, False),
    ("House Salad              $14.00",   False, False),
    ("Sparkling Water           $5.00",   False, False),
    ("---",                               False, False),
    ("Subtotal:                $69.00",   False, False),
    ("Tax (10.25%):             $7.07",   False, False),
    ("Tip (20%):               $13.80",   False, False),
    ("---",                               False, False),
    ("TOTAL:                  $89.87",    True,  False),
    ("Visa ****4321",                     False, False),
])

# ── Receipt 3: Taxi / Uber ────────────────────────────────────────────────────
make_receipt("taxi_receipt.png", [
    ("UBER TRIP RECEIPT",                 True,  True),
    ("October 14, 2024",                  False, True),
    ("---",                               False, False),
    ("From: O'Hare Intl Airport (ORD)",   False, False),
    ("To:   Marriott Chicago Downtown",   False, False),
    ("Distance: 18.2 miles",              False, False),
    ("Duration: 42 min",                  False, False),
    ("---",                               False, False),
    ("Base fare:               $5.00",    False, False),
    ("Distance (18.2 mi):     $27.30",    False, False),
    ("Time (42 min):           $8.40",    False, False),
    ("Airport surcharge:       $4.00",    False, False),
    ("Chicago tax:             $3.26",    False, False),
    ("---",                               False, False),
    ("TOTAL:                  $47.96",    True,  False),
    ("Charged to Visa ****4321",          False, False),
])

# ── Receipt 4: Airfare ────────────────────────────────────────────────────────
make_receipt("airfare_receipt.png", [
    ("UNITED AIRLINES",                   True,  True),
    ("E-TICKET RECEIPT",                  True,  True),
    ("---",                               False, False),
    ("Passenger: SMITH/JOHN",             False, False),
    ("Ticket #: 0162345678901",           False, False),
    ("---",                               False, False),
    ("Springfield (SPI)",                 False, False),
    ("  → Chicago O'Hare (ORD)",          False, False),
    ("Flight UA4521   Oct 14, 2024",      False, False),
    ("Depart 07:15  Arrive 08:10",        False, False),
    ("Class: Economy (Y)",                False, False),
    ("---",                               False, False),
    ("Base Fare:             $189.00",    False, False),
    ("Taxes & Fees:           $42.80",    False, False),
    ("Baggage (1 bag):        $35.00",    False, False),
    ("---",                               False, False),
    ("TOTAL CHARGED:        $266.80",     True,  False),
    ("Visa ****4321",                     False, False),
])

print("\nAll test receipts created in ./test_receipts/")
print("Now open http://localhost:8000 and upload them!")
