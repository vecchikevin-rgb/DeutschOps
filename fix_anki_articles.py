# fix_anki_articles.py
# Trova e corregge le carte Anki con articolo duplicato nel campo Fronte

from pathlib import Path
import requests
from anki_feeder import ankiconnect, build_front, build_back

ANKICONNECT_URL = "http://localhost:8765"
ARTICLES = ["der ", "die ", "das "]

def ankiconnect(action: str, **params):
    r = requests.post(ANKICONNECT_URL, json={
        "action": action, "version": 6, "params": params
    })
    result = r.json()
    if result.get("error"):
        raise Exception(f"AnkiConnect error: {result['error']}")
    return result["result"]

def apply_colors_to_existing():
    """Applica colori e livello alle carte esistenti leggendo i JSON."""
    import json as _json
    from anki_feeder import build_front, build_back

    print("\n🎨 Applico colori e livello alle carte esistenti...")

    # Carica tutto il vocabolario dai JSON
    all_vocab = []
    for f in Path("data").glob("*.json"):
        try:
            d = _json.loads(f.read_text(encoding="utf-8"))
            if "vocabulary" in d:
                all_vocab.extend(d["vocabulary"])
        except Exception:
            pass

    # Dedup per parola tedesca
    seen = {}
    for w in all_vocab:
        key = w.get("german","").strip().lower()
        if key and key not in seen:
            seen[key] = w

    print(f"   Vocabolario disponibile: {len(seen)} parole")

    # Leggi tutte le carte Anki
    note_ids = ankiconnect("findNotes", query="deck:Deutsch")
    notes    = ankiconnect("notesInfo", notes=note_ids)

    updated = 0
    skipped = 0

    for note in notes:
        front_raw = note["fields"]["Fronte"]["value"]

        # Estrai testo pulito rimuovendo HTML
        import re
        clean = re.sub(r'<[^>]+>', '', front_raw).strip().lower()

        # Prova lookup diretto e senza articolo
        word_data = seen.get(clean)
        if not word_data:
            for art in ["der ", "die ", "das "]:
                if clean.startswith(art):
                    word_data = seen.get(clean[len(art):])
                    if word_data:
                        break

        if word_data:
            new_front = build_front(word_data)
            new_back  = build_back(word_data)
            if new_front != front_raw:
                ankiconnect("updateNoteFields", note={
                    "id": note["noteId"],
                    "fields": {
                        "Fronte": new_front,
                        "Retro": new_back
                    }
                })
                updated += 1
            else:
                skipped += 1
        else:
            skipped += 1

    print(f"   ✅ Aggiornate: {updated}")
    print(f"   ⏭️  Skippate (non trovate nel DB): {skipped}")

def fix_double_articles():
    print("🔍 Cerco carte con articolo duplicato...")

    # Prendi tutti i note ID dai deck DeutschOps
    note_ids = ankiconnect("findNotes", query="deck:Deutsch")
    notes = ankiconnect("notesInfo", notes=note_ids)

    fixed = 0
    for note in notes:
        front = note["fields"]["Fronte"]["value"]

        # Controlla se inizia con articolo duplicato tipo "der der..." o "die die..."
        for art in ARTICLES:
            if front.lower().startswith(art + art.strip()):
                # Rimuove il primo articolo
                new_front = front[len(art):]
                ankiconnect("updateNoteFields", note={
                    "id": note["noteId"],
                    "fields": {"Fronte": new_front}
                })
                print(f"  ✅ Fixata: '{front}' → '{new_front}'")
                fixed += 1
                break

            # Controlla anche pattern con HTML tipo "der <b>der Laptop</b>"
            import re
            pattern = rf'^{art.strip()}\s+{art.strip()}\s*'
            if re.match(pattern, front, re.IGNORECASE):
                new_front = re.sub(pattern, art, front, count=1, flags=re.IGNORECASE)
                ankiconnect("updateNoteFields", note={
                    "id": note["noteId"],
                    "fields": {"Fronte": new_front}
                })
                print(f"  ✅ Fixata (HTML): '{front[:40]}' → '{new_front[:40]}'")
                fixed += 1
                break

    print(f"\n{'='*40}")
    print(f"  Carte corrette: {fixed}/{len(notes)}")
    print(f"{'='*40}")

if __name__ == "__main__":
    fix_double_articles()
    apply_colors_to_existing()