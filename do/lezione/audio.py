"""Audio: sonda, comprime, trascrive. UN modulo solo.

TRE IMPLEMENTAZIONI DIVENTANO UNA
Nella v1 la compressione ffmpeg esisteva due volte, con due soglie diverse e
due nomi di output diversi:

  main.prepare_audio        soglia 20 MB, subprocess con lista di argomenti,
                            output `Audiolessons/lezione_{data}-compressed.mp4`
  transcriber.compress_if_needed
                            soglia 24 MB, `os.system` con path quotati a mano,
                            output `{stem}_compressed.mp4`

La seconda usa os.system: e' esattamente il bug che main.py documenta come gia'
risolto nel proprio commento («os.system su Windows sbaglia il parsing con piu'
path quotati -> ffmpeg non riconosciuto»). Restava vivo perche' la chiamava
transcribe_api, un ramo che con WHISPER_MODE=local non viene mai percorso.

Qui: una soglia (config.COMPRESS_THRESHOLD_MB), un nome
(`lezione_{data}-compressed.mp4`, quello che il registry referenzia e che
staging protegge), subprocess con lista di argomenti.

LA RITENZIONE VIDEO NON RINASCE
main.prepare_audio:64-71 teneva «max 5 video originali» cancellando il piu'
vecchio. Il glob era `"Classroom with Stefanie*.mp4"`, che dal rename dei
file non corrisponde piu' a niente: quel ramo non ha MAI cancellato nulla.
Non lo resuscito. Correggere il glob significherebbe accendere oggi una
cancellazione distruttiva mai eseguita, e per giunta in doppio: la ritenzione
degli input ce l'ha gia' `base/staging.py`, con TTL esplicito e lista di
protezione. Una politica di ritenzione sola.

NIENTE input() NELLA PIPELINE
transcriber.ask_routing chiedeva "A o B" da tastiera quando l'audio superava i
20 minuti. Una pipeline che si blocca su input() non e' automatizzabile: non
gira da un hook, non gira in background, non gira da uno scheduler. Qui decide
WHISPER_MODE (default `local`, gratis).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..base.config import COMPRESS_THRESHOLD_MB, WHISPER_MODE, WHISPER_MODEL, api_key
from ..base.paths import AUDIO, AUDIO_ARCHIVE, FFMPEG, TRANSCRIPTS

# Whisper API OpenAI: 0,006 USD al minuto. Serve solo per stimare, il costo
# vero arriva da result.duration.
COSTO_API_AL_MINUTO = 0.006

# Chunk per la trascrizione locale. faster-whisper carica l'intero file in
# memoria per l'estrazione delle feature: su una lezione da 90 minuti va in OOM
# durante la STFT. 15 minuti e' la dimensione che regge sul fisso.
CHUNK_MINUTI = 15

VIDEO_SUFFIXES = {".mp4", ".mkv", ".mov", ".avi", ".m4v", ".webm", ".wmv"}


@dataclass(frozen=True)
class Trascrizione:
    testo: str
    percorso: Path
    minuti: float
    costo_eur: float
    lingua: str
    motore: str


def _ffmpeg() -> str:
    """Il binario locale se c'e', altrimenti quello di sistema."""
    return str(FFMPEG) if FFMPEG.exists() else "ffmpeg"


def e_video(percorso: str | Path) -> bool:
    return Path(percorso).suffix.lower() in VIDEO_SUFFIXES


def durata_minuti(percorso: Path) -> float:
    """Durata reale via ffprobe; ripiega sulla stima da peso se non risponde.

    La stima (2,1 minuti per MB) vale solo per l'audio compresso a 32 kbps di
    questo progetto: su un video da 140 MB darebbe 294 minuti per una lezione
    di 60. Per questo si prova ffprobe per primo.
    """
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(percorso)],
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode == 0 and r.stdout.strip():
            return float(r.stdout.strip()) / 60
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return (percorso.stat().st_size / (1024 * 1024)) * 2.1


def prepara(percorso: str | Path, data_lezione: str) -> Path:
    """Comprime a audio-only se il file supera la soglia. Idempotente.

    Se il compresso esiste gia' lo riusa: e' quello che permette di rilanciare
    una lezione senza ricomprimere 140 MB.
    """
    p = Path(percorso)
    compresso = AUDIO / f"lezione_{data_lezione}-compressed.mp4"

    if compresso.exists():
        print(f"   Gia' compresso: {compresso.name} "
              f"({compresso.stat().st_size / 1024 / 1024:.1f} MB)")
        return compresso

    mb = p.stat().st_size / (1024 * 1024)
    if mb <= COMPRESS_THRESHOLD_MB:
        return p

    print(f"   {mb:.0f} MB sopra la soglia di {COMPRESS_THRESHOLD_MB} MB — comprimo ad audio...")
    compresso.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [_ffmpeg(), "-i", str(p), "-vn", "-ar", "16000", "-ac", "1", "-b:a", "32k",
         str(compresso), "-y", "-loglevel", "quiet"],
        check=False,
    )

    if not compresso.exists():
        print("   Compressione fallita — proseguo con l'originale.")
        return p

    print(f"   {mb:.0f} MB -> {compresso.stat().st_size / 1024 / 1024:.1f} MB")
    return compresso


def archivia_audio_grezzo(percorso: str | Path, data_lezione: str) -> Path | None:
    """Estrae l'audio dal video e lo salva per sempre in AUDIO_ARCHIVE.

    Non e' il compresso di `prepara()`: quello e' scarnificato per Whisper
    (16kHz mono 32k) e ottimizzato per la trascrizione, non per la qualita'.
    Questo backup serve a poter rielaborare la lezione in futuro — un modello
    diverso, un Whisper piu' grosso — anche dopo che il video originale (che
    va in staging e scade in 20 giorni, vedi `base/staging.py`) non c'e' piu'.

    Va chiamato PRIMA che il video finisca in staging, sulla sorgente grezza.
    Idempotente: se il backup esiste gia' non rifa' nulla. Non solleva mai:
    un fallimento qui non deve bloccare la pipeline, solo essere segnalato.
    """
    p = Path(percorso)
    if not e_video(p):
        return None

    AUDIO_ARCHIVE.mkdir(parents=True, exist_ok=True)
    dest = AUDIO_ARCHIVE / f"lezione_{data_lezione}.m4a"
    if dest.exists():
        return dest

    # Primo tentativo: copia il flusso audio senza ricodificare (bit-esatto,
    # istantaneo). Funziona quando l'audio sorgente e' gia' AAC, il caso
    # comune per le registrazioni Zoom/Meet in .mp4.
    subprocess.run(
        [_ffmpeg(), "-i", str(p), "-vn", "-acodec", "copy", str(dest),
         "-y", "-loglevel", "quiet"],
        check=False,
    )

    if not dest.exists() or dest.stat().st_size == 0:
        # Codec sorgente non copiabile nel contenitore m4a (es. Opus/webm):
        # ricodifica a una qualita' comunque ben sopra il compresso Whisper.
        subprocess.run(
            [_ffmpeg(), "-i", str(p), "-vn", "-ar", "44100", "-ac", "2",
             "-b:a", "128k", str(dest), "-y", "-loglevel", "quiet"],
            check=False,
        )

    if dest.exists() and dest.stat().st_size > 0:
        mb = dest.stat().st_size / 1024 / 1024
        print(f"   Audio grezzo archiviato -> {AUDIO_ARCHIVE.name}/{dest.name} ({mb:.1f} MB)")
        return dest

    dest.unlink(missing_ok=True)
    print("   Estrazione audio d'archivio fallita — proseguo comunque.")
    return None


# ------------------------------------------------------------------ API OpenAI
def _trascrivi_api(sorgente: Path, uscita: Path) -> Trascrizione:
    from openai import OpenAI

    client = OpenAI(api_key=api_key("OPENAI_API_KEY"))
    print("   Whisper API...")
    with open(sorgente, "rb") as f:
        r = client.audio.transcriptions.create(
            model="whisper-1", file=f, response_format="verbose_json", temperature=0.0
        )
    minuti = r.duration / 60
    return Trascrizione(
        testo=r.text, percorso=uscita, minuti=minuti,
        costo_eur=minuti * COSTO_API_AL_MINUTO,
        lingua=r.language, motore="whisper-api",
    )


# ------------------------------------------------------------------ locale
def _trascrivi_locale(sorgente: Path, uscita: Path) -> Trascrizione:
    """faster-whisper a chunk, con checkpoint per chunk.

    Il checkpoint e' quello della v1 e va tenuto: una lezione da 90 minuti su
    CPU sono ore, e senza checkpoint un Ctrl+C butta via tutto.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise RuntimeError(
            "faster-whisper non installato e WHISPER_MODE=local. "
            "Installa con `py -3 -m pip install faster-whisper`, "
            "oppure imposta WHISPER_MODE=api in .env."
        ) from e

    checkpoint = uscita.parent / f"{uscita.stem}.checkpoint.json"
    fatti: list[str] = []
    chunk_fatti = 0

    if checkpoint.exists():
        try:
            ck = json.loads(checkpoint.read_text(encoding="utf-8"))
            if "chunks_done" in ck:
                fatti = ck.get("segments", [])
                chunk_fatti = ck.get("chunks_done", 0)
                print(f"   Checkpoint: {chunk_fatti} chunk gia' fatti, {len(fatti)} segmenti")
            else:
                checkpoint.unlink()
        except (OSError, ValueError):
            checkpoint.unlink(missing_ok=True)

    totale_min = durata_minuti(sorgente)
    print(f"   Locale (CPU), modello {WHISPER_MODEL} — ~{totale_min:.0f} min di audio")

    tmp = Path(tempfile.mkdtemp(prefix="whisper_chunks_"))
    try:
        subprocess.run(
            [_ffmpeg(), "-i", str(sorgente), "-f", "segment",
             "-segment_time", str(CHUNK_MINUTI * 60), "-c", "copy",
             "-reset_timestamps", "1", str(tmp / "chunk_%03d.mp4"),
             "-y", "-loglevel", "quiet"],
            check=True,
        )
        chunks = sorted(tmp.glob("chunk_*.mp4"))
        print(f"   {len(chunks)} chunk da ~{CHUNK_MINUTI} min")

        modello = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
        lingua = "de"
        nuovi: list[str] = []

        for i, c in enumerate(chunks):
            if i < chunk_fatti:
                continue
            print(f"   chunk {i + 1}/{len(chunks)}...")
            segmenti, info = modello.transcribe(
                str(c), beam_size=5, language=None, vad_filter=True, word_timestamps=False
            )
            if i == 0:
                lingua = info.language
            nuovi.extend(s.text.strip() for s in segmenti)
            checkpoint.write_text(
                json.dumps({"segments": fatti + nuovi, "chunks_done": i + 1,
                            "audio_file": str(sorgente)}, ensure_ascii=False),
                encoding="utf-8",
            )

        testo = " ".join(fatti + nuovi).strip()
        checkpoint.unlink(missing_ok=True)
        return Trascrizione(
            testo=testo, percorso=uscita, minuti=totale_min, costo_eur=0.0,
            lingua=lingua, motore=f"faster-whisper-{WHISPER_MODEL}",
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def trascrivi(sorgente: str | Path, nome: str) -> Trascrizione:
    """Trascrive e scrive testo + meta. Il meta serve al registry per la durata.

    Se il transcript canonico esiste gia' non ritrascrive: e' il caso delle
    lezioni senza video, dove il testo viene iniettato a mano.
    """
    TRANSCRIPTS.mkdir(parents=True, exist_ok=True)
    uscita = TRANSCRIPTS / f"{nome}.txt"
    meta_p = uscita.with_suffix(".meta.json")

    if uscita.exists():
        print(f"   Transcript gia' presente: {uscita.name} — non ritrascrivo.")
        meta = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.exists() else {}
        return Trascrizione(
            testo=uscita.read_text(encoding="utf-8"),
            percorso=uscita,
            minuti=meta.get("duration_minutes", 0.0),
            costo_eur=meta.get("cost_eur", 0.0),
            lingua=meta.get("language", "de"),
            motore=meta.get("engine", "preesistente"),
        )

    p = Path(sorgente)
    if not p.exists():
        raise FileNotFoundError(f"Sorgente audio non trovata: {p}")

    t = (_trascrivi_api(p, uscita) if WHISPER_MODE.lower() == "api"
         else _trascrivi_locale(p, uscita))

    uscita.write_text(t.testo, encoding="utf-8")
    meta_p.write_text(json.dumps({
        "duration_minutes": round(t.minuti, 2),
        "duration_seconds": round(t.minuti * 60),
        "cost_eur": round(t.costo_eur, 4),
        "language": t.lingua,
        "engine": t.motore,
    }, ensure_ascii=False), encoding="utf-8")

    print(f"   {len(t.testo)} caratteri, {t.minuti:.0f} min, {t.costo_eur:.3f} EUR")
    return t
