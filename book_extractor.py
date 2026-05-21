# book_extractor.py v7
# Mappa pagine esatta confermata manualmente
# --skip-transcriptions per saltare le trascrizioni e andare dritti ai Lektionen
# --fresh per ricominciare da zero
# Resume automatico — rilancia senza flags per continuare

import os
import re
import json
import sys
import time
from pathlib import Path
from dotenv import load_dotenv
import anthropic

load_dotenv()
client = anthropic.Anthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY"),
    timeout=120.0  # 2 min max per call — pagine singole non ne hanno bisogno
)

BOOK_PDF        = Path("Book/daf-kompakt-neu-a1-b1-kursbuch.pdf")
TRANSCRIPTS_PDF = Path("Book/Transkriptionen_A1.pdf")
BOOK_DB         = Path("data/book_db.json")
FILE_IDS        = Path("data/book_file_ids.json")
LEKTIONEN_DIR   = Path("Book/lektionen")

SLEEP_OK    = 8   # secondi tra call normali
SLEEP_LIMIT = 70  # secondi dopo rate limit

# Mappa esatta pagine recap (vocab_page, grammar_page)
# Confermata da ispezione manuale del PDF
RECAP_MAP = {
    1:  (22, 23),  2:  (32, 33),  3:  (40, 41),  4:  (48, 49),
    5:  (56, 57),  6:  (64, 65),  7:  (72, 73),  8:  (80, 81),
    9:  (88, 89),  10: (96, 97),  11: (104, 105), 12: (112, 113),
    13: (120, 121), 14: (128, 129), 15: (136, 137), 16: (144, 145),
    17: (152, 153), 18: (160, 161), 19: (168, 169), 20: (176, 177),
    21: (184, 185), 22: (192, 193), 23: (200, 201), 24: (208, 209),
    25: (216, 217), 26: (224, 225), 27: (232, 233), 28: (240, 241),
    29: (248, 249), 30: (258, 258),  # standalone
}

def get_level(n: int) -> str:
    if n <= 8:  return "A1"
    if n <= 18: return "A2"
    return "B1"


# ─── DB / CACHE ───────────────────────────────────────────────────────────────
def load_file_ids() -> dict:
    if FILE_IDS.exists():
        return json.loads(FILE_IDS.read_text(encoding="utf-8"))
    return {}

def save_file_ids(ids: dict):
    FILE_IDS.write_text(json.dumps(ids, indent=2), encoding="utf-8")

def load_book_db() -> dict:
    if BOOK_DB.exists():
        return json.loads(BOOK_DB.read_text(encoding="utf-8"))
    return {
        "metadata": {
            "title":                  "DaF Kompakt Neu A1-B1",
            "strategy":               "exact_pages_v7",
            "last_lektion_processed": 0,
            "transcriptions_done":    False
        },
        "lektionen":      {},
        "grammar_rules":  [],
        "vocabulary":     [],
        "redemittel":     [],
        "audio_tracks":   [],
        "transcriptions": {},
        "knowledge_map":  {}
    }

def save_book_db(db: dict):
    BOOK_DB.write_text(
        json.dumps(db, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"   Saved {BOOK_DB.stat().st_size // 1024}KB")


# ─── JSON PARSING ─────────────────────────────────────────────────────────────
def parse_json(raw: str) -> dict | None:
    if not raw:
        return None
    clean = raw.strip()
    if clean.startswith("```"):
        clean = "\n".join(clean.split("\n")[1:-1]).strip()
    s = clean.find("{")
    e = clean.rfind("}") + 1
    if s >= 0 and e > s:
        clean = clean[s:e]
    clean = re.sub(r',\s*([}\]])', r'\1', clean)
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        # Salvage truncated JSON
        opens  = clean.count("{") - clean.count("}")
        aopens = clean.count("[") - clean.count("]")
        last   = max(clean.rfind("},"), clean.rfind("],"))
        if last > 0:
            clean  = clean[:last + 1]
            clean += "]" * max(aopens, 0)
            clean += "}" * max(opens, 0)
            clean  = re.sub(r',\s*([}\]])', r'\1', clean)
            try:
                return json.loads(clean)
            except Exception:
                pass
    return None


# ─── API CALL WITH RETRY ──────────────────────────────────────────────────────
def api_call(func, retries: int = 5):
    for attempt in range(retries):
        try:
            return func()
        except anthropic.RateLimitError:
            wait = SLEEP_LIMIT * (attempt + 1)
            print(f"   Rate limit — waiting {wait}s...")
            time.sleep(wait)
        except anthropic.APIStatusError as e:
            if "overloaded" in str(e).lower():
                print(f"   Overloaded — waiting 30s...")
                time.sleep(30)
            else:
                raise
        except (anthropic.APITimeoutError, Exception) as e:
            err = str(e).lower()
            if any(k in err for k in
                   ["timeout", "ssl", "connection",
                    "network", "read"]):
                wait = 20 * (attempt + 1)
                print(f"   Network/timeout error — waiting {wait}s...")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError(f"Max retries ({retries}) exceeded")


# ─── PDF OPERATIONS ───────────────────────────────────────────────────────────
def extract_single_page(page_num: int, out_path: Path) -> Path:
    """Estrae una singola pagina dal libro."""
    from pypdf import PdfReader, PdfWriter

    if out_path.exists():
        return out_path

    reader = PdfReader(str(BOOK_PDF))
    writer = PdfWriter()
    writer.add_page(reader.pages[page_num - 1])

    LEKTIONEN_DIR.mkdir(parents=True, exist_ok=True)
    with open(str(out_path), "wb") as f:
        writer.write(f)

    size = out_path.stat().st_size // 1024
    print(f"   Page {page_num} → {out_path.name} ({size}KB)")
    return out_path


def extract_pages_range(p_start: int, p_end: int,
                         out_path: Path) -> Path:
    """Estrae un range di pagine dal libro."""
    from pypdf import PdfReader, PdfWriter

    if out_path.exists():
        return out_path

    reader = PdfReader(str(BOOK_PDF))
    writer = PdfWriter()
    total  = len(reader.pages)

    for i in range(p_start - 1, min(p_end, total)):
        writer.add_page(reader.pages[i])

    LEKTIONEN_DIR.mkdir(parents=True, exist_ok=True)
    with open(str(out_path), "wb") as f:
        writer.write(f)

    size = out_path.stat().st_size // 1024
    print(f"   Pages {p_start}-{p_end} → {out_path.name} ({size}KB)")
    return out_path


def upload_cached(pdf_path: Path, cache_key: str) -> str:
    """Upload PDF con caching — non ricarica se già uploadato."""
    file_ids = load_file_ids()
    if cache_key in file_ids:
        return file_ids[cache_key]

    size_kb = pdf_path.stat().st_size // 1024
    print(f"   Uploading {pdf_path.name} ({size_kb}KB)...")

    with open(str(pdf_path), "rb") as f:
        resp = client.beta.files.upload(
            file=(pdf_path.name, f, "application/pdf")
        )

    file_ids[cache_key] = resp.id
    save_file_ids(file_ids)
    print(f"   → {resp.id[:24]}...")
    return resp.id


# ─── PROMPTS ──────────────────────────────────────────────────────────────────
def vocab_prompt(lnum: int, level: str) -> str:
    return f"""This is the vocabulary summary page ("Lektionswortschatz in Feldern")
from Lektion {lnum} ({level}) of DaF Kompakt Neu A1-B1.

The page organizes vocabulary by semantic fields (colored section headers).
Each entry shows: article + word + plural ending (for nouns).
Small superscript numbers or speaker symbols = audio track references.

Extract EVERY SINGLE WORD. Do not skip any.

Return ONLY valid JSON, zero backtick:
{{
  "vocabulary": [
    {{
      "german": "die Technik",
      "english": "technology",
      "italian": "la tecnologia",
      "article": "die",
      "plural": "Techniken",
      "category": "noun",
      "semantic_field": "Technik / Geräte",
      "audio_ref": "",
      "level": "{level}"
    }},
    {{
      "german": "trainieren",
      "english": "to train",
      "italian": "allenarsi",
      "article": "",
      "plural": "",
      "category": "verb",
      "semantic_field": "Sport",
      "audio_ref": "12",
      "level": "{level}"
    }}
  ]
}}

Rules:
- category: noun, verb, adjective, adverb, phrase, expression,
  preposition, conjunction, pronoun
- For nouns: article = der/die/das, plural = ending shown in book
- semantic_field = the colored section header above this word group
- audio_ref = superscript number if visible, else empty string
- Extract ALL words including those in sub-lists
- Translate to both English and Italian"""


def grammar_prompt(lnum: int, level: str) -> str:
    return f"""This is the grammar summary page ("Redemittel / Grammatik")
from Lektion {lnum} ({level}) of DaF Kompakt Neu A1-B1.

The page contains:
1. REDEMITTEL section: useful communication phrases
2. GRAMMATIK section: grammar rules with conjugation/declension tables

Return ONLY valid JSON, zero backtick:
{{
  "redemittel": [
    {{
      "german": "Wir mochten gerne bestellen.",
      "english": "We would like to order.",
      "context": "Im Restaurant - ordering food",
      "audio_ref": ""
    }}
  ],
  "grammar_rules": [
    {{
      "rule": "Definite article Nominativ and Akkusativ",
      "explanation_en": "German definite articles change by case and gender",
      "full_rule": "Nominativ: M=der N=das F=die PL=die | Akkusativ: M=den N=das F=die PL=die",
      "table": {{
        "headers": ["", "Maskulinum", "Neutrum", "Femininum", "Plural"],
        "rows": [
          ["Nominativ", "der", "das", "die", "die"],
          ["Akkusativ", "den", "das", "die", "die"]
        ]
      }},
      "examples": [
        "Der Computer ist neu.",
        "Ich kaufe den Computer."
      ],
      "common_mistakes": "Italian speakers forget den for masculine Akkusativ",
      "book_order": {lnum * 10},
      "level": "{level}",
      "prerequisites": []
    }}
  ]
}}

Rules:
- Extract EVERY grammar table completely (every row and column)
- full_rule = readable text version of the table
- table = structured version with headers and rows
- All explanations in English, German stays German
- Extract ALL Redemittel phrases"""


def transcript_chunk_prompt() -> str:
    return """Extract all audio transcriptions from these pages.
Each transcription starts with a track number.

Return ONLY valid JSON:
{
  "transcriptions": [
    {
      "track_ref": "1",
      "lektion": 1,
      "level": "A1",
      "type": "dialogue",
      "text": "complete verbatim text here",
      "page": 1
    }
  ]
}"""


# ─── EXTRACTION FUNCTIONS ─────────────────────────────────────────────────────
def extract_vocab(file_id: str, lnum: int, level: str) -> list:
    prompt = vocab_prompt(lnum, level)

    def call():
        return client.beta.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=8000,
            betas=["files-api-2025-04-14"],
            messages=[{"role": "user", "content": [
                {"type": "document",
                 "source": {"type": "file", "file_id": file_id}},
                {"type": "text", "text": prompt}
            ]}]
        )

    resp  = api_call(call)
    cost  = (resp.usage.input_tokens  * 3e-6 +
             resp.usage.output_tokens * 1.5e-5)
    data  = parse_json(resp.content[-1].text)
    vocab = data.get("vocabulary", []) if data else []
    print(f"   Vocab: {len(vocab)} words | EUR {cost:.3f}")
    return vocab


def extract_grammar(file_id: str, lnum: int,
                     level: str) -> tuple[list, list]:
    prompt = grammar_prompt(lnum, level)

    def call():
        return client.beta.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=8000,
            betas=["files-api-2025-04-14"],
            messages=[{"role": "user", "content": [
                {"type": "document",
                 "source": {"type": "file", "file_id": file_id}},
                {"type": "text", "text": prompt}
            ]}]
        )

    resp       = api_call(call)
    cost       = (resp.usage.input_tokens  * 3e-6 +
                  resp.usage.output_tokens * 1.5e-5)
    data       = parse_json(resp.content[-1].text)
    grammar    = data.get("grammar_rules", []) if data else []
    redemittel = data.get("redemittel",    []) if data else []
    print(f"   Grammar: {len(grammar)} | "
          f"Redemittel: {len(redemittel)} | EUR {cost:.3f}")
    return grammar, redemittel


def extract_transcription_chunk(file_id: str,
                                  chunk_label: str) -> dict:
    """Estrae trascrizioni da un chunk di pagine."""
    prompt = transcript_chunk_prompt()

    def call():
        return client.beta.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=8000,
            betas=["files-api-2025-04-14"],
            messages=[{"role": "user", "content": [
                {"type": "document",
                 "source": {"type": "file", "file_id": file_id}},
                {"type": "text", "text": prompt}
            ]}]
        )

    resp  = api_call(call)
    cost  = (resp.usage.input_tokens  * 3e-6 +
             resp.usage.output_tokens * 1.5e-5)
    data  = parse_json(resp.content[-1].text)
    trans = data.get("transcriptions", []) if data else []
    print(f"   {chunk_label}: {len(trans)} tracks | EUR {cost:.3f}")
    return {t["track_ref"]: t for t in trans if t.get("track_ref")}


# ─── KNOWLEDGE MAP ────────────────────────────────────────────────────────────
def _related(a: str, b: str) -> bool:
    cats = [
        ["verb", "conjugat", "tense", "modal", "separable",
         "infinitive", "sein", "haben", "werden",
         "prasens", "perfekt", "prateritum"],
        ["case", "nominativ", "akkusativ", "dativ", "genitiv",
         "article", "artikel", "possessiv"],
        ["adjective", "comparative", "superlative", "adverb"],
        ["clause", "nebensatz", "conjunction", "subordinate",
         "ob", "weil", "dass", "konnektoren"],
        ["pronoun", "reflexive", "possessive", "personalpronomen"],
        ["preposition", "two-way", "praposition"],
        ["word order", "position", "inversion", "satzstellung"],
    ]
    a, b = a.lower(), b.lower()
    for cat in cats:
        if any(k in a for k in cat) and any(k in b for k in cat):
            return True
    return False

def build_knowledge_map(book_db: dict) -> dict:
    rules = []
    for lnum_str, ldata in book_db["lektionen"].items():
        lnum = int(lnum_str)
        for i, r in enumerate(ldata.get("grammar_rules", [])):
            if r.get("rule"):
                rules.append({
                    "rule":       r["rule"],
                    "lektion":    lnum,
                    "level":      r.get("level", ""),
                    "book_order": r.get("book_order", lnum * 10 + i)
                })
    rules.sort(key=lambda r: r["book_order"])
    km, seen = {}, []
    for rule in rules:
        name    = rule["rule"]
        prereqs = [s["rule"] for s in seen if _related(s["rule"], name)]
        km[name] = {
            "prerequisites": prereqs[-2:],
            "lektion":       rule["lektion"],
            "level":         rule["level"],
            "book_order":    rule["book_order"]
        }
        seen.append(rule)
    return km


# ─── MERGE INTO GRAMMAR DB ────────────────────────────────────────────────────
def merge_into_grammar_db(book_db: dict):
    gdb_path = Path("data/grammar_db.json")
    gdb      = {"rules": {}}
    if gdb_path.exists():
        gdb = json.loads(gdb_path.read_text(encoding="utf-8"))

    rules_db  = gdb.get("rules", {})
    new_count = enriched = 0

    all_rules = []
    for lnum_str, ldata in book_db["lektionen"].items():
        lnum = int(lnum_str)
        for i, r in enumerate(ldata.get("grammar_rules", [])):
            r.setdefault("book_order", lnum * 10 + i)
            r["_lektion"] = lnum
            all_rules.append(r)
    all_rules.sort(key=lambda r: r["book_order"])

    for rule in all_rules:
        key = rule.get("rule", "").strip()
        if not key:
            continue

        # Converti table → full_rule se necessario
        table = rule.get("table", {})
        full  = rule.get("full_rule", "")
        if table and not full:
            headers = table.get("headers", [])
            rows    = table.get("rows", [])
            lines   = [" | ".join(str(h) for h in headers)]
            for row in rows:
                lines.append(" | ".join(str(c) for c in row))
            full = "\n".join(lines)

        meta = {
            "book_chapter": f"Lektion {rule['_lektion']}",
            "book_order":   rule.get("book_order"),
            "level":        rule.get("level", ""),
        }

        if key not in rules_db:
            rules_db[key] = {
                "rule":            key,
                "explanation_en":  rule.get("explanation_en", ""),
                "full_rule":       full,
                "examples":        rule.get("examples", []),
                "common_mistakes": rule.get("common_mistakes", ""),
                "exceptions":      "",
                "source_verified": False,
                **meta
            }
            new_count += 1
        else:
            ex = rules_db[key]
            if not ex.get("book_order"):
                ex.update(meta)
                enriched += 1
            if full and not ex.get("full_rule"):
                ex["full_rule"] = full
                enriched += 1

    gdb["rules"] = rules_db
    gdb_path.write_text(
        json.dumps(gdb, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"   Grammar DB: +{new_count} new, {enriched} enriched")


# ─── MAIN ─────────────────────────────────────────────────────────────────────
def extract_book(skip_transcriptions: bool = False,
                  resume: bool = True):
    print(f"\n{'='*55}")
    print(f"  DeutschOps — Book Extractor v7")
    print(f"  Exact page map | 2 calls per Lektion")
    print(f"  {'Transcriptions: SKIPPED' if skip_transcriptions else 'Transcriptions: enabled'}")
    print(f"{'='*55}\n")

    book_db = load_book_db()
    last    = (book_db["metadata"].get("last_lektion_processed", 0)
               if resume else 0)

    LEKTIONEN_DIR.mkdir(parents=True, exist_ok=True)

    if last > 0:
        print(f"Resuming from Lektion {last + 1}\n")

    # ── Step 1: Transcriptions ────────────────────────────────────────────────
    if skip_transcriptions:
        print("Step 1 — Transcriptions: SKIPPED")
        print("         Run later with: python book_extractor.py --transcriptions-only\n")
        if not book_db["metadata"].get("transcriptions_done"):
            book_db["metadata"]["transcriptions_done"] = True
            save_book_db(book_db)

    elif not book_db["metadata"].get("transcriptions_done"):
        print("Step 1 — Transcriptions (split in chunks of 10 pages)...")

        trans_map = {}

        # Chunk le pagine 260-302 del libro (10 pagine per chunk)
        for chunk_start in range(260, 303, 10):
            chunk_end  = min(chunk_start + 9, 302)
            chunk_path = LEKTIONEN_DIR / f"trans_{chunk_start}_{chunk_end}.pdf"
            extract_pages_range(chunk_start, chunk_end, chunk_path)
            fid        = upload_cached(chunk_path,
                                        f"trans_book_{chunk_start}_v7")
            time.sleep(2)
            chunk_trans = extract_transcription_chunk(
                fid, f"Book pp {chunk_start}-{chunk_end}"
            )
            trans_map.update(chunk_trans)
            time.sleep(SLEEP_OK)

        # PDF esterno Transkriptionen_A1.pdf (split in chunks da 7 pagine)
        print("   External transcription PDF...")
        from pypdf import PdfReader
        ext_total = len(PdfReader(str(TRANSCRIPTS_PDF)).pages)

        for chunk_start in range(0, ext_total, 7):
            chunk_end = min(chunk_start + 6, ext_total - 1)
            # Estrai chunk dal PDF esterno
            from pypdf import PdfReader, PdfWriter
            reader = PdfReader(str(TRANSCRIPTS_PDF))
            writer = PdfWriter()
            for i in range(chunk_start, chunk_end + 1):
                writer.add_page(reader.pages[i])
            chunk_path = LEKTIONEN_DIR / f"trans_ext_{chunk_start}.pdf"
            if not chunk_path.exists():
                with open(str(chunk_path), "wb") as f:
                    writer.write(f)
            fid = upload_cached(chunk_path,
                                 f"trans_ext_{chunk_start}_v7")
            time.sleep(2)
            chunk_trans = extract_transcription_chunk(
                fid, f"Ext pp {chunk_start+1}-{chunk_end+1}"
            )
            trans_map.update(chunk_trans)
            time.sleep(SLEEP_OK)

        book_db["transcriptions"] = trans_map
        book_db["audio_tracks"]   = list(trans_map.values())
        book_db["metadata"]["transcriptions_done"] = True
        save_book_db(book_db)
        print(f"   Total: {len(trans_map)} tracks saved\n")

    else:
        n = len(book_db["transcriptions"])
        print(f"Step 1 — Transcriptions cached ({n} tracks)\n")

    trans_map = book_db["transcriptions"]

    # ── Step 2: Lektionen ─────────────────────────────────────────────────────
    print("Step 2 — Extract 30 Lektionen (2 calls each: vocab + grammar)")
    print(f"{'─'*45}")

    total_vocab = total_grammar = total_redemittel = 0

    for lnum in range(1, 31):
        if lnum <= last:
            continue

        level      = get_level(lnum)
        vocab_pg   = RECAP_MAP[lnum][0]
        grammar_pg = RECAP_MAP[lnum][1]
        standalone = vocab_pg == grammar_pg

        print(f"\nLektion {lnum:02d} ({level}) — "
              f"vocab p.{vocab_pg}"
              + (f" | grammar p.{grammar_pg}" if not standalone
                 else " [standalone]") + "...")

        # ── Vocab page ────────────────────────────────────────────────────────
        vocab_pdf = LEKTIONEN_DIR / f"l{lnum:02d}_vocab_p{vocab_pg}.pdf"
        extract_single_page(vocab_pg, vocab_pdf)
        vocab_fid = upload_cached(vocab_pdf, f"vocab_v7_{lnum:02d}")
        time.sleep(2)

        vocab = extract_vocab(vocab_fid, lnum, level)
        time.sleep(SLEEP_OK)

        # ── Grammar page ──────────────────────────────────────────────────────
        if standalone:
            # Pagina unica — estrae grammar dalla stessa pagina vocab
            grammar_fid = vocab_fid
            print(f"   Grammar: using same page (standalone)")
        else:
            grammar_pdf = LEKTIONEN_DIR / f"l{lnum:02d}_grammar_p{grammar_pg}.pdf"
            extract_single_page(grammar_pg, grammar_pdf)
            grammar_fid = upload_cached(grammar_pdf,
                                         f"grammar_v7_{lnum:02d}")
            time.sleep(2)

        grammar, redemittel = extract_grammar(grammar_fid, lnum, level)
        time.sleep(SLEEP_OK)

        # Collega trascrizioni al vocab
        for word in vocab:
            ref = word.get("audio_ref", "")
            if ref and ref in trans_map:
                word["transcription"] = trans_map[ref].get("text", "")

        # Metadati grammatica
        for i, r in enumerate(grammar):
            r["book_chapter"] = f"Lektion {lnum}"
            r["level"]        = r.get("level", level)
            r.setdefault("book_order", lnum * 10 + i)

        lektion_data = {
            "lektion_num":   lnum,
            "level":         level,
            "recap_pages":   {"vocab": vocab_pg, "grammar": grammar_pg},
            "vocabulary":    vocab,
            "grammar_rules": grammar,
            "redemittel":    redemittel,
        }

        book_db["lektionen"][str(lnum)]             = lektion_data
        book_db["grammar_rules"].extend(grammar)
        book_db["vocabulary"].extend(vocab)
        book_db["redemittel"].extend(redemittel)
        book_db["metadata"]["last_lektion_processed"] = lnum

        total_vocab      += len(vocab)
        total_grammar    += len(grammar)
        total_redemittel += len(redemittel)

        save_book_db(book_db)

    # ── Step 3: Finalize ──────────────────────────────────────────────────────
    print(f"\n{'─'*45}")
    print("Step 3 — Knowledge map and grammar DB...")
    book_db["knowledge_map"]         = build_knowledge_map(book_db)
    book_db["metadata"]["extracted"] = True
    save_book_db(book_db)
    merge_into_grammar_db(book_db)

    size = BOOK_DB.stat().st_size // 1024
    print(f"\n{'='*55}")
    print(f"  Complete!")
    print(f"  Vocabulary    : {total_vocab}")
    print(f"  Grammar rules : {total_grammar}")
    print(f"  Redemittel    : {total_redemittel}")
    print(f"  Transcriptions: {len(book_db['transcriptions'])}")
    print(f"  Book DB       : {BOOK_DB} ({size}KB)")
    print(f"\n  Next:")
    print(f"  python grammar_book.py --quick")
    print(f"  streamlit run dashboard.py")
    print(f"{'='*55}\n")


def extract_transcriptions_only():
    """Aggiunge le trascrizioni a un book_db già esistente."""
    print("\nExtracting transcriptions only...")
    book_db   = load_book_db()
    trans_map = {}

    # Book pp 260-302 in chunks da 10
    for chunk_start in range(260, 303, 10):
        chunk_end  = min(chunk_start + 9, 302)
        chunk_path = LEKTIONEN_DIR / f"trans_{chunk_start}_{chunk_end}.pdf"
        extract_pages_range(chunk_start, chunk_end, chunk_path)
        fid = upload_cached(chunk_path, f"trans_book_{chunk_start}_v7")
        time.sleep(2)
        chunk_trans = extract_transcription_chunk(
            fid, f"Book pp {chunk_start}-{chunk_end}"
        )
        trans_map.update(chunk_trans)
        time.sleep(SLEEP_OK)

    book_db["transcriptions"] = trans_map
    book_db["audio_tracks"]   = list(trans_map.values())
    book_db["metadata"]["transcriptions_done"] = True
    save_book_db(book_db)
    print(f"Done: {len(trans_map)} tracks saved")


# ─── ENTRY POINT ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    skip_trans = "--skip-transcriptions" in sys.argv
    fresh      = "--fresh"               in sys.argv
    trans_only = "--transcriptions-only" in sys.argv

    if trans_only:
        extract_transcriptions_only()

    elif fresh:
        # Reset completo
        if BOOK_DB.exists():
            BOOK_DB.unlink()
        if LEKTIONEN_DIR.exists():
            for f in LEKTIONEN_DIR.glob("l??_*.pdf"):
                f.unlink()
        # Rimuovi file_ids dei Lektionen (non delle trascrizioni)
        ids = load_file_ids()
        ids = {k: v for k, v in ids.items()
               if not any(k.startswith(p)
                          for p in ["vocab_v7_", "grammar_v7_"])}
        save_file_ids(ids)
        extract_book(skip_transcriptions=skip_trans, resume=False)

    else:
        extract_book(skip_transcriptions=skip_trans, resume=True)