# main.py
import sys
import json
import os
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
from grammar_book import update_from_lesson as update_grammar_book
from generate_astra_prompts import generate_all_prompts

def prepare_audio(audio_path: str, lesson_date: str) -> str:
    """
    Se il file è un video (>20MB), lo comprime in audio.
    Mantiene max 5 video nella cartella Audiolessons — elimina il più vecchio.
    Restituisce il percorso del file audio da usare.
    """
    audio_path = Path(audio_path)
    compressed = Path(f"Audiolessons/lezione_{lesson_date}-compressed.mp4")

    # Comprimi se necessario
    if audio_path.stat().st_size > 20 * 1024 * 1024:
        print(f"🎬 Video rilevato ({audio_path.stat().st_size/1024/1024:.0f}MB) — comprimo...")
        os.system(
            f'ffmpeg.exe -i "{audio_path}" -vn -ar 16000 -ac 1 -b:a 32k '
            f'"{compressed}" -y -loglevel quiet'
        )
        print(f"✅ Audio: {compressed.name} "
              f"({compressed.stat().st_size/1024/1024:.1f}MB)")
    else:
        compressed = audio_path

    # Mantieni max 5 video in Audiolessons — elimina il più vecchio
    video_files = sorted(
        Path("Audiolessons").glob("Classroom with Stefanie*.mp4"),
        key=lambda f: f.stat().st_mtime
    )
    if len(video_files) > 5:
        to_delete = video_files[0]  # il più vecchio
        to_delete.unlink()
        print(f"🗑️  Eliminato video vecchio: {to_delete.name}")

    return str(compressed)

def process_lesson(audio_path: str, lesson_date: str = None):

    if lesson_date is None:
        audio_path = prepare_audio(audio_path, lesson_date)
        lesson_date = date.today().isoformat()

    print(f"\n{'='*50}")
    print(f"  DeutschOps — Lezione {lesson_date}")
    print(f"{'='*50}\n")

    transcript_path = Path(f"transcripts/lezione_{lesson_date}.txt")
    json_path       = Path(f"data/lezione_{lesson_date}.json")
    pdf_path_str    = f"pdfs/lezione_{lesson_date}.pdf"

    # ── Step 1: Google Doc ──────────────────────────────
    print("STEP 1/6 — Lettura Google Doc")
    print("-" * 30)
    doc_data = read_and_diff(label=lesson_date)
    doc_new  = doc_data["new_content"]
    doc_full = doc_data["full_text"]

    # ── Step 2: Trascrizione ────────────────────────────
    if transcript_path.exists():
        print(f"\nSTEP 2/6 — Trascrizione audio")
        print("-" * 30)
        print(f"♻️  Transcript già esistente — skip trascrizione")
        print(f"   {transcript_path}")
    else:
        print(f"\nSTEP 2/6 — Trascrizione audio")
        print("-" * 30)
        transcribe(audio_path, output_filename=f"lezione_{lesson_date}")

    # Leggi durata e costo reali
    meta_path = Path(f"transcripts/lezione_{lesson_date}.meta.json")
    if meta_path.exists():
        meta             = json.loads(meta_path.read_text(encoding="utf-8"))
        duration_minutes = meta.get("duration_minutes", 0)
        transcript_cost  = meta.get("cost_eur", 0)
    else:
        size_mb          = Path(audio_path).stat().st_size / (1024 * 1024)
        duration_minutes = size_mb * 2.1
        transcript_cost  = duration_minutes * 0.006

    # ── Step 3: Estrazione ──────────────────────────────
    if json_path.exists():
        print(f"\nSTEP 3/6 — Estrazione con Claude")
        print("-" * 30)
        print(f"♻️  JSON già esistente — skip estrazione")
        print(f"   {json_path}")
        data = json.loads(json_path.read_text(encoding="utf-8"))
    else:
        print(f"\nSTEP 3/6 — Estrazione con Claude")
        print("-" * 30)
        data = extract(
            transcript_path=str(transcript_path),
            output_filename=f"lezione_{lesson_date}",
            doc_new_content=doc_new,
            doc_full_content=doc_full
        )

    # ── Step 4: Anki ────────────────────────────────────
    print(f"\nSTEP 4/6 — Caricamento in Anki")
    print("-" * 30)
    feed(str(json_path), lesson_date=lesson_date)

    # ── Step 5: PDF ─────────────────────────────────────
    print(f"\nSTEP 5/6 — Generazione PDF")
    print("-" * 30)
    pdf_path_str = generate_pdf(str(json_path))

    # ── Step 6: Google Doc ──────────────────────────────
    print(f"\nSTEP 6/6 — Aggiornamento Google Doc")
    print("-" * 30)
    try:
        append_lesson_summary(
            lesson_json_path=str(json_path),
            lesson_date=lesson_date,
            pdf_path=pdf_path_str
        )
    except Exception as e:
        print(f"⚠️  Doc writer fallito (non bloccante): {e}")

    # ── Registro + Vocab DB ─────────────────────────────
    claude_cost = 0.09
    register_lesson(
        lesson_date=lesson_date,
        audio_file=audio_path,
        data=data,
        transcript_cost=transcript_cost,
        claude_cost=claude_cost,
        duration_minutes=duration_minutes
    )
    update_from_lesson(str(json_path), lesson_date)
    update_grammar_book(f"data/lezione_{lesson_date}.json")

    
    # dopo update_from_lesson:
    generate_all_prompts()

    print(f"\n{'='*50}")
    print(f"  Lezione {lesson_date} processata.")
    print(f"  Transcript : {transcript_path}")
    print(f"  Dati       : {json_path}")
    print(f"  PDF        : {pdf_path_str}")
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