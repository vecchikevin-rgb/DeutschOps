"""Il Kursbuch come fonte di frasi vere — OCR pagina per pagina, ricerca gratis.

PERCHE' ESISTE
`carte.py` (Cloze) e `allenamento.py` (drill) usavano solo due fonti: il
transcript delle lezioni (parlato spontaneo, spesso non deducibile fuori dal
momento in cui e' stato detto — vedi `frasi.py:completabile`) o un modello che
inventa una frase dal nulla partendo dal nome di una regola. Il Kursbuch
(`Book/daf-kompakt-neu-a1-b1-kursbuch.pdf`, DaF Kompakt Neu A1-B1) e' materiale
pubblicato, pensato apposta per essere comprensibile da solo — la fonte giusta,
gia' sul disco, mai usata.

PERCHE' OCR E NON ESTRAZIONE TESTO
Verificato il 2026-08-13: `pypdf` estrae ZERO caratteri da ogni pagina del
Kursbuch e delle due appendici di trascrizione — sono scansioni, non testo
selezionabile. Le pagine PERO' incorporano un'immagine raster leggibile
(pypdf `page.images`, ~1172x1629 su un campione), ma renderizzare la pagina
INTERA con PyMuPDF (compositing vero: testo vettoriale + immagini + sfondo)
da' una resa nitida — l'estrazione naive della sola immagine incorporata
perdeva testo vettoriale sovrapposto e tornava descrizioni sbiadite/sbagliate.
Quindi: `pymupdf` per il rendering, `chiama_visione` (Claude via il tool Read,
abbonamento — vedi do/base/llm.py) per leggerla.

RESUMABLE PER COSTRUZIONE
364 pagine (307 Kursbuch + 43 book_transcriptions + 14 Transkriptionen_A1),
un batch per chiamata a `estrai()`, ogni pagina scritta su disco appena
arriva. La quota dell'abbonamento SI esaurisce su un lotto di questa taglia
(atteso, non un bug): un 429 ferma il batch pulito, il progresso resta, si
rilancia lo stesso comando piu' tardi. Vedi CLAUDE.md per il comando.

COSA NON FA (ancora)
`risolvi_tracce()` e' un primo giro deterministico e per approssimazione sui
numeri di traccia — non una seconda passata LLM. Da rivedere quando ci sara'
materiale OCR vero da guardare: il formato esatto delle appendici (Track N?
Hörtext N? numerazione per Lektion?) si vede solo allora.
"""

from __future__ import annotations

import json
import re
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path

from ..base.config import llm_config
from ..base.llm import chiama_visione, estrai_json
from ..base.paths import BOOK, LIBRO_PAGINE

# I tre PDF sorgente e la loro etichetta. L'ordine e' quello in cui si OCRano:
# prima il Kursbuch (il grosso del materiale), poi le due appendici di
# trascrizione — necessarie per risolvere gli esercizi con icona audio.
FONTI = (
    ("kursbuch", BOOK / "daf-kompakt-neu-a1-b1-kursbuch.pdf"),
    ("book_transcriptions", BOOK / "lektionen" / "book_transcriptions.pdf"),
    ("transkriptionen_a1", BOOK / "Transkriptionen_A1.pdf"),
)

SISTEMA_OCR = """You are transcribing ONE PAGE of a German course book (DaF Kompakt Neu, A1-B1) or its audio-transcript appendix, from an image. This feeds a study tool for a Goethe-exam candidate — be exhaustive and precise, this is real published material, not a summary.

Return ONLY valid JSON, no backticks:
{"tipo":"<vocabolario|grammatica|dialogo|esercizio|indice|copertina|altro>",
 "lezione":"<the Lektion number shown on the page (usually top-left, a big digit), or ''>",
 "livello":"<A1|A2|B1|''  — only if the page itself states or clearly implies it>",
 "pagina_stampata":"<the printed page number, usually bottom corner, or ''>",
 "testo":"<the full transcription of everything on the page (German + any English/Italian instructions), preserving structure with newlines and headings>",
 "frasi":["<complete, self-contained German sentences that would still make sense read in isolation months from now — full dialogue lines, full example sentences. Do NOT include vocabulary-list entries or sentence fragments.>"],
 "esercizi":[{"consegna":"<the printed instruction, in English>","stimolo":"<the German text with blanks marked as ___, exactly as printed, one blank per gap>","soluzione":"<the correct answer ONLY if an answer key is printed right on this page, else ''>"}],
 "tracce_audio":[<integer track/Hörtext numbers referenced by an audio icon on this page, e.g. a speaker symbol next to "5" means 5. Empty list if none.>],
 "note":"<anything uncertain or illegible — empty string if nothing>"}

Rules:
- If text is illegible or cut off, say so in "note" instead of inventing it.
- "esercizi": only items with a visible blank to fill (___, dots, a numbered gap). Copy printed instruction/stimulus exactly, do not solve it yourself unless the answer is printed there.
- "frasi": skip anything that only makes sense as part of a word list or grammar table.
- If the page is not real content (blank, cover, copyright, pure index), return tipo accordingly with empty testo/frasi/esercizi/tracce_audio."""


def _pagine_totali(pdf: Path) -> int:
    import pymupdf
    with pymupdf.open(pdf) as doc:
        return doc.page_count


def _rendi_pagina(pdf: Path, indice: int, cartella: Path) -> Path:
    import pymupdf
    with pymupdf.open(pdf) as doc:
        pix = doc[indice].get_pixmap(dpi=200)
        out = cartella / f"pagina_{indice:04d}.png"
        pix.save(out)
        return out


def _carica() -> dict[str, dict]:
    if not LIBRO_PAGINE.exists():
        return {}
    try:
        return json.loads(LIBRO_PAGINE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _salva(pagine: dict[str, dict]) -> None:
    LIBRO_PAGINE.parent.mkdir(parents=True, exist_ok=True)
    LIBRO_PAGINE.write_text(json.dumps(pagine, ensure_ascii=False, indent=2),
                            encoding="utf-8")


def _da_fare(pagine: dict[str, dict], *, fonte: str | None = None
            ) -> list[tuple[str, Path, int]]:
    """(fonte, path, indice) per ogni pagina non ancora OCR'ata."""
    fuori: list[tuple[str, Path, int]] = []
    for nome, pdf in FONTI:
        if fonte and nome != fonte:
            continue
        if not pdf.exists():
            continue
        for i in range(_pagine_totali(pdf)):
            if f"{nome}:{i}" not in pagine:
                fuori.append((nome, pdf, i))
    return fuori


def estrai(quanti: int = 15, *, fonte: str | None = None) -> dict:
    """OCR di un lotto di pagine non ancora fatte. Riprendibile per costruzione.

    Un 429 (quota abbonamento esaurita) ferma il lotto pulito: il progresso
    fatto finora resta scritto, si rilancia lo stesso comando piu' tardi.
    Un errore su una singola pagina (immagine corrotta, risposta non-JSON)
    non ferma le altre — si conta e si prosegue, come `allenamento.libreria()`.
    """
    pagine = _carica()
    coda = _da_fare(pagine, fonte=fonte)
    if not coda:
        return {"fatte": 0, "rimaste": 0, "falliti": 0, "fermato_da_quota": False}

    cfg = llm_config(backend="claude")
    fatte = falliti = 0
    nozionale = 0.0
    fermato_da_quota = False

    with tempfile.TemporaryDirectory(prefix="libro_ocr_") as tmp:
        cartella = Path(tmp)
        for nome, pdf, indice in coda[:quanti]:
            chiave = f"{nome}:{indice}"
            try:
                immagine = _rendi_pagina(pdf, indice, cartella)
                testo, uso = chiama_visione(
                    SISTEMA_OCR,
                    f"This is page index {indice} (0-based) of {pdf.name} — "
                    f"source group '{nome}'.",
                    immagine, cfg,
                )
                dati = estrai_json(testo)
            except RuntimeError as e:
                if "429" in str(e) or "quota" in str(e).lower():
                    print(f"   Quota abbonamento esaurita a {chiave} "
                          f"({fatte} fatte in questo lotto). Rilancia piu' tardi.")
                    fermato_da_quota = True
                    break
                print(f"   {chiave}: {str(e)[:200]}")
                falliti += 1
                continue
            except Exception as e:                              # noqa: BLE001
                print(f"   {chiave}: {type(e).__name__}: {str(e)[:200]}")
                falliti += 1
                continue

            dati["fonte"] = nome
            dati["indice"] = indice
            dati["costo_nozionale_eur"] = uso.costo_nozionale_eur
            dati["quando"] = datetime.now().isoformat(timespec="seconds")
            pagine[chiave] = dati
            nozionale += uso.costo_nozionale_eur
            fatte += 1
            _salva(pagine)          # scritto SUBITO — vedi il docstring del modulo
            print(f"   {chiave}  [{dati.get('tipo', '?')}]  "
                  f"{len(dati.get('frasi', []))} frasi, "
                  f"{len(dati.get('esercizi', []))} esercizi"
                  + (f", Lektion {dati['lezione']}" if dati.get("lezione") else ""))

    rimaste = len(_da_fare(pagine, fonte=fonte))
    return {
        "fatte": fatte, "rimaste": rimaste, "falliti": falliti,
        "fermato_da_quota": fermato_da_quota,
        "costo_nozionale_eur": round(nozionale, 4),
        "totale_pagine": sum(_pagine_totali(p) for _, p in FONTI if p.exists()),
    }


def stato() -> dict:
    """Quante pagine sono state OCR'ate, per fonte."""
    pagine = _carica()
    per_fonte = Counter(k.split(":", 1)[0] for k in pagine)
    fuori = {}
    for nome, pdf in FONTI:
        totali = _pagine_totali(pdf) if pdf.exists() else 0
        fuori[nome] = {"fatte": per_fonte.get(nome, 0), "totali": totali,
                       "presente": pdf.exists()}
    return fuori


# --------------------------------------------------------------------- export
def esporta_markdown(destinazione: Path | None = None) -> Path:
    """Le pagine OCR'ate come documento leggibile, per intero.

    Kevin, 2026-08-13: "le trascrizioni sono da salvare integralmente come
    documento di analisi del libro... torneranno utili per altro". Non e' un
    sottoprodotto della ricerca (`cerca()`/`cerca_riferimento()` leggono il
    JSON direttamente e non hanno bisogno di questo file) — e' un documento a
    se', pensato per essere letto o dato in pasto a un'analisi futura.

    Dentro `Book/`, quindi fuori da git per lo stesso motivo del resto del
    libro (copyright — vedi il commit "Add book PDFs to gitignore").
    Si rigenera per intero a ogni chiamata: e' derivato, non c'e' uno stato
    incrementale da preservare.
    """
    pagine = _carica()
    destinazione = destinazione or (BOOK / "trascrizione-completa.md")

    righe = ["# DaF Kompakt Neu A1-B1 — trascrizione OCR",
             f"\nGenerato il {datetime.now().isoformat(timespec='minutes')} "
             f"da {len(pagine)} pagine OCR'ate.\n"]

    for nome, pdf in FONTI:
        chiavi = sorted(
            (k for k in pagine if k.startswith(f"{nome}:")),
            key=lambda k: int(k.split(":", 1)[1]),
        )
        if not chiavi:
            continue
        righe.append(f"\n## {nome} ({len(chiavi)} pagine)\n")

        for k in chiavi:
            p = pagine[k]
            intestazione = f"### {k}"
            if p.get("lezione"):
                intestazione += f" — Lektion {p['lezione']}"
            if p.get("pagina_stampata"):
                intestazione += f" (p. {p['pagina_stampata']})"
            intestazione += f" [{p.get('tipo', '?')}]"
            righe.append(intestazione)

            if testo := (p.get("testo") or "").strip():
                righe.append(testo)

            if esercizi := p.get("esercizi"):
                righe.append("\n**Esercizi:**")
                for e in esercizi:
                    riga = f"- {e.get('consegna', '')}: {e.get('stimolo', '')}"
                    if e.get("soluzione"):
                        riga += f" → {e['soluzione']}"
                    righe.append(riga)

            if tracce := p.get("tracce_audio"):
                righe.append(f"\n*Riferimenti audio: traccia/e {tracce}*")

            if nota := (p.get("note") or "").strip():
                righe.append(f"\n> Nota OCR: {nota}")

            righe.append("")

    destinazione.parent.mkdir(parents=True, exist_ok=True)
    destinazione.write_text("\n".join(righe), encoding="utf-8")
    return destinazione


# --------------------------------------------------------------------- ricerca
# Stesso stile di frasi.py: deterministico, zero chiamate di rete, zero costo.
_TOKEN = re.compile(r"[a-zA-ZäöüÄÖÜß]+")


def _radice(parola: str) -> str:
    p = parola.lower()
    for s in ("en", "es", "em", "er", "e", "n", "s"):
        if len(p) > len(s) + 3 and p.endswith(s):
            return p[: -len(s)]
    return p


def cerca(parola: str, *, livello: str | None = None) -> dict | None:
    """La frase piu' corta del libro che contiene `parola`, o None.

    La piu' corta fra le candidate: meno contesto attorno da cui distrarsi,
    stesso principio di `manutenzione.esempi_dal_corpus()`. Preferisce le
    fonti "dialogo"/"esercizio" (frasi vere, complete) a "vocabolario"
    (spesso solo elenchi), ma non le esclude — meglio una frase da un elenco
    che nessuna frase.
    """
    if not parola or len(parola) < 3:
        return None
    radice = _radice(parola)
    pattern = re.compile(rf"\b{re.escape(parola)}\w*", re.IGNORECASE)

    candidate: list[tuple[int, str, dict]] = []   # (priorita, frase, riga)
    for chiave, pag in _carica().items():
        if livello and pag.get("livello") and pag["livello"] != livello:
            continue
        for frase in pag.get("frasi", []):
            token = {_radice(t) for t in _TOKEN.findall(frase)}
            if radice not in token and not pattern.search(frase):
                continue
            priorita = 0 if pag.get("tipo") in ("dialogo", "esercizio") else 1
            candidate.append((priorita, frase, pag))

    if not candidate:
        return None
    candidate.sort(key=lambda c: (c[0], len(c[1])))
    _, frase, pag = candidate[0]
    return {"testo": frase, "fonte": pag.get("fonte", "libro"),
            "lezione": pag.get("lezione", ""), "livello": pag.get("livello", "")}


def cerca_riferimento(parole_chiave: list[str], *, quante: int = 1) -> list[str]:
    """Frasi del libro che condividono piu' parole di contenuto con
    `parole_chiave` — per dare al modello un riferimento reale invece del
    vuoto quando costruisce un esercizio (vedi allenamento.py:prepara).

    Non e' un match esatto di regola grammaticale: e' somiglianza lessicale,
    grezza di proposito. Serve tono e vocabolario plausibili, non una frase
    che testi esattamente la stessa cosa.
    """
    chiavi = {_radice(p) for p in parole_chiave if len(p) > 3}
    if not chiavi:
        return []

    punteggi: list[tuple[int, str]] = []
    for pag in _carica().values():
        for frase in pag.get("frasi", []):
            token = {_radice(t) for t in _TOKEN.findall(frase)}
            comuni = len(token & chiavi)
            if comuni:
                punteggi.append((comuni, frase))

    punteggi.sort(key=lambda c: -c[0])
    viste: set[str] = set()
    fuori: list[str] = []
    for _, frase in punteggi:
        if frase in viste:
            continue
        viste.add(frase)
        fuori.append(frase)
        if len(fuori) >= quante:
            break
    return fuori


# --------------------------------------------------------------------- tracce audio
# Verificato sui dati OCR reali (2026-08-24), non per ipotesi: la numerazione
# delle tracce e' CONTINUA su tutto il libro (1, 2, 3... fino a ~199+), non
# ricomincia per Lektion. Il primo tentativo (_TRACCIA, cercava le parole
# "track"/"traccia" prima del numero) trovava zero corrispondenze: le
# trascrizioni segnano ogni traccia con il numero SOLO, su una riga a se',
# senza etichetta ("1\nChristiane Brandt: Guten Morgen...\n\n2\n...").
#
# `book_transcriptions` (43 pagine, copre "Lektionen 1-8 A1" + "9-18 A2" +
# "19-30 B1" in sequenza) e' la fonte primaria, perche' e' quella che segue
# davvero la numerazione del Kursbuch — verificato: la traccia 1 li' e' il
# dialogo di apertura della Lektion 1, esattamente cio' che kursbuch:15
# referenzia. `transkriptionen_a1` ha numeri bassi SOVRAPPOSTI (es. entrambe
# le fonti hanno una traccia "12" con testo diverso) — sembra una registrazione
# supplementare parallela (un CD di pratica A1 a parte), non una continuazione.
# Resta come riserva SOLO per i numeri assenti dalla fonte primaria.
_TESTA_TRACCIA = re.compile(r"^(\d{1,3})\s*$", re.MULTILINE)


def _tracce_da_fonte(fonte: str) -> dict[int, str]:
    """Numero di traccia -> testo del dialogo, da una fonte di trascrizione.

    Concatena TUTTE le pagine della fonte, in ordine, prima di spezzare: un
    dialogo puo' proseguire oltre un cambio pagina, e spezzare pagina per
    pagina lo troncherebbe a meta'.
    """
    pagine = _carica()
    chiavi = sorted(
        (k for k in pagine if k.startswith(f"{fonte}:")),
        key=lambda k: int(k.split(":", 1)[1]),
    )
    intero = "\n\n".join(pagine[k].get("testo", "") for k in chiavi)

    teste = list(_TESTA_TRACCIA.finditer(intero))
    fuori: dict[int, str] = {}
    for i, m in enumerate(teste):
        numero = int(m.group(1))
        fine = teste[i + 1].start() if i + 1 < len(teste) else len(intero)
        testo = intero[m.end():fine].strip()
        # La prima occorrenza vince: un numero puo' ripetersi per rumore OCR
        # (un indice, una didascalia), il vero dialogo e' quasi sempre il primo.
        if testo and numero not in fuori:
            fuori[numero] = testo
    return fuori


def indice_tracce() -> dict[int, str]:
    """Numero di traccia -> testo del dialogo, su tutte le fonti disponibili."""
    primaria = _tracce_da_fonte("book_transcriptions")
    riserva = _tracce_da_fonte("transkriptionen_a1")
    for n, testo in riserva.items():
        primaria.setdefault(n, testo)
    return primaria


def risolvi_tracce() -> dict:
    """Collega le pagine con icona audio alle trascrizioni delle appendici.

    Aggiunge le frasi del dialogo alla lista "frasi" della pagina kursbuch che
    referenzia quella traccia — cosi' `cerca()`/`cerca_riferimento()` le
    trovano senza sapere che venivano da un esercizio con audio. Le frasi
    vengono spezzate deterministicamente (stesso confine di frase di
    `frasi.py`), non prese per intero: un turno di dialogo lungo mischierebbe
    piu' battute in una sola "frase".
    """
    indice = indice_tracce()
    if not indice:
        return {"tracce_trovate": 0, "pagine_collegate": 0}

    pagine = _carica()
    confine_frase = re.compile(r"(?<=[.!?])\s+")

    collegate = 0
    for pag in pagine.values():
        if pag.get("fonte") != "kursbuch":
            continue
        nuove = []
        for n in pag.get("tracce_audio", []):
            testo = indice.get(int(n))
            if not testo:
                continue
            nuove.extend(f.strip() for f in confine_frase.split(testo)
                        if len(f.strip()) > 15)
        if nuove:
            esistenti = set(pag.get("frasi", []))
            pag.setdefault("frasi", []).extend(f for f in nuove if f not in esistenti)
            collegate += 1

    _salva(pagine)
    return {"tracce_trovate": len(indice), "pagine_collegate": collegate}


# --------------------------------------------------------------------- esercizio <-> traccia
SISTEMA_ASSOCIA_TRACCE = """You are matching listening-exercise instructions to \
audio track numbers on a page of a German course book.

You get the page's full transcription (which shows where each audio icon and \
its track number sits, relative to the exercise instructions) and a numbered \
list of the gap-fill exercises found on that page.

For each exercise, decide which single track number (if any) it requires \
listening to in order to answer — the icon closest to, or explicitly part of, \
that exercise's instruction. An exercise with no audio icon near it gets null.

Reply with valid JSON only, no backticks:
{"associazioni":[{"n":<exercise number>,"traccia":<track number or null>}]}"""


def associa_tracce_esercizi(quante_pagine: int = 20) -> dict:
    """Per le pagine con esercizi E icone audio, decide quale esercizio usa
    quale traccia. Scrive `traccia_audio` (int o None) su ogni esercizio.

    PERCHE' SERVE UN GIRO A PARTE
    L'OCR (chiama_visione) registra `tracce_audio` a livello di PAGINA — tutti
    i numeri visti, senza dire quale esercizio li usa. Su una pagina con 3
    esercizi e tracce [5,6,7] l'associazione non e' scontata (un esercizio puo'
    usare piu' tracce, o le tracce possono servire a un ascolto guidato non a
    un gap-fill specifico). Qui basta un giro di TESTO (niente vision, gia'
    tutto trascritto) — economico, backend abbonamento.

    Idempotente: salta le pagine i cui esercizi hanno gia' tutti il campo
    `traccia_audio` valorizzato (anche a None, che significa "controllato,
    nessuna traccia").
    """
    from ..base.config import llm_config
    from ..base.llm import chiama, estrai_json

    pagine = _carica()
    da_fare = [
        (k, p) for k, p in pagine.items()
        if p.get("fonte") == "kursbuch" and p.get("esercizi") and p.get("tracce_audio")
        and any("traccia_audio" not in e for e in p["esercizi"])
    ]
    if not da_fare:
        return {"pagine_associate": 0, "rimaste": 0, "costo_eur": 0.0}

    lotto = da_fare[:quante_pagine]
    fatte = 0
    costo_tot = 0.0
    for chiave, pag in lotto:
        righe = "\n".join(
            f"{i}. consegna: {e.get('consegna','')!r} | stimolo: {e.get('stimolo','')!r}"
            for i, e in enumerate(pag["esercizi"], 1)
        )
        user = (
            f"PAGE TRANSCRIPTION:\n{pag.get('testo', '')}\n\n"
            f"TRACK NUMBERS SEEN ON THIS PAGE: {pag['tracce_audio']}\n\n"
            f"EXERCISES ({len(pag['esercizi'])}):\n{righe}"
        )
        try:
            testo, uso = chiama(SISTEMA_ASSOCIA_TRACCE, user,
                                llm_config(max_tokens=2000, effort="low", backend="claude"))
            per_numero = {int(a["n"]): a.get("traccia")
                          for a in estrai_json(testo).get("associazioni", [])
                          if str(a.get("n", "")).strip().isdigit()}
        except Exception as e:                                  # noqa: BLE001
            print(f"   {chiave}: {type(e).__name__}: {str(e)[:150]}")
            continue

        for i, e in enumerate(pag["esercizi"], 1):
            e["traccia_audio"] = per_numero.get(i)
        costo_tot += uso.costo_nozionale_eur
        fatte += 1
        _salva(pagine)          # incrementale, come l'OCR

    return {"pagine_associate": fatte, "rimaste": len(da_fare) - fatte,
            "costo_nozionale_eur": round(costo_tot, 4)}


# --------------------------------------------------------------------- risoluzione esercizi
SISTEMA_RISOLVI = """You solve gap-fill exercises from a German course book \
(DaF Kompakt Neu, A1-B1).

Each item has the instruction and the German text with one or more blanks \
(___), PLUS the full transcription of the page it comes from — exercises \
routinely reference a reading passage, list, or dialogue printed elsewhere on \
the SAME page (\"see 2a\", \"see the ad above\", a table, a list of names) and \
that referenced text is usually right there in the page transcription. Read \
it before deciding you lack the reference. Some items also carry an AUDIO \
TRANSCRIPT — when present, it is the SOURCE OF TRUTH for that item: the \
answer is what the transcript actually says, not your best grammatical guess.

For each item, return the exact text filling each blank, in order, joined by \
" | " if there is more than one blank. If you truly cannot determine the \
answer even after checking the page transcription (open-ended personal \
response, illegible OCR, a photo/image to match that the transcription can't \
capture), return "" and say why in "nota" — an empty answer is honest, a \
guessed one is not.

Reply with valid JSON only, no backticks:
{"risposte":[{"n":<item number>,"soluzione":"<answer(s), or ''>","nota":"<reason if empty, else ''>"}]}"""


def risolvi_esercizi(quanti: int = 20) -> dict:
    """Risolve un lotto di esercizi senza soluzione. Priorita': traccia audio
    risolta (fonte di verita') o sola grammatica.

    Le 64 soluzioni gia' stampate nel libro (`soluzione` non vuota dall'OCR)
    non passano di qui: sono gia' fatte, a costo zero.

    Il lotto e' preso PER PAGINA INTERA, non a esercizi sciolti — verificato
    il 2026-08-24: molti esercizi rimandano a un testo/tabella/lista stampata
    altrove sulla STESSA pagina ("vedi 2a", un annuncio, un volantino), gia'
    nel corpus (`testo` della pagina). Raggrupparli permette di mandare quel
    testo UNA volta per pagina invece che ripeterlo per ogni esercizio —
    piu' pagine intere in un lotto senza sprecare token.

    Salvataggio incrementale per lotto, come `associa_tracce_esercizi()`.
    """
    pagine = _carica()
    per_pagina: dict[str, list[int]] = {}
    for chiave, pag in pagine.items():
        if pag.get("fonte") != "kursbuch":
            continue
        indici = [i for i, e in enumerate(pag.get("esercizi", []))
                 if not (e.get("soluzione") or "").strip()]
        if indici:
            per_pagina[chiave] = indici

    totale_da_fare = sum(len(v) for v in per_pagina.values())
    if not totale_da_fare:
        return {"risolti": 0, "irrisolti": 0, "rimasti": 0, "costo_nozionale_eur": 0.0}

    # Pagine intere finche' non si arriva a `quanti` esercizi (l'ultima pagina
    # puo' sforare un po': meglio un lotto leggermente piu' grande che
    # spezzare gli esercizi di una pagina fra due lotti diversi).
    scelte: dict[str, list[int]] = {}
    presi = 0
    for chiave, indici in per_pagina.items():
        if presi >= quanti:
            break
        scelte[chiave] = indici
        presi += len(indici)

    tutti_gli_esercizi = [pagine[c]["esercizi"][i] for c, idx in scelte.items() for i in idx]
    tracce = indice_tracce() if any(e.get("traccia_audio") for e in tutti_gli_esercizi) else {}

    righe: list[str] = []
    mappa_n: dict[int, tuple[str, int]] = {}
    n = 0
    for chiave, indici in scelte.items():
        pag = pagine[chiave]
        righe.append(f"=== PAGE {chiave} ===")
        if testo_pag := (pag.get("testo") or "").strip():
            righe.append(f"full page: {testo_pag[:2500]}")
        for i in indici:
            n += 1
            mappa_n[n] = (chiave, i)
            e = pag["esercizi"][i]
            pezzo = (f"{n}. consegna: {e.get('consegna', '')}\n"
                    f"   stimolo: {e.get('stimolo', '')}")
            if e.get("traccia_audio") and (testo_tr := tracce.get(int(e["traccia_audio"]))):
                # 800 caratteri tagliava a meta' i dialoghi/interviste lunghe:
                # visto piu' volte "audio transcript cuts off" fra le note di
                # irrisolvibilita' (2026-08-24). I dialoghi delle appendici
                # arrivano a ~2-3000 caratteri, non poche righe.
                pezzo += f"\n   audio transcript: {testo_tr[:3000]}"
            righe.append(pezzo)

    from ..base.config import llm_config
    from ..base.llm import chiama, estrai_json

    try:
        testo, uso = chiama(
            SISTEMA_RISOLVI, "ITEMS:\n" + "\n\n".join(righe),
            llm_config(max_tokens=8000, effort="low", backend="claude"),
        )
        risultati = {int(r["n"]): r for r in estrai_json(testo).get("risposte", [])
                    if str(r.get("n", "")).strip().isdigit()}
    except Exception as e:                                      # noqa: BLE001
        return {"risolti": 0, "irrisolti": 0, "rimasti": totale_da_fare,
                "costo_nozionale_eur": 0.0, "errore": f"{type(e).__name__}: {str(e)[:200]}"}

    risolti = irrisolti = 0
    for n, (chiave, i) in mappa_n.items():
        e = pagine[chiave]["esercizi"][i]
        r = risultati.get(n)
        if not r:
            continue
        if sol := (r.get("soluzione") or "").strip():
            pagine[chiave]["esercizi"][i]["soluzione"] = sol
            pagine[chiave]["esercizi"][i]["soluzione_fonte"] = (
                "audio" if e.get("traccia_audio") else "grammatica")
            risolti += 1
        elif nota := (r.get("nota") or "").strip():
            pagine[chiave]["esercizi"][i]["nota_irrisolto"] = nota
            irrisolti += 1

    _salva(pagine)
    return {"risolti": risolti, "irrisolti": irrisolti,
            "rimasti": totale_da_fare - len(mappa_n),
            "costo_nozionale_eur": round(uso.costo_nozionale_eur, 4)}


# ----------------------------------------------------- risoluzione visiva (secondo giro)
# Sui 730 esercizi, il giro di solo testo si ferma al 76% (558) — verificato
# il 2026-08-24, categorizzando le note di rifiuto. Il resto si spacca in tre:
# ~60 giustamente irrisolvibili (produzione libera, nessuna risposta unica),
# ~20 dove il modello ha rifiutato una traccia audio "non pertinente" invece
# di rispondere a caso (il controllo di coerenza ha funzionato, non e' un
# buco), e **~30 che citano una foto, una mappa o un simbolo** — questi soli
# sono recuperabili, e solo mandando l'immagine della pagina, non altro testo.
_PAROLE_IMMAGINE = ("photo", "foto", "image", "immagin", "picture", "map",
                    "mappa", "karte", "route", "draw", "disegn", "symbol", "bild")


def risolvi_esercizi_visione(quanti: int = 10) -> dict:
    """Secondo giro, solo per gli esercizi che il primo ha segnalato come
    dipendenti da un elemento visivo. Manda l'immagine della pagina, non solo
    la trascrizione — piu' caro (una chiamata vision a pagina, non un lotto di
    piu' pagine come `risolvi_esercizi()`), quindi lotti piccoli di proposito.
    """
    pagine = _carica()
    fonti = dict(FONTI)
    da_fare: list[tuple[str, int]] = []
    for chiave, pag in pagine.items():
        if pag.get("fonte") != "kursbuch":
            continue
        for i, e in enumerate(pag.get("esercizi", [])):
            if (e.get("soluzione") or "").strip():
                continue
            nota = (e.get("nota_irrisolto") or "").lower()
            if any(p in nota for p in _PAROLE_IMMAGINE):
                da_fare.append((chiave, i))

    if not da_fare:
        return {"risolti": 0, "irrisolti": 0, "rimasti": 0, "costo_nozionale_eur": 0.0}

    lotto = da_fare[:quanti]
    per_pagina: dict[str, list[int]] = {}
    for chiave, i in lotto:
        per_pagina.setdefault(chiave, []).append(i)

    cfg = llm_config(backend="claude")

    risolti = irrisolti = 0
    with tempfile.TemporaryDirectory(prefix="libro_visione_") as tmp:
        cartella = Path(tmp)
        for chiave, indici in per_pagina.items():
            fonte, idx_str = chiave.split(":", 1)
            pdf = fonti.get(fonte)
            if not pdf:
                continue
            pag = pagine[chiave]
            try:
                immagine = _rendi_pagina(pdf, int(idx_str), cartella)
            except Exception as e:                              # noqa: BLE001
                print(f"   {chiave}: render fallito: {str(e)[:150]}")
                continue

            righe = []
            for n, i in enumerate(indici, 1):
                e = pag["esercizi"][i]
                righe.append(f"{n}. consegna: {e.get('consegna', '')}\n"
                            f"   stimolo: {e.get('stimolo', '')}\n"
                            f"   (previously flagged: {e.get('nota_irrisolto', '')})")
            user = ("Look at the photos, maps, or symbols on this page to solve "
                    "these exercises:\n\n" + "\n\n".join(righe))

            try:
                testo, uso = chiama_visione(SISTEMA_RISOLVI, user, immagine, cfg)
                risultati = {int(r["n"]): r for r in estrai_json(testo).get("risposte", [])
                            if str(r.get("n", "")).strip().isdigit()}
            except Exception as e:                              # noqa: BLE001
                print(f"   {chiave}: {type(e).__name__}: {str(e)[:150]}")
                continue

            for n, i in enumerate(indici, 1):
                r = risultati.get(n)
                if not r:
                    continue
                if sol := (r.get("soluzione") or "").strip():
                    pag["esercizi"][i]["soluzione"] = sol
                    pag["esercizi"][i]["soluzione_fonte"] = "immagine"
                    risolti += 1
                elif nota := (r.get("nota") or "").strip():
                    pag["esercizi"][i]["nota_irrisolto"] = nota
                    irrisolti += 1
            _salva(pagine)

    return {"risolti": risolti, "irrisolti": irrisolti,
            "rimasti": len(da_fare) - len(lotto)}
