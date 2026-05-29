"""
task_tracker.py — Write-ahead log / two-phase commit per la pipeline DeutschOps.

PROBLEMA RISOLTO
----------------
Prima, lo snapshot del Google Doc veniva salvato nello STEP 1. Se la pipeline
crashava dopo (es. mkl_malloc nella trascrizione), al rilancio lo snapshot era
gia' aggiornato -> "nessuna modifica rilevata" -> il contenuto del doc non
entrava mai nell'estrazione. Lo stato veniva "committato" prima che il lavoro
fosse finito.

SOLUZIONE
---------
Ogni lezione apre un "task file" (tasks/<lesson_date>.json) che:
  1. Dichiara che la lezione e' IN LAVORAZIONE (se esiste al rilancio = run
     precedente non finito -> resume/repair).
  2. Traccia quali STAGE sono completati (cosi' non si ri-trascrive se la
     trascrizione era gia' fatta -> risparmio di tempo/costo).
  3. Mette gli effetti IRREVERSIBILI (snapshot del doc) in "deferred commits":
     vengono applicati SOLO a fine pipeline, in commit_and_finish().
  4. A completamento totale: applica i deferred commit e CANCELLA il task file.

Cosi' un crash a meta' non perde nulla e non corrompe lo stato.

USO TIPICO in main.py (vedi note in fondo al file):

    from task_tracker import TaskTracker

    task = TaskTracker(lesson_date)          # apre o riprende

    if not task.is_done("doc"):
        diff, new_snapshot = read_doc_diff(...)   # NON salva lo snapshot!
        task.save_stage("doc", {"diff": diff})
        task.defer_commit("snapshot", {"path": snap_path, "content": new_snapshot})
    else:
        diff = task.stage_result("doc")["diff"]   # riusa il diff gia' calcolato

    if not task.is_done("transcript"):
        path = transcribe(...)
        task.save_stage("transcript", {"path": path})
    transcript_path = task.stage_result("transcript")["path"]

    # ... extraction, anki, pdf, doc_update con lo stesso pattern ...

    task.commit_and_finish(commit_handlers={"snapshot": _write_snapshot})

Lanciato da solo, stampa lo stato dei task pendenti:
    python task_tracker.py            # lista task aperti (=run non finiti)
    python task_tracker.py --clear 2026-05-28-stefanie   # forza chiusura
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone

TASKS_DIR = "tasks"

# Ordine canonico delle fasi della pipeline. Usato solo per stampare lo stato
# in modo leggibile; non e' vincolante per save_stage().
PIPELINE_STAGES = ["doc", "transcript", "extraction", "anki", "pdf", "doc_update"]


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _atomic_write_json(path: str, data: dict) -> None:
    """Scrive il JSON in modo atomico (tmp + rename) cosi' il task file stesso
    non puo' corrompersi se il processo muore a meta' scrittura."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)  # atomico su Windows e POSIX
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


class TaskTracker:
    """Gestisce il ciclo di vita di un task di lezione."""

    def __init__(self, lesson_date: str, tasks_dir: str = TASKS_DIR):
        self.lesson_date = lesson_date
        self.tasks_dir = tasks_dir
        self.path = os.path.join(tasks_dir, f"{lesson_date}.json")
        self.resumed = os.path.exists(self.path)

        if self.resumed:
            with open(self.path, "r", encoding="utf-8") as f:
                self.data = json.load(f)
            done = [s for s, v in self.data.get("stages", {}).items()
                    if v.get("status") == "done"]
            print(f"[TASK] Run precedente NON completato per {lesson_date}.")
            print(f"[TASK] Fasi gia' completate: {', '.join(done) or '(nessuna)'}")
            print(f"[TASK] Riprendo da dove si era interrotto (resume).")
        else:
            self.data = {
                "lesson_date": lesson_date,
                "created_at": _utcnow(),
                "updated_at": _utcnow(),
                "stages": {},          # stage_name -> {status, result, at}
                "deferred_commits": {},  # key -> payload da applicare a fine run
            }
            self._flush()
            print(f"[TASK] Nuovo task aperto: {self.path}")

    # ---------- stato delle fasi ----------

    def is_done(self, stage: str) -> bool:
        return self.data["stages"].get(stage, {}).get("status") == "done"

    def save_stage(self, stage: str, result: dict | None = None) -> None:
        """Marca una fase come completata e ne salva l'output riutilizzabile
        (es. il path del transcript, il diff del doc)."""
        self.data["stages"][stage] = {
            "status": "done",
            "result": result or {},
            "at": _utcnow(),
        }
        self._flush()
        print(f"[TASK] Fase completata: {stage}")

    def stage_result(self, stage: str) -> dict:
        """Recupera l'output di una fase gia' completata."""
        return self.data["stages"].get(stage, {}).get("result", {})

    # ---------- effetti irreversibili (commit differiti) ----------

    def defer_commit(self, key: str, payload: dict) -> None:
        """Registra un effetto irreversibile (es. scrittura snapshot) da
        applicare SOLO quando l'intera pipeline e' andata a buon fine."""
        self.data["deferred_commits"][key] = payload
        self._flush()

    def has_deferred(self, key: str) -> bool:
        return key in self.data.get("deferred_commits", {})

    # ---------- chiusura ----------

    def commit_and_finish(self, commit_handlers: dict | None = None) -> None:
        """Applica tutti i commit differiti tramite gli handler forniti, poi
        cancella il task file. Va chiamato SOLO a fine pipeline riuscita.

        commit_handlers: dict {key: callable(payload)} che esegue l'effetto
        reale (es. scrivere lo snapshot su disco)."""
        handlers = commit_handlers or {}
        for key, payload in self.data.get("deferred_commits", {}).items():
            handler = handlers.get(key)
            if handler is None:
                print(f"[TASK][WARN] Nessun handler per commit '{key}', salto.")
                continue
            handler(payload)
            print(f"[TASK] Commit applicato: {key}")

        if os.path.exists(self.path):
            os.remove(self.path)
        print(f"[TASK] Task {self.lesson_date} COMPLETATO e chiuso.")

    def abort(self, reason: str = "") -> None:
        """Da chiamare in un except: registra il motivo ma LASCIA il task file
        in modo che il prossimo run riprenda. Non cancella nulla."""
        self.data["last_error"] = {"reason": reason, "at": _utcnow()}
        self._flush()
        print(f"[TASK] Run interrotto, task conservato per il resume. ({reason})")

    # ---------- interni ----------

    def _flush(self) -> None:
        self.data["updated_at"] = _utcnow()
        _atomic_write_json(self.path, self.data)


# ---------- utilita' a livello di cartella ----------

def list_pending(tasks_dir: str = TASKS_DIR) -> list[str]:
    """Ritorna i lesson_date con un task aperto (= run non completati)."""
    if not os.path.isdir(tasks_dir):
        return []
    out = []
    for fn in sorted(os.listdir(tasks_dir)):
        if fn.endswith(".json"):
            out.append(fn[:-5])
    return out


def _print_status(tasks_dir: str = TASKS_DIR) -> None:
    pending = list_pending(tasks_dir)
    if not pending:
        print("Nessun task pendente. Tutte le pipeline sono chiuse correttamente.")
        return
    print(f"Task PENDENTI (run non completati): {len(pending)}")
    for ld in pending:
        with open(os.path.join(tasks_dir, f"{ld}.json"), encoding="utf-8") as f:
            d = json.load(f)
        done = [s for s, v in d.get("stages", {}).items()
                if v.get("status") == "done"]
        missing = [s for s in PIPELINE_STAGES if s not in done]
        print(f"\n  {ld}")
        print(f"    creato:     {d.get('created_at')}")
        print(f"    aggiornato: {d.get('updated_at')}")
        print(f"    fatte:      {', '.join(done) or '(nessuna)'}")
        print(f"    mancanti:   {', '.join(missing) or '(nessuna)'}")
        if d.get("last_error"):
            print(f"    ultimo errore: {d['last_error'].get('reason')}")
        print(f"    -> rilancia: python main.py <audio> {ld}")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--clear":
        target = os.path.join(TASKS_DIR, f"{sys.argv[2]}.json")
        if os.path.exists(target):
            os.remove(target)
            print(f"Task {sys.argv[2]} rimosso a mano.")
        else:
            print(f"Nessun task {sys.argv[2]} trovato.")
    else:
        _print_status()