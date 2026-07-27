# bulk_import_book.py
# Importa vocabolario del libro in Anki deck Deutsch::DaF Kompakt

import json
from pathlib import Path
from anki_feeder import ankiconnect, build_front, build_back

book_db   = json.loads(Path("data/book_db.json").read_text(encoding="utf-8"))
all_vocab = book_db.get("vocabulary", [])
print(f"Total words: {len(all_vocab)}")

# Crea deck se non esiste
ankiconnect("createDeck", deck="Deutsch::DaF Kompakt")

# Trova note già esistenti per deduplicazione
existing = set()
try:
    note_ids = ankiconnect("findNotes", query="deck:\"Deutsch::DaF Kompakt\"")
    notes    = ankiconnect("notesInfo", notes=note_ids)
    for note in notes:
        front = note["fields"]["Fronte"]["value"]
        import re
        clean = re.sub(r'<[^>]+>', '', front).strip().lower()
        existing.add(clean)
    print(f"Existing cards: {len(existing)}")
except Exception:
    print("No existing cards found")

added = skipped = errors = 0

for word in all_vocab:
    # Fix articolo duplicato
    german  = word.get("german", "")
    article = word.get("article", "")
    if article and german.lower().startswith(article.lower() + " "):
        word["german"] = german[len(article)+1:].strip()

    # Check duplicato manuale
    check_key = (
        (f"{article} {word['german']}".strip() if article
         else word["german"]).lower()
    )
    if check_key in existing:
        skipped += 1
        continue

    front = build_front(word)
    back  = build_back(word)

    level    = word.get("level", "")
    sem_field = (word.get("semantic_field", "")
                 .replace(" ", "_").replace("/", "_"))

    try:
        result = ankiconnect("addNote", note={
            "deckName":  "Deutsch::DaF Kompakt",
            "modelName": "Basilare",
            "fields":    {"Fronte": front, "Retro": back},
            "options":   {"allowDuplicate": False,
                          "duplicateScope": "collection"},
            "tags":      [t for t in [level, sem_field] if t]
        })
        if result:
            added   += 1
            existing.add(check_key)
        else:
            skipped += 1
    except Exception as e:
        if "duplicate" in str(e).lower():
            skipped += 1
        else:
            errors += 1
            print(f"   Error: {word.get('german','')} — {e}")

print(f"\nDone: {added} added | {skipped} skipped | {errors} errors")
print(f"Deck 'Deutsch::DaF Kompakt' updated")