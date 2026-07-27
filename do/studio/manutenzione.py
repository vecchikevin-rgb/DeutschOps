"""Audit e riparazione del mazzo Anki esistente.

PERCHE' SERVE
Le carte sono state prodotte da tre generatori diversi in tre momenti diversi
(anki_feeder, bulk_import, bulk_import_book) e il formato e' derivato. L'audit
del 2026-07-26 su 3535 note: 1030 sane, 1665 senza frase d'esempio, 267 con
colore incoerente col genere, 238 sostantivi senza plurale, 13 senza articolo.

NOTA SU UNA DIAGNOSI SBAGLIATA, TENUTA QUI PERCHE' NON SI RIPETA
Il primo giro riportava "3535 carte senza tag". Era falso: leggeva `tags` da
`cardsInfo`, che restituisce sempre None. La fonte giusta e' `notesInfo`. Il
mazzo e' in realta' ben taggato per tema (A1, Einkaufen, Arbeit_und_Beruf), e
quei tag sono piu' utili di qualunque origine::/livello:: derivato — per questo
la riparazione NON aggiunge piu' tag propri.

COSA RIPARA, E DA DOVE
Solo con fonti verificabili, mai inventando:
- colore mancante        -> derivato dall'articolo o dalla categoria (deterministico)
- plurale mancante       -> da vocab_db, se la parola c'e'
- esempio mancante       -> da vocab_db, se la parola c'e'
- fronte non formattato  -> ri-renderizzato con gli stessi dati

COSA NON RIPARA
Articolo e plurale che non stanno in vocab_db. Qui vale la regola del piano
§2.1: in Anki un dato sbagliato non finisce in un report, finisce in memoria a
lungo termine. Un genere inventato da un modello viene ripassato per mesi e
imparato bene. Quelle carte vengono TAGGATE `da-verificare` e finiscono in una
lista da portare a Stefanie.

IL CONTROLLO CHE PUO' PESCARE ERRORI GIA' MEMORIZZATI
Il tedesco ha suffissi che determinano il genere in modo quasi assoluto:
-ung/-heit/-keit/-schaft/-ion/-tät sono femminili, -chen/-lein neutri,
-ling/-ismus maschili. Una carta che dice "der Wohnung" e' sbagliata, e se sta
in Anki da mesi e' un errore che Kevin ha gia' consolidato. Il controllo li
elenca invece di correggerli in automatico: la regola ha eccezioni, e su un
dato del genere decide una persona.
"""

from __future__ import annotations

import html
import json
import re
from collections import Counter
from dataclasses import dataclass, field

from ..base.paths import VOCAB_DB
from .carte import (COLORE_DEFAULT, COLORE_VERBO, COLORI_GENERE, anki,
                    anki_raggiungibile)
from .singolari import senza_plurale as _singularetantum

# --------------------------------------------------------------- genere da suffisso
# La prima versione di questa tabella ha prodotto 11 segnalazioni su 3535 carte,
# TUTTE false. Due cause, entrambe istruttive:
#
#   1. Ordinamento. "Ingenieur" incrociava "-ur" (femminile) prima di "-eur"
#      (maschile), perche' la lista non era ordinata per lunghezza. Ora
#      l'ordinamento e' imposto dal codice, non dall'ordine in cui scrivo.
#   2. Suffisso vs radice. "-ung" e' femminile quando e' un suffisso deverbale
#      (die Wohnung <- wohnen), non quando fa parte della radice: der Sprung,
#      der Ursprung. Stessa cosa per "-chen" in "der Knochen" e "-ei" in
#      "das Ei". Il controllo non sa distinguere i due casi.
#
# Conclusione: tengo solo i suffissi ad altissima affidabilita', con una lista
# di eccezioni cresciuta su cio' che l'audit ha effettivamente sbagliato, e
# richiedo una radice lunga. Meglio pochi controlli veri che tanti rumorosi:
# un audit che grida al lupo smette di essere letto.
_SUFFISSI_GREZZI: list[tuple[str, str]] = [
    ("ung", "die"), ("heit", "die"), ("keit", "die"), ("schaft", "die"),
    ("tion", "die"), ("sion", "die"), ("tät", "die"), ("ung", "die"),
    ("lein", "das"), ("ismus", "der"),
]
# Piu' lunghi per primi, sempre, indipendentemente da come li ho scritti sopra.
SUFFISSI_GENERE = sorted(set(_SUFFISSI_GREZZI), key=lambda x: -len(x[0]))

# Radice minima oltre il suffisso: sotto questa soglia il "suffisso" e' quasi
# sempre parte della parola (Ei, Ding, Tier).
MIN_RADICE = 4

# Eccezioni reali, quasi tutte emerse dal primo giro di audit sul mazzo vero.
ECCEZIONI_GENERE = {
    # -ung che non e' suffisso deverbale
    "der sprung", "der ursprung", "der schwung", "der dung", "der schwung",
    "der absprung", "der einsprung", "der aufschwung",
    # prestiti e casi noti
    "das restaurant", "der ingenieur", "der wirtschaftsingenieur",
    "das controlling", "der knochen", "das huhnerei", "das hühnerei",
    "die badesachen", "das mädchen", "der christ", "das abitur", "die firma",
    "der tourist", "das genie", "der irrtum", "der reichtum", "das prozent",
    "der patient", "der student", "der präsident", "der moment",
    "der elefant", "der diamant",
}


# --------------------------------------------------------------- parsing
_TAG_HTML = re.compile(r"<[^>]+>")
_COLORE = re.compile(r'color:\s*(#[0-9a-fA-F]{6})')
_PLURALE = re.compile(r"Pl:\s*([^<]+)")
_LIVELLO = re.compile(r"\[([ABC][12])\]")
_ARTICOLO = re.compile(r"^\s*(der|die|das)\s+(\S.*)$", re.IGNORECASE)


def _testo(h: str) -> str:
    return html.unescape(_TAG_HTML.sub(" ", h or "")).strip()


@dataclass
class Scheda:
    """Una carta, riportata a dati strutturati dal suo HTML."""

    note_id: int
    deck: str
    fronte_html: str
    retro_html: str

    articolo: str = ""
    parola: str = ""
    plurale: str = ""
    livello: str = ""
    colore: str = ""
    esempio: str = ""
    tags: list[str] = field(default_factory=list)

    difetti: list[str] = field(default_factory=list)


def _leggi(c: dict) -> Scheda:
    f = c["fields"].get("Fronte", {}).get("value", "")
    r = c["fields"].get("Retro", {}).get("value", "")
    s = Scheda(note_id=c["note"], deck=c.get("deckName", ""),
               fronte_html=f, retro_html=r, tags=list(c.get("tags") or []))

    if m := _COLORE.search(f):
        s.colore = m.group(1).lower()
    if m := _PLURALE.search(f):
        s.plurale = m.group(1).strip()
    if m := _LIVELLO.search(f):
        s.livello = m.group(1)

    # La prima riga del fronte, senza il blocco "Pl:" e senza il livello.
    testa = _testo(f.split("<br>")[0])
    testa = _LIVELLO.sub("", testa).strip()
    if m := _ARTICOLO.match(testa):
        s.articolo, s.parola = m.group(1).lower(), m.group(2).strip()
    else:
        s.parola = testa

    # Un esempio e' una frase tedesca in corsivo nel retro.
    if corsivi := re.findall(r"<i>(.*?)</i>", r, re.S):
        for ci in corsivi:
            t = _testo(ci)
            if len(t.split()) >= 3:
                s.esempio = t
                break
    return s


# --------------------------------------------------------------- vocab_db
def _indice_vocab() -> dict[str, dict]:
    """Parola in minuscolo -> voce di vocab_db. E' la fonte verificabile."""
    try:
        v = json.loads(VOCAB_DB.read_text(encoding="utf-8"))
    except Exception:
        return {}
    parole = v.get("words", v) if isinstance(v, dict) else v
    voci = parole.values() if isinstance(parole, dict) else parole

    idx: dict[str, dict] = {}
    for w in voci:
        if not isinstance(w, dict):
            continue
        g = (w.get("german") or "").strip()
        if not g:
            continue
        art = (w.get("article") or "").strip()
        nudo = g[len(art) + 1:].strip() if art and g.lower().startswith(art.lower() + " ") else g
        idx[nudo.lower()] = w
    return idx


def _colore_atteso(s: Scheda, voce: dict | None) -> str:
    cat = ((voce or {}).get("category") or "").lower()
    if "verb" in cat:
        return COLORE_VERBO
    if s.articolo in COLORI_GENERE:
        return COLORI_GENERE[s.articolo]
    return COLORE_DEFAULT


def genere_sospetto(articolo: str, parola: str) -> str | None:
    """L'articolo atteso dal suffisso, se contraddice quello sulla carta.

    Deliberatamente conservativo: preferisce non segnalare che segnalare a
    vuoto. Un genere davvero sbagliato in Anki e' un errore che Kevin sta
    consolidando, quindi vale la pena cercarlo — ma solo con controlli che
    reggono, altrimenti l'audit diventa rumore.
    """
    if not articolo or not parola:
        return None
    # Solo parole singole: se il fronte contiene una frase, il parsing non ha
    # isolato un sostantivo e ogni conclusione sarebbe campata in aria.
    if len(parola.split()) != 1:
        return None
    if f"{articolo} {parola}".lower() in ECCEZIONI_GENERE:
        return None

    p = parola.lower()
    for suf, atteso in SUFFISSI_GENERE:
        if p.endswith(suf) and len(p) - len(suf) >= MIN_RADICE:
            return atteso if atteso != articolo else None
    return None


# --------------------------------------------------------------- audit
def analizza(query: str = "deck:Deutsch") -> tuple[list[Scheda], dict]:
    """Legge tutte le carte e ne elenca i difetti. Non modifica niente."""
    if not anki_raggiungibile():
        raise RuntimeError("Anki non raggiungibile: apri Anki e riprova.")

    idx = _indice_vocab()
    ids = anki("findCards", query=query)

    schede: list[Scheda] = []
    for i in range(0, len(ids), 500):
        for c in anki("cardsInfo", cards=ids[i:i + 500]):
            schede.append(_leggi(c))

    # Una nota puo' avere piu' carte: si ripara la nota, non la carta.
    per_nota: dict[int, Scheda] = {}
    for s in schede:
        per_nota.setdefault(s.note_id, s)
    schede = list(per_nota.values())

    # I TAG VANNO LETTI DA notesInfo, NON DA cardsInfo.
    # cardsInfo restituisce tags=None anche quando la nota e' taggata. Il primo
    # giro di audit ci e' cascato e ha diagnosticato "3535 carte senza tag" su
    # un mazzo in realta' ben taggato per tema (A1, Einkaufen, Arbeit_und_Beruf).
    # Diagnosi falsa, prodotta da una query sbagliata e non da un difetto reale.
    per_id = {s.note_id: s for s in schede}
    note_ids = list(per_id)
    for i in range(0, len(note_ids), 500):
        for n in anki("notesInfo", notes=note_ids[i:i + 500]):
            if sc := per_id.get(n.get("noteId")):
                sc.tags = list(n.get("tags") or [])

    for s in schede:
        voce = idx.get(s.parola.lower())
        atteso = _colore_atteso(s, voce)
        cat = ((voce or {}).get("category") or "").lower()

        # Una carta con piu' parole sul fronte e' una frase o un'espressione
        # ("nach Hause", "Guten Morgen!"). Chiederle un plurale o una frase
        # d'esempio non ha senso: la carta E' gia' l'esempio. Il primo giro di
        # audit segnalava 1756 carte cosi', rendendo la lista inutilizzabile.
        parola_singola = len(s.parola.split()) == 1
        e_espressione = any(k in cat for k in ("expression", "phrase", "redemittel"))

        if not s.colore:
            s.difetti.append("senza-colore")
        elif s.colore != atteso.lower():
            s.difetti.append("colore-incoerente")
        if parola_singola and not e_espressione and not s.esempio:
            s.difetti.append("senza-esempio")

        pare_sostantivo = parola_singola and (bool(s.articolo) or "noun" in cat)
        if pare_sostantivo:
            if not s.articolo:
                s.difetti.append("senza-articolo")
            # Un sostantivo senza plurale non e' incompleto se il plurale non
            # esiste: Milch, Zucker, November, Süden, Ruhe. Vedi singolari.py —
            # l'audit ne segnalava 37 come "da chiedere a Stefanie".
            if not s.plurale and not _singularetantum(s.parola):
                s.difetti.append("senza-plurale")

        if genere_sospetto(s.articolo, s.parola):
            s.difetti.append("genere-sospetto")
        if voce is None:
            s.difetti.append("non-in-vocab-db")

    conteggio = Counter(d for s in schede for d in s.difetti)
    riepilogo = {
        "note": len(schede),
        "sane": sum(1 for s in schede if not s.difetti),
        "difetti": conteggio.most_common(),
        "per_deck": Counter(s.deck for s in schede if s.difetti).most_common(),
        "generi_sospetti": [
            (s.deck, f"{s.articolo} {s.parola}", genere_sospetto(s.articolo, s.parola))
            for s in schede if "genere-sospetto" in s.difetti
        ],
    }
    return schede, riepilogo


# --------------------------------------------------------------- riparazione
def _ricostruisci_fronte(s: Scheda, voce: dict | None) -> str:
    colore = _colore_atteso(s, voce)
    testo = f"{s.articolo} {s.parola}".strip() if s.articolo else s.parola
    out = (f'<span style="color:{colore};font-weight:bold;font-size:1.15em">'
           f'{html.escape(testo)}</span>')
    if s.plurale:
        out += (f'<br><span style="color:#90a4ae;font-size:0.8em">'
                f'Pl: {html.escape(s.plurale)}</span>')
    if s.livello:
        out += (f'&nbsp;<span style="color:#b0bec5;font-size:0.75em">'
                f'[{html.escape(s.livello)}]</span>')
    return out


def ripara(
    schede: list[Scheda],
    *,
    prova: bool = True,
) -> dict:
    """Applica le riparazioni possibili da fonti verificabili.

    `prova=True` (default) non tocca Anki: dice solo cosa cambierebbe.
    Articolo e plurale assenti da vocab_db NON vengono inventati.
    """
    idx = _indice_vocab()

    # `da-verificare` ha senso solo sulle carte che Kevin sta davvero studiando.
    # Marcarne 1633 — quasi tutte mai viste, dal backlog del libro — produce
    # un'etichetta su cui nessuno agisce. Una carta mai studiata non va
    # verificata: va studiata, oppure sospesa.
    in_rotazione: set[int] = set()
    try:
        cid = anki("findCards", query="deck:Deutsch -is:new")
        for i in range(0, len(cid), 500):
            in_rotazione.update(c["note"] for c in anki("cardsInfo", cards=cid[i:i + 500]))
    except Exception:
        pass

    modifiche: list[dict] = []
    tag_da_aggiungere: list[tuple[int, list[str]]] = []
    esito = Counter()
    da_chiedere: list[str] = []

    for s in schede:
        if not s.difetti:
            continue
        voce = idx.get(s.parola.lower())
        cambiato = False

        # --- completamento da vocab_db (fonte verificabile) ---
        if voce:
            if not s.plurale and (p := (voce.get("plural") or "").strip()):
                s.plurale, cambiato = p, True
                esito["plurale-completato"] += 1
            if not s.articolo and (a := (voce.get("article") or "").strip()):
                s.articolo, cambiato = a.lower(), True
                esito["articolo-completato"] += 1
            if not s.livello and (l := (voce.get("level") or "").strip()):
                s.livello, cambiato = l, True
                esito["livello-completato"] += 1

        # --- colore: deterministico, sempre riparabile ---
        atteso = _colore_atteso(s, voce)
        if s.colore != atteso.lower():
            cambiato = True
            esito["colore-corretto"] += 1

        # --- esempio: solo se vocab_db ne ha uno ---
        nuovo_retro = s.retro_html
        if not s.esempio and voce and (ex := (voce.get("example_de") or "").strip()):
            nuovo_retro = s.retro_html + f"<br><br><i>{html.escape(ex)}</i>"
            if exi := (voce.get("example_it") or "").strip():
                nuovo_retro += f"<br><small style='color:#666'>{html.escape(exi)}</small>"
            cambiato = True
            esito["esempio-aggiunto"] += 1

        # --- tag: NON se ne aggiungono di nuovi ---
        # Il mazzo e' gia' taggato per tema (A1, Einkaufen, Arbeit_und_Beruf)
        # dagli import originali, e quei tag sono piu' utili di un origine::
        # o livello:: derivato. L'unico tag che aggiunge informazione e'
        # da-verificare, gestito sotto.
        nuovi_tag: list[str] = []

        # --- cio' che resta scoperto: si marca, non si inventa ---
        # Solo i difetti realmente rilevati in analizza(): se una carta e' una
        # frase, "senza-plurale" non e' fra i suoi difetti e non va marcata.
        residui = []
        if "senza-articolo" in s.difetti and not s.articolo:
            residui.append("articolo")
        if "senza-plurale" in s.difetti and not s.plurale:
            residui.append("plurale")
        if "senza-esempio" in s.difetti and nuovo_retro == s.retro_html:
            residui.append("esempio")
        if residui and s.note_id in in_rotazione:
            nuovi_tag = ["da-verificare"]
            da_chiedere.append(f"{s.parola} — manca: {', '.join(residui)}")
            esito["marcati-da-verificare"] += 1
        elif residui:
            esito["scoperti-ma-mai-studiati"] += 1

        if cambiato:
            modifiche.append({
                "id": s.note_id,
                "fields": {"Fronte": _ricostruisci_fronte(s, voce),
                           "Retro": nuovo_retro},
            })
        if nuovi_tag:
            tag_da_aggiungere.append((s.note_id, sorted(set(nuovi_tag))))

    riepilogo = {
        "note_da_modificare": len(modifiche),
        "note_da_taggare": len(tag_da_aggiungere),
        "dettaglio": esito.most_common(),
        "da_chiedere_a_stefanie": da_chiedere,
        "prova": prova,
    }
    if prova:
        return riepilogo

    for m in modifiche:
        anki("updateNoteFields", note=m)

    # addTags accetta una lista di note: raggruppo per insieme di tag identico
    # cosi' 3535 chiamate diventano poche decine.
    per_tag: dict[str, list[int]] = {}
    for nid, tags in tag_da_aggiungere:
        per_tag.setdefault(" ".join(tags), []).append(nid)
    for tags, note_ids in per_tag.items():
        for i in range(0, len(note_ids), 500):
            anki("addTags", notes=note_ids[i:i + 500], tags=tags)

    riepilogo["applicate"] = len(modifiche)
    riepilogo["gruppi_tag"] = len(per_tag)
    return riepilogo


# ------------------------------------------------------- esempi dal corpus
def esempi_dal_corpus(schede: list[Scheda], *, prova: bool = True) -> dict:
    """Aggiunge la frase d'esempio mancante pescandola dai transcript.

    PERCHE' QUESTO E NON "CHIEDERE A STEFANIE"
    L'audit produceva una lista di 367 carte "manca: esempio", dominata da
    parole come auch, gut, weil, rauf. Chiedere a un'insegnante 367 frasi
    d'esempio non e' una richiesta che si fa. Ma le frasi esistono gia': sono
    nei transcript delle sue stesse lezioni, dette da lei.

    Quindi: nessuna invenzione, nessuna chiamata di rete, nessun costo. Si
    cerca nel corpus una frase che contenga la parola, tedesca (i transcript
    sono bilingui) e di lunghezza ragionevole, e la si mette sul retro.

    La frase piu' CORTA fra le candidate: su un parlato, una frase lunga porta
    dentro contesto che sulla carta non serve e distrae dal punto.
    """
    import re as _re

    from ..base.paths import TRANSCRIPTS
    from .frasi import _FRASE, _TOKEN, e_tedesca

    if not TRANSCRIPTS.is_dir():
        return {"nessun_transcript": True}

    frasi_corpus: list[str] = []
    for f in sorted(TRANSCRIPTS.glob("lezione_*.txt")):
        for fr in _FRASE.split(f.read_text(encoding="utf-8", errors="replace")):
            fr = " ".join(fr.split())
            n = len(_TOKEN.findall(fr))
            # Filtro di qualita': il parlato produce frammenti. Una frase da
            # mettere su una carta deve iniziare in maiuscolo, chiudersi con
            # una punteggiatura vera e non troncarsi in sospensione — senza
            # questo entrano cose come "Ok, das ist weil...".
            if not (4 <= n <= 16 and e_tedesca(fr)):
                continue
            if "..." in fr or "…" in fr:
                continue
            if not fr[:1].isupper() or fr[-1] not in ".!?":
                continue
            frasi_corpus.append(fr)

    # Indice parola -> frase piu' corta che la contiene.
    migliore: dict[str, str] = {}
    for fr in frasi_corpus:
        for t in set(_TOKEN.findall(fr)):
            k = t.lower()
            if k not in migliore or len(fr) < len(migliore[k]):
                migliore[k] = fr

    modifiche, aggiunti, non_trovati = [], 0, []
    for s in schede:
        if "senza-esempio" not in s.difetti:
            continue
        frase = migliore.get(s.parola.lower())
        if not frase:
            non_trovati.append(s.parola)
            continue
        retro = s.retro_html + (
            f'<br><br><i>{html.escape(frase)}</i>'
            f'<br><small style="color:#90a4ae">dalla tua lezione</small>'
        )
        modifiche.append({"id": s.note_id, "fields": {"Retro": retro}})
        aggiunti += 1

    esito = {
        "frasi_nel_corpus": len(frasi_corpus),
        "parole_coperte": len(migliore),
        "esempi_aggiunti": aggiunti,
        "senza_riscontro": len(non_trovati),
        "prova": prova,
    }
    if prova:
        esito["campione"] = [
            (s.parola, migliore[s.parola.lower()])
            for s in schede[:400]
            if "senza-esempio" in s.difetti and s.parola.lower() in migliore
        ][:6]
        return esito

    for m in modifiche:
        anki("updateNoteFields", note=m)
    return esito
