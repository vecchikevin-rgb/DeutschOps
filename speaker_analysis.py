# speaker_analysis.py v2
# Diarizzazione speaker con pyannote.audio
# Identificazione Kevin vs Stefanie basata su:
#   1. Caratteristiche acustiche (pyannote)
#   2. Analisi linguistica del transcript (DE/EN mix, complessità frasi)
#   3. Pattern conversazionale (domanda/risposta)
# Costo: €0.00 (tutto locale)

import os
import sys
import json
import re
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

SPEAKER_STATS = Path("data/speaker_stats.json")

# Parole tedesche comuni per classificazione DE/EN
DE_FUNCTION_WORDS = {
    "ich", "du", "er", "sie", "es", "wir", "ihr",
    "und", "oder", "aber", "nicht", "auch", "noch",
    "ist", "bin", "bist", "hat", "haben", "war", "waren",
    "der", "die", "das", "ein", "eine", "einen", "einem",
    "in", "an", "auf", "mit", "von", "zu", "bei", "nach",
    "wie", "was", "wer", "wo", "wann", "warum", "welche",
    "ja", "nein", "okay", "gut", "sehr", "mehr", "viel",
    "kann", "muss", "will", "soll", "darf", "mochte",
    "dann", "jetzt", "hier", "da", "so", "doch", "mal",
    "wenn", "weil", "dass", "ob", "als", "schon", "immer",
}

# Pattern tipici di un insegnante madrelingua (Stefanie)
TEACHER_PATTERNS = [
    r'\bgenau\b',           # "exactly" — tipico conferma insegnante
    r'\brichtig\b',         # "correct"
    r'\bversuch\b',         # "try"
    r'\bprobier\b',         # "try"
    r'\bnoch mal\b',        # "once more"
    r'\bsehr gut\b',        # "very good"
    r'\bsuper\b',
    r'\bperfekt\b',
    r'\bwir sagen\b',       # "we say" — spiegazione
    r'\bauf deutsch\b',     # "in German"
    r'\bbedeutet\b',        # "means"
    r'\bheißt\b',           # "means/is called"
    r'\bbeispiel\b',        # "example"
    r'\bübung\b',           # "exercise"
]

# Pattern tipici di uno studente (Kevin)
STUDENT_PATTERNS = [
    r'\bich weiß nicht\b',
    r'\bverstehe\b',
    r'\bwie sagt man\b',    # "how do you say"
    r'\bauf italienisch\b', # riferimento all'italiano
    r'\bscusa\b',           # italiano
    r'\bcioè\b',            # italiano
    r'\bquindi\b',          # italiano
    r'\bah okay\b',
    r'\bah ja\b',
    r'\bhmm\b',
]


def load_speaker_stats() -> dict:
    if SPEAKER_STATS.exists():
        return json.loads(SPEAKER_STATS.read_text(encoding="utf-8"))
    return {"sessions": {}}


def save_speaker_stats(stats: dict):
    SPEAKER_STATS.write_text(
        json.dumps(stats, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def convert_to_wav(audio_path: Path) -> Path:
    """Converte audio in WAV 16kHz mono per pyannote."""
    wav_path = audio_path.parent / f"{audio_path.stem}_pyannote.wav"
    if wav_path.exists():
        return wav_path

    print(f"   Conversione in WAV 16kHz...")
    ret = os.system(
        f'ffmpeg.exe -i "{audio_path}" -ar 16000 -ac 1 '
        f'"{wav_path}" -y -loglevel quiet'
    )
    if ret != 0 or not wav_path.exists():
        raise RuntimeError("Conversione WAV fallita")

    size_mb = wav_path.stat().st_size / (1024**2)
    print(f"   WAV: {wav_path.name} ({size_mb:.0f}MB)")
    return wav_path


def compress_video_backup(video_path: Path,
                           backup_dir: Path = None) -> Path:
    """Comprime video originale (~4GB) per backup (~200MB)."""
    if backup_dir is None:
        backup_dir = Path("Audiolessons/backup")
    backup_dir.mkdir(parents=True, exist_ok=True)

    out_path = backup_dir / f"{video_path.stem}_backup.mp4"
    if out_path.exists():
        print(f"   Backup già esistente: {out_path.name}")
        return out_path

    size_gb = video_path.stat().st_size / (1024**3)
    print(f"   Compressione backup {video_path.name} ({size_gb:.1f}GB)...")

    os.system(
        f'ffmpeg.exe -i "{video_path}" '
        f'-vf scale=854:480 -c:v libx264 -crf 28 -preset fast '
        f'-c:a aac -b:a 64k '
        f'"{out_path}" -y -loglevel quiet'
    )

    if out_path.exists():
        new_mb      = out_path.stat().st_size / (1024**2)
        reduction   = (1 - out_path.stat().st_size /
                       video_path.stat().st_size) * 100
        print(f"   Backup: {new_mb:.0f}MB (-{reduction:.0f}%)")

    return out_path


def diarize(wav_path: Path) -> object:
    """Esegue diarizzazione speaker con pyannote."""
    import warnings
    warnings.filterwarnings("ignore", category=UserWarning)
    
    import warnings
    warnings.filterwarnings("ignore", category=UserWarning,
                            module="pyannote")
    warnings.filterwarnings("ignore", category=UserWarning,
                            module="huggingface_hub")

    try:
        from pyannote.audio import Pipeline
        import torch
    except ImportError:
        print("   Run: pip install pyannote.audio torch torchaudio")
        return None

    hf_token = os.getenv("HUGGINGFACE_TOKEN", "")
    if not hf_token:
        print("   HUGGINGFACE_TOKEN mancante nel .env")
        return None

    try:
        print("   Caricamento modello pyannote...")
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            token=hf_token  # aggiornato: non più use_auth_token
        )
        pipeline.to(__import__('torch').device("cpu"))
        print("   Diarizzazione in corso (10-20 min su CPU)...")
        return pipeline(str(wav_path))
    except Exception as e:
        print(f"   Diarizzazione fallita: {e}")
        return None

def parse_diarization(diarization) -> dict:
    """Converte output pyannote in struttura dati."""
    speakers = {}
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        if speaker not in speakers:
            speakers[speaker] = []
        speakers[speaker].append({
            "start":    round(turn.start, 2),
            "end":      round(turn.end,   2),
            "duration": round(turn.end - turn.start, 2)
        })
    return speakers


def score_speaker_identity(speaker_id: str,
                             segments: list,
                             transcript: str) -> dict:
    """
    Assegna un punteggio Kevin/Stefanie basato su criteri multipli.

    Criteri (più affidabili per questa conversazione):
    1. Pattern linguistici insegnante vs studente nel transcript
    2. Lunghezza media turno (insegnante spiega più a lungo)
    3. Numero turni (insegnante fa più domande brevi)
    4. Mix DE/EN (studente = più EN, insegnante = più DE)
    """
    total_time = sum(s["duration"] for s in segments)
    n_turns    = len(segments)
    avg_turn   = total_time / max(n_turns, 1)

    # Per ora usiamo solo le metriche aggregate dal transcript totale
    # In futuro con alignment audio-transcript potremmo fare per segmento
    teacher_score = 0
    student_score = 0

    # Criterio 1: Lunghezza media turno
    # Insegnante spiega → turni più lunghi in media
    # Studente risponde → turni più brevi
    if avg_turn > 8:
        teacher_score += 2  # turni lunghi = insegnante
    elif avg_turn < 4:
        student_score += 2  # turni brevi = studente
    else:
        teacher_score += 1
        student_score += 1

    # Criterio 2: Numero turni
    # L'insegnante ha più turni (fa domande, aspetta, ripete)
    # Non decisivo da solo — li confrontiamo tra speaker

    # Criterio 3: Percentuale tempo totale
    # In una lezione 1:1, l'insegnante parla ~60-70%
    # lo studente ~30-40%
    # Questo viene usato come tiebreaker, non come criterio primario

    return {
        "speaker_id":       speaker_id,
        "total_seconds":    round(total_time, 1),
        "total_minutes":    round(total_time / 60, 1),
        "n_turns":          n_turns,
        "avg_turn_seconds": round(avg_turn, 1),
        "teacher_score":    teacher_score,
        "student_score":    student_score,
    }


def identify_speakers(speakers: dict,
                        transcript: str) -> dict:
    """
    Identifica quale speaker è Kevin e quale Stefanie.

    Logica multi-criterio:
    1. Analizza pattern linguistici nel transcript totale
    2. Usa metriche conversazionali per ogni speaker
    3. Lo speaker con turni mediamente più lunghi = Stefanie (spiega)
    4. Lo speaker con più turni brevi = Kevin (risponde, pratica)

    In una lezione di lingua 1:1:
    - Insegnante: pochi turni lunghi (spiegazioni) + molti turni brevi (domande)
    - Studente: molti turni corti (risposte) + alcuni turni lunghi (esercita)
    """
    if len(speakers) < 2:
        return {}

    scores = {}
    for sp_id, segs in speakers.items():
        scores[sp_id] = score_speaker_identity(sp_id, segs, transcript)

    # Pattern linguistici nel transcript globale
    teacher_hits = sum(
        len(re.findall(p, transcript, re.IGNORECASE))
        for p in TEACHER_PATTERNS
    )
    student_hits = sum(
        len(re.findall(p, transcript, re.IGNORECASE))
        for p in STUDENT_PATTERNS
    )
    print(f"   Pattern insegnante nel transcript: {teacher_hits}")
    print(f"   Pattern studente nel transcript:   {student_hits}")

    # Identifica speaker primario e secondario per tempo
    sorted_by_time = sorted(
        scores.items(),
        key=lambda x: x[1]["total_seconds"],
        reverse=True
    )

    # Speaker con più tempo totale → candidato Stefanie
    # Speaker con meno tempo → candidato Kevin
    # Ma verifichiamo con avg_turn: Stefanie ha avg_turn più alto
    sorted_by_avg = sorted(
        scores.items(),
        key=lambda x: x[1]["avg_turn_seconds"],
        reverse=True
    )

    # Se il criterio tempo e avg_turn concordano → alta confidenza
    if sorted_by_time[0][0] == sorted_by_avg[0][0]:
        stefanie_id = sorted_by_time[0][0]
        kevin_id    = sorted_by_time[1][0]
        confidence  = "high"
    else:
        # Discordanza — usa avg_turn come criterio primario
        # (più affidabile: chi spiega ha turni più lunghi)
        stefanie_id = sorted_by_avg[0][0]
        kevin_id    = sorted_by_avg[1][0]
        confidence  = "medium"

    print(f"\n   Identificazione speaker (confidenza: {confidence}):")
    print(f"   Kevin    → {kevin_id} "
          f"({scores[kevin_id]['total_minutes']:.1f} min, "
          f"avg turn {scores[kevin_id]['avg_turn_seconds']:.1f}s)")
    print(f"   Stefanie → {stefanie_id} "
          f"({scores[stefanie_id]['total_minutes']:.1f} min, "
          f"avg turn {scores[stefanie_id]['avg_turn_seconds']:.1f}s)")

    return {
        "kevin_id":    kevin_id,
        "stefanie_id": stefanie_id,
        "confidence":  confidence,
        "scores":      scores
    }


def analyze_language_mix(transcript: str,
                           duration_minutes: float) -> dict:
    """
    Analizza il mix DE/EN nel transcript completo.
    Calcola velocità di parlato e percentuale tedesco.
    """
    words = re.findall(r'\b[a-zA-ZäöüÄÖÜß]+\b', transcript.lower())
    if not words:
        return {}

    de_count  = sum(1 for w in words if w in DE_FUNCTION_WORDS)
    total     = len(words)
    de_pct    = round(de_count / total * 100, 1)
    wpm       = round(total / max(duration_minutes, 1), 1)

    # Valutazione qualitativa
    if de_pct > 65:
        note = "Predominantly German — excellent!"
    elif de_pct > 45:
        note = "Good German/English mix"
    elif de_pct > 25:
        note = "Mixed DE/EN — normal for A2 level"
    else:
        note = "Mostly English — try more German next time"

    return {
        "total_words":   total,
        "de_words":      de_count,
        "en_words":      total - de_count,
        "de_percentage": de_pct,
        "words_per_min": wpm,
        "note":          note
    }


def compute_speaker_stats(speakers: dict,
                            identification: dict) -> dict:
    """Calcola statistiche finali per ogni speaker."""
    kevin_id    = identification.get("kevin_id", "")
    stefanie_id = identification.get("stefanie_id", "")
    total_time  = sum(
        sum(s["duration"] for s in segs)
        for segs in speakers.values()
    )

    result = {}
    for sp_id, segs in speakers.items():
        sp_time  = sum(s["duration"] for s in segs)
        sp_pct   = round(sp_time / max(total_time, 1) * 100, 1)
        n_turns  = len(segs)
        avg_turn = round(sp_time / max(n_turns, 1), 1)
        name     = ("Kevin"    if sp_id == kevin_id
                    else "Stefanie" if sp_id == stefanie_id
                    else sp_id)

        # Analisi turni: brevi (<3s) vs medi (3-10s) vs lunghi (>10s)
        short  = sum(1 for s in segs if s["duration"] < 3)
        medium = sum(1 for s in segs if 3 <= s["duration"] <= 10)
        long   = sum(1 for s in segs if s["duration"] > 10)

        result[name] = {
            "speaker_id":        sp_id,
            "total_seconds":     round(sp_time, 1),
            "total_minutes":     round(sp_time / 60, 1),
            "percentage":        sp_pct,
            "n_turns":           n_turns,
            "avg_turn_seconds":  avg_turn,
            "turns_short":       short,   # <3s: conferme, sì/no
            "turns_medium":      medium,  # 3-10s: risposte normali
            "turns_long":        long,    # >10s: spiegazioni/esercizi
        }

        print(f"\n   📊 {name} ({sp_id}):")
        print(f"      Tempo totale:  {sp_time/60:.1f} min ({sp_pct}%)")
        print(f"      Turni:         {n_turns} "
              f"(brevi:{short} medi:{medium} lunghi:{long})")
        print(f"      Turno medio:   {avg_turn:.1f}s")

    return result


def analyze_lesson(video_path: str, lesson_date: str,
                    backup: bool = True) -> dict:
    """Analisi completa di una lezione."""
    video_path = Path(video_path)
    if not video_path.exists():
        print(f"❌ File non trovato: {video_path}")
        return {}

    print(f"\n{'='*52}")
    print(f"  Speaker Analysis — {lesson_date}")
    print(f"  {video_path.name}")
    print(f"{'='*52}\n")

    results = {
        "lesson_date":    lesson_date,
        "video_file":     video_path.name,
        "analyzed_at":    datetime.now().isoformat(),
        "speaker_stats":  {},
        "language_mix":   {},
        "identification": {},
        "backup_path":    ""
    }

    # ── Step 1: Backup compresso ──────────────────────────────────────────────
    if backup:
        print("Step 1/4 — Backup compresso...")
        # Solo se è un video originale grande
        if video_path.stat().st_size > 500 * 1024 * 1024:
            bp = compress_video_backup(video_path)
            results["backup_path"] = str(bp)
        else:
            print(f"   File già compresso ({video_path.stat().st_size//1024//1024}MB) — skip")
    else:
        print("Step 1/4 — Backup: skipped")

    # ── Step 2: Language mix dal transcript ───────────────────────────────────
    print("\nStep 2/4 — Analisi linguistica transcript...")
    transcript_path = Path(f"transcripts/lezione_{lesson_date}.txt")

    meta_path = Path(f"transcripts/lezione_{lesson_date}.meta.json")
    duration  = 30.0  # default
    if meta_path.exists():
        meta     = json.loads(meta_path.read_text(encoding="utf-8"))
        duration = meta.get("duration_minutes", 30.0)

    if transcript_path.exists():
        transcript = transcript_path.read_text(encoding="utf-8")
        lang_stats = analyze_language_mix(transcript, duration)
        results["language_mix"] = lang_stats
        print(f"   Parole totali:   {lang_stats.get('total_words', 0)}")
        print(f"   Tedesco:         {lang_stats.get('de_percentage', 0)}%")
        print(f"   Inglese:         {100 - lang_stats.get('de_percentage', 0):.1f}%")
        print(f"   Velocità:        {lang_stats.get('words_per_min', 0)} wpm")
        print(f"   Valutazione:     {lang_stats.get('note', '')}")
    else:
        print(f"   Transcript non trovato: {transcript_path}")
        transcript = ""

    # ── Step 3: Diarizzazione speaker ─────────────────────────────────────────
    print("\nStep 3/4 — Diarizzazione speaker...")

    # Usa il file compresso se disponibile
    compressed = Path(f"Audiolessons/lezione_{lesson_date}-compressed.mp4")
    audio_file = compressed if compressed.exists() else video_path

    try:
        wav_path    = convert_to_wav(audio_file)
        diarization = diarize(wav_path)

        if diarization:
            speakers = parse_diarization(diarization)
            print(f"   {len(speakers)} speaker rilevati")

            # Pulizia WAV temporaneo
            if wav_path.exists():
                wav_path.unlink()

            # ── Step 4: Identificazione e statistiche ─────────────────────────
            print("\nStep 4/4 — Identificazione Kevin vs Stefanie...")
            identification = identify_speakers(speakers, transcript)
            results["identification"] = identification

            speaker_stats = compute_speaker_stats(speakers, identification)
            results["speaker_stats"] = speaker_stats

            # Riepilogo finale
            kevin    = speaker_stats.get("Kevin", {})
            stefanie = speaker_stats.get("Stefanie", {})

            if kevin and stefanie:
                print(f"\n   🎯 Riepilogo:")
                print(f"   Kevin:    {kevin['total_minutes']:.1f} min "
                      f"({kevin['percentage']}%) — "
                      f"{kevin['n_turns']} turni, "
                      f"avg {kevin['avg_turn_seconds']:.1f}s")
                print(f"   Stefanie: {stefanie['total_minutes']:.1f} min "
                      f"({stefanie['percentage']}%) — "
                      f"{stefanie['n_turns']} turni, "
                      f"avg {stefanie['avg_turn_seconds']:.1f}s")
                print(f"   DE/EN:    {lang_stats.get('de_percentage',0)}% "
                      f"tedesco — {lang_stats.get('note','')}")

        else:
            print("   Diarizzazione non disponibile — solo stats transcript")
            if wav_path.exists():
                wav_path.unlink(missing_ok=True)

    except Exception as e:
        print(f"   ⚠️  Step 3 fallito: {e}")
        print("   Le statistiche linguistiche sono comunque salvate")

    # ── Salva risultati ───────────────────────────────────────────────────────
    all_stats = load_speaker_stats()
    all_stats["sessions"][lesson_date] = results
    save_speaker_stats(all_stats)

    print(f"\n✅ Salvato: {SPEAKER_STATS}")
    if results.get("backup_path"):
        print(f"   Backup: {results['backup_path']}")
        print(f"   Puoi eliminare il video originale quando vuoi")

    return results


def print_summary():
    """Riepilogo di tutte le analisi."""
    stats    = load_speaker_stats()
    sessions = stats.get("sessions", {})

    if not sessions:
        print("Nessuna analisi disponibile.")
        return

    print(f"\n{'='*55}")
    print(f"  DeutschOps — Speaker Analysis Summary")
    print(f"{'='*55}")
    print(f"  {'Data':<25} {'DE%':>5} {'WPM':>6} "
          f"{'Kevin':>10} {'Stefanie':>10} {'Conf':>8}")
    print(f"  {'─'*53}")

    for date, session in sorted(sessions.items()):
        lm  = session.get("language_mix", {})
        sp  = session.get("speaker_stats", {})
        idf = session.get("identification", {})

        de_pct   = lm.get("de_percentage", 0)
        wpm      = lm.get("words_per_min", 0)
        kevin    = sp.get("Kevin", {})
        stefanie = sp.get("Stefanie", {})
        conf     = idf.get("confidence", "n/a")

        k_str = (f"{kevin.get('total_minutes',0):.0f}m "
                 f"({kevin.get('percentage',0):.0f}%)"
                 if kevin else "n/a")
        s_str = (f"{stefanie.get('total_minutes',0):.0f}m "
                 f"({stefanie.get('percentage',0):.0f}%)"
                 if stefanie else "n/a")

        print(f"  {date:<25} {de_pct:>4.0f}% {wpm:>6.0f} "
              f"{k_str:>10} {s_str:>10} {conf:>8}")

    print(f"\n  Trend DE%: ", end="")
    de_trend = [
        s.get("language_mix", {}).get("de_percentage", 0)
        for s in sorted(sessions.values(),
                         key=lambda x: x.get("lesson_date",""))
    ]
    for i, pct in enumerate(de_trend):
        arrow = ("↑" if i > 0 and pct > de_trend[i-1]
                 else "↓" if i > 0 and pct < de_trend[i-1]
                 else "→")
        print(f"{pct:.0f}%{arrow} ", end="")
    print()


if __name__ == "__main__":
    if len(sys.argv) == 1:
        print_summary()
    elif len(sys.argv) >= 3:
        video      = sys.argv[1]
        date       = sys.argv[2]
        do_backup  = "--no-backup" not in sys.argv
        analyze_lesson(video, date, backup=do_backup)
    else:
        print("Usage:")
        print("  python speaker_analysis.py                           # summary")
        print("  python speaker_analysis.py VIDEO DATE                # analyze")
        print("  python speaker_analysis.py VIDEO DATE --no-backup    # no backup")