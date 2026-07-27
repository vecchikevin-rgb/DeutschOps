"""Il Google Doc di Stefanie: lettura, diff, snapshot.

E' il terreno comune con l'insegnante. Non si reinventa: si legge, si
confronta con l'ultimo snapshot, e le righe nuove diventano contesto per
l'estrazione.

DEDUP PER HASH
5 snapshot su 30 in `doc_snapshots/` sono byte-identici al precedente: sono le
lezioni in cui Stefanie non ha toccato il documento. Scriverli comunque
sporca la cartella e, peggio, sposta il riferimento del diff su un file
inutile. Qui, se il testo e' identico all'ultimo snapshot, non se ne crea uno
nuovo — e il diff continua a puntare a quello buono.

LA SCRITTURA NON E' QUI
`doc_writer.py` (400 righe di aritmetica sugli indici della Docs API, tab KPI,
marcatori) resta dov'e'. Non e' pigrizia: quel codice non e' testabile senza
scrivere sul documento REALE condiviso con Stefanie, e riscriverlo alla cieca
per guadagnarci uno spostamento di file e' un rischio senza contropartita.
Da qui si raggiunge con `aggiorna_riepilogo()`, e i suoi path sono stati resi
assoluti. La consolidazione, se mai servira', e' lavoro di S5.

L'ANALISI DELLE IMMAGINI E' OPZIONALE E FUORI DAL PERCORSO CRITICO
doc_reader chiamava Ollama con un modello vision per leggere il testo nelle
immagini del doc. Resta disponibile, ma dietro un flag: su una macchina senza
Ollama costava un timeout a ogni lezione per un contributo marginale.
"""

from __future__ import annotations

import difflib
import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ..base.config import DOC_ID, GOOGLE_SCOPES, KPI_TAB_ID
from ..base.paths import DOC_SNAPSHOTS, GOOGLE_CREDENTIALS, GOOGLE_TOKEN


@dataclass(frozen=True)
class Lettura:
    testo: str
    nuovo: str
    snapshot: Path
    aveva_precedente: bool
    identico_al_precedente: bool


def _credenziali():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if GOOGLE_TOKEN.exists():
        creds = Credentials.from_authorized_user_file(str(GOOGLE_TOKEN), GOOGLE_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(GOOGLE_CREDENTIALS), GOOGLE_SCOPES)
            creds = flow.run_local_server(port=0)
        GOOGLE_TOKEN.write_text(creds.to_json())
    return creds


def leggi() -> str:
    """Legge il doc tab per tab, escluso il tab KPI che scriviamo noi."""
    from googleapiclient.discovery import build

    creds = _credenziali()
    servizio = build("docs", "v1", credentials=creds)
    doc = servizio.documents().get(documentId=DOC_ID, includeTabsContent=True).execute()

    pezzi: list[str] = []
    immagini: dict = {}
    tabs = doc.get("tabs", [])

    if tabs:
        for tab in tabs:
            props = tab.get("tabProperties", {})
            if props.get("tabId") == KPI_TAB_ID:
                continue
            dt = tab.get("documentTab", {})
            immagini.update(dt.get("inlineObjects", {}))
            testo = "".join(
                el.get("textRun", {}).get("content", "")
                for e in dt.get("body", {}).get("content", [])
                for el in e.get("paragraph", {}).get("elements", [])
            )
            if testo.strip():
                pezzi.append(f"\n=== TAB: {props.get('title', 'untitled')} "
                             f"(id:{props.get('tabId', '')}) ===\n{testo}")
    else:
        immagini.update(doc.get("inlineObjects", {}))
        pezzi.append("".join(
            el.get("textRun", {}).get("content", "")
            for e in doc.get("body", {}).get("content", [])
            for el in e.get("paragraph", {}).get("elements", [])
        ))

    testo = "\n".join(pezzi)

    if immagini and os.getenv("DOC_IMMAGINI") == "1":
        try:
            testo += _testo_dalle_immagini(immagini, creds)
        except Exception as e:                              # noqa: BLE001
            print(f"   Analisi immagini saltata: {str(e)[:70]}")

    print(f"   Doc: {len(testo)} caratteri, {len(tabs)} tab, {len(immagini)} immagini")
    return testo


def _testo_dalle_immagini(oggetti: dict, creds) -> str:
    """OCR via modello vision locale (Ollama). Solo se DOC_IMMAGINI=1.

    Cache su disco: senza, un doc con 100 immagini le rianalizza tutte a ogni
    lezione. La cache e' per id oggetto, che Google mantiene stabile.
    """
    import requests as http
    from google.auth.transport.requests import Request

    from ..base.config import llm_config
    from ..base.paths import DATA

    cache_p = DATA / "doc_image_cache.json"
    cache: dict[str, str] = {}
    if cache_p.exists():
        try:
            cache = json.loads(cache_p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cache = {}

    nuovi = [o for o in oggetti if o not in cache]
    descrizioni = {o: d for o, d in cache.items() if o in oggetti and d}
    if not nuovi:
        return _formatta_immagini(descrizioni)

    host = llm_config().ollama_host
    try:
        disponibili = [m["name"] for m in http.get(f"{host}/api/tags", timeout=3).json()
                       .get("models", [])]
    except Exception:                                       # noqa: BLE001
        print("   Ollama non risponde — niente OCR sulle immagini.")
        return _formatta_immagini(descrizioni)

    modello = next((c for c in ("minicpm-v:latest", "llava:7b")
                    if any(c.split(":")[0] in m for m in disponibili)), None)
    if not modello:
        return _formatta_immagini(descrizioni)

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())

    import base64
    prompt = ("This image is from a German language lesson document. Extract ALL "
              "visible German text: vocabulary, grammar tables, example sentences, "
              "conjugations, exercises. Copy exactly. If there is no readable German "
              "text, respond with: NO_TEXT")

    print(f"   {len(nuovi)} immagini nuove -> OCR con {modello}")
    for oid in nuovi:
        uri = (oggetti[oid].get("inlineObjectProperties", {})
               .get("embeddedObject", {}).get("imageProperties", {}).get("contentUri", ""))
        if not uri:
            continue
        try:
            r = http.get(uri, headers={"Authorization": f"Bearer {creds.token}"}, timeout=30)
            if r.status_code != 200:
                continue
            v = http.post(f"{host}/api/generate", json={
                "model": modello, "prompt": prompt,
                "images": [base64.b64encode(r.content).decode()],
                "stream": False, "options": {"temperature": 0.1},
            }, timeout=120)
            t = v.json().get("response", "").strip() if v.status_code == 200 else ""
            cache[oid] = "" if t.upper().startswith("NO_TEXT") else t
            if cache[oid]:
                descrizioni[oid] = cache[oid]
        except Exception:                                   # noqa: BLE001, S112
            continue

    cache_p.parent.mkdir(parents=True, exist_ok=True)
    cache_p.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    return _formatta_immagini(descrizioni)


def _formatta_immagini(descrizioni: dict[str, str]) -> str:
    if not descrizioni:
        return ""
    righe = ["\n\n=== IMMAGINI NEL DOC ==="]
    righe += [f"\n[img {o[:16]}]\n{d}" for o, d in descrizioni.items()]
    return "\n".join(righe)


def ultimo_snapshot() -> tuple[Path | None, str]:
    snap = sorted(DOC_SNAPSHOTS.glob("snapshot_*.txt"))
    if not snap:
        return None, ""
    return snap[-1], snap[-1].read_text(encoding="utf-8")


def righe_nuove(vecchio: str, nuovo: str) -> str:
    """Diff riga per riga, con l'intestazione di sezione quando c'e'.

    Non e' un semplice `nuovo[len(vecchio):]`: Stefanie inserisce anche in
    mezzo al documento, non solo in coda.
    """
    v, n = vecchio.splitlines(), nuovo.splitlines()
    aggiunte: list[str] = []
    sezione = ""

    for tag, _i1, _i2, j1, j2 in difflib.SequenceMatcher(None, v, n, autojunk=False).get_opcodes():
        if tag not in ("insert", "replace"):
            continue
        for riga in n[max(0, j1 - 10):j1]:
            s = riga.strip()
            if s and ((s[0].isdigit() and "." in s[:5]) or s.startswith("=== TAB:")):
                sezione = s
        blocco = [r for r in n[j1:j2] if r.strip()]
        if blocco:
            if sezione and (not aggiunte or aggiunte[-1] != f"\n[Sezione: {sezione}]"):
                aggiunte.append(f"\n[Sezione: {sezione}]")
            aggiunte.extend(blocco)

    return "\n".join(aggiunte)


def leggi_e_confronta(etichetta: str | None = None) -> Lettura:
    """Legge il doc e calcola le novita'. NON scrive lo snapshot.

    Lo snapshot lo scrive il chiamante a pipeline completa (commit differito
    nel tracker): scriverlo qui e poi fallire piu' avanti significherebbe
    perdere il diff al rilancio, perche' il confronto avverrebbe contro un
    documento gia' aggiornato.
    """
    testo = leggi()
    prec_p, prec_t = ultimo_snapshot()

    if prec_p:
        identico = testo == prec_t
        nuovo = "" if identico else righe_nuove(prec_t, testo)
        if identico:
            print(f"   Doc invariato dal {prec_p.name} — nessuno snapshot nuovo.")
        elif nuovo:
            print(f"   {len(nuovo.splitlines())} righe nuove nel doc")
        else:
            print("   Modifiche solo formali, nessuna riga nuova")
    else:
        identico = False
        nuovo = testo
        print("   Primo snapshot: tutto il doc e' contesto nuovo.")

    etichetta = etichetta or date.today().isoformat()
    return Lettura(
        testo=testo,
        nuovo=nuovo,
        snapshot=DOC_SNAPSHOTS / f"snapshot_{etichetta}.txt",
        aveva_precedente=prec_p is not None,
        identico_al_precedente=identico,
    )


def scrivi_snapshot(percorso: Path, contenuto: str) -> None:
    percorso.parent.mkdir(parents=True, exist_ok=True)
    percorso.write_text(contenuto, encoding="utf-8")
    print(f"   Snapshot: {percorso.name}")


def aggiorna_riepilogo(json_lezione: str | Path, data_lezione: str,
                       pdf: str | Path | None = None) -> None:
    """Append del riepilogo + KPI sul Doc. Delega a doc_writer (vedi in cima)."""
    from doc_writer import append_lesson_summary

    append_lesson_summary(
        lesson_json_path=str(json_lezione),
        lesson_date=data_lezione,
        pdf_path=str(pdf) if pdf else None,
    )
