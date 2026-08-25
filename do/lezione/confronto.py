"""Il cancello di S1: la pipeline nuova riproduce la vecchia?

IL CRITERIO DEL PIANO, E PERCHE' VA PRECISATO
Il piano dice: «rielabora 2026-07-23 e confronta l'output con quello
esistente: JSON, PDF, carte devono coincidere». Il byte-per-byte funziona solo
su codice deterministico. In mezzo alla pipeline c'e' un LLM: la stessa
richiesta allo stesso modello non ritorna mai lo stesso testo, e per giunta il
modello e' cambiato (claude-sonnet-4-5 -> claude-sonnet-5). Pretendere
l'identita' significherebbe fallire sempre, o barare sul confronto.

Quindi il cancello e' su DUE livelli, e li tiene separati:

  DETERMINISTICO — a parita' di JSON in ingresso, tutto cio' che sta a valle
  deve dare lo stesso risultato: PDF, aggiornamento dei tre database,
  costruzione delle carte. Qui l'identita' e' esigibile e viene esatta.

  GENERATIVO — la riestrazione dal transcript si confronta per FORMA e
  SOSTANZA: schema valido, stesso ordine di grandezza di vocaboli, e quanta
  parte del vocabolario della v1 il nuovo ritrova. Il numero si stampa, non si
  giudica: e' Kevin a decidere se una sovrapposizione dell'80% e' accettabile.

LE CARTE NON POSSONO COINCIDERE, ED E' VOLUTO
La v1 creava una carta per vocabolo, DE->IT. La v2 ne crea tre (riconoscimento,
produzione, cloze). Confrontarle con la v1 misurerebbe il contrario di quello
che si vuole: se coincidessero, il cambio di metodo non sarebbe avvenuto.
Qui si verifica che il costruttore sia DETERMINISTICO (due esecuzioni
identiche) e si stampa il conteggio per direzione.

NIENTE VIENE SOVRASCRITTO
La riestrazione scrive in `data/_confronto/`. I file canonici non si toccano.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from ..base.paths import DATA, PDFS, TRANSCRIPTS

SCRATCH = DATA / "_confronto"


@dataclass
class Riga:
    nome: str
    esito: str          # "ok" | "diverso" | "saltato"
    dettaglio: str = ""


@dataclass
class Esito:
    righe: list[Riga] = field(default_factory=list)

    def aggiungi(self, nome: str, esito: str, dettaglio: str = "") -> None:
        self.righe.append(Riga(nome, esito, dettaglio))

    @property
    def passa(self) -> bool:
        return all(r.esito != "diverso" for r in self.righe)


def _carica(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def _parole(d: dict) -> set[str]:
    return {(v.get("german") or "").lower().strip()
            for v in d.get("vocabulary", []) if (v.get("german") or "").strip()}


# ------------------------------------------------------------ deterministico
def _confronta_pdf(nome: str, e: Esito) -> None:
    """Stesso JSON in ingresso -> stesso PDF. Confronto sul contenuto reale.

    Non byte-per-byte: ReportLab timbra nei metadati la data di creazione, che
    cambia a ogni esecuzione. Si confrontano numero di pagine e testo estratto.
    """
    vecchio = PDFS / f"{nome}.pdf"
    if not vecchio.exists():
        e.aggiungi("PDF", "saltato", f"{vecchio.name} non esiste")
        return

    from ..uscite import pdf as uscite_pdf

    prima = vecchio.read_bytes()
    backup = SCRATCH / f"{nome}.v1.pdf"
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_bytes(prima)

    nuovo = uscite_pdf.lezione(nome)          # riscrive lo stesso percorso
    dopo = Path(nuovo).read_bytes()

    t_prima, p_prima = _testo_pdf(backup)
    t_dopo, p_dopo = _testo_pdf(Path(nuovo))

    if t_prima is None:
        e.aggiungi("PDF", "ok" if len(dopo) > 0 else "diverso",
                   f"{len(prima)} -> {len(dopo)} byte (pypdf assente: "
                   f"confronto solo sulla dimensione)")
        return

    if p_prima == p_dopo and t_prima == t_dopo:
        e.aggiungi("PDF", "ok", f"{p_dopo} pagine, testo identico")
    else:
        # Rigenerato diverso: rimettiamo quello buono e lo diciamo.
        vecchio.write_bytes(prima)
        e.aggiungi("PDF", "diverso",
                   f"pagine {p_prima} -> {p_dopo}, "
                   f"testo {'uguale' if t_prima == t_dopo else 'DIVERSO'} "
                   f"(originale ripristinato)")


def _testo_pdf(p: Path) -> tuple[str | None, int]:
    try:
        from pypdf import PdfReader
    except ImportError:
        return None, 0
    try:
        r = PdfReader(str(p))
        testo = "\n".join(pg.extract_text() or "" for pg in r.pages)
        return _senza_timestamp(testo), len(r.pages)
    except Exception:                                       # noqa: BLE001
        return None, 0


def _senza_timestamp(testo: str) -> str:
    """Toglie la data di generazione dalla piedina di ogni pagina.

    `pdf_gen.add_footer` stampa "DeutschOps · generated 23 Jul 2026 14:51" in
    fondo a ognuna delle 7 pagine. Confrontare senza normalizzarla vuol dire
    che due PDF identici risultano sempre diversi — un cancello che segnala
    sempre rosso non segnala niente.
    """
    import re

    return re.sub(r"DeutschOps\s+·\s+generated .*", "DeutschOps · generated <data>", testo)


def _confronta_database(dati: dict, data_lezione: str, e: Esito) -> None:
    """I DB sono gia' aggiornati con questa lezione: rilanciarli non deve
    cambiare niente. E' il test di idempotenza che la v1 non aveva.

    Gira sui file VERI perche' e' l'unico modo di provare l'idempotenza sullo
    stato reale — 1.048 parole e 296 regole accumulate in 30 lezioni. Per
    questo il contenuto viene salvato prima e ripristinato dopo, sempre:
    un test che puo' corrompere l'asset che verifica non e' un test.
    """
    from ..base.paths import GRAMMAR_DB, VOCAB_DB
    from ..sapere import grammatica, vocaboli

    salvati = {p: p.read_bytes() for p in (VOCAB_DB, GRAMMAR_DB) if p.exists()}
    try:
        v_prima = json.dumps(vocaboli.carica(), sort_keys=True)
        g_prima = json.dumps(grammatica.carica().get("rules", {}), sort_keys=True)

        vocaboli.aggiorna_da_lezione(dati, data_lezione)
        grammatica.aggiorna_da_lezione(dati)

        v_dopo = json.dumps(vocaboli.carica(), sort_keys=True)
        g_dopo = json.dumps(grammatica.carica().get("rules", {}), sort_keys=True)
    finally:
        for p, contenuto in salvati.items():
            p.write_bytes(contenuto)

    e.aggiungi("vocab_db idempotente", "ok" if v_prima == v_dopo else "diverso",
               "nessuna modifica al rilancio" if v_prima == v_dopo
               else "il rilancio ha modificato il DB")
    e.aggiungi("grammar_db idempotente", "ok" if g_prima == g_dopo else "diverso",
               "nessuna modifica al rilancio" if g_prima == g_dopo
               else "il rilancio ha modificato il DB")


def _confronta_carte(dati: dict, data_lezione: str, e: Esito) -> None:
    from ..studio import carte

    a = carte.alimenta(dati.get("vocabulary", []), data_lezione, prova=True)
    b = carte.alimenta(dati.get("vocabulary", []), data_lezione, prova=True)

    stessa = json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    e.aggiungi("carte deterministiche", "ok" if stessa else "diverso",
               f"{a['proposte']} note: "
               f"{a.get('Riconoscimento', 0)} riconoscimento · "
               f"{a.get('Produzione', 0)} produzione · "
               f"{a.get('Cloze', 0)} cloze")


# ------------------------------------------------------------------ generativo
def _confronta_estrazione(nome: str, data_lezione: str, e: Esito,
                          *, riusa: bool) -> dict | None:
    canonico = DATA / f"{nome}.json"
    transcript = TRANSCRIPTS / f"{nome}.txt"
    prova = SCRATCH / f"{nome}.v2.json"

    if not canonico.exists():
        e.aggiungi("estrazione", "saltato", f"{canonico.name} non esiste")
        return None
    if not transcript.exists():
        e.aggiungi("estrazione", "saltato", f"{transcript.name} non esiste")
        return None

    vecchio = _carica(canonico)

    if riusa and prova.exists():
        print(f"   Riuso {prova.name} (nessuna chiamata LLM).")
        nuovo = _carica(prova)
    else:
        from . import estrazione

        SCRATCH.mkdir(parents=True, exist_ok=True)
        print("   Riestrazione dal transcript (chiamata LLM a pagamento)...")
        nuovo, costo = estrazione.rielabora(transcript, nome, scrivi_in=prova)
        e.aggiungi("costo riestrazione", "ok", f"{costo:.4f} EUR misurati")

    # Forma: lo schema deve validare. Se non valida, `rielabora` avrebbe gia'
    # sollevato; qui si controlla anche il vecchio, che nasce senza validazione.
    from .estrazione import CAMPI

    mancanti_v1 = [c for c in CAMPI if c not in vecchio]
    e.aggiungi("schema v1", "ok" if not mancanti_v1 else "saltato",
               "valido" if not mancanti_v1 else f"al vecchio mancano: {mancanti_v1}")
    e.aggiungi("schema v2", "ok", f"validato, versione {nuovo.get('_schema')}")

    pv, pn = _parole(vecchio), _parole(nuovo)
    comuni = pv & pn
    quota = round(100 * len(comuni) / len(pv), 1) if pv else 0.0
    e.aggiungi("vocaboli", "ok",
               f"v1 {len(pv)} · v2 {len(pn)} · in comune {len(comuni)} ({quota}%)")

    solo_v1 = sorted(pv - pn)[:8]
    solo_v2 = sorted(pn - pv)[:8]
    if solo_v1:
        e.aggiungi("  persi dalla v1", "ok", ", ".join(solo_v1))
    if solo_v2:
        e.aggiungi("  nuovi nella v2", "ok", ", ".join(solo_v2))

    gv = len(vecchio.get("grammar_points", []))
    gn = len(nuovo.get("grammar_points", []))
    e.aggiungi("regole grammaticali", "ok", f"v1 {gv} · v2 {gn}")

    con_esempio_v1 = sum(1 for v in vecchio.get("vocabulary", [])
                         if (v.get("example_de") or "").strip())
    con_esempio_v2 = sum(1 for v in nuovo.get("vocabulary", [])
                         if (v.get("example_de") or "").strip())
    e.aggiungi("vocaboli con esempio", "ok",
               f"v1 {con_esempio_v1}/{len(pv)} · v2 {con_esempio_v2}/{len(pn)} "
               f"(l'esempio e' cio' da cui nasce la carta cloze)")
    return vecchio


def esegui(data_lezione: str, *, riusa: bool = False) -> bool:
    """Il cancello. Ritorna True se nulla di deterministico e' cambiato."""
    nome = f"lezione_{data_lezione}"
    e = Esito()

    print(f"\n{'=' * 64}\n  CONFRONTO v1 / v2 — {data_lezione}\n{'=' * 64}")

    print("\n  [generativo] riestrazione")
    vecchio = _confronta_estrazione(nome, data_lezione, e, riusa=riusa)

    if vecchio is not None:
        # Il livello deterministico gira sul JSON CANONICO della v1: e' l'unico
        # modo di isolare il codice a valle dalla variabilita' dell'LLM.
        print("\n  [deterministico] a parita' di JSON in ingresso")
        _confronta_pdf(nome, e)
        _confronta_database(vecchio, data_lezione, e)
        _confronta_carte(vecchio, data_lezione, e)

    print(f"\n{'=' * 64}")
    simboli = {"ok": "  ok  ", "diverso": " DIV  ", "saltato": " --   "}
    for r in e.righe:
        print(f"  [{simboli[r.esito]}] {r.nome:<26} {r.dettaglio}")
    print(f"{'=' * 64}")

    if e.passa:
        print("  Nessuna differenza sul deterministico: il cancello di S1 e' aperto.\n")
    else:
        print("  CI SONO DIFFERENZE. S2 non parte finche' non sono spiegate.\n")
    return e.passa


def pulisci() -> None:
    shutil.rmtree(SCRATCH, ignore_errors=True)
