---
name: process-lesson
description: Run the DeutschOps 6-step pipeline (main.py) on a new lesson, with preflight checks for Anki/env/credentials. Handles both video lessons and video-less lessons (external transcript only).
disable-model-invocation: true
---

# Process Lesson

Runs a new Stefanie lesson through the full DeutschOps pipeline. Two shapes:
**video lesson** (normal) and **video-less lesson** (only an external transcript,
e.g. Gemini, exists — no audio to transcribe).

## Usage

`/process-lesson <video-path> <YYYY-MM-DD-stefanie>`

Example: `/process-lesson "Audiolessons/Classroom with Stefanie 2026-07-08.mp4" 2026-07-08-stefanie`

If no arguments are given, look for the most recent unprocessed file in
`Audiolessons/` (cross-reference against `lesson_registry.json`) and confirm the
inferred date with the user before proceeding.

## Steps

1. **Preflight checks** — verify before running anything:
   - Anki is **actually open** and AnkiConnect responds on `localhost:8765`
     (`curl -s -m5 -X POST http://localhost:8765 -d '{"action":"version","version":6}'`
     should return `{"result":6,...}`). Preflight only *warns* if Anki is closed —
     Step 4 then defers and the task stays open (incomplete, not failed). Do not
     infer Anki state from the run continuing; check it explicitly and, if closed,
     tell the user to open Anki and stop.
   - `.env` exists and is non-empty.
   - `credentials.json` and `token.json` exist (Google OAuth2).
   - The input file exists at the given path.
   - The date arg isn't already in `lesson_registry.json` (warn if it looks like a re-run).

2. **Run the pipeline** exactly as documented in CLAUDE.md — do not reimplement or
   call individual step modules manually:
   ```powershell
   venv\Scripts\Activate.ps1
   $env:PYTHONIOENCODING="utf-8"; $env:WHISPER_MODE="local"
   python main.py "<video-path>" <date>
   ```
   Local Whisper transcription is long (~1 min per lesson-minute) — run it in the
   background and poll the log rather than blocking. The PowerShell
   `NativeCommandError` noise around tqdm progress bars on stderr is harmless.

3. **Report results** — surface any step failures from `main.py` output clearly
   (which of the 6 steps failed), and confirm the expected outputs exist afterward:
   `transcripts/lezione_{date}.txt`, `data/lezione_{date}.json`,
   `pdfs/lezione_{date}.pdf`, and that the Google Doc was updated. On success the
   source input is auto-moved to `Audiolessons/_processed/` (20-day TTL) — see below.

## Video-less lesson (external transcript only)

When a lesson has **no audio/video**, only a ready transcript (e.g. Gemini):

1. Copy the raw text **verbatim** (UTF-8, via Read→Write, not a shell pipe; do
   **not** clean it — cleaning risks dropping German) into
   `transcripts/lezione_{date}-stefanie.txt`.
2. Write `transcripts/lezione_{date}-stefanie.meta.json` =
   `{"duration_minutes": <real lesson minutes, e.g. from the last timestamp>, "cost_eur": 0}`.
   External transcription is free; without this file the registry/dashboard logs a
   ~0-minute lesson (fallback stats the tiny `.txt`).
3. Run `main.py` passing **the raw `.txt` as the dummy audio arg**:
   `python main.py "Audiolessons/<raw-transcript>.txt" <date>-stefanie`.
   `check_video` ignores it (non-video suffix), `prepare_audio` leaves it as-is
   (<20MB), and **Step 2 skips** because the canonical transcript already exists.
   Extraction quality is inherently noisier on a raw dialogue — that's the source,
   not a bug.

## Staging & cleanup (`Audiolessons/_processed/`)

On successful completion `main.py` moves the **consumed source input** (original
video, or the raw external `.txt`) into `Audiolessons/_processed/`, timestamped;
`cleanup_expired()` deletes anything older than **20 days** at the start of each run.
Never route canonical files (`transcripts/`, `data/`, `pdfs/`) or the compressed
audio (`lezione_*-compressed.mp4`) there — `archive_cleanup.py` protects them, and
a video-less lesson's canonical transcript is irreplaceable. See CLAUDE.md
("Staging input a scadenza").

Do not skip preflight and jump straight to `python main.py` — most pipeline
failures in this project trace back to Anki not being open or an expired Google
token, both caught cheaply upfront.
