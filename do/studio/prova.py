"""Schreiben — scrivere, ed essere ripreso su cio' che scrivi.

COSA E' E COSA NON E'
**Non e' una simulazione d'esame con un voto.** Un compito inventato da un
modello e corretto dallo stesso modello produrrebbe un numero che assomiglia a
un punteggio Goethe senza esserlo, e `stato/scadenze.md` e' esplicito sul
perche' una metrica auto-prodotta non vale come misura. Il punteggio
confrontabile nel tempo sta in `modellsatz.py`, e viene dal PDF ufficiale
cronometrato.

Questo e' **allenamento alla produzione libera**, che e' un'altra cosa e serve
lo stesso — anzi, serve piu' del drill: il drill isola una regola, qui devi
tenerne trenta insieme mentre pensi a cosa dire. E' li' che si vede cosa e'
davvero automatico.

IL VALORE VERO NON E' IL FEEDBACK, E' DOVE FINISCE
Ogni errore trovato entra nel quaderno con `fonte: "studio"`, quindi finisce
nella coda dell'allenamento e torna come esercizio mirato. Scrivere un testo e
riceverne il commento e' utile una volta; scrivere un testo e vedersi
ripresentare quelle strutture per tre settimane e' un'altra cosa.

Il formato dei compiti segue il Goethe B2 (Teil 1: Forumsbeitrag argomentativo,
~150 parole; Teil 2: messaggio formale, ~100), perche' allenarsi su un formato
diverso da quello dell'esame e' lavoro sprecato — ma il formato e' l'unica cosa
che si prende in prestito, non il punteggio.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime

from ..base.config import llm_config
from ..base.llm import chiama, estrai_json
from ..base.paths import DATA
from ..sapere import errori as quaderno

REGISTRO = DATA / "prove_scritte.json"
_LUCCHETTO = threading.Lock()

TIPI = {
    "forum": {
        "nome": "Forum post",
        "descrizione": "Argumentative reply in an online discussion",
        "parole": 150,
        "minuti": 50,
    },
    "formale": {
        "nome": "Formal message",
        "descrizione": "Semi-formal email — a request, a complaint, an apology",
        "parole": 100,
        "minuti": 25,
    },
}


SYSTEM_COMPITO = """You write German B2 writing tasks in Goethe-Zertifikat format.

The learner is Kevin: Italian, working towards Goethe B2, a production manager
moving into the Swiss pharmaceutical sector (Basel area).

Write ONE task. Rules:

1. The prompt itself is in German, at B2 — he has to read it as he would in the
   exam.
2. Give a short situation, then the points he must cover. Goethe gives 4 bullet
   points for the forum post; keep that shape.
3. The topic must be something an adult has an opinion about — work, technology,
   city life, training, health, environment. Not a school essay theme.
4. Where it fits naturally, lean on his world (production, pharma, Switzerland,
   commuting, language learning) — but do not make every task about work.
5. No proper names of real people or companies.

Reply with valid JSON only, no backticks:
{"titolo":"<short English label for the task list>",
 "situazione":"<the situation, in German, 2-3 sentences>",
 "consegna":"<what he must write, in German, one line>",
 "punti":["<bullet 1, German>","<bullet 2>","<bullet 3>","<bullet 4>"],
 "aiuto_en":"<one line in English: what the task is asking, for when the German prompt is the blocker>"}"""


SYSTEM_CORREZIONE = """You are a German teacher correcting a B2 written text.

You get the task and what the learner wrote. He is Italian, working towards
Goethe B2. Be strict, precise and factual — he is here to find holes, not to
feel good. No praise, no exclamation marks, no encouragement padding.

Produce two things.

**A) Criterion feedback**, on the four dimensions the Goethe B2 Schreiben grid
uses. For each: what works, what does not, and what to do about it. Two short
lines each, in English. NO SCORES AND NO GRADES — this is practice, not an exam,
and a made-up number would be mistaken for a real one.

**B) The concrete mistakes**, as a list. This is the important part: each one is
going into his error notebook and will come back as a drill. So:
  - only real errors, not style preferences you happen to hold;
  - quote exactly what he wrote and give the exact correction;
  - name the rule in German, the way a teacher would ("Adjektivdeklination nach
    unbestimmtem Artikel"), because these names group with his existing ones;
  - be conservative — a wrong entry here poisons weeks of exercises.

Reply with valid JSON only, no backticks:
{"criteri":[{"nome":"Erfüllung|Kohärenz|Wortschatz|Strukturen",
             "commento":"<2 short lines, English>"}],
 "sintesi":"<2-3 lines in English: the single thing to fix first, and why>",
 "parole":<word count of his text, integer>,
 "errori":[{"category":"<one of: Genus, Wortstellung, Präposition, Kasus, Verbform, Wortwahl, Adjektivdeklination, Sonstiges>",
            "kevin_said":"<exactly what he wrote>",
            "correction":"<the correct German>",
            "rule":"<rule name in German>",
            "explanation_en":"<1 line, why>"}]}

If the text is too short or off-task to judge, say so in "sintesi" and return
"errori": []."""


def _carica() -> dict:
    try:
        d = json.loads(REGISTRO.read_text(encoding="utf-8"))
        if isinstance(d, dict) and isinstance(d.get("prove"), list):
            return d
    except Exception:
        pass
    return {"prove": [], "costo_totale_eur": 0.0}


def compito(tipo: str = "forum") -> dict:
    """Genera un compito di scrittura. Una chiamata LLM."""
    spec = TIPI.get(tipo) or TIPI["forum"]
    fatti = [p.get("compito", {}).get("titolo", "") for p in _carica()["prove"]]
    evita = (f"\n\nAlready used, pick something else: {', '.join(fatti[-8:])}"
             if fatti else "")

    testo, uso = chiama(
        SYSTEM_COMPITO,
        f"TASK TYPE: {spec['nome']} — {spec['descrizione']}, "
        f"about {spec['parole']} words, {spec['minuti']} minutes.{evita}",
        llm_config(max_tokens=2000),
    )
    d = estrai_json(testo)
    return {
        "tipo": tipo,
        "nome": spec["nome"],
        "parole": spec["parole"],
        "minuti": spec["minuti"],
        "titolo": (d.get("titolo") or spec["nome"]).strip(),
        "situazione": (d.get("situazione") or "").strip(),
        "consegna": (d.get("consegna") or "").strip(),
        "punti": [x.strip() for x in (d.get("punti") or []) if isinstance(x, str)],
        "aiuto_en": (d.get("aiuto_en") or "").strip(),
        "generato": datetime.now().isoformat(timespec="seconds"),
        "costo_eur": uso.costo_eur,
    }


def correggi(compito_dato: dict, testo_scritto: str) -> dict:
    """Corregge un testo e manda gli errori nel quaderno. Una chiamata LLM.

    Gli errori entrano con `fonte: "studio"`, quindi le statistiche sulle
    correzioni di Stefanie restano pulite e la coda dell'allenamento li vede.
    E' la stessa strada di una risposta sbagliata in allenamento.
    """
    scritto = (testo_scritto or "").strip()
    if len(scritto.split()) < 20:
        return {"errore": "Too short to correct — write at least a few sentences."}

    punti = "\n".join(f"- {x}" for x in compito_dato.get("punti", []))
    user = (
        f"TASK ({compito_dato.get('nome')}, ~{compito_dato.get('parole')} words)\n"
        f"{compito_dato.get('situazione','')}\n{compito_dato.get('consegna','')}\n"
        f"{punti}\n\n=== WHAT HE WROTE ===\n{scritto}"
    )
    risposta, uso = chiama(SYSTEM_CORREZIONE, user, llm_config(max_tokens=6000))
    d = estrai_json(risposta)

    # Nel quaderno solo cio' che ha una correzione utilizzabile.
    annotati = 0
    for e in d.get("errori", []):
        if not (e.get("correction") or "").strip():
            continue
        quaderno.annota({
            "category": e.get("category"),
            "kevin_said": (e.get("kevin_said") or "").strip(),
            "correction": e["correction"].strip(),
            "rule": (e.get("rule") or "").strip(),
            "explanation_en": (e.get("explanation_en") or "").strip(),
            "example_correct": e["correction"].strip(),
            "esercizio": f"Schreiben · {compito_dato.get('titolo','')}",
        })
        annotati += 1

    esito = {
        "criteri": [c for c in d.get("criteri", []) if isinstance(c, dict)],
        "sintesi": (d.get("sintesi") or "").strip(),
        "parole": d.get("parole") or len(scritto.split()),
        "errori": d.get("errori", []),
        "nel_quaderno": annotati,
        "costo_eur": uso.costo_eur,
        "costo_stimato": uso.stimato,
    }

    with _LUCCHETTO:
        reg = _carica()
        reg["prove"].append({
            "quando": datetime.now().isoformat(timespec="seconds"),
            "compito": {k: compito_dato.get(k) for k in ("tipo", "titolo", "parole")},
            "testo": scritto,
            "parole": esito["parole"],
            "errori": annotati,
            "sintesi": esito["sintesi"],
            "costo_eur": uso.costo_eur,
        })
        reg["costo_totale_eur"] = round(
            reg.get("costo_totale_eur", 0.0) + uso.costo_eur, 4)
        try:
            REGISTRO.parent.mkdir(parents=True, exist_ok=True)
            tmp = REGISTRO.with_name(REGISTRO.name + ".tmp")
            tmp.write_text(json.dumps(reg, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            tmp.replace(REGISTRO)
        except OSError:
            pass

    return esito


def storico() -> list[dict]:
    """Le prove scritte fatte, dalla piu' recente. Senza il testo integrale."""
    return [{k: v for k, v in p.items() if k != "testo"}
            for p in reversed(_carica()["prove"])]
