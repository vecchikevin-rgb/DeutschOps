"""Traccia se il materiale di studio sta girando, o solo la pipeline.

IL PROBLEMA, POSTO DA KEVIN
«ricordamelo se è da qualche giorno che elaboro lezioni senza fare girare la
quota di altro materiale».

E' esattamente il fallimento che l'audit ha documentato sulla v1: la pipeline
ha macinato 30 lezioni senza saltare un colpo, mentre il "loop di miglioramento
continuo" (b1_gap, weak_cards, pharma_glossary) e' stato eseguito UNA volta
l'11 giugno e mai piu'. Nessuno se n'e' accorto per 45 giorni, perche' niente
lo diceva. Elaborare lezioni da' la sensazione di star studiando: il sistema
lavora, i file crescono, i numeri salgono. Ma macinare non e' imparare.

COME LO MISURA
Non serve un registro nuovo: ogni attivita' lascia gia' un file, e la sua data
di modifica dice quando e' girata l'ultima volta. Si confronta con le lezioni
elaborate dopo. Se ne sono passate N senza che l'attivita' girasse, lo dice.

LA SOGLIA E' IN LEZIONI, NON IN GIORNI
Due settimane di vacanza senza lezioni non sono un problema: non c'e' materiale
nuovo da lavorare. Tre lezioni elaborate senza un drill lo sono. La metrica
giusta e' "quanto materiale nuovo e' entrato senza essere digerito".
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime

from ..base.paths import DATA, REGISTRY


@dataclass(frozen=True)
class Attivita:
    nome: str
    comando: str
    file_esito: str
    ogni_n_lezioni: int
    descrizione: str


# Le attivita' che chiudono l'anello. La pipeline non e' qui: quella gira gia'.
ATTIVITA = [
    Attivita("drill", "deutschops.py drill", "drill.json", 3,
             "esercizi di produzione sui tuoi errori reali"),
    Attivita("gap B2", "deutschops.py esame", "esame_b2.json", 8,
             "dove sei rispetto al curriculum B2"),
]


def _lezioni() -> list[str]:
    try:
        reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    except Exception:
        return []
    lez = reg if isinstance(reg, list) else reg.get("lessons", [])
    return sorted((l.get("date") or "")[:10] for l in lez if l.get("date"))


def _ultima_esecuzione(nome_file: str) -> date | None:
    """Quando l'attivita' e' girata l'ultima volta.

    Preferisce il campo `generato` dentro il JSON, che e' scritto dal codice;
    ripiega sull'mtime del file, che un backup o una sincronizzazione possono
    alterare.
    """
    p = DATA / nome_file
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        for campo in ("generato", "generated"):
            if v := d.get(campo):
                return datetime.fromisoformat(str(v)).date()
    except Exception:
        pass
    try:
        return datetime.fromtimestamp(p.stat().st_mtime).date()
    except OSError:
        return None


def stato() -> list[dict]:
    """Per ogni attivita': quando e' girata e quante lezioni sono passate dopo."""
    lezioni = _lezioni()
    out = []
    for a in ATTIVITA:
        ultima = _ultima_esecuzione(a.file_esito)
        if ultima is None:
            arretrate = len(lezioni)
        else:
            arretrate = sum(1 for d in lezioni if d > ultima.isoformat())
        out.append({
            "nome": a.nome,
            "comando": a.comando,
            "descrizione": a.descrizione,
            "ultima": ultima.isoformat() if ultima else None,
            "giorni": (date.today() - ultima).days if ultima else None,
            "lezioni_dopo": arretrate,
            "soglia": a.ogni_n_lezioni,
            "in_ritardo": arretrate >= a.ogni_n_lezioni,
        })
    return out


def righe_briefing() -> list[str]:
    """Righe per il riquadro. Vuota se tutto e' in pari — il silenzio conta."""
    righe = []
    for s in stato():
        if not s["in_ritardo"]:
            continue
        if s["ultima"] is None:
            quando = "mai eseguito"
        else:
            quando = f"ultimo il {s['ultima']}, {s['giorni']}g fa"
        righe.append(
            f"{s['nome']}: {s['lezioni_dopo']} lezioni elaborate senza farlo "
            f"({quando})"
        )
        righe.append(f"   -> py -3 {s['comando']}   [{s['descrizione']}]")
    return righe
