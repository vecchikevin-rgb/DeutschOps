# anki_feeder.py
# Legge un file JSON estratto e crea carte in Anki automaticamente

import json
import requests
from pathlib import Path
from datetime import date


ANKICONNECT_URL = "http://localhost:8765"
DECK_NAME = "Deutsch::DeutschOps"  # crea automaticamente deck e sotto-deck


def ankiconnect(action: str, **params) -> dict:
    """
    Funzione helper per chiamare AnkiConnect.
    Ogni azione è una POST a localhost:8765 con JSON.
    """
    payload = {"action": action, "version": 6, "params": params}
    response = requests.post(ANKICONNECT_URL, json=payload)
    result = response.json()
    
    if result.get("error"):
        raise Exception(f"AnkiConnect error: {result['error']}")
    
    return result["result"]


def ensure_deck_exists(deck_name: str):
    """Crea il deck se non esiste già."""
    existing = ankiconnect("deckNames")
    if deck_name not in existing:
        ankiconnect("createDeck", deck=deck_name)
        print(f"📁 Deck creato: {deck_name}")
    else:
        print(f"📁 Deck esistente: {deck_name}")


# Colori stile verbformen.com
GENDER_COLORS = {
    "der": "#0066cc",   # maschile — blu
    "die": "#cc0000",   # femminile — rosso
    "das": "#007700",   # neutro — verde
}
VERB_COLOR   = "#cc6600"   # verbi — arancione
DEFAULT_COLOR = "#555555"  # tutto il resto — grigio


def get_front_color(word: dict) -> str:
    """Determina il colore del fronte carta in base a categoria/genere."""
    cat = word.get("category", "")
    article = word.get("article", "").lower().strip()

    if "verb" in cat:
        return VERB_COLOR
    if article in GENDER_COLORS:
        return GENDER_COLORS[article]
    return DEFAULT_COLOR


def build_front(word: dict) -> str:
    german  = word.get("german", "")
    article = word.get("article", "").strip()
    plural  = word.get("plural", "").strip()
    level   = word.get("level", "")
    color   = get_front_color(word)

    # Rimuovi articolo duplicato
    if article and german.lower().startswith(article.lower() + " "):
        german = german[len(article)+1:].strip()

    # Costruisci HTML
    if article:
        front = (
            f'<span style="color:{color};font-weight:bold;font-size:1.15em">'
            f'{article} {german}</span>'
        )
    else:
        front = (
            f'<span style="color:{color};font-weight:bold;font-size:1.15em">'
            f'{german}</span>'
        )

    if plural:
        front += (
            f'<br><span style="color:#90a4ae;font-size:0.8em">'
            f'Pl: {plural}</span>'
        )

    if level:
        front += (
            f'&nbsp;<span style="color:#b0bec5;font-size:0.75em">'
            f'[{level}]</span>'
        )

    return front


def build_back(word: dict) -> str:
    """Costruisce il retro della carta."""
    back = f"<b>{word.get('italian', '')}</b>"
    if word.get("english"):
        back += f" &nbsp;·&nbsp; <i>{word['english']}</i>"
    if word.get("example_de"):
        back += f"<br><br><i>{word['example_de']}</i>"
    if word.get("example_it"):
        back += f"<br><small style='color:#666'>{word['example_it']}</small>"
    return back


def add_vocabulary_cards(vocabulary: list, lesson_date: str) -> int:
    added = 0
    skipped = 0

    for word in vocabulary:
        note = {
            "deckName": DECK_NAME,
            "modelName": "Basilare",
            "fields": {
                "Fronte": build_front(word),
                "Retro": build_back(word)
            },
            "tags": [
                "deutschops",
                f"lezione_{lesson_date}",
                "vocabolario",
                word.get("category", "other"),
                word.get("level", "unknown")
            ]
        }

        try:
            ankiconnect("addNote", note=note)
            color_info = word.get("article", word.get("category", ""))
            print(f"  ✅ {word['german']} → {word.get('italian','')}"
                  f"  [{color_info}]")
            added += 1
        except Exception as e:
            if "duplicate" in str(e).lower():
                print(f"  ⏭️  {word['german']} (già esistente, skippata)")
                skipped += 1
            else:
                print(f"  ❌ {word['german']}: {e}")

    return added


def add_phrase_cards(phrases: list, lesson_date: str) -> int:
    added = 0

    for phrase in phrases:
        front = (
            f'<span style="color:{DEFAULT_COLOR};font-weight:bold">'
            f'{phrase["german"]}</span>'
        )
        back = f"<b>{phrase.get('italian', phrase.get('english', ''))}</b>"
        if phrase.get("context"):
            back += f"<br><small style='color:#666'><i>{phrase['context']}</i></small>"

        note = {
            "deckName": DECK_NAME,
            "modelName": "Basilare",
            "fields": {"Fronte": front, "Retro": back},
            "tags": ["deutschops", f"lezione_{lesson_date}", "frasi"]
        }

        try:
            ankiconnect("addNote", note=note)
            added += 1
        except Exception as e:
            if "duplicate" not in str(e).lower():
                print(f"  ❌ {phrase['german']}: {e}")

    return added

def feed(json_path: str, lesson_date: str = None):
    """
    Funzione principale: legge il JSON e popola Anki.
    
    json_path: percorso al file .json estratto da extractor.py
    lesson_date: data della lezione (default: oggi)
    """
    if lesson_date is None:
        lesson_date = date.today().isoformat()
    
    json_path = Path(json_path)
    if not json_path.exists():
        raise FileNotFoundError(f"JSON non trovato: {json_path}")
    
    data = json.loads(json_path.read_text(encoding="utf-8"))
    
    print(f"📚 Argomento: {data.get('topic', 'N/A')}")
    print(f"📅 Data lezione: {lesson_date}")
    
    # Verifica connessione AnkiConnect
    try:
        version = ankiconnect("version")
        print(f"🔌 AnkiConnect v{version} connesso\n")
    except Exception:
        print("❌ AnkiConnect non raggiungibile. Assicurati che Anki sia aperto.")
        return False
    
    ensure_deck_exists(DECK_NAME)
    
    # Aggiunge vocabolario
    vocab = data.get("vocabulary", [])
    print(f"\n📝 Aggiungo {len(vocab)} parole vocabolario...")
    added_vocab = add_vocabulary_cards(vocab, lesson_date)
    
    # Aggiunge frasi
    phrases = data.get("phrases", [])
    print(f"\n💬 Aggiungo {len(phrases)} frasi utili...")
    added_phrases = add_phrase_cards(phrases, lesson_date)
    
    # Riepilogo
    print(f"\n{'='*40}")
    print(f"✅ Carte aggiunte: {added_vocab + added_phrases}")
    print(f"   Vocabolario: {added_vocab}/{len(vocab)}")
    print(f"   Frasi: {added_phrases}/{len(phrases)}")
    print(f"{'='*40}")
    print("Apri Anki → deck 'Deutsch::DeutschOps' per vedere le carte.")
    return True


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        d = sys.argv[1]
        feed(f"data/lezione_{d}.json", lesson_date=d)
    else:
        print("Uso: python anki_feeder.py <lesson_date>")
        print("Esempio: python anki_feeder.py 2026-05-29-stefanie")