# error_extractor.py
# Mines Kevin's German mistakes (and Stefanie's corrections) from the raw
# lesson transcripts, building a cumulative "error notebook" (data/error_db.json).
# This is the highest-value didactic signal: it's KEVIN's own recurring errors,
# not generic vocabulary. After several lessons the recurring patterns surface.
#
# Cost: 1 Claude call per lesson (~€0.02). Uses the same model as extractor.py.

import os
import sys
import json
from pathlib import Path
from datetime import datetime, date
from collections import Counter

from dotenv import load_dotenv
import anthropic

load_dotenv()
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

ERROR_DB = Path("data/error_db.json")
MODEL = "claude-sonnet-4-5"

# Canonical error categories — keep stable so patterns aggregate over time.
CATEGORIES = [
    "Genus",              # wrong der/die/das
    "Wortstellung",       # word order (V2, verb-final in Nebensatz, TeKaMoLo)
    "Präposition",        # wrong/incorrect preposition or case after it
    "Kasus",              # Akkusativ/Dativ/Genitiv mistakes
    "Verbform",           # conjugation, tense, auxiliary haben/sein, Perfekt
    "Wortwahl",           # wrong word choice / false friend / unnatural phrasing
    "Adjektivdeklination",
    "Aussprache",         # pronunciation
    "Sonstiges",          # other
]

SYSTEM_PROMPT = f"""You analyse a raw, UNDIARIZED transcript of a 1-on-1 German lesson.
Student: Kevin (Italian native, A2→B1). Teacher: Stefanie (German native).
The lesson is mostly in English with German examples; the transcript is noisy
(Whisper errors, connection chit-chat like "I hear you bad" — IGNORE that).

Your ONLY job: extract the moments where KEVIN made a German mistake and Stefanie
corrected it (or where she explicitly corrected a wrong form/word/order). Infer the
speakers from the pedagogical pattern (a wrong attempt followed by a correction,
"we don't say X, we say Y", "again", "auf Deutsch ...", "the correct form is ...").

Be CONSERVATIVE: only include clear corrections of Kevin's German. Do NOT invent
errors, do NOT include Stefanie teaching brand-new vocab that Kevin never got wrong,
do NOT include English/Italian chit-chat.

Return ONLY valid JSON (no backticks, no prose):
{{"errors":[{{"category":"<one of: {', '.join(CATEGORIES)}>","kevin_said":"<the wrong German Kevin produced, or '' if only implied>","correction":"<the correct German form>","rule":"<short rule name, e.g. 'Perfekt mit sein bei Bewegung'>","explanation_en":"<1-2 sentences, why it was wrong>","example_correct":"<one correct example sentence in German>"}}]}}

If there are no clear corrections, return {{"errors":[]}}."""


def parse_json_safe(raw: str):
    if not raw or not raw.strip():
        return None
    clean = raw.strip()
    if clean.startswith("```"):
        clean = "\n".join(clean.split("\n")[1:-1]).strip()
    start, end = clean.find("{"), clean.rfind("}") + 1
    if start >= 0 and end > start:
        clean = clean[start:end]
    try:
        return json.loads(clean)
    except json.JSONDecodeError as e:
        print(f"   Warning: JSON parse error: {e}")
        return None


def load_db() -> dict:
    if ERROR_DB.exists():
        try:
            return json.loads(ERROR_DB.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"errors": [], "lessons_processed": [], "last_updated": None}


def save_db(db: dict):
    ERROR_DB.parent.mkdir(exist_ok=True)
    db["last_updated"] = datetime.now().isoformat(timespec="seconds")
    ERROR_DB.write_text(json.dumps(db, ensure_ascii=False, indent=2),
                        encoding="utf-8")


def extract_errors_from_transcript(transcript_path: str, lesson_date: str) -> list:
    """Single Claude call: mine corrections from one transcript."""
    text = Path(transcript_path).read_text(encoding="utf-8")
    print(f"   Transcript: {Path(transcript_path).name} ({len(text)} char)")

    resp = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"=== TRANSCRIPT ===\n{text}"}],
    )
    cost = (resp.usage.input_tokens * 0.000003 +
            resp.usage.output_tokens * 0.000015)
    data = parse_json_safe(resp.content[0].text)
    errors = (data or {}).get("errors", [])
    for e in errors:
        e["lesson_date"] = lesson_date
        # normalise category to the canonical set
        if e.get("category") not in CATEGORIES:
            e["category"] = "Sonstiges"
    print(f"   {len(errors)} correzioni estratte | {cost:.3f} EUR")
    return errors


def update_from_lesson(transcript_path: str, lesson_date: str) -> list:
    """Idempotent per lesson: re-running replaces that lesson's errors."""
    db = load_db()
    errors = extract_errors_from_transcript(transcript_path, lesson_date)
    # remove any previous entries for this lesson, then add fresh ones
    db["errors"] = [e for e in db["errors"]
                    if e.get("lesson_date") != lesson_date] + errors
    if lesson_date not in db["lessons_processed"]:
        db["lessons_processed"].append(lesson_date)
    save_db(db)
    print(f"   error_db.json: {len(db['errors'])} errori totali "
          f"su {len(db['lessons_processed'])} lezioni")
    return errors


def pattern_report() -> dict:
    """Aggregate recurring error categories — the core insight."""
    db = load_db()
    by_cat = Counter(e.get("category", "Sonstiges") for e in db["errors"])
    by_rule = Counter(e.get("rule", "?") for e in db["errors"])
    return {
        "total_errors": len(db["errors"]),
        "lessons": len(db["lessons_processed"]),
        "by_category": by_cat.most_common(),
        "top_rules": by_rule.most_common(10),
    }


def print_report():
    r = pattern_report()
    print(f"\n{'='*50}\n  QUADERNO ERRORI — pattern ricorrenti\n{'='*50}")
    print(f"  {r['total_errors']} errori su {r['lessons']} lezioni\n")
    print("  Per categoria:")
    for cat, n in r["by_category"]:
        bar = "█" * n
        print(f"    {cat:20s} {n:3d}  {bar}")
    print("\n  Regole più ricorrenti:")
    for rule, n in r["top_rules"]:
        if n > 1:
            print(f"    {n}x  {rule}")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] == "--report":
        print_report()
    elif args[0] == "--all":
        # process every transcript in transcripts/
        for tp in sorted(Path("transcripts").glob("lezione_*.txt")):
            ld = tp.stem.replace("lezione_", "")
            print(f"\n>>> {ld}")
            update_from_lesson(str(tp), ld)
        print_report()
    elif args[0] == "--lesson" and len(args) > 1:
        ld = args[1]
        update_from_lesson(f"transcripts/lezione_{ld}.txt", ld)
    else:
        print("Uso: python error_extractor.py [--report | --all | --lesson <date>]")
