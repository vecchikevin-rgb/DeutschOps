"""Il registro dei Modellsatz — l'unica misura esterna che il sistema accetta.

PERCHE' QUESTO E NON UN SIMULATORE D'ESAME
Il piano dell'app prevedeva per F5 una «simulazione Lesen e Schreiben in formato
Goethe, valutata con la griglia ufficiale», con un punteggio per modulo
confrontabile nel tempo. Costruirla e' facile. Il problema e' che sarebbe una
prova inventata da un modello e corretta dallo stesso modello — cioe'
esattamente la metrica che `stato/scadenze.md` dichiara inutilizzabile:

    «`esame.py` calcola la copertura del curriculum B2 dai tuoi dati. Ma e' una
    metrica AUTO-PRODOTTA dallo stesso sistema che genera le lezioni: misura
    cosa hai incontrato, non cosa sai produrre sotto pressione in 90 minuti.
    [...] l'evidenza esterna sono due: il punteggio Modellsatz e il giudizio di
    Stefanie, che e' fuori dal sistema.»

Un punteggio auto-prodotto che assomiglia a un voto d'esame e' peggio di nessun
punteggio: da' la stessa sensazione di sapere dove sei, senza l'informazione.

Quindi il punteggio confrontabile nel tempo che F5 doveva produrre viene dal
**Modellsatz vero** — il PDF ufficiale del Goethe, cronometrato, che Kevin fa
da solo — e questo modulo lo registra, lo confronta e ne calcola la pendenza.
L'esercizio generato resta (vedi `prova.py`): ma si chiama esercizio, non esame,
e non produce un voto.

COSA REGISTRA
Un Modellsatz per volta, con i quattro moduli, la data e le condizioni. Il campo
`cronometrato` non e' un dettaglio: un Lesen fatto con calma e uno fatto in 65
minuti sono due numeri diversi, e confonderli renderebbe la pendenza una favola.
"""

from __future__ import annotations

import json
import threading
from datetime import date, datetime

from ..base.paths import DATA

REGISTRO = DATA / "modellsatz.json"

# I quattro moduli, con il punteggio pieno e la soglia. Il B2 e' modulare dal
# 2019: ogni modulo si supera per conto suo, ed e' la leva strategica che
# `stato/scadenze.md` descrive.
MODULI = [
    {"id": "lesen", "nome": "Lesen", "minuti": 65,
     "descrizione": "5 parts — detail, opinion, long texts"},
    {"id": "hoeren", "nome": "Hören", "minuti": 40,
     "descrizione": "4 parts — conversations and talks"},
    {"id": "schreiben", "nome": "Schreiben", "minuti": 75,
     "descrizione": "2 parts — argumentative text and formal message"},
    {"id": "sprechen", "nome": "Sprechen", "minuti": 15,
     "descrizione": "2 parts — short presentation and discussion"},
]

# Il Goethe-Zertifikat B2 assegna 100 punti per modulo e ne chiede 60 per
# superarlo. La soglia sta qui e non nell'interfaccia: e' un fatto sull'esame,
# non una scelta di presentazione.
PIENO = 100
SOGLIA = 60

FONTE = "https://www.goethe.de/pro/relaunch/prf/materialien/B2/b2_modellsatz_erwachsene.pdf"

_LUCCHETTO = threading.Lock()


def _carica() -> dict:
    try:
        d = json.loads(REGISTRO.read_text(encoding="utf-8"))
        if isinstance(d, dict) and isinstance(d.get("prove"), list):
            return d
    except Exception:
        pass
    return {"prove": []}


def tutte() -> list[dict]:
    return sorted(_carica()["prove"], key=lambda p: p.get("data") or "")


def registra(voce: dict) -> dict:
    """Aggiunge un Modellsatz svolto. Un punteggio per modulo, 0-100.

    I moduli assenti restano assenti: un Modellsatz fatto solo su Lesen e Hören
    e' un dato valido, e mettere zero dove non hai provato sarebbe una bugia
    che poi si vede come un crollo nel grafico.
    """
    p = {
        "data": (voce.get("data") or date.today().isoformat())[:10],
        "etichetta": (voce.get("etichetta") or "").strip(),
        "cronometrato": bool(voce.get("cronometrato")),
        "note": (voce.get("note") or "").strip(),
        "registrato": datetime.now().isoformat(timespec="seconds"),
        "punteggi": {},
    }
    for m in MODULI:
        v = voce.get("punteggi", {}).get(m["id"])
        if v is None or v == "":
            continue
        try:
            p["punteggi"][m["id"]] = max(0, min(PIENO, int(float(v))))
        except (TypeError, ValueError):
            continue

    with _LUCCHETTO:
        d = _carica()
        # Stessa data = stessa prova: si sostituisce invece di duplicare.
        d["prove"] = [x for x in d["prove"] if x.get("data") != p["data"]]
        d["prove"].append(p)
        try:
            REGISTRO.parent.mkdir(parents=True, exist_ok=True)
            tmp = REGISTRO.with_name(REGISTRO.name + ".tmp")
            tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            tmp.replace(REGISTRO)
        except OSError:
            pass
    return p


def elimina(data: str) -> int:
    with _LUCCHETTO:
        d = _carica()
        prima = len(d["prove"])
        d["prove"] = [x for x in d["prove"] if x.get("data") != data[:10]]
        tolte = prima - len(d["prove"])
        if tolte:
            tmp = REGISTRO.with_name(REGISTRO.name + ".tmp")
            tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            tmp.replace(REGISTRO)
        return tolte


def quadro() -> dict:
    """Lo stato: ultimo punteggio per modulo, e la pendenza fra le prove.

    La PENDENZA e' il numero che conta, non il livello: `scadenze.md` lo dice
    esplicitamente sul Modellsatz #2 — «serve a misurare la derivata, non il
    livello». Con una prova sola non c'e' pendenza, e si dice.
    """
    prove = tutte()
    moduli = []
    for m in MODULI:
        serie = [(p["data"], p["punteggi"][m["id"]])
                 for p in prove if m["id"] in p.get("punteggi", {})]
        ultimo = serie[-1][1] if serie else None
        delta = (serie[-1][1] - serie[-2][1]) if len(serie) >= 2 else None
        moduli.append({
            **m,
            "ultimo": ultimo,
            "quando": serie[-1][0] if serie else None,
            "delta": delta,
            "superato": ultimo is not None and ultimo >= SOGLIA,
            "serie": [{"data": d, "punti": v} for d, v in serie],
        })

    fatti = [m for m in moduli if m["ultimo"] is not None]
    return {
        "prove": prove,
        "moduli": moduli,
        "pieno": PIENO,
        "soglia": SOGLIA,
        "fonte": FONTE,
        "quante": len(prove),
        "moduli_misurati": len(fatti),
        "moduli_superati": sum(1 for m in fatti if m["superato"]),
        # Con una prova sola non esiste una derivata, e dirlo e' meta' del
        # valore di questa pagina.
        "pendenza_leggibile": len(prove) >= 2,
    }
