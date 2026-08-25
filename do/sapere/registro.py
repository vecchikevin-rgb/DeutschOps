"""Il registro delle lezioni — e la fine della costante da 0,10 EUR.

IL DEBITO STORICO
`main.py:230` scriveva `claude_cost = 0.10` per ogni lezione, mentre
`extractor.py:50-52` calcolava il costo vero da `response.usage` e lo buttava
via. Risultato: 2,95 dei 4,82 euro nel registro sono una costante moltiplicata
per 30. I numeri storici non sono recuperabili — le risposte API non si
rileggono a posteriori.

Quello che si puo' fare, e che questo modulo fa:
  1. scrivere il costo MISURATO per le lezioni nuove;
  2. marcare come `stimato: true` tutto cio' che misurato non e';
  3. non spacciare mai una stima per una misura.

Le voci gia' in `lesson_registry.json` restano dove sono. `marca_storico()`
aggiunge loro il flag una volta sola, senza toccare le cifre: riscriverle
sarebbe inventare dati che non abbiamo.
"""

from __future__ import annotations

import json
from datetime import datetime

from ..base.paths import REGISTRY

VUOTO = {"lessons": [], "stats": {"total": 0, "total_cost_eur": 0.0, "total_minutes": 0}}


def carica() -> dict:
    if REGISTRY.exists():
        return json.loads(REGISTRY.read_text(encoding="utf-8"))
    return json.loads(json.dumps(VUOTO))


def salva(reg: dict) -> None:
    REGISTRY.write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")


def _ricalcola(reg: dict) -> None:
    lez = reg["lessons"]
    reg["stats"] = {
        "total": len(lez),
        "total_cost_eur": round(sum(l.get("cost_total_eur", 0) for l in lez), 3),
        "total_minutes": round(sum(l.get("duration_minutes", 0) for l in lez), 1),
    }


def registra(*, data_lezione: str, audio: str, dati: dict,
             costo_trascrizione: float, costo_llm: float,
             minuti: float, costo_stimato: bool = False) -> dict:
    """Registra (o riscrive) una lezione. Idempotente per id."""
    reg = carica()
    reg["lessons"] = [l for l in reg["lessons"] if l.get("id") != data_lezione]

    voce = {
        "id": data_lezione,
        "date": data_lezione.split("-stefanie")[0].split("-v")[0],
        "audio_file": audio,
        "topic": dati.get("topic", "N/A"),
        "summary_it": (dati.get("summary_it") or "")[:150],
        "vocabulary_count": len(dati.get("vocabulary", [])),
        "grammar_count": len(dati.get("grammar_points", [])),
        "phrases_count": len(dati.get("phrases", [])),
        "doc_sections": dati.get("doc_sections_covered", []),
        "homework": dati.get("homework", ""),
        "duration_minutes": round(minuti, 1),
        "cost_whisper_eur": round(costo_trascrizione, 4),
        "cost_claude_eur": round(costo_llm, 4),
        "cost_total_eur": round(costo_trascrizione + costo_llm, 4),
        # Il flag che mancava. False = i due costi qui sopra vengono da
        # response.usage; True = sono una stima o un residuo storico.
        "cost_estimated": costo_stimato,
        "files": {
            "transcript": f"transcripts/lezione_{data_lezione}.txt",
            "data": f"data/lezione_{data_lezione}.json",
            "anki_deck": "Deutsch::DeutschOps",
        },
        "processed_at": datetime.now().isoformat(timespec="seconds"),
    }
    reg["lessons"].append(voce)
    _ricalcola(reg)
    salva(reg)
    marchio = " (stimato)" if costo_stimato else ""
    print(f"   registro: {data_lezione} | {voce['cost_total_eur']:.4f} EUR{marchio} "
          f"| {minuti:.0f} min")
    return voce


def marca_storico() -> int:
    """Marca `cost_estimated: true` le voci scritte prima del costo misurato.

    Riconoscimento: `cost_claude_eur` esattamente 0.1 e' la costante di
    main.py:230. Non tocca le cifre — le etichetta soltanto.
    """
    reg = carica()
    toccate = 0
    for l in reg["lessons"]:
        if "cost_estimated" in l:
            continue
        l["cost_estimated"] = abs(l.get("cost_claude_eur", 0) - 0.10) < 1e-9
        toccate += 1
    if toccate:
        salva(reg)
    return toccate


def stimate() -> int:
    return sum(1 for l in carica()["lessons"] if l.get("cost_estimated"))
