"""I tre PDF: lezione, quaderno errori, libro di grammatica.

PERCHE' QUESTO E' UN ADATTATORE E NON UNA RISCRITTURA
Il piano prevede `uscite/tema.py` con una palette sola, al posto degli stessi
valori esadecimali copiati in quattro generatori ReportLab. La duplicazione
c'e' davvero (~200 righe replicate). Ma il guadagno e' estetico e interno,
mentre il rischio non lo e': sono ~1.500 righe di layout che nessun test puo'
verificare — l'unico modo di sapere se un PDF e' ancora giusto e' aprirlo e
guardarlo.

Nell'ordine delle cose da fare, riscrivere codice che funziona per togliere
una duplicazione di colori viene dopo tutto il resto. Resta lavoro di S5.

Quello che invece serviva subito, ed e' fatto: i generatori non dipendono piu'
dalla cwd (`pdf_gen` riceveva gia' i path come argomenti, `error_pdf` e
`grammar_book` avevano costanti relative — ora leggono do/base/paths).

Gli import sono PIGRI: ReportLab pesa ~1,5 s all'import e `grammar_book`
costruisce un client Anthropic a livello di modulo. Il briefing all'avvio
sessione non deve pagare nessuna delle due cose.
"""

from __future__ import annotations

from pathlib import Path

from ..base.paths import DATA, PDFS


def lezione(nome: str) -> Path:
    """PDF della lezione da `data/<nome>.json`. Ritorna il percorso scritto."""
    from pdf_gen import generate_pdf

    sorgente = DATA / f"{nome}.json"
    if not sorgente.exists():
        raise FileNotFoundError(f"JSON lezione non trovato: {sorgente}")
    PDFS.mkdir(parents=True, exist_ok=True)
    return Path(generate_pdf(str(sorgente), output_dir=str(PDFS)))


def quaderno_errori() -> Path | None:
    """Il quaderno degli errori cumulativo. None se non c'e' ancora nulla."""
    from error_pdf import OUT, generate_error_pdf

    try:
        return Path(generate_error_pdf(OUT))
    except FileNotFoundError:
        print("   Quaderno errori: error_db.json assente, salto.")
        return None


def libro_grammatica() -> Path | None:
    """Rigenera il libro di grammatica dal DB. Nessuna chiamata LLM."""
    from grammar_book import OUTPUT_PDF, build_grammar_book

    build_grammar_book(use_doc=False, enrich_web=False)
    return Path(OUTPUT_PDF)
