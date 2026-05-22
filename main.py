# main.py
import sys
import os
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
from grammar_book import update_from_lesson as update_grammar_book
from generate_astra_prompts import generate_all_prompts


def prepare_audio(audio_path: str, lesson_date: str) -> str:
    """
    Comprimi video in audio se >20MB.
    Se il file compresso esiste gia, lo usa direttamente.
    Mantieni max 5 video originali nella cartella.
    """
    audio_path = Path(audio_path)
    compressed = Path(f"Audiolessons/lezione_{lesson_date}-compressed.mp4")

    if compressed.exists():
        print(f"   Already compressed: {compressed.name} "
              f"({compressed.stat().st_size/1024/1024:.1f}MB)")
        return str(compressed)

    if audio_path.stat().st_size > 20 * 1024 * 1024:
        size_mb = audio_path.stat().st_size / 1024 / 1024
        print(f"   Video detected ({size_mb:.0f}MB) -- compressing to audio...")
        os.system(
            f'ffmpeg.exe -i "{audio_path}" -vn -ar 16000 -ac 1 -b:a 32k '
            f'"{compressed}" -y -loglevel quiet'
        )
        if compressed.exists():
            new_mb = compressed.stat().st_size / 1024 / 1024
            print(f"   Compressed: {size_mb:.0f}MB -> {new_mb:.1f}MB")
        else:
            print("   Compression failed -- using original file")
            return str(audio_path)

        # Mantieni max 5 video originali
        videos = sorted(
            Path("Audiolessons").glob("Classroom with Stefanie*.mp4"),
            key=lambda f: f.stat().st_mtime
        )
        if len(videos) > 5:
            oldest = videos[0]
            oldest.unlink()
            print(f"   Deleted old video: {oldest.name}")

        return str(compressed)

    return str(audio_path)


def process_lesson(audio_path: str, lesson_date: str = None):

    if lesson_date is None:
        lesson_date = date.today().isoformat()

    print(f"\n{'='*50}")
    print(f"  DeutschOps -- Lesson {lesson_date}")
    print(f"{'='*50}\n")

    # Prepare audio (compress if video)
    print("PREP — Audio preparation")
    print("-" * 30)
    audio_path = prepare_audio(audio_path, lesson_date)

# Analisi speaker in background (non bloccante)
    from speaker_analysis import analyze_lesson
    try:
        print(f"📊 Avvio analisi speaker (in background)...")
        analyze_lesson(str(audio_path), lesson_date, backup=True)
    except Exception as e:
        print(f"⚠️  Speaker analysis skipped: {e}")
    
    
    transcript_path = Path(f"transcripts/lezione_{lesson_date}.txt")
    json_path       = Path(f"data/lezione_{lesson_date}.json")

    # Step 1: Google Doc
    print(f"\nSTEP 1/6 — Google Doc")
    print("-" * 30)
    doc_data = read_and_diff(label=f"pre_{lesson_date}")
    doc_new  = doc_data["new_content"]
    doc_full = doc_data["full_text"]

    # Step 2: Transcription
    if transcript_path.exists():
        print(f"\nSTEP 2/6 -- Transcription")
        print("-" * 30)
        print(f"   Already exists -- skipping: {transcript_path}")
    else:
        print(f"\nSTEP 2/6 -- Transcription")
        print("-" * 30)
        transcribe(audio_path, output_filename=f"lezione_{lesson_date}")

    # Read duration and cost from meta file
    meta_path = Path(f"transcripts/lezione_{lesson_date}.meta.json")
    if meta_path.exists():
        meta             = json.loads(meta_path.read_text(encoding="utf-8"))
        duration_minutes = meta.get("duration_minutes", 0)
        transcript_cost  = meta.get("cost_eur", 0)
    else:
        size_mb          = Path(audio_path).stat().st_size / (1024 * 1024)
        duration_minutes = size_mb * 2.1
        transcript_cost  = duration_minutes * 0.006

    # Step 3: Extraction
    if json_path.exists():
        print(f"\nSTEP 3/6 -- Extraction")
        print("-" * 30)
        print(f"   Already exists -- skipping: {json_path}")
        data = json.loads(json_path.read_text(encoding="utf-8"))
    else:
        print(f"\nSTEP 3/6 -- Extraction")
        print("-" * 30)
        data = extract(
            transcript_path=str(transcript_path),
            output_filename=f"lezione_{lesson_date}",
            doc_new_content=doc_new,
            doc_full_content=doc_full
        )

    # Step 4: Anki
    print(f"\nSTEP 4/6 -- Anki")
    print("-" * 30)
    feed(str(json_path), lesson_date=lesson_date)

    # Step 5: PDF
    print(f"\nSTEP 5/6 -- PDF generation")
    print("-" * 30)
    pdf_path = generate_pdf(str(json_path))

    # Step 6: Google Doc update
    print(f"\nSTEP 6/6 -- Google Doc update")
    print("-" * 30)
    try:
        append_lesson_summary(
            lesson_json_path=str(json_path),
            lesson_date=lesson_date,
            pdf_path=pdf_path
        )
    except Exception as e:
        print(f"   Doc writer failed (non-blocking): {e}")

    # Registry + Vocab DB + Grammar Book + Astra prompts
    claude_cost = 0.10
    register_lesson(
        lesson_date=lesson_date,
        audio_file=audio_path,
        data=data,
        transcript_cost=transcript_cost,
        claude_cost=claude_cost,
        duration_minutes=duration_minutes
    )
    update_from_lesson(str(json_path), lesson_date)
    update_grammar_book(str(json_path))

    print(f"\nGenerating Astra prompts...")
    generate_all_prompts()

    print(f"\n{'='*50}")
    print(f"  Lesson {lesson_date} complete.")
    print(f"  Transcript : transcripts/lezione_{lesson_date}.txt")
    print(f"  Data       : data/lezione_{lesson_date}.json")
    print(f"  PDF        : {pdf_path}")
    print(f"  Anki       : deck Deutsch::DeutschOps updated")
    print(f"  Google Doc : KPI + summary updated")
    print(f"  Astra      : astra_prompts/ updated")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print_registry()
        sys.exit(0)

    audio       = sys.argv[1]
    lesson_date = sys.argv[2] if len(sys.argv) > 2 else None
    process_lesson(audio, lesson_date)