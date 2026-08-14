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
_TRACCIA = re.compile(r"(?:track|hörtext|h[oö]rtext|traccia)\D{0,4}(\d{1,3})", re.IGNORECASE)


def risolvi_tracce() -> dict:
    """Prima passata, deterministica: collega le pagine con icona audio alle
    trascrizioni delle appendici, per numero di traccia.

    Aggiunge le frasi trovate nella trascrizione alla lista "frasi" della
    pagina che referenzia la traccia — cosi' `cerca()` le trova senza sapere
    che venivano da un esercizio con audio. Best-effort: se il formato delle
    appendici non usa nessuno dei pattern in `_TRACCIA`, non collega niente
    (non inventa un numero).
    """
    pagine = _carica()
    per_traccia: dict[int, list[str]] = {}
    for chiave, pag in pagine.items():
        if pag.get("fonte") not in ("book_transcriptions", "transkriptionen_a1"):
            continue
        m = _TRACCIA.search(pag.get("testo", ""))
        if m:
            per_traccia.setdefault(int(m.group(1)), []).extend(pag.get("frasi", []))

    collegate = 0
    for chiave, pag in pagine.items():
        if pag.get("fonte") != "kursbuch":
            continue
        for n in pag.get("tracce_audio", []):
            if frasi := per_traccia.get(int(n)):
                esistenti = set(pag.get("frasi", []))
                pag.setdefault("frasi", []).extend(f for f in frasi if f not in esistenti)
                collegate += 1

    _salva(pagine)
    return {"tracce_trovate": len(per_traccia), "pagine_collegate": collegate}
