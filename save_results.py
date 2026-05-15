# save_results.py — utility condivisa per salvare risultati esercizi
import json
from pathlib import Path
from datetime import datetime

RESULTS_FILE = Path("data/exercise_results.json")

def save_session_result(score: int, total: int, types_used: list, levels_used: list):
    if RESULTS_FILE.exists():
        results = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
    else:
        results = {"sessions": []}

    results["sessions"].append({
        "date": datetime.now().isoformat(),
        "score": score,
        "total": total,
        "pct": round(score/total*100) if total else 0,
        "types": types_used,
        "levels": levels_used
    })

    RESULTS_FILE.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

def load_results() -> dict:
    if not RESULTS_FILE.exists():
        return {"sessions": []}
    return json.loads(RESULTS_FILE.read_text(encoding="utf-8"))