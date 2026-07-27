# watch.py
# Detects new lesson recordings dropped into Audiolessons/ that haven't been
# processed yet (no data/lezione_<date>.json) and, on request, runs the full
# pipeline on them (local transcription). Lets new lessons flow without typing
# the long filename by hand. Recovery of corrupt videos is handled by preflight.
#
#   python watch.py            # list unprocessed lessons
#   python watch.py --process  # process them all (local, sequential)

import os
import re
import sys
import subprocess
from pathlib import Path

AUDIO = Path("Audiolessons")
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def unprocessed() -> list:
    out = []
    seen = set()
    for v in sorted(AUDIO.glob("Classroom with Stefanie*.mp4")):
        if "fixed" in v.name.lower():
            continue
        m = DATE_RE.search(v.name)
        if not m:
            continue
        lesson_date = f"{m.group(1)}-stefanie"
        if lesson_date in seen:
            continue
        seen.add(lesson_date)
        if not Path(f"data/lezione_{lesson_date}.json").exists():
            out.append((v, lesson_date))
    return out


def main(process: bool):
    todo = unprocessed()
    if not todo:
        print("✅ Nessuna lezione nuova da elaborare.")
        return
    print(f"📥 {len(todo)} lezioni NON elaborate:")
    for v, ld in todo:
        print(f"   - {ld}   ({v.name}, {v.stat().st_size/1024**3:.1f}GB)")
    if not process:
        print("\nRilancia con  python watch.py --process  per elaborarle (locale).")
        return
    env = dict(os.environ, WHISPER_MODE="local",
               PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    for v, ld in todo:
        print(f"\n{'='*50}\n>>> Elaboro {ld}\n{'='*50}")
        subprocess.run([sys.executable, "main.py", str(v), ld], env=env, check=False)


if __name__ == "__main__":
    main(process="--process" in sys.argv[1:])
