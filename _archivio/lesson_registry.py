# lesson_registry.py
# Tiene traccia di tutte le lezioni elaborate e organizza i file

import json
from pathlib import Path
from datetime import datetime

REGISTRY_FILE = Path("lesson_registry.json")

def load_registry() -> dict:
    if REGISTRY_FILE.exists():
        return json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
    return {"lessons": [], "stats": {"total": 0, "total_cost_eur": 0.0, "total_minutes": 0}}

def save_registry(registry: dict):
    REGISTRY_FILE.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

def register_lesson(lesson_date: str, audio_file: str, data: dict,
                    transcript_cost: float, claude_cost: float, duration_minutes: float):
    """
    Registra una lezione elaborata nel registro.
    Chiamata da main.py dopo ogni elaborazione riuscita.
    """
    registry = load_registry()

    # Controlla se la lezione è già registrata (evita duplicati)
    existing = [l for l in registry["lessons"] if l["id"] == lesson_date]
    if existing:
        print(f"⚠️  Lezione {lesson_date} già nel registro — aggiorno")
        registry["lessons"] = [l for l in registry["lessons"] if l["id"] != lesson_date]

    entry = {
        "id": lesson_date,
        "date": lesson_date.split("-stefanie")[0].split("-v")[0],  # data pulita
        "audio_file": audio_file,
        "topic": data.get("topic", "N/A"),
        "summary_it": data.get("summary_it", "")[:150] + "...",
        "vocabulary_count": len(data.get("vocabulary", [])),
        "grammar_count": len(data.get("grammar_points", [])),
        "phrases_count": len(data.get("phrases", [])),
        "doc_sections": data.get("doc_sections_covered", []),
        "homework": data.get("homework", ""),
        "duration_minutes": round(duration_minutes, 1),
        "cost_whisper_eur": round(transcript_cost, 3),
        "cost_claude_eur": round(claude_cost, 3),
        "cost_total_eur": round(transcript_cost + claude_cost, 3),
        "files": {
            "transcript": f"transcripts/lezione_{lesson_date}.txt",
            "data": f"data/lezione_{lesson_date}.json",
            "anki_deck": "Deutsch::DeutschOps"
        },
        "processed_at": datetime.now().isoformat()
    }

    registry["lessons"].append(entry)

    # Aggiorna statistiche globali
    registry["stats"]["total"] = len(registry["lessons"])
    registry["stats"]["total_cost_eur"] = round(
        sum(l["cost_total_eur"] for l in registry["lessons"]), 3
    )
    registry["stats"]["total_minutes"] = round(
        sum(l["duration_minutes"] for l in registry["lessons"]), 1
    )

    save_registry(registry)
    print(f"📋 Lezione registrata: {lesson_date} | "
          f"Costo totale: €{entry['cost_total_eur']:.3f} | "
          f"Durata: {duration_minutes:.0f} min")

def print_registry():
    """Stampa un riepilogo di tutte le lezioni elaborate."""
    registry = load_registry()
    lessons = registry["lessons"]

    if not lessons:
        print("Nessuna lezione nel registro.")
        return

    print(f"\n{'='*60}")
    print(f"  DeutschOps — Registro Lezioni")
    print(f"{'='*60}")
    print(f"  Lezioni totali:    {registry['stats']['total']}")
    print(f"  Audio totale:      {registry['stats']['total_minutes']:.0f} min "
          f"({registry['stats']['total_minutes']/60:.1f}h)")
    print(f"  Costo totale API:  €{registry['stats']['total_cost_eur']:.2f}")
    print(f"{'='*60}\n")

    for i, lesson in enumerate(sorted(lessons, key=lambda x: x["date"]), 1):
        print(f"  #{i:02d} [{lesson['date']}] {lesson['topic']}")
        print(f"       📝 {lesson['vocabulary_count']} parole | "
              f"📐 {lesson['grammar_count']} regole | "
              f"⏱️  {lesson['duration_minutes']:.0f} min | "
              f"💶 €{lesson['cost_total_eur']:.3f}")
        if lesson.get("homework"):
            print(f"       📌 Compiti: {lesson['homework'][:80]}")
        print()

if __name__ == "__main__":
    print_registry()