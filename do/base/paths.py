"""Percorsi del progetto — ancorati al file, mai alla cwd.

Perche' esiste questo modulo: nella v1 ogni modulo usava path relativi
(`Path("data")`, `Path("Audiolessons")`, `Path("lesson_registry.json")`).
Lanciare uno script da un'altra cartella non dava errore: creava le directory
nel posto sbagliato, in silenzio. Qui la root si calcola da __file__, quindi
il progetto funziona da qualunque cwd.

    do/base/paths.py  ->  parents[0]=base  parents[1]=do  parents[2]=DeutschOps
"""

from __future__ import annotations

from pathlib import Path

# --------------------------------------------------------------- root
ROOT = Path(__file__).resolve().parents[2]

# --------------------------------------------------------------- dati canonici
# Non scadono mai, non si archiviano: sono l'asset del progetto.
DATA = ROOT / "data"
TRANSCRIPTS = ROOT / "transcripts"
PDFS = ROOT / "pdfs"

VOCAB_DB = DATA / "vocab_db.json"
GRAMMAR_DB = DATA / "grammar_db.json"
ERROR_DB = DATA / "error_db.json"
REGISTRY = ROOT / "lesson_registry.json"

# --------------------------------------------------------------- input / staging
AUDIO = ROOT / "Audiolessons"
ARCHIVE = AUDIO / "_processed"          # staging a scadenza, TTL in base.staging
DOC_SNAPSHOTS = ROOT / "doc_snapshots"

# --------------------------------------------------------------- stato di lavoro
TASKS = ROOT / "tasks"                  # task aperti = run non completati
STATO = ROOT / "stato"                  # markdown generato + scadenze
PONTE_STATE = STATO / "ponte-motore.json"

# --------------------------------------------------------------- binari locali
FFMPEG = ROOT / "ffmpeg.exe"
UNTRUNC = ROOT / "tools" / "untrunc" / "untrunc_x64" / "untrunc.exe"

# --------------------------------------------------------------- credenziali
ENV_FILE = ROOT / ".env"
GOOGLE_CREDENTIALS = ROOT / "credentials.json"
GOOGLE_TOKEN = ROOT / "token.json"

# --------------------------------------------------------------- motore condiviso
# SOLA LETTURA. Import di metodo, mai di dati; nulla di DeutschOps esce di qui.
# Vedi CLAUDE.md della root del workspace, sezione firewall di privacy.
SHARED = ROOT.parent / "shared start up"
SHARED_SKILLS_INDEX = SHARED / "risorse-team" / "skills" / "INDICE.md"
SHARED_CHANGELOG = SHARED / "_engine" / "changelog-engine.md"
SHARED_ROADMAP = SHARED / "_engine" / "sviluppo" / "roadmap-engine.md"


def ensure_dirs() -> None:
    """Crea le cartelle di lavoro se mancano. Idempotente."""
    for d in (DATA, TRANSCRIPTS, PDFS, AUDIO, ARCHIVE, TASKS, STATO):
        d.mkdir(parents=True, exist_ok=True)


def shared_disponibile() -> bool:
    """True se il motore condiviso e' montato (Google Drive puo' essere offline).

    Ogni consumatore deve degradare in silenzio quando ritorna False: il ponte
    non e' un servizio critico e non deve mai far fallire una lezione.
    """
    return SHARED.is_dir()
