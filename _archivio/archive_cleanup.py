# archive_cleanup.py
# Staging a scadenza per gli INPUT consumati di una lezione.
#
# Dopo che una lezione e' stata elaborata con successo, il file sorgente
# (video originale ~140MB, oppure i .txt grezzi di trascrizioni esterne tipo
# Gemini) non serve piu': trascritto e output canonici esistono gia'. Lo
# spostiamo in Audiolessons/_processed/ e lo cancelliamo dopo 20 giorni.
#
# REGOLA DURA: qui dentro finiscono SOLO input consumati e ridondanti. NON
# vanno mai i file canonici (transcripts/, data/, pdfs/) ne' l'audio compresso
# lezione_*-compressed.mp4: la pipeline e i tool cumulativi li rileggono, e per
# le lezioni senza audio (solo trascrizione esterna) il transcript canonico e'
# irrecuperabile. Vedi CLAUDE.md.
#
# Cleanup: opportunistico. cleanup_expired() gira all'avvio di ogni run
# (main.py / watch.py) ed elimina cio' che ha superato la TTL. Nessun task di
# sistema richiesto. Esponiamo anche una CLI per lanciarlo a mano.

import sys
import time
from pathlib import Path

TTL_DAYS = 20
ARCHIVE_DIR = Path("Audiolessons/_processed")


def _is_protected(p: Path) -> bool:
    """File che NON devono mai essere archiviati/cancellati da qui."""
    name = p.name.lower()
    # audio compresso derivato: referenziato dal registry, riusato nei re-run
    if name.endswith("-compressed.mp4"):
        return True
    # gia' dentro la cartella a scadenza
    if ARCHIVE_DIR.resolve() in p.resolve().parents:
        return True
    return False


def archive_inputs(paths) -> list[Path]:
    """Sposta i file sorgente consumati in ARCHIVE_DIR, timbrando l'mtime a
    ORA cosi' la TTL di 20 giorni parte dall'elaborazione (non dalla data di
    registrazione del file). Ritorna i path di destinazione effettivi.
    Idempotente e non-blocking: file mancanti o protetti vengono saltati."""
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    moved = []
    for raw in paths:
        if not raw:
            continue
        src = Path(raw)
        if not src.exists() or not src.is_file():
            continue
        if _is_protected(src):
            print(f"   [archive] salto (protetto): {src.name}")
            continue
        dest = ARCHIVE_DIR / src.name
        if dest.resolve() == src.resolve():
            continue
        if dest.exists():
            dest.unlink()
        try:
            src.replace(dest)          # move atomico se stesso volume
        except OSError:
            # volumi diversi: copia + rimozione
            import shutil
            shutil.copy2(src, dest)
            src.unlink()
        now = time.time()
        import os
        os.utime(dest, (now, now))     # TTL parte da adesso
        size_mb = dest.stat().st_size / 1024 / 1024
        print(f"   [archive] input consumato -> {ARCHIVE_DIR}/{dest.name} "
              f"({size_mb:.1f}MB, scade tra {TTL_DAYS}g)")
        moved.append(dest)
    return moved


def cleanup_expired(ttl_days: int = TTL_DAYS) -> list[Path]:
    """Elimina da ARCHIVE_DIR i file piu' vecchi di ttl_days (per mtime).
    Ritorna i path cancellati. Silenzioso se non c'e' nulla da fare."""
    if not ARCHIVE_DIR.exists():
        return []
    cutoff = time.time() - ttl_days * 86400
    deleted = []
    for f in ARCHIVE_DIR.iterdir():
        if not f.is_file():
            continue
        if f.stat().st_mtime < cutoff:
            age_days = (time.time() - f.stat().st_mtime) / 86400
            try:
                f.unlink()
                print(f"   [archive] eliminato (scaduto, {age_days:.0f}g): {f.name}")
                deleted.append(f)
            except OSError as e:
                print(f"   [archive] impossibile eliminare {f.name}: {e}")
    return deleted


if __name__ == "__main__":
    if "--cleanup" in sys.argv:
        d = cleanup_expired()
        print(f"Cleanup completato: {len(d)} file eliminati.")
    elif len(sys.argv) > 1:
        archive_inputs(sys.argv[1:])
    else:
        print("Uso:")
        print("  python archive_cleanup.py --cleanup        # elimina gli scaduti (>20g)")
        print("  python archive_cleanup.py <file> [file...]  # archivia input consumati")
        # stato corrente
        if ARCHIVE_DIR.exists():
            files = [f for f in ARCHIVE_DIR.iterdir() if f.is_file()]
            print(f"\n{ARCHIVE_DIR}/ contiene {len(files)} file:")
            for f in sorted(files):
                age = (time.time() - f.stat().st_mtime) / 86400
                left = TTL_DAYS - age
                print(f"   {f.name}  ({f.stat().st_size/1024/1024:.1f}MB, "
                      f"scade tra {left:.0f}g)")
