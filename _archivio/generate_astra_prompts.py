# generate_astra_prompts.py
# Genera un PDF prompt per ogni lezione — pronto da caricare su Astra

import json
from pathlib import Path
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)

PROMPTS_DIR = Path("astra_prompts")
PROMPTS_DIR.mkdir(exist_ok=True)

C_NAVY  = colors.HexColor("#0d2137")
C_BLUE  = colors.HexColor("#1565c0")
C_TEAL  = colors.HexColor("#00838f")
C_GREEN = colors.HexColor("#2e7d32")
C_RED   = colors.HexColor("#c62828")
C_GRAY  = colors.HexColor("#546e7a")
C_WHITE = colors.white
C_LGRAY = colors.HexColor("#eceff1")
W = A4[0] - 4*cm


def S(name, **kw):
    return ParagraphStyle(name, **kw)


def banner(text: str, color, style) -> list:
    t = Table([[Paragraph(text, style)]], colWidths=[W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), color),
        ("LEFTPADDING", (0,0), (-1,-1), 10),
        ("TOPPADDING", (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
    ]))
    return [t, Spacer(1, 6)]


def build_prompt_pdf(lesson_data: dict, lesson_date: str, output_path: Path):
    topic    = lesson_data.get("topic", "")
    summary  = lesson_data.get("summary_en", "")
    vocab    = lesson_data.get("vocabulary", [])
    grammar  = lesson_data.get("grammar_points", [])
    phrases  = lesson_data.get("phrases", [])
    homework = lesson_data.get("homework", "")
    sections = lesson_data.get("doc_sections_covered", [])

    styles = {
        "hdr_title": S("HT", fontName="Helvetica-Bold", fontSize=16,
                       textColor=C_WHITE, alignment=TA_CENTER),
        "hdr_sub":   S("HS", fontName="Helvetica", fontSize=10,
                       textColor=colors.HexColor("#90caf9"), alignment=TA_CENTER),
        "sec_hdr":   S("SH", fontName="Helvetica-Bold", fontSize=11,
                       textColor=C_WHITE),
        "body":      S("BD", fontName="Helvetica", fontSize=10,
                       textColor=colors.HexColor("#212121"),
                       leading=15, alignment=TA_JUSTIFY, spaceAfter=3),
        "body_b":    S("BDB", fontName="Helvetica-Bold", fontSize=10,
                       textColor=C_NAVY, spaceAfter=3),
        "bullet":    S("BU", fontName="Helvetica", fontSize=10,
                       textColor=C_GRAY, leftIndent=14, spaceAfter=2, leading=14),
        "example":   S("EX", fontName="Helvetica-Oblique", fontSize=10,
                       textColor=C_TEAL, leftIndent=20, spaceAfter=3),
        "exercise":  S("EV", fontName="Helvetica-Bold", fontSize=10,
                       textColor=C_NAVY, spaceBefore=8, spaceAfter=3),
        "instruct":  S("IN", fontName="Helvetica-Oblique", fontSize=9.5,
                       textColor=C_GRAY, leftIndent=14, spaceAfter=2),
    }

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm, bottomMargin=2.5*cm,
        title=f"DeutschOps Astra Prompt — {topic}"
    )

    story = []

    # ── Header ────────────────────────────────────────────────────────────────
    hdr = Table([[
        Paragraph("🇩🇪  DeutschOps — Astra Study Prompt", styles["hdr_title"]),
        Spacer(1, 4),
        Paragraph(topic, styles["hdr_sub"]),
        Paragraph(f"{lesson_date}  ·  Kevin Vecchi  ·  A2-B1  ·  Stefanie",
                  styles["hdr_sub"]),
    ]], colWidths=[W])
    hdr.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), C_NAVY),
        ("TOPPADDING", (0,0), (-1,-1), 14),
        ("BOTTOMPADDING", (0,0), (-1,-1), 14),
        ("LEFTPADDING", (0,0), (-1,-1), 16),
    ]))
    story.append(hdr)
    story.append(Spacer(1, 12))

    # ── Context block ─────────────────────────────────────────────────────────
    story += banner("CONTEXT FOR ASTRA", C_TEAL, styles["sec_hdr"])
    story.append(Paragraph(
        "You are my German tutor. I am Kevin, Italian, level A2-B1. "
        "My lessons are taught in English by a native German speaker (Stefanie). "
        f"Today we are reviewing: <b>{topic}</b>",
        styles["body"]
    ))
    if sections:
        story.append(Paragraph(
            f"Sections covered: {', '.join(sections)}",
            styles["bullet"]
        ))
    story.append(Spacer(1, 8))

    # ── Summary ───────────────────────────────────────────────────────────────
    if summary:
        story += banner("LESSON SUMMARY", C_BLUE, styles["sec_hdr"])
        story.append(Paragraph(summary, styles["body"]))
        story.append(Spacer(1, 8))

    # ── Vocabulary ────────────────────────────────────────────────────────────
    if vocab:
        story += banner("KEY VOCABULARY", C_BLUE, styles["sec_hdr"])
        for w in vocab:
            art  = f"{w.get('article','')} " if w.get("article") else ""
            base = w.get("german","")
            if art and base.lower().startswith(art.strip().lower()+" "):
                base = base[len(art.strip())+1:]
            eng  = w.get("english","")
            lvl  = w.get("level","")
            story.append(Paragraph(
                f"• <b>{art}{base}</b> — {eng}  <font color='#90a4ae'>[{lvl}]</font>",
                styles["bullet"]
            ))
        story.append(Spacer(1, 8))

    # ── Grammar ───────────────────────────────────────────────────────────────
    if grammar:
        story += banner("GRAMMAR POINTS", C_BLUE, styles["sec_hdr"])
        for gp in grammar:
            story.append(Paragraph(
                f"<b>{gp.get('rule','')}</b>", styles["body_b"]
            ))
            exp = gp.get("explanation_en","")
            if exp:
                story.append(Paragraph(f"→  {exp}", styles["bullet"]))
            for ex in gp.get("examples",[])[:2]:
                story.append(Paragraph(f"e.g.  {ex}", styles["example"]))
            story.append(Spacer(1, 4))

    # ── Phrases ───────────────────────────────────────────────────────────────
    if phrases:
        story += banner("USEFUL PHRASES / REDEMITTEL", C_TEAL, styles["sec_hdr"])
        for p in phrases:
            eng = p.get("english","") or p.get("italian","")
            ctx = p.get("context","")
            story.append(Paragraph(
                f"• <b>{p.get('german','')}</b> — {eng}"
                + (f"  <font color='#90a4ae'><i>({ctx})</i></font>" if ctx else ""),
                styles["bullet"]
            ))
        story.append(Spacer(1, 8))

    # ── Homework ──────────────────────────────────────────────────────────────
    if homework:
        story += banner("HOMEWORK", colors.HexColor("#f57f17"), styles["sec_hdr"])
        story.append(Paragraph(homework, styles["body"]))
        story.append(Spacer(1, 8))

    # ── Exercises ─────────────────────────────────────────────────────────────
    story += banner("EXERCISES TO GENERATE", C_GREEN, styles["sec_hdr"])

    exercises = [
        ("1. FILL IN THE BLANK (5 sentences)",
         "Use the key vocabulary above. Leave one word blank per sentence. "
         "Show the answer after a separator."),
        ("2. TRANSLATION DE → EN (5 sentences)",
         "Use vocabulary and grammar from this lesson."),
        ("3. TRANSLATION EN → DE (5 sentences)",
         "Use vocabulary and grammar from this lesson."),
        ("4. DIALOGUE COMPLETION (2 short dialogues, 3-4 lines)",
         f"Leave one or two lines blank. Context: everyday situations "
         f"using today's grammar ({grammar[0]['rule'] if grammar else 'today grammar'})."),
        ("5. FREE WRITING PROMPT",
         "Ask me to write 3-5 sentences in German using at least 5 words "
         "from today's vocabulary."),
        ("6. GRAMMAR DRILL (5 sentences)",
         f"Focus on: {grammar[0]['rule'] if grammar else 'today grammar'}. "
         "Show sentences with errors for me to correct."),
    ]

    for title, desc in exercises:
        story.append(Paragraph(title, styles["exercise"]))
        story.append(Paragraph(desc, styles["instruct"]))

    story.append(Spacer(1, 8))

    # ── Instructions ──────────────────────────────────────────────────────────
    story += banner("INSTRUCTIONS", C_RED, styles["sec_hdr"])
    instructions = [
        "Correct all my answers immediately with explanation in English",
        "Note recurring mistakes throughout the session",
        "Use only A2-B1 vocabulary unless I ask for more",
        "If I write something correct but unnatural, suggest a more native alternative",
        "Use 'die KI' not 'AI' when referring to artificial intelligence",
    ]
    for inst in instructions:
        story.append(Paragraph(f"• {inst}", styles["bullet"]))

    # Footer
    def add_footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#90a4ae"))
        canvas.drawString(2*cm, 1.1*cm,
            f"DeutschOps  ·  Kevin Vecchi  ·  {lesson_date}")
        canvas.drawRightString(A4[0]-2*cm, 1.1*cm, f"Page {doc.page}")
        canvas.setStrokeColor(colors.HexColor("#b0bec5"))
        canvas.setLineWidth(0.5)
        canvas.line(2*cm, 1.5*cm, A4[0]-2*cm, 1.5*cm)
        canvas.restoreState()

    doc.build(story, onFirstPage=add_footer, onLaterPages=add_footer)


def generate_all_prompts():
    data_files = sorted(Path("data").glob("lezione_*.json"))
    if not data_files:
        print("❌ No lesson files found in data/")
        return

    # Rimuovi vecchi .txt
    for old in PROMPTS_DIR.glob("*.txt"):
        old.unlink()
        print(f"🗑️  Rimosso: {old.name}")

    generated = 0
    for f in data_files:
        try:
            lesson_data = json.loads(f.read_text(encoding="utf-8"))
            lesson_id   = f.stem.replace("lezione_", "")
            topic = lesson_data.get("topic","lesson")
            safe_topic = (
                topic.lower()
                    .replace(" ", "_")
                    .replace("/","-")
                    .replace(",","")
                    .replace(":","")[:50]
            )
            filename = f"{lesson_id}_{safe_topic}.pdf"
            out_path = PROMPTS_DIR / filename

            build_prompt_pdf(lesson_data, lesson_id, out_path)
            print(f"✅ {filename}")
            generated += 1

        except Exception as e:
            print(f"❌ {f.name}: {e}")

    print(f"\n📁 {generated} PDF in: {PROMPTS_DIR.absolute()}")
    print("   Carica i PDF su Astra per studiare.")


if __name__ == "__main__":
    generate_all_prompts()