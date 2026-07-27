"""Il quaderno degli errori — il segnale didattico piu' prezioso del progetto.

284 errori tuoi reali con la correzione di Stefanie accanto. Non e' vocabolario
generico: e' esattamente dove sbagli. do/studio/drill.py ci costruisce sopra
gli esercizi, do/motore/stato.py ne ricava la quota Kasus/Genus/Präposition.

Porta `error_extractor.py`. Lo schema su disco resta identico.

Cosa cambia: il client LLM era duplicato qui (righe 22-63, copia esatta di
extractor.py) con `MODEL = "claude-sonnet-4-5"` cablato a riga 67; ora passa
da base/llm.py come tutto il resto, e il costo torna misurato invece che
buttato.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from ..base.config import llm_config
from ..base.llm import chiama, estrai_json
from ..base.paths import ERROR_DB, TRANSCRIPTS

# Categorie canoniche. Stabili per costruzione: se cambiano, i pattern
# accumulati in 30 lezioni smettono di aggregarsi e il drill perde la mira.
CATEGORIE = [
    "Genus",                # der/die/das sbagliato
    "Wortstellung",         # ordine delle parole (V2, verbo finale, TeKaMoLo)
    "Präposition",
    "Kasus",                # Akkusativ/Dativ/Genitiv
    "Verbform",             # coniugazione, tempo, ausiliare, Perfekt
    "Wortwahl",             # scelta lessicale, falsi amici
    "Adjektivdeklination",
    "Aussprache",
    "Sonstiges",
]

SISTEMA = f"""You analyse a raw, UNDIARIZED transcript of a 1-on-1 German lesson.
Student: Kevin (Italian native, A2 -> B2 target). Teacher: Stefanie (German native).
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
{{"errors":[{{"category":"<one of: {', '.join(CATEGORIE)}>","kevin_said":"<the wrong German Kevin produced, or '' if only implied>","correction":"<the correct German form>","rule":"<short rule name, e.g. 'Perfekt mit sein bei Bewegung'>","explanation_en":"<1-2 sentences, why it was wrong>","example_correct":"<one correct example sentence in German>"}}]}}

If there are no clear corrections, return {{"errors":[]}}."""


def carica() -> dict:
    if ERROR_DB.exists():
        try:
            return json.loads(ERROR_DB.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return {"errors": [], "lessons_processed": [], "last_updated": None}


def salva(db: dict) -> None:
    ERROR_DB.parent.mkdir(parents=True, exist_ok=True)
    db["last_updated"] = datetime.now().isoformat(timespec="seconds")
    ERROR_DB.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")


def estrai_da_transcript(percorso: str | Path, data_lezione: str) -> tuple[list, float]:
    p = Path(percorso)
    testo = p.read_text(encoding="utf-8")
    print(f"   Transcript: {p.name} ({len(testo)} caratteri)")

    risposta, uso = chiama(SISTEMA, f"=== TRANSCRIPT ===\n{testo}",
                           llm_config(max_tokens=8000))
    errori = estrai_json(risposta).get("errors", [])
    for e in errori:
        e["lesson_date"] = data_lezione
        if e.get("category") not in CATEGORIE:
            e["category"] = "Sonstiges"
    print(f"   {len(errori)} correzioni | {uso.costo_eur:.4f} EUR")
    return errori, uso.costo_eur


def aggiorna_da_lezione(percorso: str | Path, data_lezione: str) -> tuple[list, float]:
    """Idempotente per lezione: rilanciarla sostituisce i suoi errori."""
    db = carica()
    errori, costo = estrai_da_transcript(percorso, data_lezione)
    db["errors"] = [e for e in db["errors"]
                    if e.get("lesson_date") != data_lezione] + errori
    if data_lezione not in db["lessons_processed"]:
        db["lessons_processed"].append(data_lezione)
    salva(db)
    print(f"   error_db: {len(db['errors'])} errori su "
          f"{len(db['lessons_processed'])} lezioni")
    return errori, costo


def pattern() -> dict:
    db = carica()
    return {
        "totale": len(db["errors"]),
        "lezioni": len(db["lessons_processed"]),
        "per_categoria": Counter(e.get("category", "Sonstiges")
                                 for e in db["errors"]).most_common(),
        "regole_top": Counter(e.get("rule", "?") for e in db["errors"]).most_common(10),
    }


def transcript_di(data_lezione: str) -> Path:
    return TRANSCRIPTS / f"lezione_{data_lezione}.txt"
