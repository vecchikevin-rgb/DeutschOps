"""Staging a scadenza per gli input consumati.  [PORTATO da archive_cleanup.py]

INVARIANTE DA CONSERVARE — la lista di protezione e' esplicita.
Qui dentro finiscono SOLO input consumati e ridondanti (il video originale da
~140MB, il .txt grezzo di una trascrizione esterna). Non ci finiscono MAI i
file canonici (transcripts/, data/, pdfs/) ne' l'audio compresso
`lezione_*-compressed.mp4`, che il registry referenzia e i re-run rileggono.
Per le lezioni arrivate senza audio il transcript canonico e' IRRECUPERABILE:
un errore qui non si ripara.

Il cleanup e' opportunistico: gira all'avvio di ogni run ed elimina cio' che
ha superato la TTL. Nessun Task Scheduler, nessun cron — se la pipeline non
gira, nulla scade, che e' il comportamento giusto.

Rispetto alla v1 cambia solo il contorno: i percorsi vengono da base.paths
(non piu' relativi alla cwd), la TTL da base.config, e gli import di os/shutil
sono in cima al file invece che dentro la funzione.
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

from .config import STAGING_TTL_DAYS
from .paths import ARCHIVE


def _protetto(p: Path) -> bool:
    """File che non devono MAI essere archiviati o cancellati da qui."""
    nome = p.name.lower()
    # Audio compresso derivato: referenziato dal registry, riusato nei re-run.
    if nome.endswith("-compressed.mp4"):
        return True
    # Gia' dentro la cartella a scadenza.
    if ARCHIVE.resolve() in p.resolve().parents:
        return True
    return False


def archivia(percorsi) -> list[Path]:
    """Sposta gli input consumati in ARCHIVE, timbrando l'mtime a ORA.

    La TTL parte dall'elaborazione, non dalla data di registrazione del file:
    un video girato tre settimane fa ed elaborato oggi ha comunque 20 giorni
    di vita davanti.

    Idempotente e non bloccante: file mancanti o protetti vengono saltati.
    """
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    spostati: list[Path] = []

    for grezzo in percorsi:
        if not grezzo:
            continue
        src = Path(grezzo)
        if not src.exists() or not src.is_file():
            continue
        if _protetto(src):
            print(f"   [staging] salto (protetto): {src.name}")
            continue

        dest = ARCHIVE / src.name
        if dest.resolve() == src.resolve():
            continue
        if dest.exists():
            dest.unlink()

        try:
            src.replace(dest)                 # move atomico, stesso volume
        except OSError:
            shutil.copy2(src, dest)           # volumi diversi: copia + rimozione
            src.unlink()

        adesso = time.time()
        os.utime(dest, (adesso, adesso))      # la TTL parte da adesso

        mb = dest.stat().st_size / 1024 / 1024
        print(f"   [staging] input consumato -> {ARCHIVE.name}/{dest.name} "
              f"({mb:.1f}MB, scade tra {STAGING_TTL_DAYS}g)")
        spostati.append(dest)

    return spostati


def pulisci_scaduti(ttl_giorni: int = STAGING_TTL_DAYS) -> list[Path]:
    """Elimina da ARCHIVE i file piu' vecchi di ttl_giorni. Silenzioso se vuoto."""
    if not ARCHIVE.exists():
        return []

    limite = time.time() - ttl_giorni * 86400
    eliminati: list[Path] = []

    for f in ARCHIVE.iterdir():
        if not f.is_file() or f.stat().st_mtime >= limite:
            continue
        eta = (time.time() - f.stat().st_mtime) / 86400
        try:
            f.unlink()
            print(f"   [staging] eliminato (scaduto, {eta:.0f}g): {f.name}")
            eliminati.append(f)
        except OSError as e:
            print(f"   [staging] impossibile eliminare {f.name}: {e}")

    return eliminati


def stato() -> list[tuple[Path, float, float]]:
    """(file, MB, giorni residui) per ogni elemento in staging."""
    if not ARCHIVE.exists():
        return []
    adesso = time.time()
    out = []
    for f in sorted(ARCHIVE.iterdir()):
        if not f.is_file():
            continue
        eta = (adesso - f.stat().st_mtime) / 86400
        out.append((f, f.stat().st_size / 1024 / 1024, STAGING_TTL_DAYS - eta))
    return out
