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

load_dotenv()
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

OUTPUT_PDF = Path("DeutschOps_Grammar_Book.pdf")
GRAMMAR_DB = Path("data/grammar_db.json")

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

CATEGORY_ORDER = [
    "Verben — Basics",
    "Verben — Separable & Modal",
    "Verben — Irregular & Tenses",
    "Satzstruktur — Word Order",
    "Nebensätze — Subordinate Clauses",
    "Kasus — Cases",
    "Pronomen — Pronouns",
    "Adjektive & Adverbien",
    "Präpositionen",
    "Andere Strukturen",
]

CATEGORY_MAP = [
    (["separable", "trennbar", "prefix"], "Verben — Separable & Modal"),
    (["modal", "können", "müssen", "dürfen", "wollen", "sollen", "mögen"], "Verben — Separable & Modal"),
    (["irregular", "unregelmäßig", "vowel change", "umlaut", "strong verb"], "Verben — Irregular & Tenses"),
    (["perfekt", "präteritum", "futur", "konjunktiv", "passive", "tense", "partizip"], "Verben — Irregular & Tenses"),
    (["verb", "conjugat", "konjugat", "infinitiv"], "Verben — Basics"),
    (["nebensatz", "subordinate", "conjunction", "weil", "dass", "wenn", "ob", "als", "obwohl", "damit"], "Nebensätze — Subordinate Clauses"),
    (["word order", "wortstellung", "position", "v2", "verb second", "satzstellung"], "Satzstruktur — Word Order"),
    (["akkusativ", "dativ", "genitiv", "nominativ", "case", "kasus", "declension", "deklination"], "Kasus — Cases"),
    (["pronoun", "pronomen", "reflexive", "personal", "possessiv", "relative", "demonstrativ"], "Pronomen — Pronouns"),
    (["adjektiv", "adjective", "adverb", "komparativ", "superlativ", "comparative", "superlative"], "Adjektive & Adverbien"),
    (["präposition", "preposition"], "Präpositionen"),
]


def assign_category(rule: str, explanation: str) -> str:
    text = (rule + " " + explanation).lower()
    for keywords, category in CATEGORY_MAP:
        if any(kw in text for kw in keywords):
            return category
    return "Andere Strukturen"


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
            print(f"⚠️  {f.name}: {e}")
    return rules


def collect_rules_from_doc(doc_text: str) -> list:
    print("🧠 Estrazione regole dal Google Doc...")
    prompt = f"""You are an expert German grammar tutor.
Analyze this Google Doc and extract ALL grammar rules mentioned.
For each rule extract name, brief explanation, and examples.

Return ONLY valid JSON, zero backtick:
{{
  "grammar_rules": [
    {{
      "rule": "rule name",
      "explanation_en": "explanation in English",
      "examples": ["example 1", "example 2"],
      "full_rule": "",
      "common_mistakes": "",
      "exceptions": "",
      "source_verified": false
    }}
  ]
}}

GOOGLE DOC CONTENT:
{doc_text[:40000]}"""

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:-1]).strip()
    start = raw.find("{")
    end   = raw.rfind("}") + 1
    if start >= 0 and end > start:
        raw = raw[start:end]

    try:
        data = json.loads(raw)
        rules = data.get("grammar_rules", [])
        cost = (response.usage.input_tokens * 0.000003 +
                response.usage.output_tokens * 0.000015)
        print(f"   ✅ {len(rules)} regole estratte | €{cost:.3f}")
        return rules
    except Exception as e:
        print(f"   ⚠️  Parse error: {e}")
        return []


def enrich_rules_with_web(rules: list) -> list:
    to_research  = [r for r in rules if not r.get("full_rule")]
    already_done = [r for r in rules if r.get("full_rule")]

    if not to_research:
        print("   ✅ All rules already complete")
        return rules

    print(f"🌐 Web search per {len(to_research)} regole...")
    enriched_all = []
    batch_size   = 3

    for i in range(0, len(to_research), batch_size):
        batch = to_research[i:i+batch_size]
        print(f"   Batch {i//batch_size+1}: {[r['rule'] for r in batch]}")

        prompt = f"""You are an expert German grammar tutor with web search access.
Research these German grammar rules thoroughly.
Search on: dartmouth.edu/~deutsch, germanveryeasy.com, duden.de

For each rule provide:
1. Complete rule with ALL forms, conjugation/declension tables
2. Common mistakes Italian speakers make with specific examples
3. 4 varied example sentences in different contexts
4. Exceptions and special cases

Rules to research:
{json.dumps(batch, ensure_ascii=False, indent=2)}

Return ONLY valid JSON, zero backtick:
{{
  "grammar_rules": [
    {{
      "rule": "exact rule name",
      "explanation_en": "complete clear explanation",
      "full_rule": "complete rule with all forms and tables",
      "common_mistakes": "Italian speaker mistakes with examples",
      "examples": ["example 1", "example 2", "example 3", "example 4"],
      "exceptions": "exceptions and special cases",
      "source_verified": true
    }}
  ]
}}"""

        try:
            response = client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=8000,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                messages=[{"role": "user", "content": prompt}]
            )

            raw = ""
            for block in response.content:
                if hasattr(block, "type") and block.type == "text" and block.text.strip():
                    raw = block.text

            cost = (response.usage.input_tokens * 0.000003 +
                    response.usage.output_tokens * 0.000015)
            print(f"   💶 €{cost:.3f}")

            clean = raw.strip()
            if clean.startswith("```"):
                clean = "\n".join(clean.split("\n")[1:-1]).strip()
            start = clean.find("{")
            end   = clean.rfind("}") + 1
            if start >= 0 and end > start:
                clean = clean[start:end]

            data = json.loads(clean)
            batch_enriched = data.get("grammar_rules", [])
            enriched_all.extend(batch_enriched)
            print(f"   ✅ {len(batch_enriched)} regole arricchite")

        except Exception as e:
            print(f"   ⚠️  Batch error: {e} — using base rules")
            enriched_all.extend(batch)

    return already_done + enriched_all


# ─── PDF STYLES ───────────────────────────────────────────────────────────────
def S(name, **kw):
    return ParagraphStyle(name, **kw)


def build_styles():
    return {
        "cover_title": S("CT", fontName="Helvetica-Bold", fontSize=36,
                         textColor=C_WHITE, alignment=TA_CENTER, leading=42),
        "cover_sub":   S("CS", fontName="Helvetica", fontSize=13,
                         textColor=colors.HexColor("#90caf9"), alignment=TA_CENTER),
        "cover_stat":  S("CST", fontName="Helvetica-Bold", fontSize=20,
                         textColor=colors.HexColor("#f9a825"), alignment=TA_CENTER),
        "toc_cat":     S("TC", fontName="Helvetica-Bold", fontSize=12,
                         textColor=C_BLUE, spaceBefore=10, spaceAfter=3),
        "toc_rule":    S("TR", fontName="Helvetica", fontSize=9.5,
                         textColor=C_GRAY, leftIndent=20, spaceAfter=2),
        "chapter_hdr": S("CH", fontName="Helvetica-Bold", fontSize=18,
                         textColor=C_WHITE),
        "rule_title":  S("RT", fontName="Helvetica-Bold", fontSize=14,
                         textColor=C_NAVY, spaceBefore=20, spaceAfter=6),
        "section_hdr": S("SH", fontName="Helvetica-Bold", fontSize=10,
                         textColor=C_WHITE),
        "body":        S("BD", fontName="Helvetica", fontSize=10,
                         textColor=colors.HexColor("#212121"), leading=16,
                         alignment=TA_JUSTIFY, spaceAfter=6),
        "body_b":      S("BDB", fontName="Helvetica-Bold", fontSize=10,
                         textColor=C_NAVY, spaceAfter=4),
        "italic":      S("IT", fontName="Helvetica-Oblique", fontSize=10,
                         textColor=C_GRAY, leading=15, spaceAfter=3),
        "code":        S("CD", fontName="Courier", fontSize=9.5,
                         textColor=C_NAVY, leading=14, leftIndent=8,
                         spaceAfter=2),
        "example":     S("EX", fontName="Helvetica-Oblique", fontSize=10,
                         textColor=C_TEAL, leftIndent=16, spaceAfter=4,
                         leading=15),
        "mistake":     S("MK", fontName="Helvetica", fontSize=10,
                         textColor=C_RED, leftIndent=16, spaceAfter=3,
                         leading=15),
        "exception":   S("EXC", fontName="Helvetica", fontSize=10,
                         textColor=C_ORANGE, leftIndent=16, spaceAfter=3,
                         leading=15),
        "small":       S("SM", fontName="Helvetica", fontSize=8,
                         textColor=C_GRAY),
    }


def hr(color=C_BLUE, thickness=1.0, space_before=2, space_after=8):
    return HRFlowable(width="100%", thickness=thickness, color=color,
                      spaceAfter=space_after, spaceBefore=space_before)


def section_banner(text: str, color, styles: dict) -> list:
    """Banner colorato per sezioni (Full Rule, Common Mistakes, ecc.)"""
    t = Table([[Paragraph(text, styles["section_hdr"])]], colWidths=[W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), color),
        ("LEFTPADDING", (0,0), (-1,-1), 10),
        ("TOPPADDING", (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
    ]))
    return [t, Spacer(1, 4)]


def render_multiline(text: str, style, prefix: str = "") -> list:
    """
    Renderizza testo multiriga riga per riga come paragrafi separati.
    Ogni paragrafo può andare su pagine diverse — nessun limite di altezza.
    """
    elements = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            elements.append(Spacer(1, 4))
            continue
        if prefix:
            elements.append(Paragraph(f"{prefix} {line}", style))
        else:
            elements.append(Paragraph(line, style))
    return elements


# ─── COVER ────────────────────────────────────────────────────────────────────
def make_cover(styles: dict, rule_count: int, date_str: str) -> list:
    elements = []
    elements.append(Spacer(1, 3*cm))
    elements.append(Paragraph("🇩🇪", S("EM", fontSize=60, alignment=TA_CENTER)))
    elements.append(Spacer(1, 0.5*cm))
    elements.append(Paragraph("DeutschOps", styles["cover_title"]))
    elements.append(Spacer(1, 0.3*cm))
    elements.append(Paragraph("German Grammar Reference Book", styles["cover_sub"]))
    elements.append(Spacer(1, 0.2*cm))
    elements.append(Paragraph("Kevin Vecchi · A2→B2 · Basel Pharma Track",
                               styles["cover_sub"]))
    elements.append(Spacer(1, 1.5*cm))

    # Stats box
    stats = Table([[
        Paragraph(f"{rule_count}\ngrammar rules", styles["cover_stat"]),
    ]], colWidths=[W])
    stats.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#1a3a5c")),
        ("TOPPADDING", (0,0), (-1,-1), 20),
        ("BOTTOMPADDING", (0,0), (-1,-1), 20),
    ]))
    elements.append(stats)
    elements.append(Spacer(1, 0.5*cm))
    elements.append(Paragraph(f"Last updated: {date_str}", styles["cover_sub"]))
    elements.append(PageBreak())
    return elements


# ─── HOW TO USE ───────────────────────────────────────────────────────────────
def make_how_to_use(styles: dict) -> list:
    elements = []
    elements.append(Paragraph("How to Use This Book", styles["rule_title"]))
    elements.append(hr())
    elements.append(Paragraph(
        "This grammar reference is automatically generated from your DeutschOps "
        "lessons with Stefanie and enriched with web-verified rules from authoritative "
        "German grammar sources. It grows automatically with every lesson you process.",
        styles["body"]
    ))
    elements.append(Spacer(1, 12))

    guide = [
        ("📘 Complete Rule", "Full grammar explanation with conjugation/declension tables"),
        ("✏️ Examples", "Sentences from your actual lessons and web-verified sources"),
        ("⚠️ Common Mistakes", "Errors Italian speakers typically make — read carefully"),
        ("🔸 Exceptions", "Special cases and irregular patterns to memorize"),
        ("✅ Source verified", "Rule confirmed with authoritative web sources"),
        ("📝 From lesson", "Rule extracted from lesson transcript only"),
    ]
    for label, desc in guide:
        elements.append(Paragraph(f"<b>{label}:</b>  {desc}", styles["body"]))

    elements.append(PageBreak())
    return elements


# ─── TABLE OF CONTENTS ────────────────────────────────────────────────────────
def make_toc(categories: dict, styles: dict) -> list:
    elements = []
    elements.append(Paragraph("Table of Contents", styles["rule_title"]))
    elements.append(hr())
    elements.append(Spacer(1, 8))

    for cat in CATEGORY_ORDER:
        rules = categories.get(cat, [])
        if not rules:
            continue
        elements.append(Paragraph(
            f"📗  {cat}  <font color='#90a4ae'>({len(rules)} rules)</font>",
            styles["toc_cat"]
        ))
        for rule in rules:
            verified = "✅" if rule.get("source_verified") else "📝"
            elements.append(Paragraph(
                f"{verified}  {rule['rule']}", styles["toc_rule"]
            ))

    elements.append(PageBreak())
    return elements


# ─── CHAPTER HEADER ───────────────────────────────────────────────────────────
def make_chapter_header(category: str, rule_count: int,
                         styles: dict) -> list:
    elements = []
    t = Table([[
        Paragraph(f"📗  {category}", styles["chapter_hdr"]),
        Paragraph(
            f"<font color='#90caf9'>{rule_count} rules</font>",
            S("CR", fontName="Helvetica", fontSize=11,
              textColor=colors.HexColor("#90caf9"),
              alignment=TA_CENTER)
        )
    ]], colWidths=[W*0.8, W*0.2])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), C_NAVY),
        ("LEFTPADDING", (0,0), (0,-1), 16),
        ("RIGHTPADDING", (-1,0), (-1,-1), 16),
        ("TOPPADDING", (0,0), (-1,-1), 14),
        ("BOTTOMPADDING", (0,0), (-1,-1), 14),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 16))
    return elements


# ─── RULE BLOCK ───────────────────────────────────────────────────────────────
def make_rule_block(rule: dict, styles: dict) -> list:
    """
    Ogni sezione della regola è una serie di paragrafi separati.
    Nessuna table di grandi dimensioni — tutto scorre liberamente su più pagine.
    """
    elements = []
    verified = "✅" if rule.get("source_verified") else "📝"

    # Titolo regola
    elements.append(hr(color=C_TEAL, thickness=2, space_before=16, space_after=4))
    elements.append(Paragraph(
        f"{verified}  {rule.get('rule','')}",
        styles["rule_title"]
    ))

    # Spiegazione base
    if rule.get("explanation_en"):
        elements.append(Paragraph(rule["explanation_en"], styles["body"]))
        elements.append(Spacer(1, 6))

    # ── Full Rule ────────────────────────────────────────────────────────────
    if rule.get("full_rule"):
        elements += section_banner("📘  COMPLETE RULE", C_BLUE, styles)

        for line in rule["full_rule"].split("\n"):
            line = line.strip()
            if not line:
                elements.append(Spacer(1, 4))
                continue
            # Riconosce header di sezione (tutto maiuscolo o finisce con :)
            if (line.isupper() and len(line) > 3) or \
               (len(line) < 70 and line.endswith(":")):
                elements.append(Paragraph(
                    f"<b>{line}</b>",
                    S("SL", fontName="Helvetica-Bold", fontSize=10,
                      textColor=C_BLUE, spaceBefore=8, spaceAfter=2)
                ))
            # Righe che sembrano tabelle (contengono tab o pipe)
            elif "\t" in line or "|" in line:
                elements.append(Paragraph(line, styles["code"]))
            # Bullet points
            elif line.startswith("-") or line.startswith("•") or \
                 (len(line) > 1 and line[0].isdigit() and line[1] in ".):"):
                elements.append(Paragraph(f"  {line}", styles["italic"]))
            else:
                elements.append(Paragraph(line, styles["italic"]))

        elements.append(Spacer(1, 10))

    # ── Examples ─────────────────────────────────────────────────────────────
    examples = rule.get("examples", [])
    if examples:
        elements += section_banner("✏️  EXAMPLES", C_TEAL, styles)
        for ex in examples:
            if " - " in ex or " — " in ex or "(I " in ex or "(He " in ex:
                # Esempio con traduzione — mostra su righe separate
                parts = ex.split(" - ") if " - " in ex else ex.split(" — ")
                if len(parts) >= 2:
                    elements.append(Paragraph(
                        f"→  <b>{parts[0].strip()}</b>",
                        styles["example"]
                    ))
                    elements.append(Paragraph(
                        f"   <i>{' — '.join(parts[1:]).strip()}</i>",
                        S("ET", fontName="Helvetica-Oblique", fontSize=9.5,
                          textColor=C_GRAY, leftIndent=28, spaceAfter=6)
                    ))
                else:
                    elements.append(Paragraph(f"→  {ex}", styles["example"]))
            else:
                elements.append(Paragraph(f"→  {ex}", styles["example"]))
        elements.append(Spacer(1, 10))

    # ── Common Mistakes ───────────────────────────────────────────────────────
    if rule.get("common_mistakes"):
        elements += section_banner("⚠️  COMMON MISTAKES — Italian Speakers",
                                    C_RED, styles)
        for line in rule["common_mistakes"].split("\n"):
            line = line.strip()
            if not line:
                elements.append(Spacer(1, 3))
                continue
            if line.startswith("*") and line.endswith("*"):
                # Esempio sbagliato
                elements.append(Paragraph(
                    f"❌  {line.strip('*')}",
                    S("WR", fontName="Helvetica-Oblique", fontSize=10,
                      textColor=C_RED, leftIndent=16, spaceAfter=2)
                ))
            elif "instead of" in line.lower() or "✓" in line or "correct:" in line.lower():
                elements.append(Paragraph(
                    f"✅  {line}",
                    S("CR2", fontName="Helvetica", fontSize=10,
                      textColor=C_GREEN, leftIndent=16, spaceAfter=4)
                ))
            elif line[0].isdigit() and "." in line[:3]:
                # Punto numerato
                elements.append(Paragraph(
                    f"<b>{line}</b>",
                    S("MN", fontName="Helvetica-Bold", fontSize=10,
                      textColor=C_RED, spaceBefore=6, spaceAfter=2)
                ))
            else:
                elements.append(Paragraph(line, styles["mistake"]))
        elements.append(Spacer(1, 10))

    # ── Exceptions ────────────────────────────────────────────────────────────
    if rule.get("exceptions"):
        elements += section_banner("🔸  EXCEPTIONS & SPECIAL CASES",
                                    C_YELLOW_B, styles)
        for line in rule["exceptions"].split("\n"):
            line = line.strip()
            if not line:
                elements.append(Spacer(1, 3))
                continue
            if line[0].isdigit() and "." in line[:3]:
                elements.append(Paragraph(
                    f"<b>{line}</b>",
                    S("EN", fontName="Helvetica-Bold", fontSize=10,
                      textColor=C_ORANGE, spaceBefore=6, spaceAfter=2)
                ))
            else:
                elements.append(Paragraph(line, styles["exception"]))
        elements.append(Spacer(1, 16))

    return elements


# ─── FOOTER ───────────────────────────────────────────────────────────────────
def add_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#90a4ae"))
    canvas.drawString(2*cm, 1.1*cm,
        f"DeutschOps Grammar Book · Kevin Vecchi · "
        f"Generated {datetime.now().strftime('%d %b %Y')}")
    canvas.drawRightString(A4[0]-2*cm, 1.1*cm, f"Page {doc.page}")
    canvas.setStrokeColor(colors.HexColor("#b0bec5"))
    canvas.setLineWidth(0.5)
    canvas.line(2*cm, 1.5*cm, A4[0]-2*cm, 1.5*cm)
    canvas.restoreState()


# ─── BUILD ────────────────────────────────────────────────────────────────────
def build_grammar_book(use_doc: bool = True, enrich_web: bool = True):
    print(f"\n{'='*55}")
    print(f"  DeutschOps — Grammar Book Builder")
    print(f"{'='*55}\n")

    db       = load_grammar_db()
    rules_db = db.get("rules", {})

    # 1. Regole dalle lezioni
    print("📚 Caricamento regole dalle lezioni...")
    lesson_rules = collect_rules_from_lessons()
    print(f"   {len(lesson_rules)} regole trovate nelle lezioni")
    for key, rule in lesson_rules.items():
        if key not in rules_db or (
            rule.get("full_rule") and not rules_db[key].get("full_rule")
        ):
            rules_db[key] = rule

    # 2. Regole dal Google Doc
    if use_doc:
        try:
            print("📄 Lettura Google Doc...")
            from doc_reader import get_drive_service, read_doc
            service  = get_drive_service()
            doc_text = read_doc(service)
            doc_rules = collect_rules_from_doc(doc_text)
            new_from_doc = 0
            for rule in doc_rules:
                key = rule.get("rule", "").strip()
                if key and key not in rules_db:
                    rules_db[key] = rule
                    new_from_doc += 1
            print(f"   {new_from_doc} nuove regole dal Google Doc")
        except Exception as e:
            print(f"   ⚠️  Google Doc non accessibile: {e}")

    # 3. Web search per regole incomplete
    if enrich_web:
        all_rules  = list(rules_db.values())
        incomplete = [r for r in all_rules if not r.get("full_rule")]
        print(f"🌐 {len(incomplete)}/{len(all_rules)} regole da arricchire...")
        if incomplete:
            enriched = enrich_rules_with_web(incomplete)
            for rule in enriched:
                key = rule.get("rule", "").strip()
                if key:
                    rules_db[key] = rule

    db["rules"] = rules_db
    save_grammar_db(db)
    print(f"\n💾 Grammar DB: {len(rules_db)} regole totali")

    # 4. Organizza per categoria
    categories: dict = {cat: [] for cat in CATEGORY_ORDER}
    for rule in rules_db.values():
        cat = assign_category(
            rule.get("rule", ""),
            rule.get("explanation_en", "")
        )
        categories[cat].append(rule)
    for cat in categories:
        categories[cat].sort(key=lambda r: r.get("rule", ""))

    total_rules = sum(len(v) for v in categories.values())
    print(f"📊 Distribuzione:")
    for cat in CATEGORY_ORDER:
        if categories[cat]:
            print(f"   {cat}: {len(categories[cat])} regole")

    # 5. Genera PDF
    print(f"\n📄 Generazione PDF ({total_rules} regole)...")
    styles   = build_styles()
    date_str = datetime.now().strftime("%d %b %Y")

    doc = SimpleDocTemplate(
        str(OUTPUT_PDF),
        pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm, bottomMargin=2.5*cm,
        title="DeutschOps Grammar Book",
        author="Kevin Vecchi",
        allowSplitting=1  # permette split di ogni elemento su più pagine
    )

    story = []
    story += make_cover(styles, total_rules, date_str)
    story += make_how_to_use(styles)
    story += make_toc(categories, styles)

    for cat in CATEGORY_ORDER:
        rules = categories[cat]
        if not rules:
            continue
        story += make_chapter_header(cat, len(rules), styles)
        for rule in rules:
            story += make_rule_block(rule, styles)
        story.append(PageBreak())

    doc.build(story, onFirstPage=add_footer, onLaterPages=add_footer)

    size_kb = OUTPUT_PDF.stat().st_size // 1024
    print(f"✅ PDF generato: {OUTPUT_PDF} ({total_rules} regole · {size_kb}KB)")
    return str(OUTPUT_PDF)


def update_from_lesson(lesson_json_path: str):
    """Chiamato da main.py — aggiorna DB e rigenera PDF se ci sono novità."""
    try:
        data = json.loads(Path(lesson_json_path).read_text(encoding="utf-8"))
        new_grammar = data.get("grammar_points", [])
        if not new_grammar:
            return

        db       = load_grammar_db()
        rules_db = db.get("rules", {})
        new_count = 0

        for gp in new_grammar:
            key = gp.get("rule", "").strip()
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
            print(f"📖 Grammar Book: {new_count} nuove regole — rigenero PDF...")
            build_grammar_book(use_doc=False, enrich_web=False)
        else:
            print("📖 Grammar Book: nessuna regola nuova")

    except Exception as e:
        print(f"⚠️  Grammar book update error: {e}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--quick":
        build_grammar_book(use_doc=False, enrich_web=False)
    else:
        build_grammar_book(use_doc=True, enrich_web=True)