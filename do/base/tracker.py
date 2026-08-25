"""Write-ahead log della pipeline.  [PORTATO da task_tracker.py]

IL PROBLEMA CHE HA RISOLTO (e che non va reintrodotto)
Nella versione ancora precedente lo snapshot del Google Doc veniva salvato
allo Step 1. Se la pipeline crashava dopo — succedeva davvero, es. mkl_malloc
durante la trascrizione — al rilancio lo snapshot risultava gia' aggiornato,
quindi il diff diceva "nessuna modifica" e il contenuto del Doc non entrava
mai nell'estrazione. Lo stato veniva committato prima che il lavoro fosse
finito.

DUE INVARIANTI DA CONSERVARE
1. Una fase completata non si rifa' mai. Il risultato riutilizzabile (il path
   del transcript, il diff del Doc) resta nel task file.
2. Gli effetti IRREVERSIBILI sono differiti: si registrano con `differisci()` e
   si applicano solo in `chiudi()`, a pipeline completa. Un crash a meta' non
   perde nulla e non corrompe lo stato.

Il task file viene cancellato solo a fine run riuscito: `tasks/` vuota
significa "tutto a posto". I file rimasti sono cicatrici di run non chiusi —
nella v1 ce n'erano 4, quasi tutti per Anki chiuso allo Step 4.

Rispetto alla v1 cambia solo il contorno: i percorsi vengono da base.paths e i
nomi dei metodi sono in italiano, coerenti col resto del package. La logica di
stato e la scrittura atomica sono identiche.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .paths import TASKS

# Ordine canonico delle fasi. Serve solo a stampare lo stato in modo leggibile:
# non vincola salva_fase().
FASI = ["doc", "transcript", "estrazione", "anki", "pdf", "doc_update"]


def _adesso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _scrivi_atomico(path: Path, dati: dict) -> None:
    """Scrive il JSON con tmp + rename, cosi' il task file stesso non puo'
    corrompersi se il processo muore a meta' scrittura."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(dati, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)      # atomico su Windows e POSIX
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


# Mappa dei nomi v1 -> v2. Le chiavi del task file sono cambiate con la
# traduzione in italiano; senza questa mappa un task v1 verrebbe letto come
# "nessuna fase completata" e il resume rifarebbe TUTTO — inclusa la
# trascrizione e l'estrazione a pagamento, per lavoro gia' fatto e pagato.
_FASI_V1 = {"extraction": "estrazione"}
_CHIAVI_V1 = {
    "stages": "fasi",
    "deferred_commits": "differiti",
    "lesson_date": "data_lezione",
    "created_at": "creato",
    "updated_at": "aggiornato",
    "last_error": "ultimo_errore",
}
_CAMPI_FASE_V1 = {"status": "stato", "result": "risultato", "at": "quando"}


def _migra_v1(d: dict) -> dict:
    """Rende leggibile un task file scritto dalla v1.

    Non riscrive il file su disco: la traduzione avviene in memoria e il
    prossimo _flush() lo salva nel formato nuovo.
    """
    if "fasi" in d:
        return d                                    # gia' v2

    out = {_CHIAVI_V1.get(k, k): v for k, v in d.items()}
    out.setdefault("fasi", {})
    out.setdefault("differiti", {})

    fasi = {}
    for nome, val in (out.get("fasi") or {}).items():
        if isinstance(val, dict):
            val = {_CAMPI_FASE_V1.get(k, k): v for k, v in val.items()}
        fasi[_FASI_V1.get(nome, nome)] = val
    out["fasi"] = fasi

    if err := out.get("ultimo_errore"):
        if isinstance(err, dict):
            out["ultimo_errore"] = {"motivo": err.get("reason", err.get("motivo")),
                                    "quando": err.get("at", err.get("quando"))}
    return out


class Task:
    """Ciclo di vita di una lezione in lavorazione."""

    def __init__(self, data_lezione: str):
        self.data_lezione = data_lezione
        self.path = TASKS / f"{data_lezione}.json"
        self.ripreso = self.path.exists()

        if self.ripreso:
            self.dati = _migra_v1(json.loads(self.path.read_text(encoding="utf-8")))
            fatte = [f for f, v in self.dati.get("fasi", {}).items()
                     if v.get("stato") == "done"]
            print(f"[TASK] Run precedente NON completato per {data_lezione}.")
            print(f"[TASK] Fasi gia' fatte: {', '.join(fatte) or '(nessuna)'}")
            print("[TASK] Riprendo da dove si era interrotto.")
        else:
            self.dati = {
                "data_lezione": data_lezione,
                "creato": _adesso(),
                "aggiornato": _adesso(),
                "fasi": {},                # nome -> {stato, risultato, quando}
                "differiti": {},           # chiave -> payload da applicare a fine run
            }
            self._flush()
            print(f"[TASK] Nuovo task aperto: {self.path.name}")

    # ---------------------------------------------------------- fasi
    def fatta(self, fase: str) -> bool:
        return self.dati["fasi"].get(fase, {}).get("stato") == "done"

    def salva_fase(self, fase: str, risultato: dict | None = None) -> None:
        """Marca una fase completata e ne salva l'output riutilizzabile."""
        self.dati["fasi"][fase] = {
            "stato": "done",
            "risultato": risultato or {},
            "quando": _adesso(),
        }
        self._flush()
        print(f"[TASK] Fase completata: {fase}")

    def risultato(self, fase: str) -> dict:
        return self.dati["fasi"].get(fase, {}).get("risultato", {})

    # ---------------------------------------------------------- effetti differiti
    def differisci(self, chiave: str, payload: dict) -> None:
        """Registra un effetto irreversibile da applicare SOLO a fine run."""
        self.dati["differiti"][chiave] = payload
        self._flush()

    def ha_differito(self, chiave: str) -> bool:
        return chiave in self.dati.get("differiti", {})

    # ---------------------------------------------------------- chiusura
    def chiudi(self, handler: dict | None = None) -> None:
        """Applica i commit differiti e cancella il task file.

        Da chiamare SOLO a pipeline riuscita. `handler` mappa chiave ->
        callable(payload) che esegue l'effetto reale.
        """
        handler = handler or {}
        for chiave, payload in self.dati.get("differiti", {}).items():
            fn = handler.get(chiave)
            if fn is None:
                print(f"[TASK][ATTENZIONE] Nessun handler per '{chiave}', salto.")
                continue
            fn(payload)
            print(f"[TASK] Commit applicato: {chiave}")

        if self.path.exists():
            self.path.unlink()
        print(f"[TASK] Task {self.data_lezione} COMPLETATO e chiuso.")

    def interrompi(self, motivo: str = "") -> None:
        """Da chiamare in un except: registra il motivo e LASCIA il task file,
        cosi' il prossimo run riprende. Non cancella nulla."""
        self.dati["ultimo_errore"] = {"motivo": motivo, "quando": _adesso()}
        self._flush()
        print(f"[TASK] Run interrotto, task conservato per il resume. ({motivo})")

    # ---------------------------------------------------------- interni
    def _flush(self) -> None:
        self.dati["aggiornato"] = _adesso()
        _scrivi_atomico(self.path, self.dati)


# -------------------------------------------------------------- livello cartella
def pendenti() -> list[str]:
    """Lezioni con un task aperto, cioe' run mai completati."""
    if not TASKS.is_dir():
        return []
    return sorted(f.stem for f in TASKS.glob("*.json"))


def dettaglio_pendenti() -> list[dict]:
    """Per il briefing: cosa manca a ogni run non chiuso.

    Nella v1 questa informazione esisteva ma non la guardava nessuno: 4 lezioni
    sono rimaste senza carte Anki per settimane. Il briefing la mostra.
    """
    out = []
    for data in pendenti():
        d = _migra_v1(json.loads((TASKS / f"{data}.json").read_text(encoding="utf-8")))
        fatte = [f for f, v in d.get("fasi", {}).items() if v.get("stato") == "done"]
        out.append({
            "data": data,
            "fatte": fatte,
            "mancanti": [f for f in FASI if f not in fatte],
            "ultimo_errore": (d.get("ultimo_errore") or {}).get("motivo"),
            "aggiornato": d.get("aggiornato"),
        })
    return out
