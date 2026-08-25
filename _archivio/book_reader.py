# book_reader.py
# Legge il libro DaF Kompakt Neu A1-B1 e integra regole grammaticali
# nel grammar_db con riferimenti di pagina ed esercizi

import json
import re
from pathlib import Path
from dotenv import load_dotenv
import anthropic
import pdfplumber

load_dotenv()
client = anthropic.Anthropic(api_key=__import__('os').getenv("ANTHROPIC_API_KEY"))

BOOK_PDF        = Path("Book/daf-kompakt-neu-a1-b1-kursbuch.pdf")
TRANSCRIPTS_PDF = Path("Book/Transkriptionen_A1.pdf")
GRAMMAR_DB      = Path("data/grammar_db.json")
BOOK_DB         = Path("data/book_db.json")


# ─── LOAD / SAVE ──────────────────────────────────────────────────────────────
def load_grammar_db() -> dict:
    if GRAMMAR_DB.exists():
        return json.loads(GRAMMAR_DB.read_text(encoding="utf-8"))
    return {"rules": {}}


def save_grammar_db(db: dict):
    GRAMMAR_DB.write_text(
        json.dumps(db, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def load_book_db() -> dict:
    if BOOK_DB.exists():
        return json.loads(BOOK_DB.read_text(encoding="utf-8"))
    return {
        "pages": {},          # page_num → {"text": ..., "chapter": ...}
        "grammar_rules": [],  # regole estratte dal libro
        "exercises": [],      # esercizi estratti
        "chapters": [],       # struttura capitoli
        "last_page_processed": 0
    }


def save_book_db(db: dict):
    BOOK_DB.write_text(
        json.dumps(db, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


# ─── PDF READING ──────────────────────────────────────────────────────────────
def extract_pages(pdf_path: Path, start: int = 0,
                  end: int = None) -> list[dict]:
    """
    Estrae testo da ogni pagina del PDF.
    Restituisce lista di {page_num, text, tables}.
    """
    pages = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        total = len(pdf.pages)
        end   = end or total
        print(f"   PDF: {pdf_path.name} — {total} pagine totali")

        for i in range(start, min(end, total)):
            page = pdf.pages[i]
            text = page.extract_text() or ""

            # Estrai tabelle (coniugazioni, declinazioni)
            tables = []
            for table in page.extract_tables():
                if table and any(any(cell for cell in row) for row in table):
                    tables.append(table)

            if text.strip() or tables:
                pages.append({
                    "page_num": i + 1,  # 1-indexed
                    "text": text,
                    "tables": tables
                })

    return pages


def detect_chapter(text: str, page_num: int) -> str:
    """Rileva il capitolo/lezione dalla pagina."""
    # Pattern tipici di DaF Kompakt: "Lektion 1", "Kapitel 3" etc.
    patterns = [
        r"Lektion\s+(\d+)",
        r"Kapitel\s+(\d+)",
        r"Einheit\s+(\d+)",
        r"Unit\s+(\d+)",
        r"Lektion\s+([A-Z])",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return f"Lektion {m.group(1)}"
    return ""


# ─── CLAUDE ANALYSIS ──────────────────────────────────────────────────────────
def analyze_chunk(pages: list[dict], chunk_num: int) -> dict:
    """
    Manda un chunk di pagine a Claude per estrarre:
    - Regole grammaticali con numero di pagina
    - Esercizi con numero di pagina
    - Struttura dei capitoli
    """
    # Prepara testo con marcatori di pagina
    content_parts = []
    for p in pages:
        page_text = f"\n--- PAGE {p['page_num']} ---\n{p['text']}"
        if p["tables"]:
            page_text += "\n[TABLES ON THIS PAGE:]\n"
            for table in p["tables"]:
                for row in table:
                    clean_row = [str(c or "").strip() for c in row]
                    if any(clean_row):
                        page_text += " | ".join(clean_row) + "\n"
        content_parts.append(page_text)

    content = "\n".join(content_parts)

    prompt = (
        "You are analyzing pages from 'DaF Kompakt Neu A1-B1', a German language textbook.\n"
        "Extract structured information in English only.\n\n"
        "Return ONLY valid JSON, zero backtick:\n"
        "{\n"
        '  "chapters": [\n'
        '    {"name": "Lektion 1 — Guten Tag", "page": 12}\n'
        "  ],\n"
        '  "grammar_rules": [\n'
        "    {\n"
        '      "rule": "Present tense — regular verbs",\n'
        '      "explanation_en": "explanation in English",\n'
        '      "examples": ["Ich lerne Deutsch.", "Du spielst Fußball."],\n'
        '      "book_page": 15,\n'
        '      "book_chapter": "Lektion 1",\n'
        '      "level": "A1",\n'
        '      "full_rule": "conjugation table or complete rule if present"\n'
        "    }\n"
        "  ],\n"
        '  "exercises": [\n'
        "    {\n"
        '      "type": "fill_in_blank",\n'
        '      "instruction": "Ergänzen Sie die Lücken",\n'
        '      "items": ["Ich ___ Deutsch. (lernen)", "Du ___ Fußball. (spielen)"],\n'
        '      "answers": ["lerne", "spielst"],\n'
        '      "book_page": 16,\n'
        '      "book_chapter": "Lektion 1",\n'
        '      "level": "A1",\n'
        '      "grammar_rule": "Present tense — regular verbs"\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "RULES:\n"
        "- Extract ALL grammar explanations found (Grammatik sections)\n"
        "- Extract ALL exercises (Übungen) with their items and answers if visible\n"
        "- Exercise types: fill_in_blank, translation, matching, multiple_choice, "
        "word_order, conjugation, free_writing\n"
        "- If answers not visible, leave answers as empty list\n"
        "- Include conjugation/declension tables in full_rule field\n"
        "- level: A1, A2, B1\n"
        "- All explanations in English\n\n"
        f"BOOK PAGES:\n{content[:35000]}"
    )

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

    cost = (response.usage.input_tokens * 0.000003 +
            response.usage.output_tokens * 0.000015)
    print(f"   Chunk {chunk_num}: {cost:.3f} EUR")

    try:
        return json.loads(raw)
    except Exception as e:
        print(f"   Parse error chunk {chunk_num}: {e}")
        return {"chapters": [], "grammar_rules": [], "exercises": []}


# ─── MERGE INTO GRAMMAR DB ────────────────────────────────────────────────────
def merge_book_rules_into_grammar_db(book_rules: list):
    """
    Aggiunge le regole del libro al grammar_db.
    Se la regola esiste già, aggiunge i riferimenti al libro.
    """
    db       = load_grammar_db()
    rules_db = db.get("rules", {})

    new_count     = 0
    enriched_count = 0

    for rule in book_rules:
        key = rule.get("rule", "").strip()
        if not key:
            continue

        book_metadata = {
            "book_page":    rule.get("book_page"),
            "book_chapter": rule.get("book_chapter", ""),
            "level":        rule.get("level", ""),
        }

        if key in rules_db:
            # Aggiorna con riferimenti libro se mancanti
            existing = rules_db[key]
            if not existing.get("book_page") and rule.get("book_page"):
                existing.update(book_metadata)
                enriched_count += 1
            # Aggiorna full_rule se il libro ne ha uno più completo
            if rule.get("full_rule") and not existing.get("full_rule"):
                existing["full_rule"] = rule["full_rule"]
                enriched_count += 1
        else:
            # Regola nuova dal libro
            rules_db[key] = {
                **rule,
                "source_verified": False,
                "common_mistakes": "",
                "exceptions": "",
            }
            new_count += 1

    db["rules"] = rules_db
    save_grammar_db(db)
    print(f"   Grammar DB: +{new_count} nuove regole, {enriched_count} arricchite")
    return new_count, enriched_count


# ─── MAIN ─────────────────────────────────────────────────────────────────────
def process_book(pages_per_chunk: int = 15, max_pages: int = None,
                 resume: bool = True):
    """
    Processa il libro a chunk.
    resume=True: riprende dall'ultima pagina processata.
    """
    print(f"\n{'='*55}")
    print(f"  DeutschOps — Book Reader")
    print(f"  {BOOK_PDF.name}")
    print(f"{'='*55}\n")

    book_db = load_book_db()
    start_page = book_db["last_page_processed"] if resume else 0

    if start_page > 0:
        print(f"Resuming from page {start_page + 1}...")

    # Estrai pagine
    print("Extracting pages...")
    all_pages = extract_pages(BOOK_PDF, start=start_page, end=max_pages)
    print(f"   {len(all_pages)} pages to process")

    if not all_pages:
        print("No pages to process.")
        return

    # Stima costo
    avg_chars   = sum(len(p["text"]) for p in all_pages) / max(len(all_pages), 1)
    chunks      = len(all_pages) // pages_per_chunk + 1
    est_cost    = chunks * 0.08
    print(f"   Chunks: {chunks} | Estimated cost: EUR {est_cost:.2f}")
    print()

    # Chiedi conferma se il costo è significativo
    if est_cost > 0.5:
        confirm = input(
            f"   Estimated cost: EUR {est_cost:.2f}. Continue? [y/N]: "
        ).strip().lower()
        if confirm != "y":
            print("   Aborted.")
            return

    # Processa chunk per chunk
    all_grammar_rules = []
    all_exercises     = []
    all_chapters      = []

    for chunk_idx in range(0, len(all_pages), pages_per_chunk):
        chunk      = all_pages[chunk_idx:chunk_idx + pages_per_chunk]
        chunk_num  = chunk_idx // pages_per_chunk + 1
        page_range = f"{chunk[0]['page_num']}-{chunk[-1]['page_num']}"
        print(f"Processing chunk {chunk_num} (pages {page_range})...")

        result = analyze_chunk(chunk, chunk_num)

        all_grammar_rules.extend(result.get("grammar_rules", []))
        all_exercises.extend(result.get("exercises", []))
        all_chapters.extend(result.get("chapters", []))

        # Salva progresso
        book_db["last_page_processed"] = chunk[-1]["page_num"]
        book_db["grammar_rules"]       = all_grammar_rules
        book_db["exercises"]           = all_exercises
        book_db["chapters"]            = all_chapters
        save_book_db(book_db)

    # Merge nel grammar_db principale
    print(f"\nMerging {len(all_grammar_rules)} rules into grammar DB...")
    merge_book_rules_into_grammar_db(all_grammar_rules)

    print(f"\nBook processing complete:")
    print(f"   Grammar rules found: {len(all_grammar_rules)}")
    print(f"   Exercises found:     {len(all_exercises)}")
    print(f"   Chapters found:      {len(all_chapters)}")
    print(f"   Book DB saved:       {BOOK_DB}")
    print(f"\nNext: python grammar_book.py --quick to regenerate PDF")


def process_transcripts():
    """Processa le trascrizioni audio A1."""
    print(f"\nProcessing transcripts: {TRANSCRIPTS_PDF.name}")
    pages = extract_pages(TRANSCRIPTS_PDF)
    print(f"   {len(pages)} pages extracted")

    # Salva come testo per uso futuro (Astra prompts, esercizi listening)
    transcript_text = ""
    for p in pages:
        transcript_text += f"\n--- PAGE {p['page_num']} ---\n{p['text']}\n"

    out = Path("data/book_transcripts.txt")
    out.write_text(transcript_text, encoding="utf-8")
    print(f"   Saved: {out} ({len(transcript_text)} chars)")


def get_exercises_for_rule(rule_name: str) -> list:
    """
    Restituisce esercizi dal libro relativi a una regola grammaticale.
    Usata da generate_astra_prompts.py e dalla dashboard.
    """
    book_db   = load_book_db()
    exercises = book_db.get("exercises", [])
    rule_lower = rule_name.lower()

    matching = [
        ex for ex in exercises
        if rule_lower in ex.get("grammar_rule","").lower()
        or rule_lower in ex.get("instruction","").lower()
    ]
    return matching


def get_book_reference(rule_name: str) -> dict:
    """
    Restituisce il riferimento al libro per una regola.
    Usata da grammar_book.py per mostrare la pagina.
    """
    db       = load_grammar_db()
    rule     = db.get("rules",{}).get(rule_name, {})
    page     = rule.get("book_page")
    chapter  = rule.get("book_chapter","")

    if page:
        return {
            "page":    page,
            "chapter": chapter,
            "ref":     f"DaF Kompakt Neu, p.{page}"
                       + (f" ({chapter})" if chapter else "")
        }
    return {}


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--transcripts":
        process_transcripts()
    elif len(sys.argv) > 1 and sys.argv[1] == "--resume":
        process_book(resume=True)
    elif len(sys.argv) > 1 and sys.argv[1] == "--fresh":
        process_book(resume=False)
    else:
        print("Usage:")
        print("  python book_reader.py --fresh      # Process full book from start")
        print("  python book_reader.py --resume     # Resume from last checkpoint")
        print("  python book_reader.py --transcripts # Process audio transcripts")