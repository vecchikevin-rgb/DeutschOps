# extractor.py
# Legge un transcript audio + novità Google Doc
# e usa Claude per estrarre struttura didattica in JSON

import os
import json
from pathlib import Path
from dotenv import load_dotenv
import anthropic

load_dotenv()
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

EXTRACTION_PROMPT = """Sei un tutor di tedesco specializzato per studenti italiani.
Lo studente si chiama Kevin, è livello A2→B1, madrelingua italiana, studia tramite inglese.
La lezione è tenuta in inglese da una docente madrelingua tedesca.

Hai a disposizione DUE fonti:
1. TRANSCRIPT AUDIO: la lezione registrata (dialogo orale, spiegazioni, esercizi)
2. DOC NOVITÀ: le righe aggiunte nel Google Doc condiviso durante/dopo la lezione

Integra entrambe le fonti. Il doc è più preciso per grammatica e vocabolario scritto.
Il transcript è più ricco di contesto, esempi orali e nuances della spiegazione.

- IMPORTANT: the "german" field must NEVER include the article. 
  Write ONLY the base word. Article goes ONLY in "article" field.
  CORRECT: {"german": "Sorge", "article": "die"}
  WRONG:   {"german": "die Sorge", "article": "die"}

Estrai SOLO con JSON valido, zero testo aggiuntivo, zero backtick.

Formato esatto:
{
  "lesson_number": "stima il numero progressivo della lezione se deducibile, altrimenti stringa vuota",
  "topic": "argomento principale in 5 parole",
  "summary_en": "riassunto in inglese semplice (max 120 parole)",
  "summary_it": "stesso riassunto in italiano",
  "vocabulary": [
    {
      "german": "aufstehen",
      "article": "",
      "plural": "",
      "category": "verb_separable",
      "italian": "alzarsi",
      "english": "to get up",
      "example_de": "Ich stehe um 7 Uhr auf.",
      "example_it": "Mi alzo alle 7.",
      "level": "A1"
    }
  ],
  "grammar_points": [
    {
      "rule": "nome regola grammaticale",
      "explanation_en": "explanation in English, clear and concise",
      "examples": ["esempio 1 in tedesco", "esempio 2 in tedesco"]
    }
  ],
  "phrases": [
    {
      "german": "Wie geht's?",
      "english": "How are you?",
      "context": "informal greeting"
    }
  ],
  "homework": "compiti assegnati se menzionati nel transcript o nel doc, altrimenti stringa vuota",
  "comprehension_questions": [
    {"question_de": "domanda in tedesco", "answer_de": "risposta in tedesco"}
  ],
  "doc_sections_covered": ["lista delle sezioni del Google Doc toccate in questa lezione"]
}

Regole:
- vocabulary: estrai TUTTE le parole nuove per A1→B1, senza limite numerico. Includi tutto il vocabolario genuinamente presente nella lezione.
- category deve essere esattamente uno di: verb_regular, verb_irregular, verb_separable, verb_modal, noun, adjective, adverb, phrase, expression
- article: includi sempre per i sostantivi (der/die/das), lascia stringa vuota per il resto, senza ripetere se già presente
- plural: includi per i sostantivi quando deducibile, altrimenti stringa vuota
- level: A1, A2, B1 o B2 in base alla difficoltà della parola
- grammar_points: max 4, only those explicitly covered in the lesson. All explanations in English only.
- comprehension_questions: esattamente 3
- Se una parola appare sia nel doc che nel transcript, includila una sola volta con esempio dal transcript
- doc_sections_covered: usa i titoli delle sezioni del doc (es. '2. Akkusativ', '5. Modalverben 1')"""


def extract(transcript_path: str | Path, output_filename: str | None = None,
            doc_new_content: str = "", doc_full_content: str = "") -> dict:
    """
    Estrae struttura didattica da transcript audio + novità Google Doc.

    transcript_path:   percorso al file .txt del transcript
    output_filename:   nome del file .json di output (senza estensione)
    doc_new_content:   righe aggiunte nel Google Doc dall'ultima lezione
    doc_full_content:  testo completo del doc (per contesto, non usato nel prompt)

    Restituisce: dizionario Python con tutti i dati estratti
    """

    transcript_path = Path(transcript_path)

    if not transcript_path.exists():
        raise FileNotFoundError(f"Transcript non trovato: {transcript_path}")

    if output_filename is None:
        output_filename = transcript_path.stem

    output_path = Path("data") / f"{output_filename}.json"

    transcript_text = transcript_path.read_text(encoding="utf-8")

    print(f"📄 Transcript: {transcript_path.name} ({len(transcript_text)} caratteri)")

    # Costruisce il messaggio fondendo le due fonti
    user_content = f"{EXTRACTION_PROMPT}\n\n"
    user_content += f"=== TRANSCRIPT AUDIO ===\n{transcript_text}\n\n"

    if doc_new_content.strip():
        # Limita a 8000 caratteri — le novità recenti sono alla fine
        doc_trimmed = doc_new_content[-8000:] if len(doc_new_content) > 8000 else doc_new_content
        user_content += f"=== DOC NOVITÀ (righe aggiunte questa lezione) ===\n{doc_trimmed}\n\n"
        print(f"📝 Doc novità: {len(doc_trimmed)} caratteri inclusi "
              f"(totale diff: {len(doc_new_content)})")
    else:
        print("📝 Doc novità: nessuna (primo snapshot o nessuna modifica rilevata)")

    print("🧠 Invio a Claude per estrazione...")

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=16000,
        messages=[{
            "role": "user",
            "content": user_content
        }]
    )

    block = response.content[0]
    raw_text = block.text if block.type == "text" else ""

    # Pulizia difensiva backtick
    clean_text = raw_text.strip()
    if clean_text.startswith("```"):
        lines = clean_text.split("\n")
        clean_text = "\n".join(lines[1:-1]).strip()

    data = json.loads(clean_text)

    # Salva JSON formattato
    output_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    # Riepilogo output
    print(f"✅ Salvato: {output_path}")
    print(f"📚 Argomento: {data.get('topic', 'N/A')}")
    print(f"📝 Parole: {len(data.get('vocabulary', []))} | "
          f"Grammatica: {len(data.get('grammar_points', []))} | "
          f"Frasi: {len(data.get('phrases', []))}")

    if data.get("homework"):
        print(f"📌 Compiti: {data['homework']}")

    if data.get("doc_sections_covered"):
        print(f"📖 Sezioni doc coperte: {', '.join(data['doc_sections_covered'])}")

    print(f"\n--- RIASSUNTO ---")
    print(f"EN: {data.get('summary_en', '')}")
    print(f"IT: {data.get('summary_it', '')}")

    print(f"\n--- VOCABOLARIO ({len(data.get('vocabulary', []))} parole) ---")
    for word in data.get("vocabulary", []):
        article = f"{word.get('article', '')} " if word.get("article") else ""
        print(f"  [{word.get('category', '?')}] {article}{word['german']} "
              f"→ {word['italian']} ({word.get('level', '?')})")

    cost = (response.usage.input_tokens * 0.000003 +
            response.usage.output_tokens * 0.000015)
    print(f"\n💶 Costo Claude: €{cost:.3f}")

    return data


if __name__ == "__main__":
    extract(
        transcript_path="transcripts/lezione_2026-05-15-stefanie.txt",
        output_filename="lezione_2026-05-15-stefanie",
        doc_new_content="",
        doc_full_content=""
    )