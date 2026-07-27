"""Il database cumulativo del vocabolario.

Porta `vocab_db.py`. Lo schema su disco resta IDENTICO: lo leggono
do/studio/frasi.py (parole note), do/studio/manutenzione.py (indice per
l'audit Anki) e do/motore/stato.py (conteggi per livello). Cambiarlo qui
significherebbe romperli tutti in silenzio.

Cosa cambia davvero: i path non dipendono piu' dalla cwd, e
`aggiorna_da_lezione` accetta il dict gia' in memoria invece di rileggere il
JSON dal disco — la pipeline lo ha gia' fra le mani.
"""

from __future__ import annotations

import json
from datetime import date

from ..base.paths import DATA, VOCAB_DB

VUOTO = {"words": {}, "stats": {"total_words": 0, "by_category": {}, "by_level": {}}}


def carica() -> dict:
    if VOCAB_DB.exists():
        return json.loads(VOCAB_DB.read_text(encoding="utf-8"))
    return json.loads(json.dumps(VUOTO))


def salva(db: dict) -> None:
    VOCAB_DB.parent.mkdir(parents=True, exist_ok=True)
    VOCAB_DB.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")


def _ricalcola(db: dict) -> None:
    """Ricalcola le statistiche. Aggregazione IDENTICA alla v1, di proposito.

    `w.get("category", "other")` e non `w.get("category") or "other"`: il
    default scatta solo se la chiave manca, non se vale stringa vuota. Dieci
    parole nel DB hanno `category: ""` e finiscono in un bucket chiamato `""`.

    Sembra un bug da correggere. Non lo si corregge qui, per due motivi: e' un
    cambiamento *derivato* — le parole non si toccano, cambia solo l'etichetta
    di un secchio — e quel secchio finisce nel blocco KPI scritto sul Google
    Doc di Stefanie e in chiunque altro legga `by_category`. Rinominarlo in
    mezzo a una migrazione produrrebbe una differenza che poi bisogna spiegare,
    per zero guadagno. Se va sistemato, si sistema a monte: dando una categoria
    a quelle dieci parole.
    """
    parole = db["words"]
    per_cat: dict[str, int] = {}
    per_liv: dict[str, int] = {}
    for w in parole.values():
        cat = w.get("category", "other")
        liv = w.get("level", "?")
        per_cat[cat] = per_cat.get(cat, 0) + 1
        per_liv[liv] = per_liv.get(liv, 0) + 1
    db["stats"] = {"total_words": len(parole), "by_category": per_cat, "by_level": per_liv}


def aggiorna_da_lezione(dati: dict, data_lezione: str | None = None) -> tuple[int, int]:
    """Integra il vocabolario di una lezione. Ritorna (nuove, riviste).

    Idempotente per data: rilanciare la stessa lezione non duplica le
    occorrenze, perche' `seen_in_lessons` e' controllata prima di aggiungere.
    """
    data_lezione = data_lezione or date.today().isoformat()
    db = carica()
    tema = dati.get("topic", "")
    nuove = riviste = 0

    for v in dati.get("vocabulary", []):
        chiave = (v.get("german") or "").lower().strip()
        if not chiave:
            continue
        if chiave in db["words"]:
            e = db["words"][chiave]
            if data_lezione not in e["seen_in_lessons"]:
                e["seen_in_lessons"].append(data_lezione)
                e["seen_in_topics"].append(tema)
                e["occurrences"] = len(e["seen_in_lessons"])
            riviste += 1
        else:
            db["words"][chiave] = {
                "german": v.get("german", ""),
                "article": v.get("article", ""),
                "plural": v.get("plural", ""),
                "category": v.get("category", ""),
                "italian": v.get("italian", ""),
                "english": v.get("english", ""),
                "example_de": v.get("example_de", ""),
                "level": v.get("level", ""),
                "first_seen": data_lezione,
                "seen_in_lessons": [data_lezione],
                "seen_in_topics": [tema],
                "occurrences": 1,
                "anki_status": "added",
            }
            nuove += 1

    _ricalcola(db)
    salva(db)
    print(f"   vocab_db: +{nuove} nuove, {riviste} riviste "
          f"({db['stats']['total_words']} totali)")
    return nuove, riviste


def ricostruisci() -> dict:
    """Ricostruisce il DB da tutti i JSON lezione. Non distruttivo sul disco
    finche' non chiami salva() — qui costruisce e salva, come faceva la v1.

    Serve dopo una migrazione o se il DB si corrompe: i 40 JSON lezione sono
    la sorgente, il DB e' derivato.
    """
    db = json.loads(json.dumps(VUOTO))
    salva(db)
    for f in sorted(DATA.glob("lezione_*.json")):
        etichetta = f.stem.replace("lezione_", "").split("-stefanie")[0].split("-v")[0]
        try:
            aggiorna_da_lezione(json.loads(f.read_text(encoding="utf-8")), etichetta)
        except (OSError, ValueError) as e:
            print(f"   {f.name}: {e}")
    return carica()
