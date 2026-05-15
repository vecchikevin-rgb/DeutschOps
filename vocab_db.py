# vocab_db.py
# Database master del vocabolario con tracking progressione per-parola
# Aggiornato automaticamente da ogni lezione elaborata

import json
from pathlib import Path
from datetime import date

DB_FILE = Path("data/vocab_db.json")


def load_db() -> dict:
    if DB_FILE.exists():
        return json.loads(DB_FILE.read_text(encoding="utf-8"))
    return {
        "words": {},        # chiave: german.lower() → dati parola
        "stats": {
            "total_words": 0,
            "by_category": {},
            "by_level": {}
        }
    }


def save_db(db: dict):
    DB_FILE.write_text(
        json.dumps(db, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def update_from_lesson(lesson_json_path: str, lesson_date: str = None):
    """
    Aggiorna il database con il vocabolario di una nuova lezione.
    Se la parola esiste già, aggiunge la lezione alla lista delle occorrenze.
    Se è nuova, la inserisce con tutti i metadati.
    """
    if lesson_date is None:
        lesson_date = date.today().isoformat()

    data = json.loads(Path(lesson_json_path).read_text(encoding="utf-8"))
    vocab = data.get("vocabulary", [])
    topic = data.get("topic", "")

    db = load_db()
    new_words = 0
    updated_words = 0

    for word in vocab:
        key = word.get("german", "").lower().strip()
        if not key:
            continue

        if key in db["words"]:
            # Parola già esistente — aggiunge occorrenza
            entry = db["words"][key]
            if lesson_date not in entry["seen_in_lessons"]:
                entry["seen_in_lessons"].append(lesson_date)
                entry["seen_in_topics"].append(topic)
                entry["occurrences"] = len(entry["seen_in_lessons"])
            updated_words += 1
        else:
            # Parola nuova
            db["words"][key] = {
                "german": word.get("german", ""),
                "article": word.get("article", ""),
                "plural": word.get("plural", ""),
                "category": word.get("category", ""),
                "italian": word.get("italian", ""),
                "english": word.get("english", ""),
                "example_de": word.get("example_de", ""),
                "level": word.get("level", ""),
                "first_seen": lesson_date,
                "seen_in_lessons": [lesson_date],
                "seen_in_topics": [topic],
                "occurrences": 1,
                "anki_status": "added"   # added / learning / known
            }
            new_words += 1

    # Aggiorna statistiche
    _update_stats(db)
    save_db(db)

    print(f"📊 Vocab DB aggiornato: +{new_words} nuove, {updated_words} aggiornate")
    print(f"   Totale parole nel database: {db['stats']['total_words']}")
    return new_words, updated_words


def _update_stats(db: dict):
    """Ricalcola le statistiche globali."""
    words = db["words"]
    db["stats"]["total_words"] = len(words)

    by_cat = {}
    by_level = {}
    for w in words.values():
        cat = w.get("category", "other")
        lvl = w.get("level", "?")
        by_cat[cat] = by_cat.get(cat, 0) + 1
        by_level[lvl] = by_level.get(lvl, 0) + 1

    db["stats"]["by_category"] = by_cat
    db["stats"]["by_level"] = by_level


def get_words_by_category(category: str) -> list:
    """Restituisce tutte le parole di una categoria."""
    db = load_db()
    return [w for w in db["words"].values() if w.get("category") == category]


def get_recurring_words(min_occurrences: int = 2) -> list:
    """Restituisce parole apparse in più lezioni — quelle più importanti."""
    db = load_db()
    return sorted(
        [w for w in db["words"].values() if w.get("occurrences", 1) >= min_occurrences],
        key=lambda x: x["occurrences"],
        reverse=True
    )


def print_stats():
    """Stampa statistiche del database."""
    db = load_db()
    stats = db["stats"]

    print(f"\n{'='*50}")
    print(f"  DeutschOps — Vocab Database")
    print(f"{'='*50}")
    print(f"  Totale parole: {stats['total_words']}")

    print(f"\n  Per categoria:")
    for cat, count in sorted(stats["by_category"].items(),
                              key=lambda x: x[1], reverse=True):
        bar = "█" * min(count, 30)
        print(f"    {cat:<20} {bar} {count}")

    print(f"\n  Per livello:")
    for lvl in ["A1", "A2", "B1", "B2", "?"]:
        count = stats["by_level"].get(lvl, 0)
        bar = "█" * min(count, 30)
        print(f"    {lvl:<6} {bar} {count}")

    recurring = get_recurring_words(2)
    if recurring:
        print(f"\n  Parole più ricorrenti (≥2 lezioni):")
        for w in recurring[:10]:
            print(f"    {w['german']:<20} → visto {w['occurrences']}x "
                  f"in: {', '.join(w['seen_in_lessons'])}")

    print(f"{'='*50}\n")


def build_from_existing_lessons():
    """
    Costruisce il database da zero leggendo tutti i JSON esistenti.
    Utile per inizializzare su lezioni già elaborate.
    """
    print("🔨 Costruzione database da lezioni esistenti...")
    data_files = sorted(Path("data").glob("lezione_*.json"))

    if not data_files:
        print("  Nessun file lezione trovato.")
        return

    # Reset DB
    DB_FILE.write_text(json.dumps({
        "words": {},
        "stats": {"total_words": 0, "by_category": {}, "by_level": {}}
    }, ensure_ascii=False, indent=2))

    for f in data_files:
        # Estrai data dal nome file
        lesson_date = f.stem.replace("lezione_", "").split("-stefanie")[0].split("-v")[0]
        print(f"  📄 {f.name}...")
        update_from_lesson(str(f), lesson_date)

    # Aggiungi anche bulk vocab con data "storico"
    bulk_path = Path("data/bulk_vocab.json")
    if bulk_path.exists():
        print(f"  📄 bulk_vocab.json...")
        bulk_data = json.loads(bulk_path.read_text(encoding="utf-8"))
        db = load_db()
        for word in bulk_data.get("vocabulary", []):
            key = word.get("german", "").lower().strip()
            if key and key not in db["words"]:
                db["words"][key] = {
                    **word,
                    "first_seen": "storico",
                    "seen_in_lessons": ["storico"],
                    "seen_in_topics": ["bulk_import"],
                    "occurrences": 1,
                    "anki_status": "added"
                }
        _update_stats(db)
        save_db(db)
        print(f"  ✅ Bulk vocab integrato")

    print_stats()


if __name__ == "__main__":
    build_from_existing_lessons()