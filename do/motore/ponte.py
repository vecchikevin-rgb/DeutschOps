"""Ponte periodico verso il motore di `shared start up/`.

COSA FA
A cadenza definita controlla se nel motore condiviso e' comparso qualcosa di
nuovo — skill nel catalogo, pattern in `_engine/`, voci recenti nel changelog —
e lo segnala nel briefing. Non importa niente da solo: propone.

FIREWALL, PER COSTRUZIONE
Questo modulo apre la cartella condivisa in SOLA LETTURA e non ha nessun
percorso di scrittura verso di essa. Import di solo metodo, senso unico: nulla
di DeutschOps puo' finire in `shared start up/`. C'e' anche una seconda
barriera indipendente — l'hook `block-outside-project-writes.ps1` blocca a
livello di sistema ogni scrittura fuori da DeutschOps.

COME RILEVA SENZA LEGGERE 128 KB
`changelog-engine.md` pesa 128 KB: rileggerlo a ogni avvio e' inaccettabile.
La sequenza e' a costo crescente e si ferma appena puo':
  1. sono passati meno di N giorni dall'ultimo check?  -> esce, costo zero
  2. mtime e dimensione sono identici a prima?         -> esce, due stat()
  3. solo allora calcola l'hash, e del changelog legge solo la CODA (8 KB),
     che e' dove finiscono le voci nuove.
Il file intero non viene mai letto.

IL SILENZIO E' UN REQUISITO
Quando non c'e' niente di nuovo il ponte non stampa nulla. Un blocco che
compare a ogni avvio anche da vuoto smette di essere letto in due settimane —
e' esattamente come e' morto `log-loop.md` nel motore condiviso, che ha una
sola riga di cinque settimane fa.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ..base.config import PONTE_CADENZA_GIORNI
from ..base.paths import (PONTE_STATE, SHARED_CHANGELOG, SHARED_ROADMAP,
                          SHARED_SKILLS_INDEX, shared_disponibile)

CODA_BYTE = 8192      # del changelog leggiamo solo la fine

SORGENTI: dict[str, Path] = {
    "catalogo-skill": SHARED_SKILLS_INDEX,
    "changelog-engine": SHARED_CHANGELOG,
    "roadmap-engine": SHARED_ROADMAP,
}


@dataclass(frozen=True)
class Novita:
    sorgente: str
    percorso: str
    estratto: str


# ------------------------------------------------------------------ stato
def _leggi_stato() -> dict:
    try:
        return json.loads(PONTE_STATE.read_text(encoding="utf-8"))
    except Exception:
        return {"ultimo_check": None, "cadenza_giorni": PONTE_CADENZA_GIORNI,
                "sorgenti": {}, "importati": [], "scartati": []}


def _salva_stato(s: dict) -> None:
    PONTE_STATE.parent.mkdir(parents=True, exist_ok=True)
    PONTE_STATE.write_text(json.dumps(s, ensure_ascii=False, indent=2),
                           encoding="utf-8")


def _impronta(p: Path, solo_coda: bool) -> dict:
    st = p.stat()
    if solo_coda:
        with open(p, "rb") as f:
            f.seek(max(0, st.st_size - CODA_BYTE))
            dati = f.read()
    else:
        dati = p.read_bytes()
    return {
        "size": st.st_size,
        "mtime": int(st.st_mtime),
        "sha256": hashlib.sha256(dati).hexdigest(),
    }


def _scaduto(stato: dict) -> bool:
    ultimo = stato.get("ultimo_check")
    if not ultimo:
        return True
    try:
        passati = (date.today() - date.fromisoformat(ultimo)).days
    except ValueError:
        return True
    return passati >= stato.get("cadenza_giorni", PONTE_CADENZA_GIORNI)


# ------------------------------------------------------------------ check
def controlla(*, forza: bool = False) -> list[Novita]:
    """Le novita' dal motore condiviso. Lista vuota = silenzio.

    Non solleva mai: se Drive e' offline o un file manca, il ponte tace. Non e'
    un servizio critico e non deve poter far fallire nient'altro.
    """
    stato = _leggi_stato()
    if not forza and not _scaduto(stato):
        return []
    if not shared_disponibile():
        return []                       # Drive non montato: silenzio, non errore

    precedenti = stato.get("sorgenti", {})
    novita: list[Novita] = []
    aggiornate: dict[str, dict] = dict(precedenti)

    for nome, percorso in SORGENTI.items():
        try:
            if not percorso.is_file():
                continue
            prima = precedenti.get(nome)
            st = percorso.stat()

            # Passo economico: se dimensione e mtime combaciano, niente hash.
            if prima and prima.get("size") == st.st_size and prima.get("mtime") == int(st.st_mtime):
                continue

            solo_coda = nome == "changelog-engine"
            adesso = _impronta(percorso, solo_coda)
            aggiornate[nome] = adesso

            if prima is None:
                continue                # primo giro: si prende la fotografia
            if prima.get("sha256") == adesso.get("sha256"):
                continue                # ritoccato ma identico nei contenuti

            novita.append(Novita(
                sorgente=nome,
                percorso=str(percorso),
                estratto=_estratto(percorso, solo_coda),
            ))
        except OSError:
            continue                    # file irraggiungibile: si tace

    stato["sorgenti"] = aggiornate
    stato["ultimo_check"] = date.today().isoformat()
    _salva_stato(stato)
    return novita


def _estratto(p: Path, solo_coda: bool) -> str:
    """Le ultime righe non vuote, per dare un'idea di cosa e' cambiato."""
    try:
        if solo_coda:
            with open(p, "rb") as f:
                f.seek(max(0, p.stat().st_size - CODA_BYTE))
                testo = f.read().decode("utf-8", errors="replace")
        else:
            testo = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    righe = [r.strip() for r in testo.splitlines() if r.strip()]
    return " · ".join(righe[-3:])[:300]


def righe_briefing() -> list[str]:
    """Righe per il riquadro di avvio. Vuota quando non c'e' niente da dire."""
    nov = controlla()
    if not nov:
        return []
    out = [f"Motore condiviso: {len(nov)} sorgenti cambiate dall'ultimo check"]
    out += [f"  - {n.sorgente}" for n in nov]
    out.append("  Per valutare cosa importare: /ponte-motore")
    return out


def registra(cosa: str, *, importato: bool, perche: str = "") -> None:
    """Annota una decisione di import o di scarto.

    Il registro degli SCARTI conta quanto quello degli import: senza, ogni
    check ripropone gli stessi pattern multi-utente gia' valutati e rifiutati.
    """
    stato = _leggi_stato()
    voce = {"data": date.today().isoformat(), "cosa": cosa}
    if perche:
        voce["perche"] = perche
    stato.setdefault("importati" if importato else "scartati", []).append(voce)
    _salva_stato(stato)
