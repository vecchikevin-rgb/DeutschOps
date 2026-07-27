# grammar_book.py
import os
import json
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
import anthropic

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak
)
from reportlab.platypus.tableofcontents import TableOfContents
from reportlab.platypus.doctemplate import BaseDocTemplate, PageTemplate
from reportlab.platypus.frames import Frame

load_dotenv()
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Path ancorati al progetto, non alla cwd (vedi do/base/paths.py). Questo
# modulo resta il generatore ReportLab del libro di grammatica finche' non
# viene consolidato in do/uscite/ — vedi la nota in do/uscite/pdf.py.
from do.base.paths import GRAMMAR_DB, ROOT  # noqa: E402

OUTPUT_PDF = ROOT / "DeutschOps_Grammar_Book.pdf"

C_NAVY    = colors.HexColor("#0d2137")
C_BLUE    = colors.HexColor("#1565c0")
C_TEAL    = colors.HexColor("#00838f")
C_GREEN   = colors.HexColor("#2e7d32")
C_GRAY    = colors.HexColor("#546e7a")
C_LGRAY   = colors.HexColor("#eceff1")
C_LIGHT   = colors.HexColor("#e3f2fd")
C_WHITE   = colors.white
C_YELLOW  = colors.HexColor("#fff8e1")
C_YELLOW_B = colors.HexColor("#f9a825")
C_RED     = colors.HexColor("#c62828")
C_RED_L   = colors.HexColor("#ffebee")
C_ORANGE  = colors.HexColor("#e65100")

W = A4[0] - 4*cm

# Didactic order — English only
CATEGORY_ORDER = [
    "Verbs — Basics",
    "Verbs — Separable & Modal",
    "Verbs — Irregular & Tenses",
    "Sentence Structure — Word Order",
    "Subordinate Clauses",
    "Cases — Kasus",
    "Pronouns",
    "Adjectives & Adverbs",
    "Prepositions",
    "Other Structures",
]

# Keywords → category mapping
CATEGORY_MAP = [
    (["separable", "trennbar", "prefix", "trennbare"], "Verbs — Separable & Modal"),
    (["modal", "können", "müssen", "dürfen", "wollen", "sollen", "mögen",
      "shall", "should", "konjunktiv ii"], "Verbs — Separable & Modal"),
    (["irregular", "unregelmäßig", "vowel change", "umlaut", "strong verb",
      "ablaut"], "Verbs — Irregular & Tenses"),
    (["perfekt", "präteritum", "futur", "passive", "partizip", "perfect tense",
      "past tense", "tense", "haben/sein"], "Verbs — Irregular & Tenses"),
    (["verb", "conjugat", "konjugat", "infinitiv", "infinitive",
      "conjugation"], "Verbs — Basics"),
    (["nebensatz", "subordinate", "conjunction", "weil", "dass", "wenn",
      "ob", "als", "obwohl", "damit", "indirect question",
      "word order in"], "Subordinate Clauses"),
    (["word order", "wortstellung", "position", "v2", "verb second",
      "satzstellung", "sentence structure", "tekamolo",
      "main clause"], "Sentence Structure — Word Order"),
    (["akkusativ", "dativ", "genitiv", "nominativ", "case", "kasus",
      "declension", "deklination", "außer",
      "preposition with dativ"], "Cases — Kasus"),
    (["pronoun", "pronomen", "reflexive", "personal", "possessiv",
      "relative", "demonstrativ"], "Pronouns"),
    (["adjektiv", "adjective", "adverb", "komparativ", "superlativ",
      "comparative", "superlative", "gefallen",
      "dative object"], "Adjectives & Adverbs"),
    (["präposition", "preposition", "mit dativ", "mit akkusativ",
      "two-way"], "Prepositions"),
]


def assign_category(rule: str, explanation: str) -> str:
    text = (rule + " " + explanation).lower()
    for keywords, category in CATEGORY_MAP:
        if any(kw in text for kw in keywords):
            return category
    return "Other Structures"


def load_grammar_db() -> dict:
    if GRAMMAR_DB.exists():
        return json.loads(GRAMMAR_DB.read_text(encoding="utf-8"))
    return {"rules": {}, "last_updated": ""}


def save_grammar_db(db: dict):
    db["last_updated"] = datetime.now().isoformat()
    GRAMMAR_DB.write_text(
        json.dumps(db, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def collect_rules_from_lessons() -> dict:
    rules = {}
    for f in sorted(Path("data").glob("lezione_*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            for gp in d.get("grammar_points", []):
                key = gp.get("rule", "").strip()
                if not key:
                    continue
                if key not in rules or (
                    gp.get("full_rule") and not rules[key].get("full_rule")
                ):
                    rules[key] = gp
        except Exception as e:
            print(f"Warning: {f.name}: {e}")
    return rules


_DOC_EXTRACT_SYSTEM = (
    "You are a German grammar expert. Extract ALL grammar rules from the provided document. All explanations in English.\n"
    'Return ONLY valid JSON, no backticks: {"grammar_rules":[{"rule":"<English name>","explanation_en":"<str>","examples":["<str>"],"full_rule":"","common_mistakes":"","exceptions":"","source_verified":false}]}'
)


def collect_rules_from_doc(doc_text: str) -> list:
    print("Extracting rules from Google Doc...")

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=8000,
        system=_DOC_EXTRACT_SYSTEM,
        messages=[{"role": "user", "content": f"GOOGLE DOC:\n{doc_text[:40000]}"}]
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:-1]).strip()
    start = raw.find("{")
    end   = raw.rfind("}") + 1
    if start >= 0 and end > start:
        raw = raw[start:end]

    try:
        data  = json.loads(raw)
        rules = data.get("grammar_rules", [])
        cost  = (response.usage.input_tokens * 0.000003 +
                 response.usage.output_tokens * 0.000015)
        print(f"   {len(rules)} rules extracted | EUR {cost:.3f}")
        return rules
    except Exception as e:
        print(f"   Parse error: {e}")
        return []


def enrich_rules_with_web(rules: list) -> list:
    to_research  = [r for r in rules if not r.get("full_rule")]
    already_done = [r for r in rules if r.get("full_rule")]

    if not to_research:
        print("   All rules already complete")
        return rules

    print(f"Web search for {len(to_research)} rules...")
    enriched_all = []
    batch_size   = 3

    for i in range(0, len(to_research), batch_size):
        batch = to_research[i:i+batch_size]
        print(f"   Batch {i//batch_size+1}: {[r['rule'] for r in batch]}")

        _web_system = (
            "You are a German grammar expert with web search access. All output in English.\n"
            "Search: dartmouth.edu/~deutsch, germanveryeasy.com, duden.de\n"
            "For each rule: complete forms/declension tables, Italian-speaker mistakes with examples, 4 example sentences, exceptions.\n"
            'Return ONLY valid JSON, no backticks: {"grammar_rules":[{"rule":"<exact name>","explanation_en":"<str>","full_rule":"<complete with tables>","common_mistakes":"<Italian examples>","examples":["<str>","<str>","<str>","<str>"],"exceptions":"<str>","source_verified":true}]}'
        )

        try:
            response = client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=8000,
                system=_web_system,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                messages=[{"role": "user", "content": f"Rules:\n{json.dumps(batch, ensure_ascii=False, indent=2)}"}]
            )

            raw = ""
            for block in response.content:
                if hasattr(block, "type") and block.type == "text" and block.text.strip():
                    raw = block.text

            cost = (response.usage.input_tokens * 0.000003 +
                    response.usage.output_tokens * 0.000015)
            print(f"   EUR {cost:.3f}")

            clean = raw.strip()
            if clean.startswith("```"):
                clean = "\n".join(clean.split("\n")[1:-1]).strip()
            start = clean.find("{")
            end   = clean.rfind("}") + 1
            if start >= 0 and end > start:
                clean = clean[start:end]

            data           = json.loads(clean)
            batch_enriched = data.get("grammar_rules", [])
            enriched_all.extend(batch_enriched)
            print(f"   {len(batch_enriched)} rules enriched")

        except Exception as e:
            print(f"   Batch error: {e} -- using base rules")
            enriched_all.extend(batch)

    return already_done + enriched_all


# ─── DOC TEMPLATE WITH TOC SUPPORT ───────────────────────────────────────────
class GrammarBookTemplate(BaseDocTemplate):
    """Custom template that supports TOC with page numbers."""

    def __init__(self, filename, **kwargs):
        super().__init__(filename, **kwargs)
        frame = Frame(
            self.leftMargin, self.bottomMargin,
            self.width, self.height,
            id="normal"
        )
        template = PageTemplate(id="Later", frames=frame,
                                onPage=self._add_footer)
        self.addPageTemplates([template])

    def afterFlowable(self, flowable):
        """Notify TOC when a heading is encountered."""
        if isinstance(flowable, Paragraph):
            style = flowable.style.name
            if style == "TOCChapter":
                text = flowable.getPlainText()
                self.notify("TOCEntry", (0, text, self.page, None))
            elif style == "TOCRule":
                text = flowable.getPlainText()
                self.notify("TOCEntry", (1, text, self.page, None))

    @staticmethod
    def _add_footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#90a4ae"))
        canvas.drawString(
            2*cm, 1.1*cm,
            f"DeutschOps Grammar Book  |  Kevin Vecchi  |  "
            f"Generated {datetime.now().strftime('%d %b %Y')}"
        )
        canvas.drawRightString(A4[0]-2*cm, 1.1*cm, f"Page {doc.page}")
        canvas.setStrokeColor(colors.HexColor("#b0bec5"))
        canvas.setLineWidth(0.5)
        canvas.line(2*cm, 1.5*cm, A4[0]-2*cm, 1.5*cm)
        canvas.restoreState()


def heading_with_bookmark(text: str, style_name: str,
                           bookmark: str, styles: dict) -> Paragraph:
    """Create a paragraph that registers with TOC via style name."""
    return Paragraph(text, styles[style_name])


# ─── COVER ────────────────────────────────────────────────────────────────────
def make_cover(styles: dict, rule_count: int, cat_count: int,
               date_str: str) -> list:
    elements = []
    elements.append(Spacer(1, 3*cm))
    elements.append(Paragraph(
        "DeutschOps",
        styles["cover_title"]
    ))
    elements.append(Spacer(1, 0.3*cm))
    elements.append(Paragraph(
        "German Grammar Reference Book",
        styles["cover_sub"]
    ))
    elements.append(Paragraph(
        "Kevin Vecchi  ·  A2 → B2  ·  Basel Pharma Track",
        styles["cover_sub"]
    ))
    elements.append(Spacer(1, 1.5*cm))

    stats = Table([[
        Paragraph(
            f"{rule_count} grammar rules<br/>"
            f"<font size='12'>{cat_count} categories</font>",
            styles["cover_stat"]
        )
    ]], colWidths=[W])
    stats.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#1a3a5c")),
        ("TOPPADDING", (0,0), (-1,-1), 20),
        ("BOTTOMPADDING", (0,0), (-1,-1), 20),
        ("ALIGN", (0,0), (-1,-1), "CENTER"),
    ]))
    elements.append(stats)
    elements.append(Spacer(1, 0.8*cm))
    elements.append(Paragraph(f"Last updated: {date_str}", styles["cover_sub"]))
    elements.append(Paragraph(
        "Auto-generated by DeutschOps pipeline + web-verified sources",
        S("CS2", fontName="Helvetica-Oblique", fontSize=9,
          textColor=colors.HexColor("#607d8b"), alignment=TA_CENTER)
    ))
    elements.append(PageBreak())
    return elements


# ─── HOW TO USE ───────────────────────────────────────────────────────────────
def make_how_to_use(styles: dict) -> list:
    elements = []
    elements.append(Paragraph("How to Use This Book", styles["toc_title"]))
    elements.append(hr(thickness=2))
    elements.append(Paragraph(
        "This grammar reference is automatically generated from your DeutschOps "
        "lessons with Stefanie, enriched with web-verified rules from authoritative "
        "German grammar sources (Duden, Dartmouth, GermanVeryEasy). "
        "It updates automatically after every lesson you process.",
        styles["how_to"]
    ))
    elements.append(Spacer(1, 10))

    guide = [
        ("Complete Rule",    "Full grammar with conjugation/declension tables",   C_BLUE),
        ("Examples",         "Sentences from your actual lessons + verified sources", C_TEAL),
        ("Common Mistakes",  "Errors Italian speakers typically make — read carefully", C_RED),
        ("Exceptions",       "Special cases and irregular patterns to memorize",  C_ORANGE),
        ("Source verified",  "Rule confirmed with authoritative web sources",      C_GREEN),
        ("From lesson only", "Rule extracted from transcript, not yet web-verified", C_GRAY),
    ]
    for label, desc, color in guide:
        t = Table([[
            Paragraph(f"<b>{label}</b>",
                      S(f"GL{label[:3]}", fontName="Helvetica-Bold", fontSize=10,
                        textColor=C_WHITE)),
            Paragraph(desc, styles["how_to"])
        ]], colWidths=[3.5*cm, W-3.5*cm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (0,-1), color),
            ("LEFTPADDING", (0,0), (-1,-1), 8),
            ("TOPPADDING", (0,0), (-1,-1), 5),
            ("BOTTOMPADDING", (0,0), (-1,-1), 5),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ("GRID", (0,0), (-1,-1), 0.3, colors.HexColor("#b0bec5")),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 3))

    elements.append(PageBreak())
    return elements


# ─── TOC ──────────────────────────────────────────────────────────────────────
def make_toc(styles: dict) -> list:
    elements = []
    elements.append(Paragraph("Table of Contents", styles["toc_title"]))
    elements.append(hr(thickness=2))
    elements.append(Spacer(1, 8))

    toc = TableOfContents()
    toc.levelStyles = [
        S("TOCL0", fontName="Helvetica-Bold", fontSize=11,
          textColor=C_BLUE, leftIndent=0, spaceAfter=4,
          spaceBefore=6),
        S("TOCL1", fontName="Helvetica", fontSize=9.5,
          textColor=C_GRAY, leftIndent=20, spaceAfter=2),
    ]
    toc.dotsMinLevel = 0
    elements.append(toc)
    elements.append(PageBreak())
    return elements


# ─── CHAPTER HEADER ───────────────────────────────────────────────────────────
def make_chapter_header(category: str, rule_count: int,
                         bookmark: str, styles: dict) -> list:
    elements = []

    hdr_para = Paragraph(category, styles["TOCChapter"])

    t = Table([[
        hdr_para,
        Paragraph(
            f"<font color='#90caf9'>{rule_count} rules</font>",
            S("RC", fontName="Helvetica", fontSize=11,
              textColor=colors.HexColor("#90caf9"), alignment=TA_CENTER)
        )
    ]], colWidths=[W*0.82, W*0.18])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), C_NAVY),
        ("LEFTPADDING", (0,0), (0,-1), 16),
        ("RIGHTPADDING", (-1,0), (-1,-1), 16),
        ("TOPPADDING", (0,0), (-1,-1), 14),
        ("BOTTOMPADDING", (0,0), (-1,-1), 14),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 14))
    return elements


# ─── RULE BLOCK ───────────────────────────────────────────────────────────────
def make_rule_block(rule: dict, styles: dict) -> list:
    elements = []

    elements.append(hr(color=C_TEAL, thickness=1.5, space_before=14, space_after=4))

    # Rule title — TOCRule style triggers TOC entry at level 1
    elements.append(Paragraph(rule.get("rule", ""), styles["TOCRule"]))

    # Verified badge inline
    verified    = "✅ Web verified" if rule.get("source_verified") else "📝 From lesson"
    v_color     = C_GREEN if rule.get("source_verified") else C_GRAY
    badge = Table([[
        Paragraph(verified,
                  S("VB", fontName="Helvetica", fontSize=8, textColor=C_WHITE))
    ]], colWidths=[3.5*cm])
    badge.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), v_color),
        ("LEFTPADDING", (0,0), (-1,-1), 8),
        ("TOPPADDING", (0,0), (-1,-1), 3),
        ("BOTTOMPADDING", (0,0), (-1,-1), 3),
    ]))
    elements.append(badge)
    elements.append(Spacer(1, 6))

    # Base explanation
    if rule.get("explanation_en"):
        elements.append(Paragraph(rule["explanation_en"], styles["body"]))
        elements.append(Spacer(1, 6))

    # Complete rule
    if rule.get("full_rule"):
        elements += banner("COMPLETE RULE", C_BLUE, styles["section_hdr"])
        for line in rule["full_rule"].split("\n"):
            line = line.strip()
            if not line:
                elements.append(Spacer(1, 4))
                continue
            if (line.isupper() and len(line) > 3) or \
               (len(line) < 70 and line.endswith(":")):
                elements.append(Paragraph(
                    f"<b>{line}</b>",
                    S("FR_HDR", fontName="Helvetica-Bold", fontSize=10,
                      textColor=C_BLUE, spaceBefore=8, spaceAfter=2)
                ))
            elif "\t" in line or "|" in line:
                elements.append(Paragraph(line, styles["code"]))
            elif line.startswith("-") or line.startswith("•") or \
                 (len(line) > 1 and line[0].isdigit() and line[1] in ".):"):
                elements.append(Paragraph(f"  {line}", styles["italic"]))
            else:
                elements.append(Paragraph(line, styles["italic"]))
        elements.append(Spacer(1, 10))

    # Examples
    examples = rule.get("examples", [])
    if examples:
        elements += banner("EXAMPLES", C_TEAL, styles["section_hdr"])
        for ex in examples:
            sep = " — " if " — " in ex else " - " if " - " in ex else None
            if sep and ("I " in ex or "He " in ex or "She " in ex or
                        "We " in ex or "You " in ex):
                parts = ex.split(sep, 1)
                elements.append(Paragraph(
                    f"→  <b>{parts[0].strip()}</b>", styles["example"]
                ))
                elements.append(Paragraph(
                    f"    <i>{parts[1].strip()}</i>",
                    S("ExTr", fontName="Helvetica-Oblique", fontSize=9.5,
                      textColor=C_GRAY, leftIndent=28, spaceAfter=5)
                ))
            else:
                elements.append(Paragraph(f"→  {ex}", styles["example"]))
        elements.append(Spacer(1, 10))

    # Common mistakes
    if rule.get("common_mistakes"):
        elements += banner(
            "COMMON MISTAKES — Italian Speakers", C_RED, styles["section_hdr"]
        )
        for line in rule["common_mistakes"].split("\n"):
            line = line.strip()
            if not line:
                elements.append(Spacer(1, 3))
                continue
            if line.startswith("*") and line.endswith("*"):
                elements.append(Paragraph(
                    f"❌  {line.strip('*')}",
                    S("WR", fontName="Helvetica-Oblique", fontSize=10,
                      textColor=C_RED, leftIndent=16, spaceAfter=2)
                ))
            elif ("instead of" in line.lower() or "correct:" in line.lower()
                  or line.startswith("✓") or "✅" in line):
                elements.append(Paragraph(
                    f"✅  {line}",
                    S("CR2", fontName="Helvetica", fontSize=10,
                      textColor=C_GREEN, leftIndent=16, spaceAfter=4)
                ))
            elif len(line) > 1 and line[0].isdigit() and line[1] in ".):":
                elements.append(Paragraph(
                    f"<b>{line}</b>",
                    S("MN", fontName="Helvetica-Bold", fontSize=10,
                      textColor=C_RED, spaceBefore=6, spaceAfter=2)
                ))
            else:
                elements.append(Paragraph(line, styles["mistake"]))
        elements.append(Spacer(1, 10))

    # Exceptions
    if rule.get("exceptions"):
        elements += banner(
            "EXCEPTIONS & SPECIAL CASES", C_YELLOW_B, styles["section_hdr"]
        )
        for line in rule["exceptions"].split("\n"):
            line = line.strip()
            if not line:
                elements.append(Spacer(1, 3))
                continue
            if len(line) > 1 and line[0].isdigit() and line[1] in ".):":
                elements.append(Paragraph(
                    f"<b>{line}</b>",
                    S("EN", fontName="Helvetica-Bold", fontSize=10,
                      textColor=C_ORANGE, spaceBefore=6, spaceAfter=2)
                ))
            else:
                elements.append(Paragraph(line, styles["exception"]))
        elements.append(Spacer(1, 16))

    return elements

def S(name, **kw):
    return ParagraphStyle(name, **kw)

def hr(color=C_BLUE, thickness=1.0, space_before=2, space_after=8):
    return HRFlowable(width="100%", thickness=thickness, color=color,
                      spaceAfter=space_after, spaceBefore=space_before)


def banner(text: str, color, style) -> list:
    t = Table([[Paragraph(text, style)]], colWidths=[W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), color),
        ("LEFTPADDING", (0,0), (-1,-1), 10),
        ("TOPPADDING", (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
    ]))
    return [t, Spacer(1, 5)]

def build_styles():
    return {
        "cover_title": S("CoverTitle", fontName="Helvetica-Bold", fontSize=36,
                         textColor=C_WHITE, alignment=TA_CENTER, leading=42),
        "cover_sub":   S("CoverSub", fontName="Helvetica", fontSize=13,
                         textColor=colors.HexColor("#90caf9"),
                         alignment=TA_CENTER, spaceAfter=4),
        "cover_stat":  S("CoverStat", fontName="Helvetica-Bold", fontSize=22,
                         textColor=C_YELLOW_B, alignment=TA_CENTER),
        "toc_title":   S("TOCTitle", fontName="Helvetica-Bold", fontSize=18,
                         textColor=C_NAVY, spaceBefore=0, spaceAfter=12),
        "toc_1":       S("TOC1", fontName="Helvetica-Bold", fontSize=11,
                         textColor=C_BLUE, leftIndent=0, spaceAfter=3),
        "toc_2":       S("TOC2", fontName="Helvetica", fontSize=9.5,
                         textColor=C_GRAY, leftIndent=16, spaceAfter=2),
        "TOCChapter":  S("TOCChapter", fontName="Helvetica-Bold", fontSize=16,
                         textColor=C_WHITE),
        "TOCRule":     S("TOCRule", fontName="Helvetica-Bold", fontSize=13,
                         textColor=C_NAVY, spaceBefore=18, spaceAfter=6),
        "body":        S("Body", fontName="Helvetica", fontSize=10,
                         textColor=colors.HexColor("#212121"), leading=15,
                         alignment=TA_JUSTIFY, spaceAfter=5),
        "body_b":      S("BodyB", fontName="Helvetica-Bold", fontSize=10,
                         textColor=C_NAVY, spaceAfter=4),
        "italic":      S("Italic", fontName="Helvetica-Oblique", fontSize=10,
                         textColor=C_GRAY, leading=15, spaceAfter=3),
        "code":        S("Code", fontName="Courier", fontSize=9,
                         textColor=C_NAVY, leading=13, leftIndent=8, spaceAfter=2),
        "example":     S("Example", fontName="Helvetica-Oblique", fontSize=10,
                         textColor=C_TEAL, leftIndent=16, spaceAfter=4, leading=15),
        "mistake":     S("Mistake", fontName="Helvetica", fontSize=10,
                         textColor=C_RED, leftIndent=16, spaceAfter=3, leading=15),
        "exception":   S("Exception", fontName="Helvetica", fontSize=10,
                         textColor=C_ORANGE, leftIndent=16, spaceAfter=3,
                         leading=15),
        "section_hdr": S("SectionHdr", fontName="Helvetica-Bold", fontSize=10.5,
                         textColor=C_WHITE),
        "how_to":      S("HowTo", fontName="Helvetica", fontSize=10,
                         textColor=colors.HexColor("#212121"), leading=15,
                         spaceAfter=4),
    }

# ─── MAIN BUILD ───────────────────────────────────────────────────────────────
def build_grammar_book(use_doc: bool = True, enrich_web: bool = True):
    print(f"\n{'='*55}")
    print(f"  DeutschOps — Grammar Book Builder")
    print(f"{'='*55}\n")

    db       = load_grammar_db()
    rules_db = db.get("rules", {})

    # 1. Rules from lessons
    print("Loading rules from lessons...")
    lesson_rules = collect_rules_from_lessons()
    print(f"   {len(lesson_rules)} rules found in lessons")
    for key, rule in lesson_rules.items():
        if key not in rules_db or (
            rule.get("full_rule") and not rules_db[key].get("full_rule")
        ):
            rules_db[key] = rule

    # 2. Rules from Google Doc
    if use_doc:
        try:
            print("Reading Google Doc...")
            # Era `from doc_reader import get_drive_service, read_doc` seguito
            # da `read_doc(service)`. Ma doc_reader.read_doc non accetta
            # argomenti: questo ramo sollevava TypeError da sempre — non si
            # vedeva perche' la pipeline chiama solo use_doc=False.
            from do.lezione.doc import leggi as read_doc
            doc_text  = read_doc()
            doc_rules = collect_rules_from_doc(doc_text)
            new_from_doc = 0
            for rule in doc_rules:
                key = rule.get("rule", "").strip()
                if key and key not in rules_db:
                    rules_db[key] = rule
                    new_from_doc += 1
            print(f"   {new_from_doc} new rules from Google Doc")
        except Exception as e:
            print(f"   Google Doc not accessible: {e}")

    # 3. Web search for incomplete rules
    if enrich_web:
        all_rules  = list(rules_db.values())
        incomplete = [r for r in all_rules if not r.get("full_rule")]
        print(f"{len(incomplete)}/{len(all_rules)} rules to enrich...")
        if incomplete:
            enriched = enrich_rules_with_web(incomplete)
            for rule in enriched:
                key = rule.get("rule", "").strip()
                if key:
                    rules_db[key] = rule

    db["rules"] = rules_db
    save_grammar_db(db)
    print(f"\nGrammar DB: {len(rules_db)} rules total")

    # 4. Deduplicate and organize by category
    categories: dict = {cat: [] for cat in CATEGORY_ORDER}
    seen_keys = set()

    for rule in rules_db.values():
        key = rule.get("rule", "").strip().lower()
        if key in seen_keys:
            continue
        seen_keys.add(key)
        cat = assign_category(
            rule.get("rule", ""),
            rule.get("explanation_en", "")
        )
        categories[cat].append(rule)

    for cat in categories:
        categories[cat].sort(
            key=lambda r: (r.get("book_order") or 9999,
                           r.get("rule", "").lower())
        )

    total_rules = sum(len(v) for v in categories.values())
    active_cats = sum(1 for v in categories.values() if v)

    print("Distribution:")
    for cat in CATEGORY_ORDER:
        if categories[cat]:
            print(f"   {cat}: {len(categories[cat])} rules")

    # 5. Generate PDF
    print(f"\nGenerating PDF ({total_rules} rules, {active_cats} categories)...")
    styles   = build_styles()
    date_str = datetime.now().strftime("%d %b %Y")

    doc = GrammarBookTemplate(
        str(OUTPUT_PDF),
        pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm, bottomMargin=2.5*cm,
        title="DeutschOps Grammar Book",
        author="Kevin Vecchi",
        allowSplitting=1
    )

    story = []

    # Cover
    story += make_cover(styles, total_rules, active_cats, date_str)

    # How to use
    story += make_how_to_use(styles)

    # TOC (populated on second pass by multiBuild)
    story += make_toc(styles)

    # Chapters
    for cat in CATEGORY_ORDER:
        rules = categories[cat]
        if not rules:
            continue

        # Chapter header — TOCChapter style triggers TOC entry
        t = Table([[
            Paragraph(cat, styles["TOCChapter"]),
            Paragraph(
                f"<font color='#90caf9'>{len(rules)} rules</font>",
                S("RC", fontName="Helvetica", fontSize=11,
                  textColor=colors.HexColor("#90caf9"),
                  alignment=TA_CENTER)
            )
        ]], colWidths=[W*0.82, W*0.18])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,-1), C_NAVY),
            ("LEFTPADDING", (0,0), (0,-1), 16),
            ("RIGHTPADDING", (-1,0), (-1,-1), 16),
            ("TOPPADDING", (0,0), (-1,-1), 14),
            ("BOTTOMPADDING", (0,0), (-1,-1), 14),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ]))
        story.append(t)
        story.append(Spacer(1, 14))

        for rule in rules:
            story += make_rule_block(rule, styles)

        story.append(PageBreak())

    # Build twice for TOC page numbers
    doc.multiBuild(story)

    size_kb = OUTPUT_PDF.stat().st_size // 1024
    print(f"PDF generated: {OUTPUT_PDF} ({total_rules} rules · {size_kb}KB)")
    return str(OUTPUT_PDF)


def update_from_lesson(lesson_json_path: str):
    """Called from main.py after each lesson."""
    try:
        data        = json.loads(Path(lesson_json_path).read_text(encoding="utf-8"))
        new_grammar = data.get("grammar_points", [])
        if not new_grammar:
            return

        db       = load_grammar_db()
        rules_db = db.get("rules", {})
        new_count = 0

        for gp in new_grammar:
            key = gp.get("rule","").strip()
            if not key:
                continue
            if key not in rules_db:
                rules_db[key] = gp
                new_count += 1
            elif gp.get("full_rule") and not rules_db[key].get("full_rule"):
                rules_db[key] = gp
                new_count += 1

        if new_count > 0:
            db["rules"] = rules_db
            save_grammar_db(db)
            print(f"Grammar Book: {new_count} new rules -- regenerating PDF...")
            build_grammar_book(use_doc=False, enrich_web=False)
        else:
            print("Grammar Book: no new rules")

    except Exception as e:
        print(f"Grammar book update error: {e}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--quick":
        build_grammar_book(use_doc=False, enrich_web=False)
    else:
        build_grammar_book(use_doc=True, enrich_web=True)