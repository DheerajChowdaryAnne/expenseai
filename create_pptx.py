#!/usr/bin/env python3
"""
ExpenseAI_Presentation.pptx
Steve Jobs / CEO product-style — dark theme
6 slides matching course requirements
"""

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.enum.shapes import MSO_AUTO_SHAPE_TYPE

# ── Palette ─────────────────────────────────────────────────────
BG      = RGBColor(0x0D, 0x0D, 0x1A)
CARD    = RGBColor(0x1A, 0x1A, 0x2E)
WHITE   = RGBColor(0xFF, 0xFF, 0xFF)
BLUE    = RGBColor(0x3B, 0x82, 0xF6)
RED     = RGBColor(0xEF, 0x44, 0x44)
GREEN   = RGBColor(0x22, 0xC5, 0x5E)
AMBER   = RGBColor(0xF5, 0x9E, 0x0B)
MUTED   = RGBColor(0x64, 0x74, 0x8B)
LGRAY   = RGBColor(0x94, 0xA3, 0xB8)
RED_DK  = RGBColor(0x2D, 0x0D, 0x0D)
GRN_DK  = RGBColor(0x0D, 0x2D, 0x1A)
BLU_DK  = RGBColor(0x0D, 0x1A, 0x2D)
AMB_DK  = RGBColor(0x2D, 0x1E, 0x05)

W = Inches(13.33)
H = Inches(7.5)

prs = Presentation()
prs.slide_width  = W
prs.slide_height = H
blank = prs.slide_layouts[6]   # blank layout


# ── Helpers ─────────────────────────────────────────────────────

def new_slide():
    s = prs.slides.add_slide(blank)
    fill = s.background.fill
    fill.solid()
    fill.fore_color.rgb = BG
    return s


def T(slide, text, l, t, w, h,
      sz=18, bold=False, italic=False,
      c=None, align=PP_ALIGN.LEFT, font="Calibri"):
    """Add a multi-line textbox (use \\n for line breaks)."""
    if c is None:
        c = WHITE
    tb = slide.shapes.add_textbox(Inches(l), Inches(t), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    for i, line in enumerate(text.split('\n')):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        run = p.add_run()
        run.text = line
        run.font.size = Pt(sz)
        run.font.bold = bold
        run.font.italic = italic
        run.font.color.rgb = c
        run.font.name = font


def R(slide, l, t, w, h, fill=CARD, border=None, bw=1.5):
    """Add a colored rectangle (coords in inches)."""
    shape = slide.shapes.add_shape(
        MSO_AUTO_SHAPE_TYPE.RECTANGLE,
        Inches(l), Inches(t), Inches(w), Inches(h)
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    if border:
        shape.line.color.rgb = border
        shape.line.width = Pt(bw)
    else:
        shape.line.fill.background()
    return shape


def hbar(slide, color=BLUE):
    """Thin accent bar across the top."""
    R(slide, 0, 0, 13.33, 0.07, fill=color)


# ════════════════════════════════════════════════════════════════
# SLIDE 1  –  Title
# ════════════════════════════════════════════════════════════════
s1 = new_slide()
hbar(s1, BLUE)

# Subtle side accent
R(s1, 0, 0.07, 0.06, 7.43, fill=BLUE)

T(s1, "ExpenseAI",
  1.0, 1.1, 11.3, 2.1,
  sz=90, bold=True, c=WHITE, align=PP_ALIGN.CENTER)

T(s1, "Receipts In.     Report Out.",
  1.0, 3.2, 11.3, 0.9,
  sz=28, italic=True, c=BLUE, align=PP_ALIGN.CENTER)

# Divider
R(s1, 4.0, 4.35, 5.3, 0.04, fill=MUTED)

T(s1, "Dheeraj Chowdary Anne   \u00b7   [Partner Name]   \u00b7   [Course Number]   \u00b7   [Instructor Name]",
  1.0, 4.55, 11.3, 0.5,
  sz=13, c=MUTED, align=PP_ALIGN.CENTER)

T(s1, "Agentic AI for Expense Automation",
  1.0, 5.2, 11.3, 0.5,
  sz=14, c=RGBColor(0x3B, 0x4A, 0x6B), align=PP_ALIGN.CENTER)


# ════════════════════════════════════════════════════════════════
# SLIDE 2  –  Roadmap
# ════════════════════════════════════════════════════════════════
s2 = new_slide()
hbar(s2, BLUE)

T(s2, "Today's Story",
  0.6, 0.28, 12, 0.82,
  sz=44, bold=True, c=WHITE)

acts = [
    ("01", "The Broken\nSystem",    RED,   RED_DK),
    ("02", "Our\nArchitecture",     BLUE,  BLU_DK),
    ("03", "The\nIntelligence",     AMBER, AMB_DK),
    ("04", "Live\nDemo",            GREEN, GRN_DK),
]

cw, ch = 2.8, 4.3
cy = 1.5
sx = 0.66
gap = 0.43

for i, (num, label, accent, bg) in enumerate(acts):
    cx = sx + i * (cw + gap)
    R(s2, cx, cy, cw, ch, fill=bg, border=accent, bw=2.5)
    T(s2, num,
      cx + 0.1, cy + 0.2, cw - 0.2, 1.3,
      sz=56, bold=True, c=accent, align=PP_ALIGN.CENTER)
    T(s2, label,
      cx + 0.1, cy + 1.65, cw - 0.2, 2.4,
      sz=22, bold=True, c=WHITE, align=PP_ALIGN.CENTER)


# ════════════════════════════════════════════════════════════════
# SLIDE 3  –  Problem & Contribution
# ════════════════════════════════════════════════════════════════
s3 = new_slide()
hbar(s3, RED)

# Left panel – problem
R(s3, 0, 0.07, 6.4, 7.43, fill=RED_DK)
T(s3, "The Problem",
  0.4, 0.52, 5.7, 0.8,
  sz=30, bold=True, c=RED)

for i, p in enumerate([
    "\u2717   Templates fail messy receipts",
    "\u2717   Rules coded.  Always stale.",
    "\u2717   Humans review everything.",
]):
    T(s3, p, 0.5, 1.65 + i * 1.3, 5.6, 0.95, sz=20, c=WHITE)

# Right panel – solution
R(s3, 6.55, 0.07, 6.78, 7.43, fill=GRN_DK)
T(s3, "We Fixed All Three.",
  6.8, 0.52, 6.1, 0.8,
  sz=30, bold=True, c=GREEN)

for i, sol in enumerate([
    "\u2713   Vision AI.  Zero templates.",
    "\u2713   Live web search.  Always current.",
    "\u2713   RAG learns your policies.",
]):
    T(s3, sol, 6.8, 1.65 + i * 1.3, 6.0, 0.95, sz=20, c=WHITE)

# Novelty badges
badges = [
    ("Zero-template extraction", RED),
    ("Real-time rate lookup",     BLUE),
    ("Instant policy ingestion",  GREEN),
]
for i, (label, color) in enumerate(badges):
    bx = 0.38 + i * 4.35
    R(s3, bx, 5.7, 4.1, 0.68, fill=CARD, border=color, bw=1.5)
    T(s3, label, bx + 0.18, 5.76, 3.74, 0.56,
      sz=14, bold=True, c=color, align=PP_ALIGN.CENTER)


# ════════════════════════════════════════════════════════════════
# SLIDE 4  –  Architecture  (clean, Masters AI level)
# ════════════════════════════════════════════════════════════════
s4 = new_slide()
hbar(s4, BLUE)

T(s4, "Three Agents.  One Pipeline.",
  0.55, 0.18, 12.2, 0.72,
  sz=36, bold=True, c=WHITE)
T(s4, "Multimodal Vision   \u00b7   Agentic Tool-Use Loop (Anthropic Messages API)   \u00b7   Retrieval-Augmented Generation",
  0.55, 0.86, 12.2, 0.36,
  sz=13, c=LGRAY)

# ── PIPELINE ROW  ────────────────────────────────────────────────
# Positions: Receipt(0.38) → Claude(2.24) → Policy(5.50) → Report(9.84)
py, ph = 1.3, 1.05

R(s4, 0.38, py, 1.38, ph, fill=CARD, border=MUTED, bw=1.5)
T(s4, "Receipt\nimage / PDF", 0.4, py + 0.15, 1.34, ph - 0.3,
  sz=11, c=LGRAY, align=PP_ALIGN.CENTER)

T(s4, "\u2192", 1.8, py + 0.28, 0.4, 0.5, sz=24, bold=True, c=MUTED, align=PP_ALIGN.CENTER)

R(s4, 2.24, py, 2.78, ph, fill=RED_DK, border=RED, bw=2.5)
T(s4, "Claude Vision\nAgent", 2.26, py + 0.15, 2.74, ph - 0.3,
  sz=15, bold=True, c=RED, align=PP_ALIGN.CENTER)

T(s4, "\u2192", 5.06, py + 0.28, 0.4, 0.5, sz=24, bold=True, c=MUTED, align=PP_ALIGN.CENTER)

R(s4, 5.50, py, 4.30, ph, fill=BLU_DK, border=BLUE, bw=2.5)
T(s4, "Policy Verification Agent\nAgentic Tool-Use Loop", 5.52, py + 0.15, 4.26, ph - 0.3,
  sz=15, bold=True, c=BLUE, align=PP_ALIGN.CENTER)

T(s4, "\u2192", 9.84, py + 0.28, 0.4, 0.5, sz=24, bold=True, c=MUTED, align=PP_ALIGN.CENTER)

R(s4, 10.28, py, 2.67, ph, fill=GRN_DK, border=GREEN, bw=2.5)
T(s4, "Report\nGenerator", 10.3, py + 0.15, 2.63, ph - 0.3,
  sz=15, bold=True, c=GREEN, align=PP_ALIGN.CENTER)

# Down arrows to spec panels
T(s4, "\u2193", 3.43, 2.38, 0.4, 0.3, sz=14, c=MUTED, align=PP_ALIGN.CENTER)
T(s4, "\u2193", 7.44, 2.38, 0.4, 0.3, sz=14, c=MUTED, align=PP_ALIGN.CENTER)

# ── SPEC PANELS  (y=2.7, aligned under each pipeline box) ────────
sp_y, sp_h = 2.70, 2.55

# Claude Vision spec panel
R(s4, 2.24, sp_y, 2.78, sp_h, fill=RED_DK, border=RED, bw=1.5)
T(s4, "Claude Vision Agent", 2.36, sp_y + 0.14, 2.54, 0.42,
  sz=13, bold=True, c=RED)
for i, item in enumerate([
    "Model  claude-sonnet-4-6",
    "Input  base64 image bytes",
    "Format JPEG/PNG/HEIC/PDF",
    "Output JSON {amount, date,",
    "       vendor, confidence}",
]):
    T(s4, item, 2.36, sp_y + 0.62 + i * 0.38, 2.54, 0.36,
      sz=11, c=LGRAY, font="Courier New")

# Policy Verifier spec panel
R(s4, 5.50, sp_y, 4.30, sp_h, fill=BLU_DK, border=BLUE, bw=1.5)
T(s4, "max_iter = 6  \u00b7  stop_reason = tool_use", 5.62, sp_y + 0.14, 4.06, 0.42,
  sz=12, bold=True, c=BLUE)

# Tool 1 header + bullets
T(s4, "Tool 1: rag_search", 5.62, sp_y + 0.60, 1.9, 0.36,
  sz=12, bold=True, c=RGBColor(0x93, 0xC5, 0xFD))
for i, item in enumerate([
    "ChromaDB (HNSW)",
    "all-MiniLM-L6-v2",
    "384-dim, cosine",
    "Top-k=4, \u03b8\u22650.5",
]):
    T(s4, "\u00b7 " + item, 5.62, sp_y + 1.0 + i * 0.36, 1.9, 0.34,
      sz=11, c=LGRAY, font="Courier New")

# Vertical divider line between tools
R(s4, 7.52, sp_y + 0.56, 0.03, sp_h - 0.70, fill=MUTED)

# Fallback label
T(s4, "\u21e8 fallback\nif score\n< 0.5", 7.56, sp_y + 1.12, 0.7, 0.75,
  sz=10, bold=True, c=AMBER, align=PP_ALIGN.CENTER)

# Tool 2 header + bullets
T(s4, "Tool 2: web_search", 8.32, sp_y + 0.60, 1.35, 0.36,
  sz=12, bold=True, c=RGBColor(0x6E, 0xE7, 0xB7))
for i, item in enumerate([
    "Tavily API",
    "gsa.gov",
    "irs.gov",
    "live rates",
]):
    T(s4, "\u00b7 " + item, 8.32, sp_y + 1.0 + i * 0.36, 1.35, 0.34,
      sz=11, c=LGRAY, font="Courier New")

# Report spec panel
R(s4, 10.28, sp_y, 2.67, sp_h, fill=GRN_DK, border=GREEN, bw=1.5)
T(s4, "Report Generator", 10.4, sp_y + 0.14, 2.43, 0.42,
  sz=13, bold=True, c=GREEN)
for i, item in enumerate([
    "WeasyPrint + Jinja2",
    "HTML \u2192 PDF",
    "SQLite session store",
    "CSV export",
    "Audit-ready report",
]):
    T(s4, item, 10.4, sp_y + 0.62 + i * 0.38, 2.43, 0.36,
      sz=11, c=LGRAY, font="Courier New")

# ── INFRASTRUCTURE STRIP  (y = 5.42) ─────────────────────────────
infra4 = [
    ("FastAPI + uvicorn\nasync REST API",         BLUE),
    ("asyncio.gather()\nSemaphore(4)",             AMBER),
    ("WebSocket\nreal-time updates",               GREEN),
    ("SQLite + SQLAlchemy\nsession persistence",   MUTED),
    ("WeasyPrint + Jinja2\nPDF rendering",         RED),
]
sy4 = 5.42
sw4 = 13.33 / len(infra4)
for i, (label, color) in enumerate(infra4):
    R(s4, i * sw4 + 0.02, sy4, sw4 - 0.04, 0.82, fill=CARD, border=color, bw=1)
    T(s4, label, i * sw4 + 0.1, sy4 + 0.07, sw4 - 0.18, 0.68,
      sz=11, c=color, align=PP_ALIGN.CENTER)


# ════════════════════════════════════════════════════════════════
# SLIDE 5  –  Algorithms  (Masters AI level)
# ════════════════════════════════════════════════════════════════
s5 = new_slide()
hbar(s5, AMBER)

T(s5, "The 60% Rule.",
  0.55, 0.15, 8.5, 0.72,
  sz=42, bold=True, c=WHITE)
T(s5, "HITL Routing   \u00b7   Cosine Similarity   \u00b7   GSA M&IE Compliance   \u00b7   Agentic Tool-Use Loop",
  0.55, 0.82, 12.2, 0.36,
  sz=13, c=LGRAY)

# ── CONFIDENCE GATE  (y=1.1 to 3.05) ────────────────────────────
# NO box (left)
R(s5, 0.38, 1.1, 2.78, 1.82, fill=RED_DK, border=RED, bw=2)
T(s5, "\u26a0  Flag for Manager", 0.5, 1.2, 2.54, 0.46,
  sz=13, bold=True, c=RED, align=PP_ALIGN.CENTER)
for i, note in enumerate(["low image clarity", "ambiguous fields", "missing location"]):
    T(s5, "\u00b7 " + note, 0.52, 1.72 + i * 0.34, 2.52, 0.32,
      sz=11, c=LGRAY, font="Courier New")

# Arrow ← NO
T(s5, "\u2190 NO", 3.2, 1.87, 0.46, 0.38, sz=12, bold=True, c=RED)

# Main decision box (center)
R(s5, 3.70, 1.1, 6.0, 1.82, fill=AMB_DK, border=AMBER, bw=2)
T(s5, "Confidence Gate  \u2014  HITL Routing", 3.84, 1.18, 5.72, 0.44,
  sz=14, bold=True, c=AMBER)
T(s5,
  "         \u23a7 auto_approve(r)   conf(r) \u2265 \u03c4\n"
  "route(r)=\u23a8\n"
  "         \u23a9 flag_review(r)    conf(r) < \u03c4",
  3.84, 1.64, 5.72, 0.82,
  sz=12, c=LGRAY, font="Courier New")
T(s5, "\u03c4 = 0.6     conf : X \u2192 [0.0, 1.0]",
  3.84, 2.5, 5.72, 0.32,
  sz=11, c=RGBColor(0xFD, 0xD8, 0x7A), font="Courier New")

# Arrow YES →
T(s5, "YES \u2192", 9.74, 1.87, 0.5, 0.38, sz=12, bold=True, c=GREEN)

# YES box (right)
R(s5, 10.28, 1.1, 2.67, 1.82, fill=GRN_DK, border=GREEN, bw=2)
T(s5, "\u2713  Auto-Approve", 10.4, 1.2, 2.43, 0.46,
  sz=13, bold=True, c=GREEN, align=PP_ALIGN.CENTER)
for i, note in enumerate(["within policy limit", "approved_amt stored", "PDF generated"]):
    T(s5, "\u00b7 " + note, 10.4, 1.72 + i * 0.34, 2.43, 0.32,
      sz=11, c=LGRAY, font="Courier New")

# ── THREE ALGORITHM BOXES  (y=3.18 to 6.38) ─────────────────────
bx_y, bx_h = 3.18, 3.2
bx_w = (13.33 - 0.76 - 0.44) / 3   # = 4.04

# Box 1 — Semantic Retrieval (Cosine Similarity)
R(s5, 0.38, bx_y, bx_w, bx_h, fill=CARD, border=BLUE, bw=1.5)
T(s5, "Semantic Retrieval  (RAG)", 0.52, bx_y + 0.14, bx_w - 0.28, 0.42,
  sz=13, bold=True, c=BLUE)
T(s5,
  "sim(q,d) = cos(E\u03b8(q), E\u03b8(d))\n\n"
  "         E\u03b8(q) \u00b7 E\u03b8(d)\n"
  "       = \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
  "         \u2016E\u03b8(q)\u2016 \u00b7 \u2016E\u03b8(d)\u2016\n\n"
  "E\u03b8 = all-MiniLM-L6-v2 (d=384)\n"
  "Retrieve: D* = {d | sim \u2265 0.5}",
  0.52, bx_y + 0.62, bx_w - 0.28, 2.42,
  sz=12.5, c=LGRAY, font="Courier New")

# Box 2 — GSA M&IE Compliance
R(s5, 0.38 + bx_w + 0.22, bx_y, bx_w, bx_h, fill=CARD, border=AMBER, bw=1.5)
bx2_x = 0.38 + bx_w + 0.22
T(s5, "GSA M&IE Compliance", bx2_x + 0.14, bx_y + 0.14, bx_w - 0.28, 0.42,
  sz=13, bold=True, c=AMBER)
T(s5,
  "cap(l,t)=GSA_rate(city,YM)\u00d7\u03b4(t)\n\n"
  "       \u23a7 0.75  t\u2208{t_first,t_last}\n"
  "\u03b4(t) = \u23a8\n"
  "       \u23a9 1.00  otherwise\n\n"
  "a_i = min(x_i, cap(l_i, t_i))\n\n"
  "Daily: if \u03a3x_i > cap_d:\n"
  "  a_i \u2190 x_i\u00d7(cap_d/\u03a3x_i)",
  bx2_x + 0.14, bx_y + 0.62, bx_w - 0.28, 2.42,
  sz=12, c=LGRAY, font="Courier New")

# Box 3 — Agentic Tool-Use Loop
R(s5, 0.38 + 2 * (bx_w + 0.22), bx_y, bx_w, bx_h, fill=CARD, border=GREEN, bw=1.5)
bx3_x = 0.38 + 2 * (bx_w + 0.22)
T(s5, "Agentic Tool-Use Loop", bx3_x + 0.14, bx_y + 0.14, bx_w - 0.28, 0.42,
  sz=13, bold=True, c=GREEN)
T(s5,
  "msgs \u2190 [system, user_ctx]\n\n"
  "for t=0\u2026MAX_ITER-1:\n"
  "  r_t \u2190 LLM(msgs, tools)\n"
  "  if r_t.stop=end_turn: break\n"
  "  T_t={b|b.type=tool_use}\n"
  "  R_t=\u22c3 execute(b) \u2200b\u2208T_t\n"
  "  msgs += tool_results(R_t)\n\n"
  "MAX_ITER=6\n"
  "Tools:{rag_search,web_search}",
  bx3_x + 0.14, bx_y + 0.62, bx_w - 0.28, 2.42,
  sz=12, c=LGRAY, font="Courier New")


# ════════════════════════════════════════════════════════════════
# SLIDE 6  –  Key Takeaways
# ════════════════════════════════════════════════════════════════
s6 = new_slide()
hbar(s6, GREEN)

T(s6, "It Just Works.",
  0.6, 0.28, 8, 0.82,
  sz=44, bold=True, c=WHITE)

takeaways = [
    ("No templates.",               "Ever.",                              RED),
    ("Always current rates.",        "",                                  BLUE),
    ("Humans only when uncertain.", "",                                  GREEN),
]

for i, (main, sub, color) in enumerate(takeaways):
    ty = 1.45 + i * 1.5
    R(s6, 0.48, ty, 0.07, 1.15, fill=color)
    T(s6, f"{i + 1}.", 0.7, ty + 0.08, 0.62, 0.9,
      sz=34, bold=True, c=color)
    T(s6, main, 1.45, ty + 0.05, 5.7, 0.65,
      sz=27, bold=True, c=WHITE)
    if sub:
        T(s6, sub, 1.45, ty + 0.65, 5.7, 0.55,
          sz=23, bold=True, c=color)

# Screenshot placeholder
R(s6, 7.55, 1.3, 5.35, 4.95, fill=CARD, border=MUTED, bw=1)
T(s6, "[ Dashboard Screenshot ]",
  7.65, 1.55, 5.15, 0.55,
  sz=13, c=MUTED, align=PP_ALIGN.CENTER)
# Green annotation box inside placeholder
R(s6, 7.75, 2.3, 4.95, 1.0, fill=GRN_DK, border=GREEN, bw=1.5)
T(s6, "\u2713   $521.72  Auto-Approved\n      airfare + hotel",
  7.85, 2.37, 4.75, 0.86,
  sz=13, c=GREEN)
# Red annotation box inside placeholder
R(s6, 7.75, 3.55, 4.95, 1.0, fill=RED_DK, border=RED, bw=1.5)
T(s6, "\u26a0   $0.00  Flagged for Review\n      mileage \u2014 incomplete data",
  7.85, 3.62, 4.75, 0.86,
  sz=13, c=RED)

T(s6, "Thank you.",
  0.5, 6.72, 6.5, 0.65,
  sz=26, bold=True, c=MUTED)


# ── Save ─────────────────────────────────────────────────────────
out = "/Users/dheerajchowdaryanne/Documents/document ai/ExpenseAI_Presentation.pptx"
prs.save(out)
print(f"Saved: {out}")
