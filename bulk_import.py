# bulk_import.py
# Legge l'intero Google Doc e importa tutto il vocabolario in Anki
# Operazione una-tantum per caricare lo storico

import json
import os
from pathlib import Path
from dotenv import load_dotenv
import anthropic
from doc_reader import get_drive_service, read_doc
from anki_feeder import ankiconnect, ensure_deck_exists, DECK_NAME

load_dotenv()
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

BULK_DECK = "Deutsch::Storico"  # deck separato per non mischiare con lezioni

BULK_PROMPT = """Sei un tutor di tedesco. Hai il contenuto completo di un Google Doc
usato durante lezioni di tedesco per uno studente italiano livello A2→B1.

Il documento contiene sezioni con vocabolario, grammatica, esempi e esercizi.

Estrai TUTTO il vocabolario presente nel documento. SOLO JSON valido, zero backtick.

Formato:
{
  "vocabulary": [
    {
      "german": "aufstehen",
      "article": "",
      "plural": "",
      "category": "verb_separable",
      "italian": "alzarsi",
      "english": "to get up",
      "example_de": "Ich stehe um 7 Uhr auf.",
      "level": "A1"
    }
  ]
}

Regole:
- Includi TUTTO: verbi regolari, irregolari, separabili, modali, nomi, aggettivi, avverbi, espressioni
- category: verb_regular, verb_irregular, verb_separable, verb_modal, noun, adjective, adverb, phrase, expression
- article: der/die/das per sostantivi, stringa vuota per il resto
- plural: includi se presente nel doc, altrimenti stringa vuota
- Per i verbi modali includi la coniugazione nell'esempio
- NON duplicare parole — se appare più volte, includila una sola volta
- level: A1, A2, B1, B2"""


def extract_vocab_from_doc(doc_text: str) -> list:
    """
    Manda il doc a Claude a blocchi e raccoglie tutto il vocabolario.
    Il doc è lungo quindi lo dividiamo in 4 parti.
    """
    chunk_size = len(doc_text) // 4
    chunks = [
        doc_text[:chunk_size],
        doc_text[chunk_size:chunk_size*2],
        doc_text[chunk_size*2:chunk_size*3],
        doc_text[chunk_size*3:]
    ]

    all_vocab = []
    seen_words = set()

    for i, chunk in enumerate(chunks, 1):
        print(f"\n🧠 Analisi parte {i}/4 ({len(chunk)} caratteri)...")

        response = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=16000,
            messages=[{
                "role": "user",
                "content": f"{BULK_PROMPT}\n\nDOCUMENTO (parte {i}/4):\n{chunk}"
            }]
        )

        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1]).strip()

        # Debug: mostra se il JSON è troncato
        if not raw.endswith("}"):
            print(f"   ⚠️  Risposta troncata (finisce con: ...{raw[-80:]})")
            print(f"   Token output usati: {response.usage.output_tokens}")
            # Ripara il JSON troncato: trova l'ultimo oggetto completo e chiude
            last_brace = raw.rfind("},")
            if last_brace > 0:
                raw = raw[:last_brace+1] + "\n  ]\n}"
                print(f"   🔧 JSON riparato automaticamente")

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"   ❌ JSON non parsabile nella parte {i}: {e}")
            print(f"   Salto questa parte e continuo.")
            continue

        vocab = data.get("vocabulary", [])

        # Deduplication cross-chunk
        new_words = 0
        for word in vocab:
            key = word["german"].lower().strip()
            if key not in seen_words:
                seen_words.add(key)
                all_vocab.append(word)
                new_words += 1

        cost = (response.usage.input_tokens * 0.000003 +
                response.usage.output_tokens * 0.000015)
        print(f"   ✅ {new_words} parole nuove estratte | 💶 €{cost:.3f}")

    return all_vocab


def add_bulk_to_anki(vocabulary: list) -> tuple[int, int]:
    """
    Aggiunge tutto il vocabolario ad Anki nel deck Storico.
    Restituisce (aggiunte, skippate).
    """
    ensure_deck_exists(BULK_DECK)

    added = 0
    skipped = 0

    print(f"\n📇 Caricamento {len(vocabulary)} parole in Anki...")

    for word in vocabulary:
        front = word["german"]
        if word.get("article"):
            front = f"{word['article']} {word['german']}"
        if word.get("plural") and word["plural"]:
            front += f"<br><small>Plural: {word['plural']}</small>"

        back = f"<b>{word.get('italian', '')}</b>"
        if word.get("english"):
            back += f" &nbsp;|&nbsp; <i>{word['english']}</i>"
        if word.get("example_de"):
            back += f"<br><br>{word['example_de']}"

        # Tag per categoria e livello
        tags = [
            "storico",
            f"cat_{word.get('category', 'unknown')}",
            f"level_{word.get('level', 'unknown')}"
        ]

        note = {
            "deckName": BULK_DECK,
            "modelName": "Basilare",
            "fields": {"Fronte": front, "Retro": back},
            "tags": tags
        }

        try:
            ankiconnect("addNote", note=note)
            added += 1
        except Exception as e:
            if "duplicate" in str(e).lower():
                skipped += 1
            else:
                print(f"   ❌ {word['german']}: {e}")

    return added, skipped


def run_bulk_import():
    """Funzione principale."""
    print(f"\n{'='*55}")
    print(f"  DeutschOps — Import Storico da Google Doc")
    print(f"{'='*55}\n")

    # Leggi doc
    print("📄 Lettura Google Doc...")
    service = get_drive_service()
    doc_text = read_doc(service)
    print(f"   {len(doc_text)} caratteri totali\n")

    # Estrai vocabolario
    vocab = extract_vocab_from_doc(doc_text)
    print(f"\n📚 Totale parole estratte (dedup): {len(vocab)}")

    # Salva lista locale per riferimento
    output = Path("data/bulk_vocab.json")
    output.write_text(
        json.dumps({"vocabulary": vocab}, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"💾 Salvato in: {output}")

    # Carica in Anki
    added, skipped = add_bulk_to_anki(vocab)

    print(f"\n{'='*55}")
    print(f"  Import completato")
    print(f"  Carte aggiunte:  {added}")
    print(f"  Duplicate skip:  {skipped}")
    print(f"  Deck:            {BULK_DECK}")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    run_bulk_import()