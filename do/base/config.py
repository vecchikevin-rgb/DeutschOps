"""Configurazione unica del progetto.

Nella v1 le costanti erano sparse e duplicate: il DOC_ID del Google Doc di
Stefanie era hardcoded in TRE file (doc_reader.py:17, doc_writer.py:11,
retroactive_doc_images.py:29), stessa cosa per KPI_TAB_ID, e i moduli che
parlavano con Ollama ignoravano OLLAMA_HOST usandolo hardcoded.

Qui c'e' una sola fonte. Tutto e' sovrascrivibile da .env, con i valori
attuali come default cosi' il progetto continua a funzionare senza toccare
niente.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal

from .paths import ENV_FILE


# --------------------------------------------------------------------- .env
def _carica_env() -> None:
    """Legge .env senza dipendere da python-dotenv.

    Non sovrascrive le variabili gia' presenti nell'ambiente: un valore
    passato a mano sulla riga di comando deve vincere sul file.
    """
    if not ENV_FILE.exists():
        return
    for riga in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
        riga = riga.strip()
        if not riga or riga.startswith("#") or "=" not in riga:
            continue
        chiave, _, valore = riga.partition("=")
        chiave = chiave.strip()
        valore = valore.strip().strip('"').strip("'")
        if chiave and chiave not in os.environ:
            os.environ[chiave] = valore


_carica_env()


def _bool(nome: str, default: bool = False) -> bool:
    val = os.getenv(nome)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "si", "on")


# --------------------------------------------------------------------- Google
# Il Doc condiviso con Stefanie e la tab dei KPI. Erano hardcoded in 3 file.
DOC_ID = os.getenv("STEFANIE_DOC_ID", "165S8CsHT3TrCpr6Se3l3VYakb7r16_bgg81l5ygJvpc")
KPI_TAB_ID = os.getenv("STEFANIE_KPI_TAB_ID", "t.wjmdnwq7d6ek")

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
]

# --------------------------------------------------------------------- Anki
ANKI_URL = os.getenv("ANKI_URL", "http://localhost:8765")
ANKI_DECK = os.getenv("ANKI_DECK", "Deutsch::DeutschOps")

# --------------------------------------------------------------------- audio
# Soglia unica di compressione. Nella v1 ce n'erano due incoerenti:
# main.prepare_audio usava 20MB, transcriber.compress_if_needed 24MB.
COMPRESS_THRESHOLD_MB = int(os.getenv("COMPRESS_THRESHOLD_MB", "20"))
WHISPER_MODE = os.getenv("WHISPER_MODE", "local")       # local | api
# `small`, non `large-v3`: e' il modello che la v1 usava davvero
# (transcriber.transcribe_local:190 lo aveva cablato). Su CPU la differenza e'
# fra ore e mezze giornate. Sovrascrivibile da .env se un giorno gira su GPU.
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")

# --------------------------------------------------------------------- staging
STAGING_TTL_DAYS = int(os.getenv("STAGING_TTL_DAYS", "20"))

# --------------------------------------------------------------------- costi
# LA RICERCA WEB E' SPENTA DI DEFAULT. Misurato il 2026-07-27 sulla stessa
# lezione, sulle stesse regole:
#
#     con ricerca web    0,5815 EUR a regola
#     senza              0,0222 EUR a regola      <- 26 volte meno
#
# e il testo prodotto e' equivalente per lunghezza e struttura (tabelle di
# coniugazione, errori tipici dell'italiano, eccezioni). L'arricchimento
# grammaticale RESTA — e' utile e costa poco; quello che cade e' il giro sui
# siti esterni, che gonfia il contesto di ogni ricerca e fa pagare la stessa
# grammatica di base a peso d'oro.
#
# Cosa si perde davvero: `source_verified: true`, cioe' l'asserzione che la
# regola sia stata confrontata con duden/dartmouth. Per la grammatica A2-B2
# e' un'assicurazione cara. Quando serve — una regola dubbia, una correzione
# di Stefanie da verificare — si accende per quella volta:
#
#     RICERCA_WEB=1 py -3 deutschops.py lezione ...
RICERCA_WEB = _bool("RICERCA_WEB", False)

# Tetto di ricerche per singola chiamata, quando la ricerca e' accesa. Senza,
# il modello ne fa quante ne vuole e ogni giro rimanda in input tutto il
# contesto accumulato: e' li' che nasce il fattore 26.
RICERCA_MAX_USI = int(os.getenv("RICERCA_MAX_USI", "3"))

# --------------------------------------------------------------------- ponte
PONTE_CADENZA_GIORNI = int(os.getenv("PONTE_CADENZA_GIORNI", "14"))


# --------------------------------------------------------------------- LLM
Backend = Literal["anthropic", "ollama"]


@dataclass(frozen=True)
class LLMConfig:
    """Configurazione del backend LLM.

    Nella v1 questa logica era duplicata in extractor.py ed error_extractor.py
    e IGNORATA da altri 7 moduli, che avevano il nome del modello cablato.
    """

    backend: Backend
    model: str
    max_tokens: int
    ollama_host: str
    # Il pensiero adattivo e' ATTIVO di default su Sonnet 5 quando il campo
    # `thinking` viene omesso (su Sonnet 4.6 era il contrario). E `max_tokens`
    # limita pensiero + risposta INSIEME: lasciarlo implicito su un'estrazione
    # JSON con max_tokens stretto significa rischiare il troncamento a meta'.
    # Per l'estrazione strutturata lo disattiviamo esplicitamente.
    thinking: bool = False
    effort: str | None = None       # low | medium | high | xhigh | max


def llm_config(
    *,
    max_tokens: int = 12000,
    thinking: bool = False,
    effort: str | None = None,
) -> LLMConfig:
    """Costruisce la configurazione leggendo l'ambiente.

    max_tokens sale da 8000 (v1) a 12000: Sonnet 5 usa un tokenizer nuovo che
    produce circa il 30% di token in piu' a parita' di testo, quindi un limite
    tarato su Sonnet 4.5 puo' troncare lo stesso output.
    """
    backend: Backend = "ollama" if os.getenv("LLM_BACKEND", "").lower() == "ollama" else "anthropic"
    if backend == "ollama":
        model = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct")
    else:
        # Migrazione dal claude-sonnet-4-5 della v1. Bumpalo a claude-opus-5
        # in .env se vuoi il modello piu' capace: ANTHROPIC_MODEL=claude-opus-5
        model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")
    return LLMConfig(
        backend=backend,
        model=model,
        max_tokens=max_tokens,
        ollama_host=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
        thinking=thinking,
        effort=effort,
    )


def api_key(nome: str) -> str:
    """Legge una chiave API, con un errore parlante se manca.

    Deliberatamente NON valutata all'import: nella v1 transcriber.py creava il
    client OpenAI a livello di modulo (riga 9), quindi l'intera pipeline moriva
    all'import senza OPENAI_API_KEY — anche con WHISPER_MODE=local, dove quella
    chiave non serve e il costo e' zero.
    """
    val = os.getenv(nome)
    if not val:
        raise RuntimeError(
            f"{nome} non impostata. Aggiungila a {ENV_FILE} "
            f"(il file non e' in git: vedi .gitignore)."
        )
    return val
