# main.py
import sys
import json
import subprocess
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
from notebooklm_export import update_from_lesson as update_notebooklm
from error_extractor import update_from_lesson as update_errors
from error_pdf import generate_error_pdf

from task_tracker import TaskTracker
from preflight import run_preflight


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
        # ffmpeg.exe vive nella cartella del progetto, non nel PATH.
        # subprocess.run con lista di argomenti: niente shell, niente problemi
        # di quoting (os.system su Windows sbaglia il parsing con piu' path
        # quotati -> "ffmpeg non riconosciuto" / "compression failed").
        ffmpeg = Path(__file__).resolve().parent / "ffmpeg.exe"
        ffmpeg_bin = str(ffmpeg) if ffmpeg.exists() else "ffmpeg"
        subprocess.run(
            [ffmpeg_bin, "-i", str(audio_path),
             "-vn", "-ar", "16000", "-ac", "1", "-b:a", "32k",
             str(compressed), "-y", "-loglevel", "quiet"],
            check=False,
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

    # Apre (o riprende) il task. Se esiste gia' = run precedente non finito.
    task = TaskTracker(lesson_date)

    # Preflight: recupera video corrotto (moov mancante -> untrunc) e avvisa su
    # token Google / sessione NotebookLM / Anki PRIMA di iniziare il lavoro.
    audio_path, _preflight = run_preflight(audio_path)

    # Prepare audio (compress if video)
    print("PREP — Audio preparation")
    print("-" * 30)
    audio_path = prepare_audio(audio_path, lesson_date)

    transcript_path = Path(f"transcripts/lezione_{lesson_date}.txt")
    json_path       = Path(f"data/lezione_{lesson_date}.json")

    try:
        # ---------------------------------------------------------------
        # Step 1: Google Doc
        # Lo snapshot NON viene piu' scritto qui: read_and_diff calcola il
        # diff e restituisce il nuovo snapshot, che mettiamo in commit
        # differito. Verra' scritto solo a fine pipeline (commit_and_finish).
        # ---------------------------------------------------------------
        print(f"\nSTEP 1/6 — Google Doc")
        print("-" * 30)
        if not task.is_done("doc"):
            doc_data = read_and_diff(label=f"pre_{lesson_date}", write_snapshot=False)
            task.save_stage("doc", {"new_content": doc_data["new_content"]})
            # effetto irreversibile differito: scrittura snapshot
            task.defer_commit("snapshot", {
                "path": doc_data["snapshot_path"],
                "content": doc_data["snapshot_content"],
            })
        else:
            print("   Gia' fatto in un run precedente -- riuso il diff.")
        doc_new = task.stage_result("doc")["new_content"]

        # ---------------------------------------------------------------
        # Step 2: Transcription
        # ---------------------------------------------------------------
        print(f"\nSTEP 2/6 -- Transcription")
        print("-" * 30)
        if transcript_path.exists():
            print(f"   Already exists -- skipping: {transcript_path}")
            task.save_stage("transcript", {"path": str(transcript_path)})
        elif task.is_done("transcript"):
            print("   Gia' fatto in un run precedente -- skip.")
        else:
            transcribe(audio_path, output_filename=f"lezione_{lesson_date}")
            task.save_stage("transcript", {"path": str(transcript_path)})

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

        # ---------------------------------------------------------------
        # Step 3: Extraction
        # ---------------------------------------------------------------
        print(f"\nSTEP 3/6 -- Extraction")
        print("-" * 30)
        if json_path.exists():
            print(f"   Already exists -- skipping: {json_path}")
            data = json.loads(json_path.read_text(encoding="utf-8"))
            task.save_stage("extraction", {"path": str(json_path)})
        elif task.is_done("extraction"):
            print("   Gia' fatto in un run precedente -- carico il JSON.")
            data = json.loads(json_path.read_text(encoding="utf-8"))
        else:
            data = extract(
                transcript_path=str(transcript_path),
                output_filename=f"lezione_{lesson_date}",
                doc_new_content=doc_new,
            )
            task.save_stage("extraction", {"path": str(json_path)})

        # ---------------------------------------------------------------
        # Step 4: Anki  (dipendenza fragile: app desktop puo' essere chiusa)
        # ---------------------------------------------------------------
        print(f"\nSTEP 4/6 -- Anki")
        print("-" * 30)
        if task.is_done("anki"):
            print("   Gia' fatto in un run precedente -- skip.")
        else:
            ok = feed(str(json_path), lesson_date=lesson_date)
            # feed() ritorna True solo se AnkiConnect era raggiungibile.
            # Se Anki era chiuso, NON marchiamo la fase: al prossimo run
            # (con Anki aperto) ripartira' da qui.
            if ok:
                task.save_stage("anki", {})
            else:
                print("   [TASK] Anki non completato: verra' ritentato al "
                      "prossimo run (apri Anki e rilancia).")

        # ---------------------------------------------------------------
        # Step 5: PDF
        # ---------------------------------------------------------------
        print(f"\nSTEP 5/6 -- PDF generation")
        print("-" * 30)
        pdf_path = generate_pdf(str(json_path))
        task.save_stage("pdf", {"path": str(pdf_path)})

        # ---------------------------------------------------------------
        # Step 6: Google Doc update + registry + DB + grammar + astra + NLM
        # ---------------------------------------------------------------
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
        # Questi sono idempotenti per data, quindi li eseguiamo solo se la
        # fase doc_update non era gia' stata completata.
        if not task.is_done("doc_update"):
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

            # Quaderno degli errori: mina gli errori di Kevin dal transcript e
            # rigenera il PDF cumulativo (non-blocking: feature di studio).
            print(f"\nUpdating error notebook...")
            try:
                update_errors(str(transcript_path), lesson_date)
                generate_error_pdf()
            except Exception as e:
                print(f"   Error notebook failed (non-blocking): {e}")

            print(f"\nGenerating Astra prompts...")
            generate_all_prompts()

            print(f"\nUpdating NotebookLM...")
            try:
                update_notebooklm(str(json_path))
            except Exception as e:
                print(f"   NotebookLM update failed (non-blocking): {e}")

            task.save_stage("doc_update", {})

        # ---------------------------------------------------------------
        # Commit finale: scrive lo snapshot del doc SOLO ora, poi chiude
        # il task. Se Anki era ancora da fare, il task resta aperto.
        # ---------------------------------------------------------------
        def _write_snapshot(payload):
            Path(payload["path"]).parent.mkdir(parents=True, exist_ok=True)
            with open(payload["path"], "w", encoding="utf-8") as f:
                f.write(payload["content"])
            print(f"   Snapshot doc scritto: {payload['path']}")

        all_core_done = all(
            task.is_done(s) for s in
            ["doc", "transcript", "extraction", "pdf", "doc_update"]
        )
        if all_core_done and task.is_done("anki"):
            task.commit_and_finish(commit_handlers={"snapshot": _write_snapshot})
        else:
            # Scriviamo comunque lo snapshot (il doc e' stato letto e usato),
            # ma lasciamo il task aperto perche' manca Anki.
            if task.has_deferred("snapshot"):
                _write_snapshot(task.data["deferred_commits"]["snapshot"])
                # rimuove il commit per non riscriverlo al prossimo run
                task.data["deferred_commits"].pop("snapshot", None)
                task._flush()
            print("   [TASK] Pipeline quasi completa: manca solo Anki. "
                  "Task lasciato aperto per il ritento.")

    except Exception as e:
        task.abort(str(e))
        raise

    print(f"\n{'='*50}")
    print(f"  Lesson {lesson_date} complete.")
    print(f"  Transcript : transcripts/lezione_{lesson_date}.txt")
    print(f"  Data       : data/lezione_{lesson_date}.json")
    print(f"  PDF        : {pdf_path}")
    print(f"  Anki       : {'updated' if task.is_done('anki') else 'PENDING (Anki chiuso)'}")
    print(f"  Google Doc : KPI + summary updated")
    print(f"  Astra      : astra_prompts/ updated")
    print(f"  NotebookLM : sync attempted")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print_registry()
        sys.exit(0)

    audio       = sys.argv[1]
    lesson_date = sys.argv[2] if len(sys.argv) > 2 else None
    process_lesson(audio, lesson_date)