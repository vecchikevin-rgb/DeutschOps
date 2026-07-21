---
name: process-lesson
description: Run the DeutschOps 6-step pipeline (main.py) on a new lesson video, with preflight checks for Anki/env/credentials before launching.
disable-model-invocation: true
---

# Process Lesson

Runs a new Stefanie lesson through the full DeutschOps pipeline.

## Usage

`/process-lesson <video-path> <YYYY-MM-DD-stefanie>`

Example: `/process-lesson "Audiolessons/Classroom with Stefanie 2026-07-08.mp4" 2026-07-08-stefanie`

If no arguments are given, look for the most recent unprocessed file in `Audiolessons/` (cross-reference against `lesson_registry.json`) and confirm the inferred date with the user before proceeding.

## Steps

1. **Preflight checks** — verify before running anything:
   - Anki is open and AnkiConnect responds on `localhost:8765` (a quick HTTP check is fine; if it fails, tell the user to open Anki and stop).
   - `.env` exists and is non-empty.
   - `credentials.json` and `token.json` exist (Google OAuth2).
   - The video file exists at the given path.
   - The date arg isn't already in `lesson_registry.json` (warn if it looks like a re-run).

2. **Run the pipeline** exactly as documented in CLAUDE.md — do not reimplement or call individual step modules manually:
   ```batch
   venv\Scripts\activate
   set PYTHONIOENCODING=utf-8
   set WHISPER_MODE=local
   python main.py "<video-path>" <date>
   ```
   On Windows this project uses PowerShell — activate via `venv\Scripts\Activate.ps1` and set env vars with `$env:PYTHONIOENCODING="utf-8"; $env:WHISPER_MODE="local"`.

3. **Report results** — surface any step failures from `main.py` output clearly (which of the 6 steps failed), and confirm the expected outputs exist afterward: `transcripts/lezione_{date}.txt`, `data/lezione_{date}.json`, `pdfs/lezione_{date}.pdf`, and that the Google Doc was updated.

Do not skip preflight and jump straight to `python main.py` — most pipeline failures in this project trace back to Anki not being open or an expired Google token, both caught cheaply upfront.
