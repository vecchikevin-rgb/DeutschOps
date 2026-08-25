"""Frasi costruite su misura, quando il corpus non basta.

PERCHE' ESISTE, VISTO CHE `frasi.py` DICE IL CONTRARIO
`frasi.py` sostiene — e ha ragione — che per il sentence mining i+1 un LLM non
serve: e' aritmetica su insiemi, e un modello puo' solo inventare frasi che
Stefanie non ha mai detto. Quella resta la sorgente primaria.

Il problema e' emerso all'uso, e l'ha posto Kevin: dei 861 candidati i+1 del
corpus, solo 89 superano `completabile()`. Gli altri sono parlato spontaneo —
frammenti, esitazioni, balbettii, refusi di trascrizione — dove il buco non si
deduce ma si indovina. 89 frasi coprono tre sessioni da 30, poi si ripetono.

Qui si copre il vuoto, con due vincoli che tengono la cosa onesta:

1. **Le frasi reali vengono prima.** Queste entrano solo quando quelle del
   corpus sono finite o gia' sapute. Una frase davvero detta dalla tua
   insegnante vale piu' di una costruita, sempre.
2. **Sono marcate.** `fonte: "composta"` viaggia con ogni frase fino al
   registro, cosi' nessuna misura confonde le due popolazioni.

Il vocabolario bersaglio non e' inventato: viene da `vocab_db`, cioe' da parole
che sono davvero passate nelle tue lezioni. Cambia il contesto, non il lessico.
"""

from __future__ import annotations

import json
import random
from datetime import datetime

from ..base.config import llm_config
from ..base.llm import chiama, estrai_json
from ..base.paths import DATA, VOCAB_DB

DEPOSITO = DATA / "frasi_composte.json"

# Sotto questa soglia di frasi ancora da fare, il deposito si ricarica.
SCORTA_MINIMA = 12
QUANTE_PER_VOLTA = 24


SYSTEM = """You write German example sentences for a gap-fill exercise.

The learner is Kevin: Italian, working towards Goethe B2, moving into the Swiss
pharmaceutical sector. He has a weekly lesson with a native teacher.

You receive TARGET WORDS taken from his own lesson vocabulary. For each one
write ONE sentence, following these rules without exception:

1. The sentence must be **grammatically correct, natural German**. It will be
   studied as a model — an error here gets memorised as if it were right.
2. The target word must be **deducible from the sentence alone**. A reader who
   knows the rest of the sentence should be able to arrive at that word, not
   guess between five plausible ones. Build a context that forces it:
   a collocation, a clear semantic frame, a contrast.
3. **8 to 18 words.** Enough context on BOTH sides of the target word — never
   put it in the last two positions.
4. Everyday or professional register, the kind of thing said in a real
   conversation. No textbook artificiality, no proper names, no quotation marks.
5. Use the target word in the exact form given. Do not inflect it differently.
6. Level A2-B1, occasionally B2. Simple sentences, one subordinate clause at
   most.

Reply with JSON only, no backticks:
{"frasi":[{"parola":"<the target word, unchanged>",
           "testo":"<the full sentence, with the word in it>",
           "perche":"<in English, one short line: what in the sentence makes the word deducible>"}]}"""


def _vocabolario(quanti: int, escludi: set[str]) -> list[dict]:
    """Parole bersaglio da `vocab_db`: gia' passate nelle sue lezioni."""
    try:
        v = json.loads(VOCAB_DB.read_text(encoding="utf-8"))
    except Exception:
        return []

    parole = v.get("words", v) if isinstance(v, dict) else v
    valori = list(parole.values()) if isinstance(parole, dict) else list(parole)

    buone = [
        w for w in valori
        if isinstance(w, dict)
        and (w.get("german") or "").strip()
        and len(w["german"].split()) == 1
        and w["german"].lower() not in escludi
        and w.get("level") in ("A2", "B1", "B2")
    ]
    # Le meno incontrate per prime: sono quelle che rendono di piu' a rivedere.
    buone.sort(key=lambda w: w.get("occurrences") or 0)
    return buone[: quanti * 3]


def _carica() -> dict:
    try:
        d = json.loads(DEPOSITO.read_text(encoding="utf-8"))
        if isinstance(d, dict) and isinstance(d.get("frasi"), list):
            return d
    except Exception:
        pass
    return {"frasi": [], "costo_totale_eur": 0.0}


def disponibili(escludi_testi: set[str] | None = None) -> list[dict]:
    """Le frasi in deposito, meno le segnalate e le non completabili.

    Il prompt CHIEDE frasi deducibili, ma chiederlo non e' ottenerlo: le stesse
    regole che filtrano il corpus si applicano anche qui. Costa niente ed evita
    che una generazione storta finisca davanti a Kevin.
    """
    from .frasi import completabile

    escludi_testi = escludi_testi or set()
    fuori = []
    for f in _carica()["frasi"]:
        testo, parola = (f.get("testo") or "").strip(), (f.get("parola") or "").strip()
        if not testo or not parola:
            continue
        if " ".join(testo.split()) in escludi_testi:
            continue
        if not completabile(testo, parola):
            continue
        fuori.append(f)
    return fuori


def componi(quante: int = QUANTE_PER_VOLTA, *, escludi: set[str] | None = None) -> dict:
    """Genera un blocco di frasi e le aggiunge al deposito. Una chiamata LLM.

    Si genera **a blocchi** e non su richiesta: una chiamata per venti frasi
    costa una frazione di centesimo e non fa aspettare all'apertura dell'app.
    """
    deposito = _carica()
    gia_fatte = {(f.get("parola") or "").lower() for f in deposito["frasi"]}
    gia_fatte |= {p.lower() for p in (escludi or set())}

    scelte = _vocabolario(quante, gia_fatte)
    if not scelte:
        raise RuntimeError(
            "Nessuna parola bersaglio disponibile in vocab_db. "
            "Il vocabolario si popola elaborando le lezioni."
        )
    random.shuffle(scelte)
    scelte = scelte[:quante]

    righe = "\n".join(
        f"- {w['german']}"
        + (f" ({w['article']})" if w.get("article") else "")
        + (f" — {w.get('english') or w.get('italian')}" if (w.get("english") or w.get("italian")) else "")
        + (f" · {w['category']}" if w.get("category") else "")
        for w in scelte
    )
    user = f"TARGET WORDS ({len(scelte)}):\n{righe}\n\nWrite one sentence for each."

    testo, uso = chiama(SYSTEM, user, llm_config(max_tokens=8000))
    dati = estrai_json(testo)

    quando = datetime.now().isoformat(timespec="seconds")
    aggiunte = []
    for f in dati.get("frasi", []):
        parola, frase = (f.get("parola") or "").strip(), (f.get("testo") or "").strip()
        # Scarta in silenzio cio' che non e' utilizzabile: una frase che non
        # contiene la sua stessa parola bersaglio non e' un esercizio.
        if not parola or not frase or parola.lower() not in frase.lower():
            continue
        aggiunte.append({
            "parola": parola,
            "testo": frase,
            "perche": (f.get("perche") or "").strip(),
            "fonte": "composta",
            "generata": quando,
        })

    deposito["frasi"].extend(aggiunte)
    deposito["costo_totale_eur"] = round(
        deposito.get("costo_totale_eur", 0.0) + uso.costo_eur, 4)
    deposito["ultimo_costo_eur"] = uso.costo_eur
    deposito["costo_stimato"] = uso.stimato
    deposito["aggiornato"] = quando

    DEPOSITO.parent.mkdir(parents=True, exist_ok=True)
    DEPOSITO.write_text(json.dumps(deposito, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    return {
        "aggiunte": len(aggiunte),
        "chieste": len(scelte),
        "in_deposito": len(deposito["frasi"]),
        "costo_eur": uso.costo_eur,
        "costo_stimato": uso.stimato,
    }
