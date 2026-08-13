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

from ..base.paths import DATA, TRANSCRIPTS, VOCAB_DB

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


# Esitazioni e segnali conversazionali. Una frase che comincia cosi' e' un
# frammento di parlato, non un enunciato: il contesto che offre e' quasi nullo.
_RIEMPITIVI = {
    "ähm", "äh", "hmm", "mhm", "hm", "okay", "ok", "ja", "nein", "also",
    "genau", "achso", "ach", "naja", "tja", "eh", "quasi", "gut", "so",
}


def completabile(frase: str, nuova: str) -> bool:
    """Se il buco e' deducibile, o solo indovinabile.

    IL PROBLEMA, POSTO DA KEVIN
    «alcune sono deducibili solo dal contesto e non naturalmente generabili».
    Ha ragione, e la causa e' la sorgente: i transcript sono PARLATO SPONTANEO.
    "Nicht das, was in der _____ ist." non determina "Saison" per nessuno;
    "Ähm, aber ich würde das Zeit-Kontext _____." nemmeno. Un buco che non si
    puo' dedurre trasforma la scelta multipla in un tiro a caso, e il voto che
    segue non misura piu' niente — che e' peggio di non avere l'esercizio.

    I CRITERI
    Nessuno di questi giudica il significato: sono tutti verificabili sul testo.
    Un enunciato intero (maiuscola, punteggiatura), senza esitazione in apertura,
    abbastanza lungo, e con contesto su ENTRAMBI i lati del buco — una parola in
    fondo alla frase non ha niente a destra da cui dedurla.
    """
    testo = frase.strip()
    if not testo[:1].isupper() or testo[-1:] not in ".!?":
        return False

    # I due punti reggono le etichette di chi parla: "Stefanie Huber: und ich
    # habe _____, Kevin Vecchi: Mhm." non e' una frase, e' un pezzo di verbale.
    if ":" in testo:
        return False

    token = _TOKEN.findall(testo)
    if len(token) < 8:
        return False

    # Trascrizioni rotte: un token isolato di una lettera ("es gibt keine e").
    if any(len(t) == 1 for t in token):
        return False

    # Esitazioni ovunque, non solo in apertura: una sola tollerata.
    if sum(1 for t in token if t.lower() in _RIEMPITIVI) > 1:
        return False
    if token[0].lower() in _RIEMPITIVI:
        return False

    # Balbettii: "Das ist, das ist wirklich…", "wenn, wenn, wenn, wenn du…".
    # Il parlato spontaneo ripete, e una frase che ripete non porta contesto.
    if any(a.lower() == b.lower() for a, b in zip(token, token[1:])):
        return False
    if len(set(t.lower() for t in token)) < len(token) * 0.75:
        return False

    # Il contesto conta per quanto ce n'e', non per da che lato sta. La regola
    # dura riguarda la CODA: un buco in fondo non ha niente a destra da cui
    # dedurlo ("Warum habe ich dich nicht _____?"). All'inizio invece va bene,
    # se dopo c'e' abbastanza — "Der _____ überwacht die gesamte Herstellung
    # der Medikamente in der Fabrik." si deduce benissimo.
    radice = nuova.lower()[:4]
    posto = next((i for i, t in enumerate(token) if t.lower().startswith(radice)), -1)
    if posto < 1 or len(token) - posto - 1 < 3:
        return False

    # Il contesto deve portare significato, non solo grammatica.
    contenuto = [t for t in token
                 if t.lower() not in _FUNZIONALI and not t.lower().startswith(radice)]
    return len(contenuto) >= 2


def _parola_plausibile(parola: str) -> bool:
    """Se la parola merita di essere studiata come vocabolo tedesco.

    Tre scarti, tutti visti nell'output reale:

    - **rifiuti di trascrizione** — Whisper produce forme che non esistono
      ("warle") o sigle incidentali ("BDFs"). Studiarle e' peggio che inutile:
      si memorizza qualcosa di falso. La forma tedesca vuole tutto minuscolo o
      la sola iniziale maiuscola (i sostantivi), e una parola vera ricorre.
    - **parole inglesi** — "shoe", "boom", "presence" arrivano dalle spiegazioni
      di Stefanie. Si riconoscono perche' vivono nelle frasi inglesi del corpus,
      non in quelle tedesche.
    """
    p = parola.lower()
    if not (parola.islower() or (parola[:1].isupper() and parola[1:].islower())):
        return False

    de, en = _per_lingua()
    if de[p] < 2:
        return False
    return de[p] > en[p]


def buca(testo: str, parola: str) -> str:
    """La frase col buco al posto della parola. Prima occorrenza soltanto."""
    return re.sub(rf"\b{re.escape(parola)}\w*", "_____", testo,
                  count=1, flags=re.IGNORECASE)


@dataclass(frozen=True)
class FraseIPiuUno:
    testo: str
    nuova: str
    frequenza: int          # quante volte la parola nuova compare nel corpus
    lezione: str

    def con_buco(self) -> str:
        return buca(self.testo, self.nuova)


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


def _firma_corpus() -> tuple:
    """Identita' leggera del corpus: quanti file e quando e' cambiato l'ultimo.

    Serve a invalidare la cache sotto senza rileggere niente. Costa uno stat per
    file — irrilevante — e copre il caso reale: una lezione elaborata mentre il
    server dell'app e' aperto.
    """
    if not TRANSCRIPTS.is_dir():
        return ()
    file = list(TRANSCRIPTS.glob("lezione_*.txt"))
    return (len(file), max((f.stat().st_mtime for f in file), default=0.0))


# I transcript si leggono UNA volta per processo. Senza questa cache
# `contesti()` rileggeva tutti e 30 i file per ogni parola: 3 secondi per 4
# frasi, che su una sessione da 30 sarebbero stati venti secondi di attesa
# prima della prima domanda.
_CACHE: dict[str, object] = {"firma": None, "frasi": [], "frequenze": Counter()}


def _corpus() -> tuple[list[tuple[str, str]], Counter[str]]:
    """Le frasi del corpus con la loro lezione, e le frequenze delle forme."""
    firma = _firma_corpus()
    if _CACHE["firma"] == firma:
        return _CACHE["frasi"], _CACHE["frequenze"]        # type: ignore[return-value]

    frasi: list[tuple[str, str]] = []
    frequenze: Counter[str] = Counter()
    if TRANSCRIPTS.is_dir():
        for f in sorted(TRANSCRIPTS.glob("lezione_*.txt")):
            testo = f.read_text(encoding="utf-8", errors="replace")
            lezione = f.stem.replace("lezione_", "")
            frequenze.update(t.lower() for t in _TOKEN.findall(testo))
            for frase in _FRASE.split(testo):
                frase = " ".join(frase.split())
                if frase:
                    frasi.append((frase, lezione))

    _CACHE.update(firma=firma, frasi=frasi, frequenze=frequenze)
    return frasi, frequenze


def _frequenze_corpus() -> Counter[str]:
    """Quante volte ogni forma compare nei transcript. E' la storia
    dell'esposizione reale di Kevin, non un corpus di riferimento generico."""
    return _corpus()[1]


def _per_lingua() -> tuple[Counter[str], Counter[str]]:
    """Quante volte ogni forma compare in frasi tedesche, e quante in inglesi.

    I transcript sono bilingui perche' Stefanie spiega in inglese, e questo li
    rende il discriminatore di se stessi: "shoe", "boom", "presence" vivono
    nelle spiegazioni, "gewöhnt" e "Stimmung" nelle frasi tedesche. Confrontare
    i due conteggi separa le due lingue senza dizionari e senza rete.
    """
    if _CACHE.get("lingua") is not None and _CACHE["firma"] == _firma_corpus():
        return _CACHE["lingua"]                            # type: ignore[return-value]

    de: Counter[str] = Counter()
    en: Counter[str] = Counter()
    for frase, _ in _corpus()[0]:
        bersaglio = de if e_tedesca(frase) else en
        bersaglio.update(t.lower() for t in _TOKEN.findall(frase))

    _CACHE["lingua"] = (de, en)
    return de, en


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
    solo_completabili: bool = True,
) -> list[FraseIPiuUno]:
    """Le frasi i+1 dai transcript, ordinate per utilita'.

    L'ordinamento e' per frequenza della parola nuova nel corpus: imparare una
    parola che ricorre 12 volte nelle lezioni rende piu' che una che compare
    una volta sola.

    Il filtro di `completabile()` si applica PRIMA del limite: filtrare dopo
    aver gia' tagliato le prime 40 lasciava 7 frasi, non perche' il corpus sia
    povero ma perche' le piu' frequenti sono anche le piu' frammentarie.
    """
    note = parole_note()
    if not TRANSCRIPTS.is_dir():
        return []

    candidate: list[tuple[str, str, str]] = []     # (frase, nuova, lezione)
    contatore: Counter[str] = Counter()

    for frase, lezione in _corpus()[0]:
        n = len(_TOKEN.findall(frase))
        if not (min_parole <= n <= max_parole):
            continue
        if not e_tedesca(frase):            # i transcript sono bilingui
            continue
        fuori = _sconosciute(frase, note)
        if len(fuori) != 1:
            continue
        nuova = fuori[0]
        if solo_completabili and not (completabile(frase, nuova)
                                      and _parola_plausibile(nuova)):
            continue
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


def contesti(parola: str, escludi: str = "", limite: int = 3) -> list[dict]:
    """Le altre frasi del corpus in cui la parola compare.

    Serve allo scoprimento: vedere una parola nuova in tre contesti reali dice
    molto piu' di una traduzione secca, e non costa niente perche' il corpus e'
    gia' li'. E' anche l'unico modo di rispondere alla domanda "come la usava
    Stefanie?", che finora nessuna parte del sistema sapeva fare.

    `escludi` e' la frase gia' mostrata: ripeterla non aggiunge contesto.
    """
    if not parola or not TRANSCRIPTS.is_dir():
        return []

    re_parola = re.compile(rf"\b{re.escape(parola)}\w*", re.IGNORECASE)
    fuori: list[dict] = []
    viste: set[str] = {" ".join(escludi.split())}

    for frase, lezione in _corpus()[0]:
        if frase in viste:
            continue
        n = len(_TOKEN.findall(frase))
        if not (4 <= n <= 26):
            continue
        if not re_parola.search(frase) or not e_tedesca(frase):
            continue
        viste.add(frase)
        fuori.append({"testo": frase, "lezione": lezione})
        if len(fuori) >= limite:
            break
    return fuori


def _suffisso(parola: str, n: int = 3) -> str:
    p = parola.lower()
    return p[-n:] if len(p) > n else p


def _impronta(parola: str) -> int:
    """Hash stabile fra esecuzioni. `hash()` non lo e' (PYTHONHASHSEED), e qui
    serve che le stesse opzioni escano nello stesso ordine a ogni avvio."""
    n = 0
    for i, ch in enumerate(parola.lower()):
        n = (n * 131 + ord(ch) * (i + 1)) & 0xFFFFFFFF
    return n


def _pool_distrattori() -> list[str]:
    """Le parole da cui pescare le alternative sbagliate.

    NON il corpus grezzo. I transcript sono BILINGUI — Stefanie spiega in
    inglese — e Whisper ogni tanto sbaglia una parola. Pescando da li' uscivano
    distrattori come "against" (inglese) e "abitator" (che non esiste):
    scartabili senza sapere una parola di tedesco, quindi inutili.

    La whitelist e' `vocab_db`: 1069 vocaboli estratti dalle lezioni e
    validati, tedesco garantito. Il corpus resta come rinforzo, ma solo per le
    forme che compaiono in frasi riconosciute tedesche e almeno due volte —
    cosi' le sbavature di trascrizione, che sono episodi isolati, non entrano.
    """
    if _CACHE.get("pool") is not None and _CACHE["firma"] == _firma_corpus():
        return _CACHE["pool"]                              # type: ignore[return-value]

    forme: set[str] = set()
    solo_vocabolario: set[str] = set()

    # 1. vocab_db, la whitelist.
    try:
        v = json.loads(VOCAB_DB.read_text(encoding="utf-8"))
        parole = v.get("words", v) if isinstance(v, dict) else v
        valori = parole.values() if isinstance(parole, dict) else parole
        for w in valori:
            if not isinstance(w, dict):
                continue
            for campo in ("german", "plural"):
                if val := (w.get(campo) or "").strip():
                    solo_vocabolario |= {t.lower() for t in _TOKEN.findall(val)}
    except Exception:
        pass

    # 2. Il corpus, ma solo le forme viste in frasi tedesche e non una volta sola.
    conteggio: Counter[str] = Counter()
    for frase, _ in _corpus()[0]:
        if e_tedesca(frase):
            conteggio.update(t.lower() for t in _TOKEN.findall(frase))
    forme = solo_vocabolario | {p for p, n in conteggio.items() if n >= 2}

    def utile(p: str) -> bool:
        return len(p) > 3 and p not in _FUNZIONALI

    pool = (sorted(p for p in solo_vocabolario if utile(p)),
            sorted(p for p in forme if utile(p)))
    _CACHE["pool"] = pool
    return pool


def distrattori(parola: str, frase: str = "", quanti: int = 3) -> list[str]:
    """Le alternative sbagliate per la scelta multipla.

    PERCHE' DAL CORPUS E NON DA UN DIZIONARIO
    Un distrattore preso a caso e' inutile: si scarta senza sapere il tedesco,
    solo perche' stona. Questi vengono dalle stesse lezioni, quindi sono parole
    che Stefanie usa davvero, e sono scelti per SOMIGLIARE morfologicamente a
    quella giusta — stesso suffisso, che in tedesco porta la classe: -ste per i
    superlativi, -ung per i femminili, -en per gli infiniti, -lich per gli
    aggettivi. Per "teuerste" escono "schnellste", "beste", "groesste": quattro
    superlativi plausibili, e discriminarli richiede il contesto.

    Deterministico e senza rete, come tutto il resto di questo modulo.
    """
    if not parola:
        return []

    _, frequenze = _corpus()
    p = parola.lower()
    gia_nella_frase = {t.lower() for t in _TOKEN.findall(frase)}

    def ammissibile(c: str) -> bool:
        return (c != p
                and c not in gia_nella_frase
                and not c.startswith(p[:4])        # niente varianti della stessa radice
                and not p.startswith(c[:4]))

    vocabolario, allargato = _pool_distrattori()
    atteso = frequenze.get(p, 1)
    # Deterministico ma non alfabetico: senza questo il ripiego pescava sempre
    # dall'inizio dell'alfabeto, e due parole diverse finivano con gli stessi
    # tre distrattori ("adria, anders, angst").
    sale = _impronta(p)

    def scegli(gruppo: list[str]) -> list[str]:
        # `hash()` sulle stringhe e' randomizzato a ogni processo: userebbe un
        # ordine diverso a ogni riavvio del server. _impronta e' stabile.
        gruppo.sort(key=lambda c: (abs(frequenze.get(c, 0) - atteso),
                                   (_impronta(c) ^ sale) & 0xFFFF))
        return gruppo[:quanti]

    # Cerchi concentrici, dal piu' somigliante al piu' generico, e per ognuno
    # prima il vocabolario verificato e poi il pool allargato. Il suffisso e' la
    # chiave: in tedesco porta la classe (-en infiniti, -lich aggettivi, -ung
    # femminili, -te/-nt participi), quindi discriminare richiede il contesto.
    for lunghezza in (4, 3, 2):
        for pool in (vocabolario, allargato):
            gruppo = [c for c in pool
                      if ammissibile(c) and _suffisso(c, lunghezza) == _suffisso(p, lunghezza)]
            if len(gruppo) >= quanti:
                return scegli(gruppo)

    # Ripiego: nessun suffisso in comune, si va per lunghezza simile.
    for pool in (vocabolario, allargato):
        gruppo = [c for c in pool if ammissibile(c) and abs(len(c) - len(p)) <= 2]
        if len(gruppo) >= quanti:
            return scegli(gruppo)
    return []


def opzioni(parola: str, frase: str = "", quante: int = 4) -> list[str]:
    """Le `quante` alternative, con quella giusta in una posizione stabile.

    La posizione viene da un hash della parola invece che da random: ricaricando
    la pagina la risposta non salta altrove (sarebbe disorientante), ma non e'
    nemmeno sempre la prima.
    """
    scelte = distrattori(parola, frase, quanti=quante - 1)
    if len(scelte) < quante - 1:
        return []                      # meglio nessuna scelta multipla che una a due opzioni
    posto = sum(ord(c) for c in parola) % quante
    scelte.insert(posto, parola)
    return scelte


# --------------------------------------------------------------------- traduzione
# ECCEZIONE DELIBERATA AL "NIENTE RETE" DI CIMA AL MODULO
# `estrai()` e tutto sopra restano deterministici, zero chiamate, zero costo —
# non cambia niente qui. Kevin ha chiesto pero' che le frasi mostrate in app
# abbiano una traduzione inglese, e senza una il buco resta un muro invece di
# un esercizio (stessa ragione di "traduzione" in allenamento.py). Isolato in
# fondo al file e chiamato SOLO dal layer web (do/uscite/web.py), sulle poche
# frasi davvero servite in una sessione — mai su tutto il pool da 400.
FRASI_TRADUZIONI = DATA / "frasi_traduzioni.json"

SISTEMA_TRADUZIONE_FRASI = """You translate German sentences into English.

For each numbered German sentence, return a natural English translation of
the WHOLE sentence.

- Pure English. Not a single German word in the output.
- Natural, not word-for-word.
- Do not explain, do not comment. Just the sentence.

Reply with valid JSON only, no backticks:
{"traduzioni":[{"n":<the number>,"testo":"<the English sentence>"}]}"""


def _carica_traduzioni() -> dict[str, str]:
    try:
        return json.loads(FRASI_TRADUZIONI.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def traduci_lotto(frasi: list[str]) -> dict[str, str]:
    """Traduzione inglese delle frasi date, con cache persistente su disco.

    BACKEND SEMPRE ABBONAMENTO, MAI API
    Come `vocaboli.backfill_example_en()`: `backend="claude"` esplicito, non
    delegato a LLM_BACKEND/--motore. La sezione "frasi" dell'app deve restare
    a costo zero in fattura, con o senza traduzione.

    Ritorna un dict frase->traduzione per TUTTE le frasi date (dalla cache
    quando c'e', tradotte adesso quando manca). Le frasi senza traduzione
    (fallita la chiamata) semplicemente non compaiono nel dict — chi chiama
    tratta l'assenza come "nessuna traduzione", non come errore fatale: una
    sessione di studio non deve fermarsi per questo.
    """
    cache = _carica_traduzioni()
    mancanti = [f for f in dict.fromkeys(frasi) if f not in cache]
    if not mancanti:
        return {f: cache[f] for f in frasi if f in cache}

    from ..base.config import llm_config
    from ..base.llm import chiama, estrai_json

    righe = "\n".join(f"{n}. {f}" for n, f in enumerate(mancanti, 1))
    try:
        testo, _ = chiama(
            SISTEMA_TRADUZIONE_FRASI, f"SENTENCES ({len(mancanti)}):\n{righe}",
            llm_config(max_tokens=4000, effort="low", backend="claude"),
        )
        per_numero = {int(t.get("n", 0)): (t.get("testo") or "").strip()
                      for t in estrai_json(testo).get("traduzioni", [])
                      if str(t.get("n", "")).strip().isdigit()}
    except Exception:                                          # noqa: BLE001
        per_numero = {}                                        # degrada, non fallisce

    for n, f in enumerate(mancanti, 1):
        if en := per_numero.get(n, ""):
            cache[f] = en

    if per_numero:
        FRASI_TRADUZIONI.parent.mkdir(parents=True, exist_ok=True)
        FRASI_TRADUZIONI.write_text(json.dumps(cache, ensure_ascii=False, indent=2),
                                    encoding="utf-8")

    return {f: cache[f] for f in frasi if f in cache}


def statistiche() -> dict:
    """Copertura del corpus. Utile per capire se il livello dei transcript e'
    ancora appropriato: se le frasi i+0 dominano, i materiali sono troppo
    facili e non stanno piu' insegnando niente."""
    note = parole_note()
    if not TRANSCRIPTS.is_dir():
        return {}

    distribuzione: Counter[int] = Counter()
    totali = 0
    for frase, _ in _corpus()[0]:
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
