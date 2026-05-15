# main.py
import sys
import json
from datetime import date
from pathlib import Path

from transcriber import transcribe
from extractor import extract
from anki_feeder import feed
from doc_reader import read_and_diff
from lesson_registry import register_lesson, print_registry
from pdf_gen import generate_pdf
from doc_writer import append_lesson_summary
from vocab_db import update_from_lesson


def process_lesson(audio_path: str, lesson_date: str | None = None):

    if lesson_date is None:
        lesson_date = date.today().isoformat()

    print(f"\n{'='*50}")
    print(f"  DeutschOps — Lezione {lesson_date}")
    print(f"{'='*50}\n")

    # Step 1: Google Doc
    print("STEP 1/6 — Lettura Google Doc")
    print("-" * 30)
    doc_data = read_and_diff(label=lesson_date)
    doc_new  = doc_data["new_content"]
    doc_full = doc_data["full_text"]

    # Step 2: Trascrizione
    print(f"\nSTEP 2/6 — Trascrizione audio")
    print("-" * 30)
    transcribe(audio_path, output_filename=f"lezione_{lesson_date}")

    # Leggi durata e costo reali dal file meta
    meta_path = Path(f"transcripts/lezione_{lesson_date}.meta.json")
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        duration_minutes = meta.get("duration_minutes", 0)
        transcript_cost  = meta.get("cost_eur", 0)
    else:
        # Fallback stima da dimensione file
        size_mb          = Path(audio_path).stat().st_size / (1024 * 1024)
        duration_minutes = size_mb * 2.1
        transcript_cost  = duration_minutes * 0.006

    # Step 3: Estrazione
    print(f"\nSTEP 3/6 — Estrazione con Claude")
    print("-" * 30)
    data = extract(
        transcript_path=f"transcripts/lezione_{lesson_date}.txt",
        output_filename=f"lezione_{lesson_date}",
        doc_new_content=doc_new,
        doc_full_content=doc_full
    )

    # Step 4: Anki
    print(f"\nSTEP 4/6 — Caricamento in Anki")
    print("-" * 30)
    feed(f"data/lezione_{lesson_date}.json", lesson_date=lesson_date)

    # Step 5: PDF
    print(f"\nSTEP 5/6 — Generazione PDF")
    print("-" * 30)
    pdf_path = generate_pdf(f"data/lezione_{lesson_date}.json")

    # Step 6: Google Doc update
    print(f"\nSTEP 6/6 — Aggiornamento Google Doc")
    print("-" * 30)
    try:
        append_lesson_summary(
            lesson_json_path=f"data/lezione_{lesson_date}.json",
            lesson_date=lesson_date,
            pdf_path=pdf_path
        )
    except Exception as e:
        print(f"⚠️  Doc writer fallito (non bloccante): {e}")

    # Registro + Vocab DB
    claude_cost = 0.08  # media osservata
    register_lesson(
        lesson_date=lesson_date,
        audio_file=audio_path,
        data=data,
        transcript_cost=transcript_cost,
        claude_cost=claude_cost,
        duration_minutes=duration_minutes
    )
    update_from_lesson(f"data/lezione_{lesson_date}.json", lesson_date)

    print(f"\n{'='*50}")
    print(f"  Lezione {lesson_date} processata.")
    print(f"  Transcript : transcripts/lezione_{lesson_date}.txt")
    print(f"  Dati       : data/lezione_{lesson_date}.json")
    print(f"  PDF        : {pdf_path}")
    print(f"  Anki       : deck Deutsch::DeutschOps aggiornato")
    print(f"  Google Doc : tab KPI + summary aggiornato")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print_registry()
        sys.exit(0)

    audio      = sys.argv[1]
    lesson_date = sys.argv[2] if len(sys.argv) > 2 else None
    process_lesson(audio, lesson_date)