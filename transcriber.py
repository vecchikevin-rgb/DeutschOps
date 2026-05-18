# transcriber.py
import os
import json
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Soglia in minuti oltre la quale chiede all'utente dove elaborare
THRESHOLD_MINUTES = 20

# Limite Whisper API in MB
MAX_API_SIZE_MB = 24


def estimate_duration_minutes(audio_path: Path) -> float:
    """
    Stima la durata in minuti dal peso del file.
    ~1MB per minuto a qualità WhatsApp/compressed.
    """
    size_mb = audio_path.stat().st_size / (1024 * 1024)
    return size_mb * 2.1


def compress_if_needed(audio_path: Path) -> Path:
    """
    Se il file supera il limite API, lo comprime con ffmpeg.
    Restituisce il percorso del file da usare (originale o compresso).
    """
    size_mb = audio_path.stat().st_size / (1024 * 1024)

    if size_mb <= MAX_API_SIZE_MB:
        return audio_path

    print(f"⚠️  File {size_mb:.1f}MB supera limite API ({MAX_API_SIZE_MB}MB) — compressione automatica...")
    compressed_path = audio_path.parent / f"{audio_path.stem}_compressed.mp4"

    ffmpeg_exe = Path("ffmpeg.exe") if Path("ffmpeg.exe").exists() else Path("ffmpeg")
    os.system(
        f'"{ffmpeg_exe}" -i "{audio_path}" -vn -ar 16000 -ac 1 -b:a 32k "{compressed_path}" -y -loglevel quiet'
    )

    new_size = compressed_path.stat().st_size / (1024 * 1024)
    print(f"✅ Compresso: {size_mb:.1f}MB → {new_size:.1f}MB")
    return compressed_path


def ask_routing(estimated_minutes: float) -> str:
    """
    Chiede all'utente dove elaborare quando il file è lungo.
    Restituisce 'api' o 'local'.
    """
    api_cost = estimated_minutes * 0.006
    local_time = estimated_minutes * 1.8

    print(f"\n⚠️  File lungo stimato: ~{estimated_minutes:.0f} minuti di audio")
    print(f"   Opzione A) API Whisper  → pronto in ~30s    | costo ~€{api_cost:.2f}")
    print(f"   Opzione B) Locale CPU   → pronto in ~{local_time:.0f} min | costo €0.00 (in background)")
    print()

    while True:
        choice = input("Dove elaborare? [A/B]: ").strip().upper()
        if choice in ("A", "B"):
            return "api" if choice == "A" else "local"
        print("Scrivi A o B.")


def transcribe_api(audio_path: Path, output_path: Path) -> str:
    """
    Trascrizione via Whisper API OpenAI.
    Comprime automaticamente se il file supera il limite.
    Restituisce il testo trascritto.
    """
    # Comprimi se necessario
    audio_path = compress_if_needed(audio_path)

    print("🌐 Elaborazione via API Whisper...")

    with open(audio_path, "rb") as f:
        result = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            response_format="verbose_json",
            temperature=0.0
        )

    text = result.text
    duration = result.duration
    cost = (duration / 60) * 0.006

    output_path.write_text(text, encoding="utf-8")

    # Salva metadati per main.py
    meta_path = output_path.with_suffix(".meta.json")
    meta_path.write_text(json.dumps({
        "duration_seconds": duration,
        "duration_minutes": duration / 60,
        "cost_eur": cost,
        "language": result.language
    }), encoding="utf-8")

    print(f"✅ Trascritto in: {output_path}")
    print(f"⏱️  Durata reale: {duration:.0f}s ({duration/60:.1f} min)")
    print(f"🌍 Lingua rilevata: {result.language}")
    print(f"💶 Costo: €{cost:.2f}")

    return text


def transcribe_local(audio_path: Path, output_path: Path) -> str:
    """
    Trascrizione locale via faster-whisper con:
    - Progress bar con % e tempo rimanente
    - Resume automatico da checkpoint se interrotta
    """
    try:
        from faster_whisper import WhisperModel
        from tqdm import tqdm
    except ImportError:
        print("⚠️  faster-whisper o tqdm non installati.")
        print("   Esegui: pip install faster-whisper tqdm")
        return transcribe_api(audio_path, output_path)

    # File checkpoint — salva progresso ogni N segmenti
    checkpoint_path = output_path.parent / f"{output_path.stem}.checkpoint.json"

    # Carica checkpoint se esiste
    completed_segments = []
    start_from = 0.0

    if checkpoint_path.exists():
        try:
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            completed_segments = checkpoint.get("segments", [])
            start_from = checkpoint.get("last_end", 0.0)
            print(f"♻️  Checkpoint trovato — riprendo da {start_from:.0f}s "
                  f"({len(completed_segments)} segmenti già completati)")
        except Exception:
            print("⚠️  Checkpoint corrotto, ricomincio da zero")
            completed_segments = []
            start_from = 0.0
    else:
        print("🖥️  Elaborazione locale (CPU)")
        print("   Premi Ctrl+C per interrompere — il progresso verrà salvato")

    print(f"   Modello: small | Lingua: auto-detect\n")

    model = WhisperModel("small", device="cpu", compute_type="int8")

    # Prima passata veloce per ottenere durata totale e numero segmenti stimati
    import wave
    import contextlib
    try:
        # Stima durata dal file
        import subprocess
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
            capture_output=True, text=True
        )
        total_duration = float(result.stdout.strip()) if result.returncode == 0 else 3600.0
    except Exception:
        total_duration = 3600.0  # fallback 60 min

    print(f"   Durata stimata: {total_duration/60:.0f} minuti")

    # Trascrizione con progress bar
    segments_gen, info = model.transcribe(
        str(audio_path),
        beam_size=5,
        language=None,
        vad_filter=True,
        word_timestamps=False
    )

    actual_duration = info.duration if hasattr(info, 'duration') else total_duration
    print(f"🌍 Lingua rilevata: {info.language} "
          f"(confidenza: {info.language_probability:.0%})\n")

    new_segments = []
    last_save = 0
    SAVE_EVERY = 30  # salva checkpoint ogni 30 segmenti

    try:
        with tqdm(
            total=actual_duration,
            unit="s",
            unit_scale=True,
            bar_format="   {l_bar}{bar}| {n:.0f}/{total:.0f}s [{elapsed}<{remaining}]",
            colour="green"
        ) as pbar:

            # Avanza la progress bar ai segmenti già completati
            if start_from > 0:
                pbar.update(start_from)

            for segment in segments_gen:
                # Salta segmenti già completati nel checkpoint
                if segment.end <= start_from:
                    continue

                new_segments.append(segment.text.strip())

                # Aggiorna progress bar
                pbar.update(segment.end - max(segment.start, start_from))
                pbar.set_postfix({
                    "segmenti": len(completed_segments) + len(new_segments),
                    "checkpoint": "💾" if len(new_segments) % SAVE_EVERY == 0 else "  "
                })

                # Salva checkpoint periodicamente
                if len(new_segments) - last_save >= SAVE_EVERY:
                    all_so_far = completed_segments + new_segments
                    checkpoint_data = {
                        "segments": all_so_far,
                        "last_end": segment.end,
                        "audio_file": str(audio_path)
                    }
                    checkpoint_path.write_text(
                        json.dumps(checkpoint_data, ensure_ascii=False),
                        encoding="utf-8"
                    )
                    last_save = len(new_segments)

    except KeyboardInterrupt:
        # Salva checkpoint prima di uscire
        print("\n\n⏸️  Trascrizione interrotta — salvo checkpoint...")
        all_so_far = completed_segments + new_segments
        if all_so_far:
            checkpoint_data = {
                "segments": all_so_far,
                "last_end": new_segments[-1] if new_segments else start_from,
                "audio_file": str(audio_path)
            }
            checkpoint_path.write_text(
                json.dumps(checkpoint_data, ensure_ascii=False),
                encoding="utf-8"
            )
            print(f"💾 Checkpoint salvato: {len(all_so_far)} segmenti")
            print(f"   Rilancia lo script per riprendere da dove eri.")
        raise SystemExit(0)

    # Completato — unisci tutto e pulisci checkpoint
    all_segments = completed_segments + new_segments
    text = " ".join(all_segments).strip()
    output_path.write_text(text, encoding="utf-8")

    if checkpoint_path.exists():
        checkpoint_path.unlink()
        print("🗑️  Checkpoint rimosso (trascrizione completata)")

    print(f"\n✅ Trascritto in: {output_path}")
    return text


def transcribe(audio_path: str | Path, output_filename: str | None = None) -> str:
    """
    Funzione principale. Routing automatico basato su durata stimata.
    - Sotto soglia → API diretta senza chiedere
    - Sopra soglia → chiede all'utente A o B
    Restituisce il testo trascritto.
    """
    audio_path = Path(audio_path)

    if not audio_path.exists():
        raise FileNotFoundError(f"File non trovato: {audio_path}")

    if output_filename is None:
        output_filename = audio_path.stem

    output_path = Path("transcripts") / f"{output_filename}.txt"

    print(f"📂 File: {audio_path.name}")
    print(f"📏 Dimensione: {audio_path.stat().st_size / (1024*1024):.1f} MB")

    estimated = estimate_duration_minutes(audio_path)

    if estimated <= THRESHOLD_MINUTES:
        print(f"⏱️  Durata stimata: ~{estimated:.0f} min → API automatica")
        text = transcribe_api(audio_path, output_path)
    else:
        # Controlla variabile d'ambiente per scelta automatica
        auto_mode = os.environ.get("WHISPER_MODE", "").lower()
        if auto_mode == "api":
            print(f"⏱️  Durata stimata: ~{estimated:.0f} min → API (auto)")
            text = transcribe_api(audio_path, output_path)
        elif auto_mode == "local":
            print(f"⏱️  Durata stimata: ~{estimated:.0f} min → Locale (auto)")
            text = transcribe_local(audio_path, output_path)
        else:
            mode = ask_routing(estimated)
            if mode == "api":
                text = transcribe_api(audio_path, output_path)
            else:
                text = transcribe_local(audio_path, output_path)

    print(f"\n--- ANTEPRIMA (prime 300 caratteri) ---")
    print(text[:300])
    print("...")

    return text


if __name__ == "__main__":
    AUDIO_PATH = r"Audiolessons\lezione_2026-05-14-stefanie-compressed.mp4"
    transcribe(AUDIO_PATH, output_filename="lezione_2026-05-14-stefanie")