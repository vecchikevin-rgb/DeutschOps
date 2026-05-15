# pdf_gen.py — DeutschOps PDF Generator v2
import json
import sys
from pathlib import Path
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, KeepTogether
)
from reportlab.graphics.shapes import Drawing, Rect, String, Line, Circle
from reportlab.graphics import renderPDF
from reportlab.graphics.shapes import Group

# ─── PALETTE ──────────────────────────────────────────────────────────────────
C_NAVY      = colors.HexColor("#0d2137")
C_BLUE      = colors.HexColor("#1565c0")
C_ACCENT    = colors.HexColor("#0288d1")
C_TEAL      = colors.HexColor("#00838f")
C_LIGHT     = colors.HexColor("#e3f2fd")
C_LIGHT2    = colors.HexColor("#f0f7ff")
C_VERB      = colors.HexColor("#2e7d32")
C_NOUN      = colors.HexColor("#6a1b9a")
C_ADJ       = colors.HexColor("#bf360c")
C_EXPR      = colors.HexColor("#00695c")
C_ADV       = colors.HexColor("#1565c0")
C_GRAY      = colors.HexColor("#546e7a")
C_LGRAY     = colors.HexColor("#eceff1")
C_BORDER    = colors.HexColor("#b0bec5")
C_WHITE     = colors.white
C_YELLOW    = colors.HexColor("#fff8e1")
C_YELLOW_B  = colors.HexColor("#f9a825")
C_GREEN_L   = colors.HexColor("#e8f5e9")
C_RED_L     = colors.HexColor("#ffebee")

CAT_COLOR = {
    "verb_regular":   C_VERB,
    "verb_irregular": C_VERB,
    "verb_separable": C_TEAL,
    "verb_modal":     C_VERB,
    "noun":           C_NOUN,
    "adjective":      C_ADJ,
    "adverb":         C_ADV,
    "phrase":         C_EXPR,
    "expression":     C_EXPR,
}
CAT_LABEL = {
    "verb_regular":   "V·reg",
    "verb_irregular": "V·irr",
    "verb_separable": "V·sep",
    "verb_modal":     "V·mod",
    "noun":           "Noun",
    "adjective":      "Adj",
    "adverb":         "Adv",
    "phrase":         "Phrase",
    "expression":     "Expr",
}
CAT_ORDER = [
    "verb_modal","verb_separable","verb_irregular","verb_regular",
    "noun","adjective","adverb","expression","phrase"
]

W = A4[0] - 4*cm  # usable width

# ─── STYLES ───────────────────────────────────────────────────────────────────
def S(**kw):
    """Shortcut per creare ParagraphStyle inline."""
    name = kw.pop("name", "s")
    return ParagraphStyle(name, **kw)

def build_styles():
    return {
        "h_title": S(name="HT", fontName="Helvetica-Bold", fontSize=18,
                     textColor=C_WHITE, alignment=TA_LEFT, leading=22),
        "h_sub":   S(name="HS", fontName="Helvetica", fontSize=9,
                     textColor=colors.HexColor("#90caf9"), alignment=TA_LEFT),
        "h_date":  S(name="HD", fontName="Helvetica-Bold", fontSize=9,
                     textColor=colors.HexColor("#bbdefb"), alignment=TA_RIGHT),
        "section": S(name="SEC", fontName="Helvetica-Bold", fontSize=12,
                     textColor=C_BLUE, spaceBefore=16, spaceAfter=4),
        "body":    S(name="BD", fontName="Helvetica", fontSize=9.5,
                     textColor=colors.HexColor("#212121"), leading=14,
                     alignment=TA_JUSTIFY, spaceAfter=3),
        "body_b":  S(name="BDB", fontName="Helvetica-Bold", fontSize=9.5,
                     textColor=C_NAVY, leading=14),
        "italic":  S(name="IT", fontName="Helvetica-Oblique", fontSize=9,
                     textColor=C_GRAY, leading=13),
        "small":   S(name="SM", fontName="Helvetica", fontSize=8,
                     textColor=C_GRAY),
        "small_b": S(name="SMB", fontName="Helvetica-Bold", fontSize=8,
                     textColor=C_GRAY),
        "badge":   S(name="BG", fontName="Helvetica-Bold", fontSize=7.5,
                     textColor=C_WHITE, alignment=TA_CENTER),
        "german":  S(name="GR", fontName="Helvetica-Bold", fontSize=9.5,
                     textColor=C_NAVY),
        "ex":      S(name="EX", fontName="Helvetica-Oblique", fontSize=8.5,
                     textColor=C_GRAY, leftIndent=8),
        "q":       S(name="QQ", fontName="Helvetica-Bold", fontSize=9.5,
                     textColor=C_NAVY, spaceBefore=6),
        "a":       S(name="AA", fontName="Helvetica", fontSize=9.5,
                     textColor=colors.HexColor("#1b5e20"), leftIndent=14),
        "a_exp":   S(name="AX", fontName="Helvetica-Oblique", fontSize=8.5,
                     textColor=C_GRAY, leftIndent=14, spaceAfter=6),
        "footer":  S(name="FT", fontName="Helvetica", fontSize=7.5,
                     textColor=colors.HexColor("#90a4ae")),
    }


# ─── HELPERS ──────────────────────────────────────────────────────────────────
def hr(color=C_ACCENT, thickness=0.8, space=6):
    return HRFlowable(width="100%", thickness=thickness,
                      color=color, spaceAfter=space, spaceBefore=2)

def section_title(text: str, styles: dict):
    return [Paragraph(text, styles["section"]), hr()]

def fix_article(word: dict) -> str:
    """Restituisce la parola tedesca senza duplicare l'articolo."""
    german = word.get("german", "")
    article = word.get("article", "")
    plural = word.get("plural", "")

    # Rimuovi articolo duplicato se già presente nella parola
    if article and german.lower().startswith(article.lower() + " "):
        base = german[len(article)+1:]
    else:
        base = german

    if article:
        display = f"{article} <b>{base}</b>"
    else:
        display = f"<b>{base}</b>"

    if plural:
        display += f" <font size='7.5' color='#78909c'>· {plural}</font>"

    return display

def sort_vocabulary(vocab: list) -> list:
    """Ordina vocabolario: prima per categoria, poi alfabeticamente."""
    def sort_key(w):
        cat = w.get("category", "zzz")
        order = CAT_ORDER.index(cat) if cat in CAT_ORDER else 99
        return (order, w.get("german", "").lower())
    return sorted(vocab, key=sort_key)


# ─── HEADER ───────────────────────────────────────────────────────────────────
def make_header(data: dict, styles: dict) -> list:
    topic = data.get("topic", "Lesson").upper()
    lesson_num = data.get("lesson_number", "")
    lesson_date = data.get("_lesson_date", "")
    doc_sections = data.get("doc_sections_covered", [])
    vocab_n = len(data.get("vocabulary", []))
    grammar_n = len(data.get("grammar_points", []))

    label = f"LESSON {lesson_num}  ·  DEUTSCHOPS" if lesson_num else "DEUTSCHOPS"

    left_col = [
        Paragraph(label, styles["h_sub"]),
        Spacer(1, 4),
        Paragraph(topic, styles["h_title"]),
        Spacer(1, 6),
    ]
    if doc_sections:
        secs = " · ".join(doc_sections[:3])
        left_col.append(Paragraph(secs, styles["h_sub"]))

    right_col = [
        Paragraph(lesson_date, styles["h_date"]),
        Spacer(1, 8),
        Paragraph(
            f"<b>{vocab_n}</b> words<br/><b>{grammar_n}</b> grammar points",
            S(name="HR2", fontName="Helvetica", fontSize=8.5,
              textColor=colors.HexColor("#90caf9"), alignment=TA_RIGHT)
        ),
    ]

    t = Table([[left_col, right_col]], colWidths=[12*cm, 5*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), C_NAVY),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("TOPPADDING", (0,0), (-1,-1), 18),
        ("BOTTOMPADDING", (0,0), (-1,-1), 18),
        ("LEFTPADDING", (0,0), (0,-1), 20),
        ("RIGHTPADDING", (-1,0), (-1,-1), 16),
    ]))
    return [t, Spacer(1, 14)]


# ─── SUMMARY ──────────────────────────────────────────────────────────────────
def make_summary(data: dict, styles: dict) -> list:
    elements = []
    elements += section_title("📋  LESSON SUMMARY", styles)

    summary = data.get("summary_en", "")
    if summary:
        elements.append(Paragraph(summary, styles["body"]))
        elements.append(Spacer(1, 6))

    # Stats row
    vocab_n = len(data.get("vocabulary", []))
    grammar_n = len(data.get("grammar_points", []))
    phrases_n = len(data.get("phrases", []))
    homework = data.get("homework", "")

    stat_items = [
        (str(vocab_n), "vocabulary items"),
        (str(grammar_n), "grammar rules"),
        (str(phrases_n), "useful phrases"),
    ]

    stat_cells = []
    for num, label in stat_items:
        stat_cells.append([
            Paragraph(
                f'<font size="20" color="#1565c0"><b>{num}</b></font>',
                S(name="SN", fontName="Helvetica-Bold", fontSize=20,
                  textColor=C_BLUE, alignment=TA_CENTER)
            ),
            Paragraph(label, S(name="SL", fontName="Helvetica", fontSize=8.5,
                               textColor=C_GRAY, alignment=TA_CENTER)),
        ])

    stat_row = []
    for cell in stat_cells:
        stat_row.append(cell)

    # Flatten for Table: one row, each stat is a mini-table
    flat = []
    for num, label in stat_items:
        flat.append(
            Paragraph(
                f'<font size="18"><b>{num}</b></font><br/>'
                f'<font size="8" color="#546e7a">{label}</font>',
                S(name="SF", fontName="Helvetica-Bold", fontSize=18,
                  textColor=C_BLUE, alignment=TA_CENTER, leading=22)
            )
        )

    stats_t = Table([flat], colWidths=[W/3]*3)
    stats_t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), C_LIGHT2),
        ("ALIGN", (0,0), (-1,-1), "CENTER"),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,-1), 10),
        ("BOTTOMPADDING", (0,0), (-1,-1), 10),
        ("BOX", (0,0), (-1,-1), 0.5, C_BORDER),
        ("LINEBEFORE", (1,0), (1,0), 0.5, C_BORDER),
        ("LINEBEFORE", (2,0), (2,0), 0.5, C_BORDER),
    ]))
    elements.append(stats_t)

    if homework:
        elements.append(Spacer(1, 10))
        hw = Table(
            [[Paragraph(f"📌  <b>Homework:</b>  {homework}", styles["body"])]],
            colWidths=[W]
        )
        hw.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,-1), C_YELLOW),
            ("LINEBEFORE", (0,0), (0,-1), 3, C_YELLOW_B),
            ("LEFTPADDING", (0,0), (-1,-1), 12),
            ("TOPPADDING", (0,0), (-1,-1), 8),
            ("BOTTOMPADDING", (0,0), (-1,-1), 8),
        ]))
        elements.append(hw)

    elements.append(Spacer(1, 6))
    return elements


# ─── VOCABULARY ───────────────────────────────────────────────────────────────
def make_vocabulary(data: dict, styles: dict) -> list:
    elements = []
    vocab = sort_vocabulary(data.get("vocabulary", []))
    if not vocab:
        return elements

    elements += section_title("📚  VOCABULARY", styles)

    header = [
        Paragraph("<b>Type</b>", styles["badge"]),
        Paragraph("<b>German</b>", styles["badge"]),
        Paragraph("<b>English</b>", styles["badge"]),
        Paragraph("<b>Example</b>", styles["badge"]),
        Paragraph("<b>Lvl</b>", styles["badge"]),
    ]

    rows = [header]
    style_cmds = [
        ("BACKGROUND", (0,0), (-1,0), C_BLUE),
        ("TEXTCOLOR", (0,0), (-1,0), C_WHITE),
        ("ALIGN", (0,0), (0,-1), "CENTER"),
        ("ALIGN", (-1,0), (-1,-1), "CENTER"),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
        ("RIGHTPADDING", (0,0), (-1,-1), 6),
        ("GRID", (0,0), (-1,-1), 0.3, C_BORDER),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [C_WHITE, C_LIGHT2]),
    ]

    for i, word in enumerate(vocab, 1):
        cat = word.get("category", "other")
        cat_color = CAT_COLOR.get(cat, C_GRAY)
        cat_label = CAT_LABEL.get(cat, cat[:5])
        level = word.get("level", "")
        german_html = fix_article(word)

        row = [
            Paragraph(cat_label, S(name=f"B{i}", fontName="Helvetica-Bold",
                                   fontSize=7, textColor=C_WHITE, alignment=TA_CENTER)),
            Paragraph(german_html, styles["german"]),
            Paragraph(word.get("english", ""), styles["body"]),
            Paragraph(f"<i>{word.get('example_de', '')}</i>", styles["ex"]),
            Paragraph(f"<b>{level}</b>", S(name=f"LV{i}", fontName="Helvetica-Bold",
                                            fontSize=7.5, textColor=cat_color,
                                            alignment=TA_CENTER)),
        ]
        rows.append(row)
        style_cmds.append(("BACKGROUND", (0,i), (0,i), cat_color))

    t = Table(rows, colWidths=[1.4*cm, 3.5*cm, 3.3*cm, 6.5*cm, 1.1*cm])
    t.setStyle(TableStyle(style_cmds))
    elements.append(t)
    elements.append(Spacer(1, 8))
    return elements


# ─── GRAMMAR ──────────────────────────────────────────────────────────────────
def make_grammar(data: dict, styles: dict) -> list:
    elements = []
    grammar = data.get("grammar_points", [])
    if not grammar:
        return elements

    elements += section_title("📐  GRAMMAR", styles)

    for i, point in enumerate(grammar, 1):
        content = []
        content.append(
            Paragraph(f"<b>{i}.  {point.get('rule','')}</b>", styles["body_b"])
        )
        exp = point.get("explanation_en", "") or point.get("explanation_it", "")
        if exp:
            content.append(Paragraph(exp, styles["italic"]))

        for ex in point.get("examples", []):
            content.append(Paragraph(f"→  <i>{ex}</i>", styles["ex"]))

        block = Table([[content]], colWidths=[W])
        block.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,-1), C_LIGHT2),
            ("LINEBEFORE", (0,0), (0,-1), 3.5, C_ACCENT),
            ("LEFTPADDING", (0,0), (-1,-1), 14),
            ("RIGHTPADDING", (0,0), (-1,-1), 10),
            ("TOPPADDING", (0,0), (-1,-1), 8),
            ("BOTTOMPADDING", (0,0), (-1,-1), 8),
        ]))
        elements.append(KeepTogether([block, Spacer(1, 6)]))

    return elements


# ─── PHRASES ──────────────────────────────────────────────────────────────────
def make_phrases(data: dict, styles: dict) -> list:
    elements = []
    phrases = data.get("phrases", [])
    if not phrases:
        return elements

    elements += section_title("💬  USEFUL PHRASES", styles)

    header = [
        Paragraph("<b>German</b>", styles["badge"]),
        Paragraph("<b>English</b>", styles["badge"]),
        Paragraph("<b>Context</b>", styles["badge"]),
    ]
    rows = [header]
    for phrase in phrases:
        rows.append([
            Paragraph(f"<b>{phrase.get('german','')}</b>", styles["german"]),
            Paragraph(phrase.get("english", "") or phrase.get("english",""), styles["body"]),
            Paragraph(f"<i>{phrase.get('context','')}</i>", styles["small"]),
        ])

    t = Table(rows, colWidths=[W*0.33, W*0.33, W*0.34])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), C_TEAL),
        ("TEXTCOLOR", (0,0), (-1,0), C_WHITE),
        ("ALIGN", (0,0), (-1,0), "CENTER"),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("LEFTPADDING", (0,0), (-1,-1), 8),
        ("RIGHTPADDING", (0,0), (-1,-1), 8),
        ("GRID", (0,0), (-1,-1), 0.3, C_BORDER),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [C_WHITE, C_GREEN_L]),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 6))
    return elements


# ─── DIAGRAM: direzioni ───────────────────────────────────────────────────────
def make_direction_diagram() -> Drawing:
    """
    Disegna un diagramma visivo per Wo? vs Wohin?
    Usato quando la lezione tratta avverbi direzionali.
    """
    d = Drawing(W, 90)

    # Box WO (stato)
    d.add(Rect(10, 10, 130, 70, fillColor=colors.HexColor("#e3f2fd"),
               strokeColor=C_ACCENT, strokeWidth=1.5))
    d.add(String(75, 68, "WO?  (state)", fontSize=8, fontName="Helvetica-Bold",
                 fillColor=C_BLUE, textAnchor="middle"))
    for y, txt in [(52,"drinnen — inside"), (38,"draußen — outside"),
                   (24,"oben — above"), (10,"unten — below")]:
        d.add(String(75, y+4, txt, fontSize=7.5, fontName="Helvetica",
                     fillColor=C_GRAY, textAnchor="middle"))

    # Freccia centrale
    d.add(Line(150, 45, 195, 45, strokeColor=C_ACCENT, strokeWidth=2))
    d.add(String(172, 50, "→ movement", fontSize=7, fontName="Helvetica-Oblique",
                 fillColor=C_GRAY, textAnchor="middle"))

    # Box WOHIN (movimento)
    offset = 200
    d.add(Rect(offset, 10, 145, 70, fillColor=colors.HexColor("#e8f5e9"),
               strokeColor=C_TEAL, strokeWidth=1.5))
    d.add(String(offset+72, 68, "WOHIN?  (movement)", fontSize=8,
                 fontName="Helvetica-Bold", fillColor=C_TEAL, textAnchor="middle"))
    for y, txt in [(52,"rein — going in"), (38,"raus — going out"),
                   (24,"rauf — going up"), (10,"runter — going down")]:
        d.add(String(offset+72, y+4, txt, fontSize=7.5, fontName="Helvetica",
                     fillColor=C_GRAY, textAnchor="middle"))

    return d


# ─── EXERCISES PAGE ───────────────────────────────────────────────────────────
def make_exercises(data: dict, styles: dict) -> list:
    elements = [PageBreak()]
    elements += section_title("✏️  COMPREHENSION EXERCISES", styles)

    questions = data.get("comprehension_questions", [])
    grammar = data.get("grammar_points", [])
    vocab = data.get("vocabulary", [])

    # ══ SECTION A: Direct questions — NO answers ══
    if questions:
        elements.append(Paragraph("<b>A.  Answer the following questions in German</b>",
                                   styles["body_b"]))
        elements.append(Spacer(1, 8))
        for i, q in enumerate(questions, 1):
            q_de = q.get("question_de", "")
            # Domanda e spazio risposta in celle separate, non nella stessa riga
            content = [
                Paragraph(f"<b>Q{i}:</b>  {q_de}", styles["q"]),
                Spacer(1, 4),
                Paragraph(
                    "<font color='#b0bec5'>Your answer: _________________________________________________</font>",
                    styles["small"]
                ),
                Spacer(1, 4),
            ]
            block = Table([[content]], colWidths=[W])
            block.setStyle(TableStyle([
                ("BACKGROUND", (0,0), (-1,-1), C_LIGHT2),
                ("LEFTPADDING", (0,0), (-1,-1), 12),
                ("RIGHTPADDING", (0,0), (-1,-1), 12),
                ("TOPPADDING", (0,0), (-1,-1), 8),
                ("BOTTOMPADDING", (0,0), (-1,-1), 8),
                ("LINEBEFORE", (0,0), (0,-1), 3, C_ACCENT),
            ]))
            elements.append(block)
            elements.append(Spacer(1, 8))


    # ══ SECTION B: Fill-in-the-blank — NO answers ══
    elements.append(Spacer(1, 8))
    elements.append(Paragraph(
        "<b>B.  Fill in the blank</b>  "
        "<font size='8' color='#546e7a'>(use the correct form)</font>",
        styles["body_b"]))
    elements.append(Spacer(1, 6))

    blanks = []
    for point in grammar:
        for ex in point.get("examples", []):
            words = ex.split()
            if len(words) >= 3:
                for j, w in enumerate(words):
                    if len(w) > 2 and j > 0:
                        blanked = words[:j] + ["_______"] + words[j+1:]
                        blanks.append({
                            "exercise": " ".join(blanked),
                            "answer": ex,
                            "hint": point.get("rule", "")
                        })
                        break

    for i, b in enumerate(blanks[:6], 1):
        block = Table([[
            Paragraph(
                f"<b>{i}.</b>  {b['exercise']}"
                f"  <font size='7' color='#90a4ae'>({b['hint']})</font>",
                styles["q"]
            ),
        ]], colWidths=[W])
        block.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,-1), C_LGRAY),
            ("LEFTPADDING", (0,0), (-1,-1), 12),
            ("TOPPADDING", (0,0), (-1,-1), 7),
            ("BOTTOMPADDING", (0,0), (-1,-1), 14),
        ]))
        elements.append(KeepTogether([block, Spacer(1, 5)]))

    # ══ SECTION C: Translate into German — NO answers ══
    elements.append(Spacer(1, 8))
    elements.append(Paragraph("<b>C.  Translate into German</b>", styles["body_b"]))
    elements.append(Spacer(1, 6))

    sample = [w for w in vocab if w.get("english")][:8]
    if sample:
        rows = [[
            Paragraph("<b>#</b>", styles["badge"]),
            Paragraph("<b>English</b>", styles["badge"]),
            Paragraph("<b>Your answer</b>", styles["badge"]),
        ]]
        for i, w in enumerate(sample, 1):
            rows.append([
                Paragraph(str(i), S(name=f"N{i}", fontName="Helvetica",
                                     fontSize=9, alignment=TA_CENTER)),
                Paragraph(w.get("english", ""), styles["body"]),
                Paragraph("", styles["body"]),  # spazio vuoto
            ])
        t = Table(rows, colWidths=[1*cm, (W-1*cm)*0.4, (W-1*cm)*0.6])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), C_NAVY),
            ("TEXTCOLOR", (0,0), (-1,0), C_WHITE),
            ("ALIGN", (0,0), (0,-1), "CENTER"),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ("TOPPADDING", (0,0), (-1,-1), 8),
            ("BOTTOMPADDING", (0,0), (-1,-1), 8),
            ("LEFTPADDING", (0,0), (-1,-1), 8),
            ("GRID", (0,0), (-1,-1), 0.3, C_BORDER),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [C_WHITE, C_LIGHT2]),
        ]))
        elements.append(t)

    # ══ PAGE BREAK → ANSWER KEY ══
    elements.append(PageBreak())
    elements += section_title("✅  ANSWER KEY", styles)
    elements.append(Paragraph(
        "<i>Check your answers only after completing all exercises above.</i>",
        styles["italic"]
    ))
    elements.append(Spacer(1, 10))

    # Risposte A
    if questions:
        elements.append(Paragraph("<b>A.  Answers</b>", styles["body_b"]))
        elements.append(Spacer(1, 6))
        for i, q in enumerate(questions, 1):
            a_de = q.get("answer_de", "")
            elements.append(Paragraph(f"<b>Q{i}:</b>  {a_de}", styles["a"]))
            elements.append(Spacer(1, 4))

    # Risposte B
    if blanks:
        elements.append(Spacer(1, 10))
        elements.append(Paragraph("<b>B.  Answers</b>", styles["body_b"]))
        elements.append(Spacer(1, 6))
        for i, b in enumerate(blanks[:6], 1):
            elements.append(Paragraph(f"<b>{i}.</b>  {b['answer']}", styles["a"]))
            elements.append(Spacer(1, 4))

    # Risposte C
    if sample:
        elements.append(Spacer(1, 10))
        elements.append(Paragraph("<b>C.  Answers</b>", styles["body_b"]))
        elements.append(Spacer(1, 6))
        for i, w in enumerate(sample, 1):
            german_display = fix_article(w)
            elements.append(
                Paragraph(f"<b>{i}.</b>  {german_display}", styles["a"])
            )
            elements.append(Spacer(1, 4))

    # Grammar recap D — sempre visibile
    elements.append(Spacer(1, 12))
    elements += section_title("📖  GRAMMAR REFERENCE", styles)
    for point in grammar:
        rule = point.get("rule", "")
        exp = point.get("explanation_en", "") or point.get("explanation_it", "")
        examples = point.get("examples", [])

        content = [
            Paragraph(f"<b>{rule}</b>", styles["body_b"]),
        ]
        if exp:
            content.append(Paragraph(exp, styles["italic"]))
        for ex in examples:
            content.append(Paragraph(f"→  <i>{ex}</i>", styles["ex"]))

        recap = Table([[content]], colWidths=[W])
        recap.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,-1), C_LGRAY),
            ("LINEBEFORE", (0,0), (0,-1), 3, C_BLUE),
            ("LEFTPADDING", (0,0), (-1,-1), 12),
            ("TOPPADDING", (0,0), (-1,-1), 7),
            ("BOTTOMPADDING", (0,0), (-1,-1), 7),
        ]))
        elements.append(KeepTogether([recap, Spacer(1, 5)]))

    return elements


# ─── FOOTER ───────────────────────────────────────────────────────────────────
def add_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#90a4ae"))
    ts = datetime.now().strftime("%d %b %Y  %H:%M")
    canvas.drawString(2*cm, 1.1*cm, f"DeutschOps  ·  generated {ts}")
    canvas.drawRightString(A4[0]-2*cm, 1.1*cm, f"page {doc.page}")
    # Linea sottile
    canvas.setStrokeColor(C_BORDER)
    canvas.setLineWidth(0.5)
    canvas.line(2*cm, 1.5*cm, A4[0]-2*cm, 1.5*cm)
    canvas.restoreState()


# ─── MAIN ─────────────────────────────────────────────────────────────────────
def generate_pdf(json_path: str, output_dir: str = "pdfs") -> str:
    Path(output_dir).mkdir(exist_ok=True)
    json_path = Path(json_path)
    data = json.loads(json_path.read_text(encoding="utf-8"))

    lesson_id = json_path.stem.replace("lezione_", "")
    data["_lesson_date"] = lesson_id

    # Converti sommario in inglese se era in italiano
    if not data.get("summary_en") and data.get("summary_it"):
        data["summary_en"] = data["summary_it"]

    output_path = Path(output_dir) / f"{json_path.stem}.pdf"

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm, bottomMargin=2.5*cm,
        title=f"DeutschOps — {data.get('topic','Lesson')}",
        author="DeutschOps"
    )

    styles = build_styles()
    story = []

    story += make_header(data, styles)
    story += make_summary(data, styles)

    # Aggiungi diagramma direzioni se rilevante
    topic = data.get("topic", "").lower()
    sections = " ".join(data.get("doc_sections_covered", [])).lower()
    if any(k in topic+sections for k in ["direction","wohin","rein","raus","adverb"]):
        story += section_title("🗺️  VISUAL REFERENCE: Wo? vs Wohin?", styles)
        story.append(make_direction_diagram())
        story.append(Spacer(1, 12))

    story += make_vocabulary(data, styles)
    story += make_grammar(data, styles)
    story += make_phrases(data, styles)
    story += make_exercises(data, styles)

    doc.build(story, onFirstPage=add_footer, onLaterPages=add_footer)
    print(f"✅ PDF generato: {output_path}")
    return str(output_path)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        files = sorted(Path("data").glob("lezione_*.json"))
        if not files:
            print("No JSON files found in data/")
            sys.exit(1)
        json_file = str(files[-1])
        print(f"Using most recent: {json_file}")
    else:
        json_file = sys.argv[1]

    generate_pdf(json_file)