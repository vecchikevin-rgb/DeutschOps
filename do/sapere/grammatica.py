"""Il database cumulativo delle regole grammaticali (296 regole).

Porta la parte DATI di `grammar_book.py` — le ~25 righe che aggiornano
`data/grammar_db.json`. La parte PDF (700 righe di ReportLab) resta dov'e' e
si raggiunge da do/uscite/pdf.py: vedi la nota li' sul perche' la
consolidazione dei generatori e' rimandata.

Regola di merge (invariata dalla v1): una regola nuova entra; una regola gia'
presente viene sostituita solo se la nuova ha `full_rule` e la vecchia no —
cioe' solo se la ricerca web l'ha arricchita. Non si sovrascrive mai una
regola completa con una piu' povera.
"""

from __future__ import annotations

import json
from datetime import datetime

from ..base.paths import DATA, GRAMMAR_DB


def carica() -> dict:
    if GRAMMAR_DB.exists():
        try:
            return json.loads(GRAMMAR_DB.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return {"rules": {}, "last_updated": None}


def salva(db: dict) -> None:
    GRAMMAR_DB.parent.mkdir(parents=True, exist_ok=True)
    db["last_updated"] = datetime.now().isoformat(timespec="seconds")
    GRAMMAR_DB.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")


def aggiorna_da_lezione(dati: dict) -> int:
    """Integra i grammar_points di una lezione. Ritorna quante regole entrano."""
    punti = dati.get("grammar_points", [])
    if not punti:
        return 0

    db = carica()
    regole = db.get("rules", {})
    nuove = 0

    for gp in punti:
        k = (gp.get("rule") or "").strip()
        if not k:
            continue
        if k not in regole:
            regole[k] = gp
            nuove += 1
        elif gp.get("full_rule") and not regole[k].get("full_rule"):
            regole[k] = gp
            nuove += 1

    if nuove:
        db["rules"] = regole
        salva(db)
    print(f"   grammar_db: +{nuove} regole ({len(regole)} totali)")
    return nuove


def raccogli_dalle_lezioni() -> dict:
    """Ricostruisce l'insieme delle regole dai JSON lezione (sorgente vera)."""
    regole: dict[str, dict] = {}
    for f in sorted(DATA.glob("lezione_*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for gp in d.get("grammar_points", []):
            k = (gp.get("rule") or "").strip()
            if not k:
                continue
            if k not in regole or (gp.get("full_rule") and not regole[k].get("full_rule")):
                regole[k] = gp
    return regole
