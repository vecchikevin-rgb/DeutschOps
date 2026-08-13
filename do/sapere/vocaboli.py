"""Il database cumulativo del vocabolario.

Porta `vocab_db.py`. Lo schema su disco resta IDENTICO: lo leggono
do/studio/frasi.py (parole note), do/studio/manutenzione.py (indice per
l'audit Anki) e do/motore/stato.py (conteggi per livello). Cambiarlo qui
significherebbe romperli tutti in silenzio.

Cosa cambia davvero: i path non dipendono piu' dalla cwd, e
`aggiorna_da_lezione` accetta il dict gia' in memoria invece di rileggere il
JSON dal disco — la pipeline lo ha gia' fra le mani.

AGGIUNTA 2026-08-13: `example_it`/`example_en` in `words[...]`, additiva
(nessun campo tolto o rinominato). Prima solo `example_de` veniva copiato
qui: `manutenzione.ripara()` legge gia' `voce.get("example_it")` per le carte
Riconoscimento/Produzione ma quel campo era sempre vuoto perche' non arrivava
mai fin qui. `example_en` serve alla carta Cloze — vedi
`backfill_example_en()`.
"""

from __future__ import annotations

import json
from datetime import date

from ..base.config import llm_config
from ..base.llm import chiama, estrai_json
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
            # Backfill non distruttivo: una lezione rielaborata dopo che il
            # campo e' diventato obbligatorio puo' avere cio' che il primo
            # giro non aveva. Non si sovrascrive un valore gia' presente.
            for campo in ("example_it", "example_en"):
                if not (e.get(campo) or "").strip() and (v.get(campo) or "").strip():
                    e[campo] = v[campo]
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
                "example_it": v.get("example_it", ""),
                "example_en": v.get("example_en", ""),
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


SYSTEM_BACKFILL_EN = """You translate German example sentences into English.

For each numbered German sentence, return a natural English translation of the
WHOLE sentence.

- Pure English. Not a single German word in the output.
- Natural, not word-for-word.
- Do not explain, do not comment. Just the sentence.

Reply with valid JSON only, no backticks:
{"traduzioni":[{"n":<the number>,"testo":"<the English sentence>"}]}"""


def backfill_example_en(quanti: int = 80) -> dict:
    """Aggiunge `example_en` ai vocaboli storici che ne sono privi.

    LAVORO A LOTTI SU MATERIALE STORICO -> BACKEND ABBONAMENTO SEMPRE
    Non e' un percorso interattivo e non deve mai finire sulla fattura a
    consumo: `backend="claude"` e' passato esplicito, non delegato a
    LLM_BACKEND/--motore. Vedi la nota "Chi paga" nel CLAUDE.md di progetto.

    Scrive sui JSON per lezione (la fonte vera — carte.py li legge diretti,
    non da vocab_db) e poi ricostruisce vocab_db, cosi' i due restano
    allineati. Un batch per chiamata, come `allenamento.traduci()`: chiamare
    di nuovo finche' `rimasti` e' zero.
    """
    file_dati: dict = {}
    da_tradurre: list[tuple] = []          # (file, indice, example_de)

    for f in sorted(DATA.glob("lezione_*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        file_dati[f] = d
        for i, v in enumerate(d.get("vocabulary", [])):
            if not isinstance(v, dict):
                continue
            de = (v.get("example_de") or "").strip()
            if de and not (v.get("example_en") or "").strip():
                da_tradurre.append((f, i, de))

    if not da_tradurre:
        return {"tradotti": 0, "rimasti": 0, "file_toccati": 0, "costo_eur": 0.0}

    lotto = da_tradurre[:quanti]
    righe = "\n".join(f"{n}. {de}" for n, (_, _, de) in enumerate(lotto, 1))
    testo, uso = chiama(
        SYSTEM_BACKFILL_EN, f"SENTENCES ({len(lotto)}):\n{righe}",
        llm_config(max_tokens=6000, effort="low", backend="claude"),
    )
    per_numero = {int(t.get("n", 0)): (t.get("testo") or "").strip()
                  for t in estrai_json(testo).get("traduzioni", [])
                  if str(t.get("n", "")).strip().isdigit()}

    file_toccati: set = set()
    tradotti = 0
    for n, (f, i, _) in enumerate(lotto, 1):
        en = per_numero.get(n, "")
        if not en:
            continue
        file_dati[f]["vocabulary"][i]["example_en"] = en
        file_toccati.add(f)
        tradotti += 1

    for f in file_toccati:
        f.write_text(json.dumps(file_dati[f], ensure_ascii=False, indent=2),
                     encoding="utf-8")
    if file_toccati:
        ricostruisci()          # riallinea vocab_db, che carte.py non legge
                                 # ma manutenzione.py si': senza, il fix delle
                                 # carte storiche (Task Cloze) vedrebbe zero.

    return {"tradotti": tradotti, "rimasti": len(da_tradurre) - tradotti,
            "file_toccati": len(file_toccati), "costo_eur": uso.costo_eur,
            "costo_nozionale_eur": uso.costo_nozionale_eur}


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
