"""Esercizi di produzione dal quaderno errori.

SOSTITUISCE IL BLOCCO ESERCIZI DI ASTRA
`generate_astra_prompts.py` impaginava in un PDF una specifica di 6 drill
(fill-in-the-blank, traduzione DE->EN e EN->DE, completamento dialoghi, free
writing, grammar drill) che Kevin caricava a mano su un chatbot. Astra non e'
mai esistito come integrazione: nessun SDK, nessun retrieval, solo PDF
write-only. Qui la stessa funzione consuma direttamente `error_db.json` — 284
errori reali con la correzione di Stefanie — senza upload e senza vendor.

PERCHE' DAGLI ERRORI E NON DA UN CURRICULUM
Un esercizio generico su "i casi" allena i casi in astratto. Un esercizio
costruito su una frase che Kevin ha DAVVERO sbagliato, con la correzione che
Stefanie gli ha DAVVERO dato, colpisce il suo profilo d'errore. E' il testing
effect applicato al dato che gia' possiede: 60 errori di Kasus, 55 di Wortwahl,
44 di Verbform, 42 di Wortstellung, 40 di Präposition, 27 di Genus.

Kasus + Genus + Präposition sono 127 errori, il 45% del totale, e sono lo
stesso sistema visto da tre lati. E' li' che il drill deve battere.

PRODUZIONE, NON RICONOSCIMENTO
Gli esercizi chiedono di PRODURRE la forma corretta, non di riconoscerla fra
opzioni. Riconoscere e' facile e da' l'illusione di sapere; produrre e' quello
che serve a parlare ed e' quello che l'esame misura.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime

from ..base.config import llm_config
from ..base.llm import chiama, estrai_json
from ..base.paths import DATA
from ..sapere import errori as quaderno

OUT = DATA / "drill.json"

# Le tre categorie che condividono la radice: il sistema dei casi.
FAMIGLIA_CASI = {"Kasus", "Genus", "Präposition"}


def carica_errori(fonte: str | None = quaderno.LEZIONE) -> list[dict]:
    """Gli errori con una correzione utilizzabile.

    Per difetto solo quelli di lezione: un foglio di esercizi costruito su cio'
    che una madrelingua ha corretto vale piu' di uno costruito su cio' che un
    modello ha giudicato. `fonte=None` prende anche quelli fatti nell'app —
    lo usa la coda dell'allenamento, dove ripresentarli e' il punto.
    """
    return [x for x in quaderno.registrati(fonte) if x.get("correction")]


def per_categoria() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for e in carica_errori():
        out[e.get("category") or "?"].append(e)
    return dict(out)


def profilo() -> dict:
    """Il quadro degli errori, calcolato. Nessuna chiamata di rete."""
    errori = carica_errori()
    cat = Counter(e.get("category") or "?" for e in errori)
    regole = Counter(e.get("rule") or "?" for e in errori)
    n_casi = sum(n for c, n in cat.items() if c in FAMIGLIA_CASI)
    return {
        "totale": len(errori),
        "per_categoria": cat.most_common(),
        "regole_ricorrenti": [r for r in regole.most_common(12) if r[1] > 1],
        "famiglia_casi": n_casi,
        "quota_casi": round(100 * n_casi / len(errori), 1) if errori else 0.0,
    }


def _seleziona(categoria: str | None, quanti: int) -> list[dict]:
    """Gli errori su cui costruire il foglio.

    Senza categoria, prende dalla famiglia dei casi: e' dove sta il 45% del
    problema, e insistere li' rende piu' che spalmare su tutto.
    """
    gruppi = per_categoria()
    if categoria:
        scelti = gruppi.get(categoria, [])
    else:
        scelti = [e for c in FAMIGLIA_CASI for e in gruppi.get(c, [])]
        if not scelti:
            scelti = carica_errori()

    # I piu' recenti per primi: un errore di due mesi fa puo' essere superato,
    # uno di ieri no.
    scelti.sort(key=lambda e: e.get("lesson_date") or "", reverse=True)
    return scelti[:quanti]


SYSTEM = """You are a German teacher preparing targeted exercises for Kevin
(Italian native, working towards B2, moving into the Swiss pharmaceutical sector).

You receive a list of his REAL MISTAKES: what he said, the correction his native
teacher gave him, and the rule he broke.

Build a PRODUCTION exercise sheet. Non-negotiable rules:

1. Every exercise must come from a mistake in the list. Do not invent topics.
2. Ask him to PRODUCE, never to choose between options. No multiple choice:
   recognising is easy and gives the illusion of knowing.
3. Do NOT reuse the original wrong sentence. Build a NEW context that requires
   the same structure: if he recognises it by heart he is not learning.
4. Block word-for-word translation from Italian: it is the source of most of his
   Wortwahl and Präposition mistakes.
5. Solutions must be correct, natural German. If you are not certain of a form,
   do not use it: a mistake here would be studied as if it were right.

Write the instructions in ENGLISH, the German content in German. No Italian.

Reply with valid JSON only, no backticks:
{"titolo":"<short, says what is being worked on>",
 "esercizi":[{"consegna":"<what he has to do, in English>",
              "stimolo":"<the starting sentence or context>",
              "soluzione":"<the correct German>",
              "errore_bersaglio":"<the rule this trains>",
              "tipo":"translation|rewrite|gap|free_production"}],
 "nota_finale":"<1-2 sentences, in English, on what to watch while doing it>"}

Vary the types. Order from simplest to hardest."""


def genera(categoria: str | None = None, quanti: int = 10) -> dict:
    """Un foglio di esercizi mirato. Una chiamata LLM, costo misurato."""
    errori = _seleziona(categoria, quanti)
    if not errori:
        raise RuntimeError(
            "Nessun errore utilizzabile in error_db.json. "
            "Il quaderno errori si popola durante la pipeline della lezione."
        )

    righe = "\n".join(
        f"- [{e.get('category')}] he said: {e.get('kevin_said')!r}\n"
        f"  corrected: {e.get('correction')!r}\n"
        f"  rule: {e.get('rule')}"
        for e in errori
    )
    p = profilo()
    user = (
        f"KEVIN'S REAL MISTAKES ({len(errori)} selected):\n{righe}\n\n"
        f"OVERALL PICTURE: {p['totale']} mistakes in total, "
        f"{p['famiglia_casi']} of them ({p['quota_casi']}%) on the case system "
        f"(Kasus/Genus/Präposition).\n"
        f"Distribution: {json.dumps(p['per_categoria'], ensure_ascii=False)}\n\n"
        f"Generate {quanti} exercises."
    )

    testo, uso = chiama(SYSTEM, user, llm_config(max_tokens=12000))
    dati = estrai_json(testo)
    dati["generato"] = datetime.now().isoformat(timespec="seconds")
    dati["categoria"] = categoria or "famiglia casi (Kasus/Genus/Präposition)"
    dati["errori_usati"] = len(errori)
    dati["costo_eur"] = uso.costo_eur
    dati["costo_stimato"] = uso.stimato

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(dati, ensure_ascii=False, indent=2), encoding="utf-8")
    return dati


def stampa(dati: dict, *, soluzioni: bool = False) -> None:
    sep = "=" * 62
    print(f"\n{sep}\n  {dati.get('titolo','Drill')}\n"
          f"  su {dati.get('categoria')} · da {dati.get('errori_usati')} errori reali\n{sep}")
    for i, e in enumerate(dati.get("esercizi", []), 1):
        print(f"\n  {i}. [{e.get('tipo','')}] {e.get('consegna','')}")
        print(f"     {e.get('stimolo','')}")
        if soluzioni:
            print(f"     -> {e.get('soluzione','')}")
            print(f"        ({e.get('errore_bersaglio','')})")
    if nota := dati.get("nota_finale"):
        print(f"\n  -- Da tenere d'occhio --\n   {nota}")
    costo = dati.get("costo_eur", 0)
    print(f"\n  Costo: {costo:.4f} EUR{' (stimato)' if dati.get('costo_stimato') else ''}\n{sep}\n")
