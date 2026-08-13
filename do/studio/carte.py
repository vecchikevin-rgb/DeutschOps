"""Generazione carte Anki — riconoscimento, produzione, cloze.

IL PROBLEMA CHE RISOLVE
`anki_feeder.py:114-161` della v1 costruiva UNA carta per vocabolo: fronte
"die Rechnung", retro "fattura". Una direzione sola, DE->IT. E' riconoscimento:
vedi la parola, la riconosci, ti senti bravo. Non e' richiamo attivo — partire
dal significato e produrre la forma tedesca corretta, con l'articolo giusto,
nella frase giusta. La seconda e' piu' difficile, e' quella che serve per
parlare, ed e' quella che l'esame misura. Il sistema non l'ha mai allenata.

TRE DIREZIONI, TRE SOTTODECK
- Riconoscimento  die Rechnung -> fattura          (quello che c'era)
- Produzione      fattura (f.) -> die Rechnung, -en  NUOVO
- Cloze           "Ich habe die ___ bezahlt."        NUOVO, frase reale

Sottodeck e non solo tag: cosi' si puo' regolare il carico di ogni direzione
separatamente nelle opzioni di Anki, e sospendere una direzione senza toccare
le altre.

LA FRASE DEL CLOZE NON E' INVENTATA
Preferenza in due passi (dal 2026-08-13). Prima il libro (`do/sapere/libro.py`,
OCR del Kursbuch): frasi pubblicate, gia' pensate per essere comprensibili da
sole. Se la parola non c'e' nel libro, `example_de` — ma solo se
`_frase_utilizzabile()` dice che basta a se stessa. Ne' l'uno ne' l'altro ->
niente carta cloze. Meglio due carte buone che tre di cui una storta.

PERCHE' IL FILTRO NON E' frasi.completabile()
Provato il 2026-08-13 su una lezione vera: `completabile()` — tarato sul
PARLATO SPONTANEO dei transcript, soglia 8 token, controlli su esitazioni e
balbettii — scartava 44 `example_de` su 48, tutte frasi corrette e complete
tipo "Ich bleibe zu Hause, weil ich krank bin." Il motivo era il conteggio
token: `example_de` e' gia' curato (do/lezione/estrazione.py lo corregge o
riscrive apposta), non e' un frammento di parlato da giudicare con lo stesso
righello. `_frase_utilizzabile()` sotto e' il controllo giusto per QUESTA
popolazione — leggero, senza soglia sulla lunghezza. `completabile()` resta
intatto in frasi.py: serve intatta la' per il parlato vero (la sezione i+1
dell'app), e Kevin si era gia' lamentato una volta di quella proprio perche'
troppo permissiva.

REGOLA ANTI-ALLUCINAZIONE (piano §2.1)
Qui un dato sbagliato non finisce in un report: finisce in memoria a lungo
termine con ripetizione spaziata. Un `der` al posto di `die` te lo ripassi per
mesi e lo impari bene. I sostantivi senza articolo o senza plurale — cioe'
quelli su cui l'estrazione era incerta — vengono taggati `da-verificare` e
finiscono in una lista da portare a Stefanie, invece di entrare in silenzio.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

import requests

from ..base.config import ANKI_DECK, ANKI_URL
from ..sapere import libro

# Sottodeck per direzione.
DECK_RICONOSCIMENTO = f"{ANKI_DECK}::Riconoscimento"
DECK_PRODUZIONE = f"{ANKI_DECK}::Produzione"
DECK_CLOZE = f"{ANKI_DECK}::Cloze"

# Colori per genere, stile verbformen.com. Restano: sono un aiuto mnemonico
# reale, non decorazione.
COLORI_GENERE = {"der": "#0066cc", "die": "#cc0000", "das": "#007700"}
COLORE_VERBO = "#cc6600"
COLORE_DEFAULT = "#555555"

ABBREV_GENERE = {"der": "m.", "die": "f.", "das": "n."}


# --------------------------------------------------------------------- AnkiConnect
def anki(azione: str, *, timeout: float = 30, **params):
    """Una chiamata ad AnkiConnect.

    Il timeout e' generoso per difetto — caricare un mazzo intero durante la
    pipeline puo' richiedere tempo — ma va stretto quando la risposta serve a
    disegnare un riquadro di stato: li' aspettare mezzo minuto un programma che
    non risponde e' peggio che dire subito «Anki non c'e'».
    """
    r = requests.post(
        ANKI_URL, json={"action": azione, "version": 6, "params": params},
        timeout=timeout,
    )
    r.raise_for_status()
    res = r.json()
    if res.get("error"):
        raise RuntimeError(f"AnkiConnect: {res['error']}")
    return res["result"]


def anki_raggiungibile() -> bool:
    try:
        anki("version")
        return True
    except Exception:
        return False


# --------------------------------------------------------------------- modello dati
@dataclass
class Carte:
    """Le carte generate da un vocabolo, piu' il motivo di cio' che manca."""

    note: list[dict] = field(default_factory=list)
    saltate: list[str] = field(default_factory=list)


def _colore(v: dict) -> str:
    if "verb" in (v.get("category") or ""):
        return COLORE_VERBO
    return COLORI_GENERE.get((v.get("article") or "").lower().strip(), COLORE_DEFAULT)


def _pulisci(parola: str, articolo: str) -> str:
    """Toglie l'articolo duplicato dentro il campo german ('die Rechnung')."""
    p = (parola or "").strip()
    a = (articolo or "").strip()
    if a and p.lower().startswith(a.lower() + " "):
        return p[len(a) + 1:].strip()
    return p


def chiave(v: dict) -> str:
    """Chiave di deduplica stabile.

    La v1 confrontava la stringa HTML del primo campo, con dentro gli
    `<span style=...>`: bastava cambiare un colore e il duplicato non veniva
    piu' riconosciuto. Qui la chiave e' il testo nudo.
    """
    return f"{(v.get('article') or '').strip().lower()}|{_pulisci(v.get('german',''), v.get('article','')).lower()}"


def da_verificare(v: dict) -> str | None:
    """Motivo per cui questo vocabolo NON e' affidabile, o None se lo e'.

    Non blocca la carta: la marca. Bloccare significherebbe perdere materiale
    utile; marcare significa poterlo ricontrollare con Stefanie.
    """
    cat = (v.get("category") or "").lower()
    if "noun" in cat or "sostantivo" in cat:
        if not (v.get("article") or "").strip():
            return "sostantivo senza articolo"
        if (v.get("article") or "").strip().lower() not in COLORI_GENERE:
            return f"articolo anomalo: {v.get('article')!r}"
        if not (v.get("plural") or "").strip():
            return "sostantivo senza plurale"
    return None


# --------------------------------------------------------------------- rendering
def _fronte_riconoscimento(v: dict) -> str:
    parola = _pulisci(v.get("german", ""), v.get("article", ""))
    art = (v.get("article") or "").strip()
    testo = f"{art} {parola}".strip()
    out = (f'<span style="color:{_colore(v)};font-weight:bold;font-size:1.15em">'
           f'{html.escape(testo)}</span>')
    if plur := (v.get("plural") or "").strip():
        out += f'<br><span style="color:#90a4ae;font-size:0.8em">Pl: {html.escape(plur)}</span>'
    if liv := (v.get("level") or "").strip():
        out += f'&nbsp;<span style="color:#b0bec5;font-size:0.75em">[{html.escape(liv)}]</span>'
    return out


def _retro_riconoscimento(v: dict) -> str:
    out = f"<b>{html.escape(v.get('italian') or v.get('english') or '')}</b>"
    if (v.get("italian") or "").strip() and (v.get("english") or "").strip():
        out += f" &nbsp;·&nbsp; <i>{html.escape(v['english'])}</i>"
    if ex := (v.get("example_de") or "").strip():
        out += f"<br><br><i>{html.escape(ex)}</i>"
    if exi := (v.get("example_it") or "").strip():
        out += f"<br><small style='color:#666'>{html.escape(exi)}</small>"
    return out


def _fronte_produzione(v: dict) -> str:
    """Dal significato alla forma tedesca. E' la direzione che mancava.

    Mostra il genere come abbreviazione (f./m./n.) invece dell'articolo: dare
    'die' nella domanda regalerebbe la meta' della risposta, che e' proprio la
    parte che Kevin sbaglia — 27 errori di Genus in error_db.
    """
    significato = (v.get("italian") or v.get("english") or "").strip()
    gen = ABBREV_GENERE.get((v.get("article") or "").strip().lower(), "")
    out = f'<span style="font-weight:bold;font-size:1.15em">{html.escape(significato)}</span>'
    if gen:
        out += f' <span style="color:#90a4ae;font-size:0.85em">({gen})</span>'
    out += '<br><span style="color:#b0bec5;font-size:0.8em">→ in tedesco, con articolo e plurale</span>'
    return out


def _retro_produzione(v: dict) -> str:
    parola = _pulisci(v.get("german", ""), v.get("article", ""))
    art = (v.get("article") or "").strip()
    testo = f"{art} {parola}".strip()
    out = (f'<span style="color:{_colore(v)};font-weight:bold;font-size:1.15em">'
           f'{html.escape(testo)}</span>')
    if plur := (v.get("plural") or "").strip():
        out += f', <span style="color:#546e7a">{html.escape(plur)}</span>'
    if ex := (v.get("example_de") or "").strip():
        out += f"<br><br><i>{html.escape(ex)}</i>"
    return out


def _frase_utilizzabile(frase: str, parola: str) -> bool:
    """Se la frase basta a se stessa per una carta Cloze — controllo leggero,
    pensato per `example_de` (gia' curato), non per il parlato spontaneo.
    Vedi "PERCHE' IL FILTRO NON E' frasi.completabile()" in cima al modulo.
    """
    testo = frase.strip()
    if not testo[:1].isupper() or testo[-1:] not in ".!?":
        return False
    if ":" in testo:                        # etichette di chi parla
        return False
    token = re.findall(r"[a-zA-ZäöüÄÖÜß]+", testo)
    if len(token) < 4:
        return False
    radice = parola.lower()[:4]
    contenuto = [t for t in token if not t.lower().startswith(radice) and len(t) > 3]
    return len(contenuto) >= 2


def _frase_cloze(v: dict, parola: str) -> tuple[str, str] | None:
    """(frase, fonte) da usare per il buco, o None se non ce n'e' una buona.

    Libro prima (frasi pubblicate, pensate per stare da sole); altrimenti la
    frase di lezione, se `_frase_utilizzabile()` la promuove. Vedi il
    docstring del modulo.
    """
    pattern = re.compile(rf"\b{re.escape(parola)}\w*", re.IGNORECASE)

    if trovata := libro.cerca(parola):
        # cerca() puo' aver trovato per radice (nomi composti: "Verkehr" dentro
        # "Schriftverkehr") — un match cosi' non isola un buco pulito con un
        # confine di parola netto. Non e' un errore da propagare: si scarta il
        # match del libro e si prova comunque example_de sotto.
        if pattern.search(trovata["testo"]):
            return trovata["testo"], f"libro · {trovata.get('fonte', '')}".strip(" ·")

    frase = (v.get("example_de") or "").strip()
    if frase and pattern.search(frase) and _frase_utilizzabile(frase, parola):
        return frase, "lezione"
    return None


def _cloze(v: dict) -> tuple[str, str] | None:
    """(fronte, retro) della carta cloze, o None se non c'e' una frase buona.

    Deterministico: se la parola non compare nella frase scelta non si
    inventa niente, si rinuncia alla carta.
    """
    parola = _pulisci(v.get("german", ""), v.get("article", ""))
    if not parola or len(parola) < 3:
        return None

    scelta = _frase_cloze(v, parola)
    if not scelta:
        return None
    frase, fonte = scelta

    pattern = re.compile(rf"\b{re.escape(parola)}\w*", re.IGNORECASE)
    if not pattern.search(frase):
        return None

    buco = pattern.sub("_____", frase, count=1)
    fronte = (f'<span style="font-size:1.05em">{html.escape(buco)}</span>'
              f'<br><span style="color:#b0bec5;font-size:0.8em">Quale parola manca?</span>')
    retro = (f'<span style="color:{_colore(v)};font-weight:bold">'
             f'{html.escape(frase)}</span>')
    # La traduzione dell'INTERA frase, non solo della parola: un buco giusto
    # ma incastrato in una frase illeggibile mesi dopo non aiuta a rileggerla.
    # Fonte libro (sempre presente per costruzione) o `example_en` (post
    # backfill — vedi do/sapere/vocaboli.py). Il significato della sola
    # parola resta come ultimo ripiego, per non lasciare il retro nudo.
    if fonte.startswith("libro"):
        # do/sapere/libro.py non traduce (deterministico, zero LLM): qui c'e'
        # solo la parola, come prima del 2026-08-13.
        if sig := (v.get("italian") or v.get("english") or "").strip():
            retro += f'<br><small style="color:#666">{html.escape(sig)}</small>'
    elif en := (v.get("example_en") or "").strip():
        retro += f'<br><small style="color:#666">{html.escape(en)}</small>'
    elif sig := (v.get("italian") or v.get("english") or "").strip():
        retro += f'<br><small style="color:#666">{html.escape(sig)}</small>'
    retro += f'<br><span style="color:#b0bec5;font-size:0.7em">{html.escape(fonte)}</span>'
    return fronte, retro


# --------------------------------------------------------------------- costruzione
def costruisci(v: dict, data_lezione: str) -> Carte:
    """Le note Anki per un vocabolo. Non tocca la rete."""
    out = Carte()
    significato = (v.get("italian") or v.get("english") or "").strip()
    parola = _pulisci(v.get("german", ""), v.get("article", ""))

    if not parola:
        out.saltate.append("(vocabolo senza campo german)")
        return out

    tag_base = ["deutschops", f"lezione::{data_lezione}",
                f"livello::{v.get('level') or 'ignoto'}",
                f"tipo::{v.get('category') or 'altro'}"]
    if motivo := da_verificare(v):
        tag_base.append("da-verificare")
        out.saltate.append(f"{parola}: {motivo} (carta creata ma marcata)")

    def nota(deck: str, fronte: str, retro: str, direzione: str) -> dict:
        return {
            "deckName": deck,
            "modelName": "Basilare",
            "fields": {"Fronte": fronte, "Retro": retro},
            "tags": tag_base + [f"direzione::{direzione}"],
            # Anki deduplica sul primo campo; scopeamo al deck cosi' le tre
            # direzioni della stessa parola non si annullano a vicenda.
            "options": {"allowDuplicate": False,
                        "duplicateScope": "deck",
                        "duplicateScopeOptions": {"deckName": deck,
                                                  "checkChildren": False}},
        }

    out.note.append(nota(DECK_RICONOSCIMENTO,
                         _fronte_riconoscimento(v), _retro_riconoscimento(v),
                         "riconoscimento"))

    if significato:
        out.note.append(nota(DECK_PRODUZIONE,
                             _fronte_produzione(v), _retro_produzione(v),
                             "produzione"))
    else:
        out.saltate.append(f"{parola}: niente carta di produzione (manca italiano e inglese)")

    if c := _cloze(v):
        out.note.append(nota(DECK_CLOZE, c[0], c[1], "cloze"))

    return out


def alimenta(vocabolario: list[dict], data_lezione: str, *, prova: bool = False) -> dict:
    """Crea le carte delle tre direzioni. `prova=True` non tocca Anki.

    Ritorna un riepilogo con anche cio' che NON e' stato creato e perche': un
    conteggio di successi da solo nasconde i buchi.
    """
    tutte: list[dict] = []
    note_saltate: list[str] = []
    for v in vocabolario:
        c = costruisci(v, data_lezione)
        tutte.extend(c.note)
        note_saltate.extend(c.saltate)

    riepilogo = {
        "proposte": len(tutte),
        "aggiunte": 0,
        "duplicate": 0,
        "errori": [],
        "note_qualita": note_saltate,
        "da_verificare": [n for n in note_saltate if "marcata" in n],
    }

    if prova:
        riepilogo["prova"] = True
        for d in (DECK_RICONOSCIMENTO, DECK_PRODUZIONE, DECK_CLOZE):
            riepilogo[d.rsplit("::", 1)[-1]] = sum(1 for n in tutte if n["deckName"] == d)
        return riepilogo

    if not anki_raggiungibile():
        raise RuntimeError(
            "AnkiConnect non risponde su " + ANKI_URL +
            ". Apri Anki: la fase resta aperta e si ritenta al prossimo run."
        )

    esistenti = set(anki("deckNames"))
    for d in (DECK_RICONOSCIMENTO, DECK_PRODUZIONE, DECK_CLOZE):
        if d not in esistenti:
            anki("createDeck", deck=d)

    # I DUPLICATI VANNO TOLTI PRIMA, NON GESTITI DOPO
    # La documentazione di AnkiConnect dice che `addNotes` ritorna null per le
    # note rifiutate senza toccare le altre. Questa versione (AnkiConnect 6,
    # misurato il 2026-07-27) fa l'opposto: al primo duplicato ABORTISCE
    # l'intero lotto e ritorna `result: null` con l'errore in cima. Su
    # 2026-07-06: 6 note gia' presenti su 74, e tutte e 74 rifiutate.
    #
    # Non e' un caso limite. Ogni lezione che ripassa vocaboli gia' visti ha
    # duplicati: la fase Anki sarebbe fallita quasi sempre. Non si e' visto
    # prima solo perche' la lezione su cui il codice era stato provato non
    # aveva sovrapposizioni.
    #
    # Due filtri, in ordine:
    #   1. dentro il lotto — due vocaboli possono generare lo stesso fronte;
    #   2. contro la collezione — `canAddNotes`, che risponde per-nota.
    visti: set[tuple[str, str]] = set()
    candidate: list[dict] = []
    for n in tutte:
        k = (n["deckName"], n["fields"]["Fronte"])
        if k in visti:
            riepilogo["duplicate"] += 1
            continue
        visti.add(k)
        candidate.append(n)

    aggiungibili = anki("canAddNotes", notes=candidate) if candidate else []
    da_inviare = [n for n, ok in zip(candidate, aggiungibili) if ok]
    riepilogo["duplicate"] += sum(1 for ok in aggiungibili if not ok)

    if not da_inviare:
        print(f"   Nessuna carta nuova: tutte e {riepilogo['proposte']} gia' nel mazzo.")
        return riepilogo

    esiti = anki("addNotes", notes=da_inviare)
    riepilogo["aggiunte"] = sum(1 for e in esiti if e is not None)
    # Se qualcosa viene comunque rifiutata dopo il filtro, e' una collisione
    # nata fra il controllo e l'invio: si conta, non si nasconde.
    riepilogo["duplicate"] += sum(1 for e in esiti if e is None)
    return riepilogo
