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
import re
import threading
import unicodedata
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


# --------------------------------------------------------------- provenienza
# I 295 record storici vengono tutti dallo stesso posto: una forma tedesca che
# Stefanie ha corretto a voce, in lezione. Da F2 anche l'app scrive qui, e la
# differenza non e' contabilita': un errore giudicato da un modello su una
# risposta scritta NON e' una correzione verificata da una madrelingua.
#
# Stessa cartella, campo diverso. Il drill deve vederli entrambi — e' il senso
# stesso di chiudere il ciclo — ma le statistiche no: e' cosi' che «il 45% sono
# i casi» smetterebbe di essere vero senza che nessuno se ne accorga.
#
# Campo assente = "lezione": nessuna migrazione da fare sui record esistenti.
LEZIONE = "lezione"
STUDIO = "studio"

# Il server dell'app e' un ThreadingHTTPServer: due risposte valutate a un
# istante di distanza farebbero due leggi-modifica-scrivi sovrapposti.
_LUCCHETTO = threading.Lock()


def fonte_di(e: dict) -> str:
    return e.get("fonte") or LEZIONE


# --------------------------------------------------------------- chiave regola
# Il nome della regola lo scrive un modello, in linguaggio libero: «Modalverb am
# Ende im Nebensatz» e «Nebensatz: Verb am Ende» sono la stessa cosa e contano
# uno ciascuno. Sui 295 record storici questo fa 288 nomi distinti — cioe' la
# recidiva non esiste, e la coda dell'allenamento non avrebbe su cosa insistere.
#
# Normalizzando (minuscole, diacritici via, parole vuote fuori, token ordinati)
# i distinti scendono a 283 e le regole con almeno due occorrenze diventano 8.
# Poche, ma vere: due chiavi uguali sono la stessa regola per costruzione, ed e'
# l'unica relazione fra errori che si possa AFFERMARE invece che stimare.
#
# Sta qui e non in `studio/allenamento.py` perche' e' una proprieta' del record,
# non del drill: la usano l'allenamento e l'indice di consultazione, e `sapere/`
# non deve dipendere da `studio/`.
_VUOTE = {
    "der", "die", "das", "den", "dem", "des", "ein", "eine", "einen", "einem",
    "einer", "bei", "mit", "im", "in", "the", "of", "and", "for", "with",
    "statt", "und", "oder", "als", "fuer", "zum", "zur", "vs", "nach",
}


def chiave_regola(nome: str | None) -> str:
    """Nome di regola -> chiave stabile e confrontabile."""
    t = unicodedata.normalize("NFKD", (nome or "").lower().replace("ß", "ss"))
    t = "".join(c for c in t if not unicodedata.combining(c))
    tok = [x for x in re.split(r"[^a-z0-9]+", t)
           if len(x) > 2 and x not in _VUOTE]
    return " ".join(sorted(set(tok)))


def carica() -> dict:
    if ERROR_DB.exists():
        try:
            return json.loads(ERROR_DB.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return {"errors": [], "lessons_processed": [], "last_updated": None}


def registrati(fonte: str | None = LEZIONE) -> list[dict]:
    """Gli errori del quaderno. Per difetto SOLO quelli corretti in lezione.

    `fonte=None` li restituisce tutti: lo vuole la coda dell'allenamento, che
    deve ripresentare anche cio' che hai sbagliato nell'app.
    """
    errori = [e for e in carica().get("errors", []) if isinstance(e, dict)]
    if fonte is None:
        return errori
    return [e for e in errori if fonte_di(e) == fonte]


def salva(db: dict) -> None:
    """Scrittura atomica.

    Fino a F2 questo file veniva scritto una volta a lezione, a fine pipeline.
    Adesso lo scrive anche una richiesta web, a ogni risposta sbagliata. Un
    `write_text` interrotto a meta' lascia un JSON troncato, e li' dentro ci
    sono 295 correzioni raccolte in 30 lezioni: non si rifanno.
    """
    ERROR_DB.parent.mkdir(parents=True, exist_ok=True)
    db["last_updated"] = datetime.now().isoformat(timespec="seconds")
    tmp = ERROR_DB.with_name(ERROR_DB.name + ".tmp")
    tmp.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(ERROR_DB)


def annota(voce: dict) -> dict:
    """Aggiunge un errore fatto nell'app. Marcato `fonte: "studio"`, sempre."""
    voce = dict(voce)
    voce["fonte"] = STUDIO
    voce.setdefault("quando", datetime.now().isoformat(timespec="seconds"))
    voce.setdefault("lesson_date", None)
    if voce.get("category") not in CATEGORIE:
        voce["category"] = "Sonstiges"
    with _LUCCHETTO:
        db = carica()
        db["errors"].append(voce)
        salva(db)
    return voce


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
    # Rifare una lezione sostituisce i SUOI errori. Quelli fatti nell'app non
    # appartengono a nessuna lezione e non devono sparire perche' ne rielabori
    # una: senza questa guardia un `lezione --auto` cancellerebbe la coda.
    db["errors"] = [e for e in db["errors"]
                    if fonte_di(e) != LEZIONE
                    or e.get("lesson_date") != data_lezione] + errori
    if data_lezione not in db["lessons_processed"]:
        db["lessons_processed"].append(data_lezione)
    salva(db)
    print(f"   error_db: {len(db['errors'])} errori su "
          f"{len(db['lessons_processed'])} lezioni")
    return errori, costo


def ritira(esercizio: str) -> int:
    """Toglie dal quaderno gli errori nati da un esercizio dichiarato rotto.

    PERCHE' UN ERRORE SI PUO' RITIRARE, E SOLO QUESTO
    Un esercizio indovinabile invece che deducibile produce una risposta
    sbagliata che NON dice niente su cosa Kevin sa: «Meine Firma hat eine neue
    Fabrik ___ gebaut» ammette im Norden, im Süden, in Berlin. Lasciare quel
    record nel quaderno sposta il profilo d'errore verso una regola che non ha
    mai violato, e la coda dell'allenamento gli ripresenta quella regola.

    Tocca SOLO i record `fonte: "studio"` con quell'esercizio: le correzioni di
    Stefanie non si ritirano — quelle sono successe.
    """
    with _LUCCHETTO:
        db = carica()
        chiave = " ".join((esercizio or "").split())
        if not chiave:
            return 0
        prima = len(db["errors"])
        db["errors"] = [
            e for e in db["errors"]
            if fonte_di(e) != STUDIO
            or " ".join((e.get("esercizio") or "").split()) != chiave
        ]
        tolti = prima - len(db["errors"])
        if tolti:
            salva(db)
        return tolti


def pattern(fonte: str | None = LEZIONE) -> dict:
    """Il quadro degli errori. Per difetto solo quelli verificati in lezione."""
    errori = registrati(fonte)
    return {
        "totale": len(errori),
        "lezioni": len(carica()["lessons_processed"]),
        "dallo_studio": len(registrati(STUDIO)),
        "per_categoria": Counter(e.get("category", "Sonstiges")
                                 for e in errori).most_common(),
        "regole_top": Counter(e.get("rule", "?") for e in errori).most_common(10),
    }


def transcript_di(data_lezione: str) -> Path:
    return TRANSCRIPTS / f"lezione_{data_lezione}.txt"
