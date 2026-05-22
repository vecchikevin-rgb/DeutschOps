# enrich_lesson_pdfs.py
# Aggiunge cross-reference libro ai JSON delle lezioni
# e rigenera i PDF

import json
from pathlib import Path

BOOK_DB = Path("data/book_db.json")
LESSONS = Path("data")


def load_book_db() -> dict:
    if not BOOK_DB.exists():
        print("book_db.json non trovato")
        return {}
    return json.loads(BOOK_DB.read_text(encoding="utf-8"))


def build_vocab_index(book_db: dict) -> dict:
    """
    Costruisce indice {german_word_lower: {lektion, page, semantic_field}}
    da tutte le Lektionen del libro.
    """
    index = {}
    for lnum_str, ldata in book_db.get("lektionen", {}).items():
        lnum  = int(lnum_str)
        pages = ldata.get("recap_pages", {})
        vp    = pages.get("vocab") if isinstance(pages, dict) else None

        for w in ldata.get("vocabulary", []):
            key = w.get("german", "").lower().strip()
            # Rimuovi articolo se presente
            for art in ["der ", "die ", "das "]:
                if key.startswith(art):
                    key = key[len(art):]
            if key and key not in index:
                index[key] = {
                    "lektion":        lnum,
                    "book_page":      vp,
                    "semantic_field": w.get("semantic_field", ""),
                    "level":          w.get("level", ""),
                }
    return index


def build_grammar_index(book_db: dict) -> dict:
    """
    Costruisce indice {rule_lower: {lektion, page}} dal libro.
    """
    index = {}
    for lnum_str, ldata in book_db.get("lektionen", {}).items():
        lnum  = int(lnum_str)
        pages = ldata.get("recap_pages", {})
        gp    = pages.get("grammar") if isinstance(pages, dict) else None

        for g in ldata.get("grammar_rules", []):
            key = g.get("rule", "").lower().strip()
            if key and key not in index:
                index[key] = {
                    "lektion":   lnum,
                    "book_page": gp,
                    "book_rule": g.get("rule", ""),
                }
    return index


def find_vocab_ref(german: str, article: str,
                    vocab_index: dict) -> dict:
    """Cerca una parola nell'indice vocab del libro."""
    # Prova con la parola base
    candidates = [
        german.lower().strip(),
        german.lower().strip().lstrip("der ").lstrip("die ").lstrip("das "),
    ]
    if article:
        candidates.append(german.lower().strip())

    for key in candidates:
        if key in vocab_index:
            return vocab_index[key]

    # Prova match parziale (parola senza articolo)
    base = german.lower().strip()
    for art in ["der ", "die ", "das ", "Der ", "Die ", "Das "]:
        if base.startswith(art.lower()):
            base = base[len(art):]
            break

    if base in vocab_index:
        return vocab_index[base]

    return {}


def find_grammar_ref(rule: str, grammar_index: dict) -> dict:
    """Cerca una regola grammaticale nell'indice del libro."""
    rule_lower = rule.lower().strip()

    # Match esatto
    if rule_lower in grammar_index:
        return grammar_index[rule_lower]

    # Match parziale — cerca se la regola della lezione
    # è contenuta in una regola del libro o viceversa
    for book_rule_lower, ref in grammar_index.items():
        if (rule_lower in book_rule_lower or
                book_rule_lower in rule_lower):
            return ref

    return {}


def enrich_lesson_json(lesson_path: Path,
                        vocab_index: dict,
                        grammar_index: dict) -> bool:
    """
    Aggiunge/aggiorna cross-reference libro al JSON della lezione.
    Forza l'aggiornamento anche se book_ref già esiste (per fix None).
    """
    data     = json.loads(lesson_path.read_text(encoding="utf-8"))
    modified = False

    for word in data.get("vocabulary", []):
        german  = word.get("german", "")
        article = word.get("article", "")
        ref     = find_vocab_ref(german, article, vocab_index)

        if ref:
            existing = word.get("book_ref", {})
            # Aggiorna solo se il ref attuale è vuoto o ha None
            if not existing or not existing.get("lektion"):
                word["book_ref"] = ref
                modified = True

    for gp in data.get("grammar_points", []):
        rule = gp.get("rule", "")
        ref  = find_grammar_ref(rule, grammar_index)

        if ref:
            existing = gp.get("book_ref", {})
            if not existing or not existing.get("lektion"):
                gp["book_ref"] = ref
                modified = True

    if modified:
        lesson_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    return modified


def enrich_all_lessons():
    book_db = load_book_db()
    if not book_db:
        return

    vocab_index   = build_vocab_index(book_db)
    grammar_index = build_grammar_index(book_db)

    print(f"Vocab index:   {len(vocab_index)} words")
    print(f"Grammar index: {len(grammar_index)} rules")

    # Debug: mostra prime 5 entries dell'indice
    print("\nSample vocab index:")
    for i, (k, v) in enumerate(list(vocab_index.items())[:5]):
        print(f"  '{k}' → Lektion {v['lektion']} p.{v['book_page']}")

    lesson_files = sorted(LESSONS.glob("lezione_*.json"))
    enriched = 0

    for lesson_path in lesson_files:
        lesson_id = lesson_path.stem.replace("lezione_", "")
        modified  = enrich_lesson_json(lesson_path,
                                        vocab_index, grammar_index)
        status = "✅ Enriched" if modified else "⏭️  No changes"
        print(f"  {status}: {lesson_id}")
        if modified:
            enriched += 1

    print(f"\n{enriched}/{len(lesson_files)} lessons enriched")

    if enriched > 0:
        print("\nRegenerating PDFs...")
        from pdf_gen import generate_pdf
        for lesson_path in lesson_files:
            try:
                pdf_path = generate_pdf(str(lesson_path))
                print(f"  ✅ {Path(pdf_path).name}")
            except Exception as e:
                print(f"  ⚠️  {lesson_path.name}: {e}")


def show_book_references():
    lesson_files = sorted(LESSONS.glob("lezione_*.json"))
    total_refs = 0

    for lesson_path in lesson_files:
        data      = json.loads(lesson_path.read_text(encoding="utf-8"))
        lesson_id = lesson_path.stem.replace("lezione_", "")
        refs      = []

        for word in data.get("vocabulary", []):
            ref = word.get("book_ref", {})
            if ref and ref.get("lektion"):
                refs.append(
                    f"  📚 {word.get('german','')} → "
                    f"Lektion {ref['lektion']} p.{ref['book_page']} "
                    f"({ref.get('semantic_field','')})"
                )

        for gp in data.get("grammar_points", []):
            ref = gp.get("book_ref", {})
            if ref and ref.get("lektion"):
                refs.append(
                    f"  📐 {gp.get('rule','')} → "
                    f"Lektion {ref['lektion']} p.{ref['book_page']}"
                )

        if refs:
            print(f"\n{lesson_id} ({len(refs)} refs):")
            for r in refs[:8]:
                print(r)
            if len(refs) > 8:
                print(f"  ... +{len(refs)-8} more")
            total_refs += len(refs)

    print(f"\nTotal cross-references: {total_refs}")


if __name__ == "__main__":
    import sys
    if "--show" in sys.argv:
        show_book_references()
    else:
        enrich_all_lessons()