"""Genera `stato/stato-tedesco.md` — la verita' operativa, in una pagina.

PRESO DAL MOTORE CONDIVISO, CON UNA CORREZIONE
`shared start up/_engine/stato-sistema.md` e' lo stesso pattern: un file che
non duplica i dati ma punta alle fonti. Il principio e' buono. La meccanica no:
li' e' scritto a mano, e infatti al 2026-07-26 porta "Ultimo aggiornamento:
2026-07-06" e ammette da solo di essere indietro di due settimane.

Qui il file e' GENERATO. Nessuna disciplina richiesta, nessun modo di essere
stale: se lo leggi, e' fresco, perche' lo produce lo script che lo mostra.

Non sostituisce la dashboard Streamlit: la rimpiazza. Quella non veniva aperta
— e un cruscotto che va aperto e' un cruscotto che non si guarda. Questo
compare da solo nel briefing.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime

from ..base.paths import (ERROR_DB, GRAMMAR_DB, REGISTRY, STATO, TRANSCRIPTS,
                          VOCAB_DB)
from ..base.tracker import dettaglio_pendenti
from . import scadenze

OUT = STATO / "stato-tedesco.md"


def _json(p, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def raccogli() -> dict:
    """Tutti i numeri, da una sola passata sui file. Nessuna chiamata di rete."""
    reg = _json(REGISTRY, [])
    lezioni = reg if isinstance(reg, list) else reg.get("lessons", [])

    v = _json(VOCAB_DB, {})
    parole = v.get("words", v)
    parole = list(parole.values()) if isinstance(parole, dict) else parole
    livelli = Counter((w.get("level") or "?") for w in parole if isinstance(w, dict))

    g = _json(GRAMMAR_DB, {})
    regole = g.get("rules", g)

    e = _json(ERROR_DB, {})
    errori = e.get("errors", e)
    errori = list(errori.values()) if isinstance(errori, dict) else errori
    cat = Counter((x.get("category") or "?") for x in errori if isinstance(x, dict))
    famiglia_casi = sum(n for c, n in cat.items() if c in ("Kasus", "Genus", "Präposition"))

    date_lez = sorted(l.get("date", "") for l in lezioni if l.get("date"))
    ultima = date_lez[-1][:10] if date_lez else None
    giorni_da_ultima = (
        (date.today() - date.fromisoformat(ultima)).days if ultima else None
    )

    return {
        "lezioni": len(lezioni),
        "ore": round(sum(float(l.get("duration_minutes") or 0) for l in lezioni) / 60, 1),
        "ultima_lezione": ultima,
        "giorni_da_ultima": giorni_da_ultima,
        "vocaboli": sum(livelli.values()),
        "livelli": dict(sorted(livelli.items())),
        "b2_o_oltre": sum(n for l, n in livelli.items() if l in ("B2", "C1", "C2")),
        "regole": len(regole) if isinstance(regole, dict) else 0,
        "errori": len(errori),
        "errori_per_categoria": cat.most_common(8),
        "famiglia_casi": famiglia_casi,
        "quota_casi": round(100 * famiglia_casi / len(errori), 1) if errori else 0.0,
        "transcript": len(list(TRANSCRIPTS.glob("lezione_*.txt"))) if TRANSCRIPTS.is_dir() else 0,
        "pendenti": dettaglio_pendenti(),
        "giorni_esame": scadenze.giorni_all_esame(),
        "data_esame": scadenze.prossima_data_esame(),
    }


def genera() -> str:
    d = raccogli()
    oggi = date.today().isoformat()

    r = [
        "# Stato — tedesco",
        "",
        f"> **GENERATO** da `deutschops.py stato` il {oggi}. Non modificare a mano:",
        "> viene sovrascritto. L'unico file di stato scritto a mano e'",
        "> [`scadenze.md`](scadenze.md).",
        "",
        "## Dove sono",
        "",
        "| | |",
        "|---|---|",
        f"| Lezioni con Stefanie | {d['lezioni']} · {d['ore']} ore |",
    ]

    if d["ultima_lezione"]:
        nota = ""
        if (g := d["giorni_da_ultima"]) is not None:
            nota = f" ({g} giorni fa)" + ("  ⚠️ oltre 3 settimane" if g > 21 else "")
        r.append(f"| Ultima lezione | {d['ultima_lezione']}{nota} |")

    r += [
        f"| Vocaboli tracciati | {d['vocaboli']} · di cui B2+ **{d['b2_o_oltre']}** |",
        f"| Regole di grammatica | {d['regole']} |",
        f"| Errori corretti da Stefanie | {d['errori']} |",
    ]

    if d["data_esame"] and d["giorni_esame"] is not None:
        sett = round(d["giorni_esame"] / 7)
        r.append(f"| Esame B2 | {d['data_esame']} — fra {d['giorni_esame']} giorni (~{sett} settimane) |")

    r += ["", "### Vocaboli per livello", "",
          "| " + " | ".join(d["livelli"]) + " |",
          "|" + "---|" * len(d["livelli"]) + "",
          "| " + " | ".join(str(v) for v in d["livelli"].values()) + " |", ""]

    # -------------------------------------------------- errori
    r += [
        "## Dove sbaglio",
        "",
        f"**{d['famiglia_casi']} errori su {d['errori']} ({d['quota_casi']}%) sono "
        "Kasus, Genus o Präposition** — tre facce dello stesso sistema. E' il "
        "bersaglio prioritario del drill.",
        "",
        "| Categoria | Errori |",
        "|---|---|",
    ]
    r += [f"| {c} | {n} |" for c, n in d["errori_per_categoria"]]
    r.append("")

    # -------------------------------------------------- cose aperte
    if d["pendenti"]:
        r += ["## Lezioni non chiuse", "",
              "Un task aperto significa che quel run non e' arrivato in fondo. "
              "Finche' resta aperto, quella lezione ha dei pezzi mancanti.", "",
              "| Lezione | Manca | Ultimo errore |", "|---|---|---|"]
        for p in d["pendenti"]:
            r.append(f"| {p['data']} | {', '.join(p['mancanti'])} | "
                     f"{p['ultimo_errore'] or '—'} |")
        r.append("")

    # -------------------------------------------------- scadenze
    righe = scadenze.righe_briefing()
    if righe:
        r += ["## Scadenze da guardare", ""] + [f"- {x}" for x in righe] + [""]

    r += [
        "---",
        "",
        "### Fonti (non duplicate qui — questo file e' una vista)",
        "",
        f"- `lesson_registry.json` — {d['lezioni']} lezioni",
        f"- `data/vocab_db.json` — {d['vocaboli']} vocaboli",
        f"- `data/grammar_db.json` — {d['regole']} regole",
        f"- `data/error_db.json` — {d['errori']} errori",
        f"- `transcripts/` — {d['transcript']} trascrizioni",
        f"- [`stato/scadenze.md`](scadenze.md) — il registro scritto a mano",
        "",
    ]

    testo = "\n".join(r)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(testo, encoding="utf-8")
    return testo
