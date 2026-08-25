"""Chiudere i run rimasti aperti.

IL BUCO CHE QUESTO MODULO TAPPA
Il tracker sa riprendere un run interrotto, ma solo se rilanci la pipeline su
quella lezione. Nella pratica non succede: la lezione dopo arriva, si elabora
quella, e il task vecchio resta aperto per sempre. Al 2026-07-27 ce n'erano
quattro, il piu' vecchio del 26 giugno — un mese.

Il briefing li mostra da quando esiste, ma mostrarli non basta: serviva un
modo di chiuderli che non fosse "rilancia tutta la pipeline di giugno".

DUE MODI DI CHIUDERE, E LA DIFFERENZA CONTA
  recupera()  esegue davvero cio' che manca (oggi: le carte Anki). La fase
              diventa fatta perche' il lavoro e' stato fatto.
  archivia()  chiude il task dichiarando che la fase non e' piu' recuperabile.
              Serve per `doc`: il diff del Google Doc di una lezione di giugno
              non esiste piu': gli snapshot successivi hanno spostato il punto
              di riferimento. Fingere di rifarlo produrrebbe il diff di oggi
              attaccato a una lezione di un mese fa.

Chiudere non cancella nulla: il task file sparisce, gli output della lezione
(transcript, JSON, PDF, database) sono gia' tutti al loro posto.
"""

from __future__ import annotations

import json

from .paths import DATA
from .tracker import FASI, Task, pendenti

# Le fasi che qui si sanno rifare. Le altre si possono solo archiviare.
RECUPERABILI = {"anki"}


def _vocabolario(data_lezione: str) -> list[dict] | None:
    p = DATA / f"lezione_{data_lezione}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("vocabulary", [])
    except (OSError, ValueError):
        return None


def mancanti(t: Task) -> list[str]:
    return [f for f in FASI if not t.fatta(f)]


def recupera(data_lezione: str, *, prova: bool = False) -> dict:
    """Esegue le fasi mancanti recuperabili e chiude il task se non resta altro."""
    t = Task(data_lezione)
    manca = mancanti(t)
    esito = {"lezione": data_lezione, "mancanti": manca, "fatte": [],
             "non_recuperabili": [f for f in manca if f not in RECUPERABILI]}

    if "anki" in manca:
        voc = _vocabolario(data_lezione)
        if voc is None:
            esito["errore"] = f"data/lezione_{data_lezione}.json assente"
            return esito
        from ..studio import carte

        r = carte.alimenta(voc, data_lezione, prova=prova)
        esito["anki"] = r
        if not prova:
            t.salva_fase("anki", r)
            esito["fatte"].append("anki")

    if not prova and not [f for f in mancanti(t) if f in RECUPERABILI]:
        residue = mancanti(t)
        if residue:
            esito["resta_aperto_per"] = residue
        else:
            t.chiudi()
            esito["chiuso"] = True
    return esito


def archivia(data_lezione: str, motivo: str) -> dict:
    """Chiude un task dichiarando irrecuperabile cio' che manca.

    Il motivo viene scritto nel task prima di chiuderlo, cosi' resta nella
    cronologia di chi legge il file (o il diff di git) invece di sparire.
    """
    t = Task(data_lezione)
    residue = mancanti(t)
    t.dati["chiuso_senza"] = {"fasi": residue, "motivo": motivo}
    t._flush()
    t.chiudi()
    return {"lezione": data_lezione, "chiuso_senza": residue, "motivo": motivo}


def tutti(*, prova: bool = False) -> list[dict]:
    return [recupera(d, prova=prova) for d in pendenti()]
