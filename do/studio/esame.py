"""Gap analysis verso il Goethe-Zertifikat B2.

Sostituisce b1_gap.py, che puntava al curriculum sbagliato (B1) ed era fermo
all'11 giugno con numeri falsi: diceva "118 parole B1" quando oggi sono 264.
Assorbe anche weak_cards.py e pharma_glossary.py — tre script, tre client, tre
prompt per un'unica domanda ("cosa devo studiare").

DUE DIFFERENZE DI SOSTANZA RISPETTO A b1_gap.py

1. Il conteggio e' deterministico, il giudizio no.
   b1_gap mandava tutto all'LLM. Qui le parti calcolabili (vocaboli per
   livello, categorie d'errore, quante regole coprono un tema) le calcola
   Python; all'LLM resta solo il giudizio di copertura, che e' fuzzy per
   natura. Meno superficie per inventare, e il conteggio non puo' sbagliare.

2. Il costo e' quello vero, e la copertura si dichiara per cio' che e'.
   E' una metrica AUTO-PRODOTTA dallo stesso sistema che genera le lezioni:
   misura cosa hai incontrato, non cosa produci sotto esame. Il verdetto vero
   e' il Modellsatz cronometrato — vedi stato/scadenze.md.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime

from ..base.config import llm_config
from ..base.llm import chiama, estrai_json
from ..base.paths import DATA, GRAMMAR_DB, VOCAB_DB

OUT = DATA / "esame_b2.json"


# --------------------------------------------------------------- il curriculum
# Grammatica B2 canonica: cio' che si aggiunge sopra il B1, non l'elenco
# completo. Se un tema B1 non e' consolidato lo dice il quaderno errori.
B2_GRAMMATICA = [
    "Konjunktiv I und indirekte Rede (Berichten, Zitieren)",
    "Konjunktiv II der Vergangenheit (hätte/wäre + Partizip II)",
    "Zustandspassiv vs Vorgangspassiv",
    "Passiv mit Modalverben in allen Zeitformen",
    "Passiversatzformen (sich lassen, sein + zu + Infinitiv, -bar/-lich)",
    "Erweiterte Partizipialattribute (der von allen erwartete Bericht)",
    "Partizipialkonstruktionen als Nebensatzersatz",
    "Nominalisierung und Verbalisierung (Nominalstil ↔ Verbalstil)",
    "Präpositionen mit Genitiv (aufgrund, anhand, hinsichtlich, mittels, seitens)",
    "Subjektive Bedeutung der Modalverben (er muss krank sein, sie will es gesehen haben)",
    "Futur II (Vermutung über Vergangenes)",
    "Relativsätze mit Genitiv (dessen/deren), wo-/was-/wer-Relativsätze",
    "Irreale Vergleichssätze (als ob, als wenn, als + Konjunktiv)",
    "Konzessivsätze (obgleich, wenngleich, ungeachtet, zwar...aber)",
    "Zweiteilige Konnektoren (einerseits...andererseits, weder...noch, je...desto)",
    "Adverbialsätze: indem, sodass, insofern als, ohne dass, anstatt dass",
    "Funktionsverbgefüge (zur Verfügung stellen, in Betracht ziehen, Anspruch erheben)",
    "Wortbildung: trennbare vs untrennbare Präfixe (durch-, über-, um-, unter-)",
    "Wortbildung: Nominalsuffixe und Adjektivsuffixe (-ung, -heit, -bar, -los, -haft)",
    "Negation: Stellung von nicht, keineswegs/keinesfalls, Negationspräfixe",
    "Textkohäsion: Konnektoradverbien und Verweiswörter im Text",
    "Gradpartikeln und Modalpartikeln (doch, ja, wohl, eben, halt)",
]

# I quattro moduli d'esame. Sostenibili separatamente: e' la leva strategica
# quando il tempo e' poco (vedi stato/scadenze.md).
MODULI = {
    "Lesen": "5 parti, 65 min — testi lunghi, dettaglio e opinione",
    "Hören": "2 parti, 40 min — dialoghi quotidiani e conferenze",
    "Schreiben": "2 parti, 75 min — testo argomentativo e messaggio formale",
    "Sprechen": "2 parti, 15 min — presentazione breve e discussione",
}


# --------------------------------------------------------------- dati (calcolati)
def _json(p, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def _regole_coperte() -> list[str]:
    g = _json(GRAMMAR_DB, {})
    regole = g.get("rules", g) if isinstance(g, dict) else {}
    if not isinstance(regole, dict):
        return []
    return sorted({
        (r.get("rule") or "").strip()
        for r in regole.values() if isinstance(r, dict) and r.get("rule")
    })


def _vocaboli_per_livello() -> dict[str, int]:
    v = _json(VOCAB_DB, {})
    parole = v.get("words", v) if isinstance(v, dict) else v
    if isinstance(parole, dict):
        parole = list(parole.values())
    return dict(Counter(
        (w.get("level") or w.get("cefr") or "?") for w in parole if isinstance(w, dict)
    ))


def _errori_ricorrenti(top: int = 12) -> list[tuple[str, int]]:
    """Solo gli errori corretti in lezione.

    Quelli fatti nell'app sono segnale, ma di natura diversa: li giudica un
    modello, non una madrelingua. La gap analysis decide quanto sei pronto per
    il B2 — mescolare le due fonti in quel giudizio, senza distinguerle, e'
    esattamente il tipo di contaminazione silenziosa che rende un numero
    inutilizzabile. Riammetterli, se serve, va fatto come stream etichettato.
    """
    from ..sapere import errori as quaderno

    return Counter(
        (x.get("category") or "?") for x in quaderno.registrati(quaderno.LEZIONE)
    ).most_common(top)


def istantanea() -> dict:
    """Tutto cio' che si puo' sapere senza chiamare un modello. Gratis."""
    livelli = _vocaboli_per_livello()
    return {
        "vocaboli_per_livello": livelli,
        "vocaboli_totali": sum(livelli.values()),
        "vocaboli_b2_o_oltre": sum(n for l, n in livelli.items() if l in ("B2", "C1", "C2")),
        "regole_coperte": len(_regole_coperte()),
        "errori_ricorrenti": _errori_ricorrenti(),
    }


# --------------------------------------------------------------- giudizio (LLM)
SYSTEM = """Sei un esaminatore Goethe-Zertifikat B2 e insegnante di tedesco.

Lo studente: Kevin, italiano, in transizione verso il settore pharma svizzero
(area Basilea). Obiettivo dichiarato: B2 entro ottobre 2026.

Ricevi: (1) la checklist di grammatica B2, (2) le regole gia' coperte nelle sue
lezioni, (3) i conteggi reali del suo vocabolario per livello, (4) le sue
categorie d'errore ricorrenti, (5) le settimane rimaste.

Sii ONESTO sulla fattibilita'. Se i dati suggeriscono che il B2 completo a
ottobre non e' realistico, dillo e indica quali MODULI sono plausibili: l'esame
e' modulare, si possono dare separatamente. Non essere incoraggiante per
cortesia — una stima ottimista sbagliata costa a Kevin la tassa d'esame.

Nota sui dati: i conteggi del vocabolario misurano cio' che la pipeline ha
estratto dalle lezioni, NON tutto cio' che lo studente sa. Trattali come limite
inferiore, e dillo se e' rilevante per il giudizio.

Rispondi SOLO con JSON valido, niente backtick:
{"grammatica":[{"tema":"<dalla checklist>","stato":"coperto|parziale|mancante","nota":"<breve>"}],
 "moduli":[{"modulo":"Lesen|Hören|Schreiben|Sprechen","prontezza":"probabile|incerta|improbabile","perche":"<1 frase>"}],
 "valutazione_vocabolario":"<2-3 frasi>",
 "fattibilita_ottobre":"<3-4 frasi oneste, con quali moduli tentare>",
 "priorita":[{"tema":"<cosa studiare>","perche":"<legato a un gap o a un errore ricorrente>","modulo":"<quale modulo aiuta>"}],
 "messaggio_stefanie":"<messaggio breve in tedesco che Kevin puo' mandare a Stefanie con i 3 temi successivi>"}

priorita: esattamente 6, ordinate per impatto sull'esame di ottobre."""


def analizza(settimane_rimaste: int | None = None) -> dict:
    snap = istantanea()
    coperte = _regole_coperte()

    if settimane_rimaste is None:
        from ..motore.scadenze import giorni_all_esame
        g = giorni_all_esame()
        settimane_rimaste = round(g / 7) if g is not None else 10

    user = (
        "CHECKLIST GRAMMATICA B2:\n" + "\n".join(f"- {t}" for t in B2_GRAMMATICA)
        + f"\n\nREGOLE GIA' COPERTE NELLE LEZIONI ({len(coperte)}):\n"
        + "\n".join(f"- {r}" for r in coperte)
        + f"\n\nVOCABOLARIO PER LIVELLO (conteggio reale): {json.dumps(snap['vocaboli_per_livello'])}"
        + f"\nTotale {snap['vocaboli_totali']}, di cui B2 o oltre: {snap['vocaboli_b2_o_oltre']}"
        + f"\n\nERRORI RICORRENTI (categoria, conteggio): {json.dumps(snap['errori_ricorrenti'], ensure_ascii=False)}"
        + f"\n\nSETTIMANE RIMASTE ALL'ESAME: {settimane_rimaste}"
        + f"\n\nMODULI D'ESAME: {json.dumps(MODULI, ensure_ascii=False)}"
    )

    # 16k e non 6k: l'output e' grosso (22 temi di grammatica + 4 moduli + 6
    # priorita' + un messaggio in tedesco) e a 6000 veniva troncato a meta'.
    testo, uso = chiama(SYSTEM, user, llm_config(max_tokens=16000))
    dati = estrai_json(testo)

    dati["generato"] = datetime.now().isoformat(timespec="seconds")
    dati["settimane_rimaste"] = settimane_rimaste
    dati["istantanea"] = snap
    dati["costo_eur"] = uso.costo_eur
    dati["costo_stimato"] = uso.stimato
    dati["modello"] = uso.model

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(dati, ensure_ascii=False, indent=2), encoding="utf-8")
    return dati


def stampa(dati: dict) -> None:
    sep = "=" * 62
    print(f"\n{sep}\n  GAP B2 — {dati.get('settimane_rimaste','?')} settimane all'esame\n{sep}")

    c = Counter(t["stato"] for t in dati.get("grammatica", []))
    print(f"  Grammatica B2: {c.get('coperto',0)} coperti · "
          f"{c.get('parziale',0)} parziali · {c.get('mancante',0)} mancanti")

    snap = dati.get("istantanea", {})
    print(f"  Vocabolario  : {snap.get('vocaboli_totali',0)} totali, "
          f"{snap.get('vocaboli_b2_o_oltre',0)} a livello B2+")

    print(f"\n  -- Prontezza per modulo --")
    for m in dati.get("moduli", []):
        print(f"   {m['modulo']:10s} {m['prontezza']:12s} {m['perche']}")

    print(f"\n  -- Fattibilita' ottobre --\n   {dati.get('fattibilita_ottobre','')}")

    print(f"\n  -- Da studiare, per impatto sull'esame --")
    for i, p in enumerate(dati.get("priorita", []), 1):
        print(f"   {i}. [{p.get('modulo','—')}] {p['tema']}")
        print(f"      -> {p['perche']}")

    print(f"\n  -- Messaggio pronto per Stefanie --\n   {dati.get('messaggio_stefanie','')}")

    costo = dati.get("costo_eur", 0)
    nota = " (stimato)" if dati.get("costo_stimato") else ""
    print(f"\n  Costo reale di questa analisi: {costo:.4f} EUR{nota}\n{sep}\n")
