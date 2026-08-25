# preflight.py
# Pre-pipeline health checks. In a single day we hit ALL of these failures:
#   - corrupt video (missing moov atom) -> auto-recover with untrunc
#   - expired Google OAuth token        -> warn (needs interactive re-login)
#   - expired NotebookLM session        -> warn (needs `python -m notebooklm login`)
#   - Anki closed                       -> warn (pipeline retries Step 4 anyway)
# run_preflight() returns a possibly-substituted audio path (the recovered file)
# plus a report dict; it never hard-blocks except on an unrecoverable video.

import sys
import struct
import subprocess
from pathlib import Path

UNTRUNC = Path("tools/untrunc/untrunc_x64/untrunc.exe")
AUDIO_DIR = Path("Audiolessons")


# ---------------------------------------------------------------- video / moov

def has_moov(path: Path) -> bool:
    """True if the MP4 has a 'moov' atom (i.e. it was finalised / is decodable)."""
    try:
        with open(path, "rb") as f:
            off = 0
            size = path.stat().st_size
            for _ in range(40):
                hdr = f.read(8)
                if len(hdr) < 8:
                    break
                box_size, typ = struct.unpack(">I4s", hdr)
                typ = typ.decode("latin1", "replace")
                if typ == "moov":
                    return True
                if box_size == 1:                      # 64-bit size
                    box_size = struct.unpack(">Q", f.read(8))[0]
                elif box_size == 0:                    # extends to EOF (mdat tail)
                    break
                if box_size < 8:
                    break
                off += box_size
                if off >= size:
                    break
                f.seek(off)
    except Exception:
        return True   # if we can't tell, don't block — let the pipeline try
    return False


def _find_healthy_reference(broken: Path) -> Path | None:
    """A finalised Classroom recording to use as untrunc reference."""
    cands = sorted(AUDIO_DIR.glob("Classroom with Stefanie*.mp4"),
                   key=lambda p: p.stat().st_size, reverse=True)
    for c in cands:
        if c.resolve() == broken.resolve():
            continue
        if "fixed" in c.name.lower():
            continue
        if has_moov(c):
            return c
    return None


def recover_video(broken: Path) -> Path | None:
    """Rebuild the moov with untrunc using a healthy reference. Returns fixed path."""
    if not UNTRUNC.exists():
        print(f"   [preflight] untrunc non presente ({UNTRUNC}) — impossibile recuperare.")
        return None
    ref = _find_healthy_reference(broken)
    if not ref:
        print("   [preflight] nessun video di riferimento sano per untrunc.")
        return None
    print(f"   [preflight] recupero con untrunc (ref: {ref.name})...")
    subprocess.run([str(UNTRUNC), "-n", str(ref), str(broken)], check=False)
    produced = broken.parent / f"{broken.name}_fixed.mp4"
    if produced.exists():
        clean = broken.parent / f"{broken.stem}-fixed.mp4"
        produced.replace(clean)
        print(f"   [preflight] recuperato: {clean.name}")
        return clean
    print("   [preflight] untrunc non ha prodotto output.")
    return None


def check_video(audio_path: str) -> str:
    """Returns the path to use (original or recovered)."""
    p = Path(audio_path)
    if p.suffix.lower() not in (".mp4", ".m4a", ".mov"):
        return audio_path
    if has_moov(p):
        return audio_path
    print(f"   [preflight] ⚠️  '{p.name}' senza atomo moov (registrazione non finalizzata).")
    fixed = recover_video(p)
    if fixed:
        return str(fixed)
    raise RuntimeError(
        f"Video corrotto e non recuperabile: {p.name}. "
        f"Serve una copia pulita o un video di riferimento sano in {AUDIO_DIR}/."
    )


# ---------------------------------------------------------------- credentials

def check_google_token() -> bool:
    """NON-interactive: validate/refresh token.json but NEVER launch the browser
    flow (that would block the pipeline). Warn-only on failure."""
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from doc_reader import SCOPES
        tok = Path("token.json")
        if not tok.exists():
            print("   [preflight] ⚠️  token.json assente -> login Google necessario.")
            return False
        creds = Credentials.from_authorized_user_file(str(tok), SCOPES)
        if creds and creds.valid:
            return True
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            tok.write_text(creds.to_json())
            return True
        return False
    except Exception as e:
        print(f"   [preflight] ⚠️  Google token non valido: {str(e)[:60]} -> rifai "
              f"login Google (Step 1/6 falliranno).")
        return False


def check_nblm() -> bool:
    try:
        res = subprocess.run(
            [sys.executable, "-m", "notebooklm", "auth", "check", "--test"],
            capture_output=True, text=True, encoding="utf-8")
        ok = res.returncode == 0 and "fail" not in (res.stdout or "").lower()
        if not ok:
            print("   [preflight] ⚠️  NotebookLM session scaduta -> sync NBLM salterà "
                  "(`python -m notebooklm login`).")
        return ok
    except Exception:
        return False


def check_anki() -> bool:
    try:
        from anki_feeder import ensure_anki_running
        ok = ensure_anki_running()
        if not ok:
            print("   [preflight] ⚠️  Anki non raggiungibile -> Step 4 verrà ritentato.")
        return ok
    except Exception:
        return False


def run_preflight(audio_path: str) -> tuple[str, dict]:
    print("\nPREFLIGHT — health checks")
    print("-" * 30)
    new_path = check_video(audio_path)        # may raise if unrecoverable
    report = {
        "video_ok": True,
        "video_recovered": new_path != audio_path,
        "google_token": check_google_token(),
        "nblm_session": check_nblm(),
        "anki": check_anki(),
    }
    ok = "✅"
    print(f"   {ok if report['google_token'] else '⚠️ '} Google token   "
          f"{ok if report['nblm_session'] else '⚠️ '} NBLM session   "
          f"{ok if report['anki'] else '⚠️ '} Anki")
    if report["video_recovered"]:
        print(f"   {ok} Video recuperato automaticamente con untrunc")
    return new_path, report


if __name__ == "__main__":
    if len(sys.argv) > 1:
        path, rep = run_preflight(sys.argv[1])
        print("\n", rep, "\n-> usa:", path)
    else:
        print("Uso: python preflight.py <video.mp4>")
