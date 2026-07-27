"""Sentence mining i+1 — deterministico, senza LLM.

PERCHE' NON SERVE UN MODELLO
La ricerca sull'input comprensibile converge su una soglia: perche' l'input
produca acquisizione deve essere comprensibile al 95-98%, cioe' con pochi
elementi nuovi sostenuti dal contesto. Tradotto in operazione: per ogni frase,
conta le parole che Kevin NON conosce; se e' esattamente una, e' una frase i+1.

E' aritmetica su insiemi. Un LLM qui non aggiunge niente e puo' solo inventare
frasi che Stefanie non ha mai detto. Questo modulo non fa nessuna chiamata di
rete e costa zero.

LE FRASI SONO REALI
Vengono dai transcript delle lezioni: tedesco detto da una madrelingua nel
contesto di Kevin, non testo generato.

IL PROBLEMA DELLA MORFOLOGIA, E COME LO AGGIRIAMO
Il tedesco flette molto: "gibt" non si riconduce a "geben" con uno sfoltimento
di suffissi, ne' "gemacht" a "machen" o "würde" a "werden". La prima versione
di questo modulo proponeva esattamente quelle come "parole nuove" — parole che
Kevin ha sentito decine di volte. L'output era inutilizzabile.

La correzione non e' un lemmatizzatore (spaCy `de_core_news_sm`, ~40MB): e'
usare il corpus come storia dell'esposizione. Una parola che compare 79 volte
nelle SUE 30 lezioni con Stefanie non e' nuova, qualunque forma abbia e
qualunque cosa dica `vocab_db`. Quindi:

    note = vocab_db  ∪  parole funzionali  ∪  { w : frequenza_corpus(w) >= N }

Deterministico, nessuna dipendenza, e piu' calibrato su Kevin di quanto sarebbe
un lemmatizzatore generico: misura la sua esposizione reale, non la lingua in
astratto.

Resta un limite: una parola frequente che non ha mai capito viene contata come
nota. E' un errore per difetto (proponiamo meno frasi), che e' il verso giusto.
Il quaderno errori copre il caso opposto — se la sbaglia, finisce li'.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass

from ..base.paths import TRANSCRIPTS, VOCAB_DB

# Lettere tedesche, incluse le umlaut e la eszett.
_TOKEN = re.compile(r"[a-zA-ZäöüÄÖÜß]+")
# Confine di frase: punto/!/? seguiti da spazio. Grezzo ma sufficiente su
# trascritti parlati, dove le frasi sono corte.
_FRASE = re.compile(r"(?<=[.!?])\s+")

_SUFFISSI = ("en", "es", "em", "er", "e", "n", "s")

# Parole grammaticali sempre considerate note: non sono "vocaboli nuovi" e
# contarle come sconosciute rovinerebbe ogni conteggio.
_FUNZIONALI = {
    "der", "die", "das", "den", "dem", "des", "ein", "eine", "einen", "einem",
    "eines", "einer", "und", "oder", "aber", "denn", "sondern", "doch",
    "ich", "du", "er", "sie", "es", "wir", "ihr", "mich", "dich", "sich", "uns", "euch",
    "mir", "dir", "ihm", "ihn", "ihnen", "mein", "dein", "sein", "unser", "euer",
    "in", "an", "auf", "zu", "mit", "von", "bei", "nach", "aus", "über", "unter",
    "vor", "hinter", "neben", "zwischen", "für", "um", "durch", "gegen", "ohne",
    "ist", "sind", "war", "waren", "bin", "bist", "seid", "sein", "hat", "haben",
    "hatte", "hatten", "habe", "hast", "wird", "werden", "wurde", "wurden",
    "kann", "können", "muss", "müssen", "will", "wollen", "soll", "sollen",
    "darf", "dürfen", "mag", "möchte", "nicht", "kein", "keine", "auch", "noch",
    "schon", "nur", "sehr", "so", "wie", "was", "wer", "wo", "wann", "warum",
    "dass", "weil", "wenn", "ob", "als", "dann", "da", "hier", "man", "es",
    "ja", "nein", "gut", "mal", "eigentlich", "vielleicht", "immer",
}


# I transcript sono BILINGUI: Stefanie spiega in inglese e parla in tedesco,
# spesso nella stessa lezione. Senza un filtro, "I go for a walk, right?"
# diventa una frase i+1 con "walk" come parola tedesca nuova.
# Marcatori inequivocabilmente tedeschi — esclusi di proposito i falsi amici
# ortografici con l'inglese (in, so, man, war, will, hat, an, am, ist/is).
_MARCATORI_DE = {
    "der", "die", "das", "den", "dem", "des", "und", "nicht", "ich", "du",
    "wir", "ihr", "sie", "sich", "auch", "noch", "schon", "sehr", "aber",
    "dass", "weil", "wenn", "oder", "für", "über", "mit", "auf", "zu", "aus",
    "sind", "haben", "hast", "habe", "hatte", "werden", "wird", "wurde",
    "kann", "können", "muss", "müssen", "möchte", "wie", "was", "wer", "wo",
    "eine", "einen", "einem", "eines", "einer", "kein", "keine", "mein",
    "dein", "sein", "ja", "nein", "genau", "vielleicht", "eigentlich", "immer",
}
MIN_MARCATORI = 2


def e_tedesca(frase: str) -> bool:
    """True se la frase e' plausibilmente tedesca e non inglese.

    Soglia bassa (2 marcatori) di proposito: una frase tedesca corta ne ha
    quasi sempre almeno due, una inglese quasi mai.
    """
    token = {t.lower() for t in _TOKEN.findall(frase)}
    return len(token & _MARCATORI_DE) >= MIN_MARCATORI


@dataclass(frozen=True)
class FraseIPiuUno:
    testo: str
    nuova: str
    frequenza: int          # quante volte la parola nuova compare nel corpus
    lezione: str

    def con_buco(self) -> str:
        return re.sub(rf"\b{re.escape(self.nuova)}\w*", "_____", self.testo,
                      count=1, flags=re.IGNORECASE)


def _radice(parola: str) -> str:
    """Sfoltimento di suffissi molto conservativo (vedi limite in cima)."""
    p = parola.lower()
    for s in _SUFFISSI:
        if len(p) > len(s) + 3 and p.endswith(s):
            return p[: -len(s)]
    return p


# Soglia di esposizione: una parola incontrata almeno cosi' tante volte nelle
# lezioni di Kevin e' trattata come nota, in qualunque forma flessa. 8 su un
# corpus di 30 lezioni significa "ricorrente", non "capitata una volta".
SOGLIA_ESPOSIZIONE = 8


def _frequenze_corpus() -> Counter[str]:
    """Quante volte ogni forma compare nei transcript. E' la storia
    dell'esposizione reale di Kevin, non un corpus di riferimento generico."""
    c: Counter[str] = Counter()
    if not TRANSCRIPTS.is_dir():
        return c
    for f in TRANSCRIPTS.glob("lezione_*.txt"):
        testo = f.read_text(encoding="utf-8", errors="replace")
        c.update(t.lower() for t in _TOKEN.findall(testo))
    return c


def parole_note(soglia: int = SOGLIA_ESPOSIZIONE) -> set[str]:
    """vocab_db + funzionali + tutto cio' che il corpus ha ripetuto abbastanza."""
    note: set[str] = set(_FUNZIONALI)

    try:
        v = json.loads(VOCAB_DB.read_text(encoding="utf-8"))
        parole = v.get("words", v) if isinstance(v, dict) else v
        if isinstance(parole, dict):
            note |= {str(k).lower() for k in parole}
            valori = parole.values()
        else:
            valori = parole
        for w in valori:
            if isinstance(w, dict):
                for campo in ("german", "plural"):
                    if val := (w.get(campo) or "").strip():
                        note |= {t.lower() for t in _TOKEN.findall(val)}
    except Exception:
        pass

    # L'esposizione ripetuta vale quanto il DB: e' cio' che aggira la morfologia.
    note |= {p for p, n in _frequenze_corpus().items() if n >= soglia}

    note |= {_radice(p) for p in list(note)}
    return note


def _sconosciute(frase: str, note: set[str]) -> list[str]:
    fuori = []
    for t in _TOKEN.findall(frase):
        tl = t.lower()
        if tl in note or _radice(tl) in note or len(tl) <= 2:
            continue
        fuori.append(t)
    return fuori


def estrai(
    *,
    min_parole: int = 5,
    max_parole: int = 22,
    limite: int = 40,
) -> list[FraseIPiuUno]:
    """Le frasi i+1 dai transcript, ordinate per utilita'.

    L'ordinamento e' per frequenza della parola nuova nel corpus: imparare una
    parola che ricorre 12 volte nelle lezioni rende piu' che una che compare
    una volta sola.
    """
    note = parole_note()
    if not TRANSCRIPTS.is_dir():
        return []

    candidate: list[tuple[str, str, str]] = []     # (frase, nuova, lezione)
    contatore: Counter[str] = Counter()

    for f in sorted(TRANSCRIPTS.glob("lezione_*.txt")):
        testo = f.read_text(encoding="utf-8", errors="replace")
        lezione = f.stem.replace("lezione_", "")
        for frase in _FRASE.split(testo):
            frase = " ".join(frase.split())
            n = len(_TOKEN.findall(frase))
            if not (min_parole <= n <= max_parole):
                continue
            if not e_tedesca(frase):        # i transcript sono bilingui
                continue
            fuori = _sconosciute(frase, note)
            if len(fuori) != 1:
                continue
            nuova = fuori[0]
            contatore[nuova.lower()] += 1
            candidate.append((frase, nuova, lezione))

    # Una parola nuova per volta: la prima frase in cui compare, non tutte.
    vista: set[str] = set()
    out: list[FraseIPiuUno] = []
    for frase, nuova, lezione in candidate:
        k = nuova.lower()
        if k in vista:
            continue
        vista.add(k)
        out.append(FraseIPiuUno(frase, nuova, contatore[k], lezione))

    out.sort(key=lambda f: -f.frequenza)
    return out[:limite]


def statistiche() -> dict:
    """Copertura del corpus. Utile per capire se il livello dei transcript e'
    ancora appropriato: se le frasi i+0 dominano, i materiali sono troppo
    facili e non stanno piu' insegnando niente."""
    note = parole_note()
    if not TRANSCRIPTS.is_dir():
        return {}

    distribuzione: Counter[int] = Counter()
    totali = 0
    for f in TRANSCRIPTS.glob("lezione_*.txt"):
        for frase in _FRASE.split(f.read_text(encoding="utf-8", errors="replace")):
            if len(_TOKEN.findall(frase)) < 5 or not e_tedesca(frase):
                continue
            totali += 1
            distribuzione[min(len(_sconosciute(frase, note)), 4)] += 1

    return {
        "frasi_analizzate": totali,
        "parole_note": len(note),
        "i_piu_0": distribuzione[0],
        "i_piu_1": distribuzione[1],
        "i_piu_2": distribuzione[2],
        "i_piu_3_o_oltre": distribuzione[3] + distribuzione[4],
        "comprensibilita": round(
            100 * (distribuzione[0] + distribuzione[1]) / totali, 1
        ) if totali else 0.0,
    }
