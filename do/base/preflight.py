"""Health-check pre-pipeline.  [PORTATO da preflight.py]

NATO DA UN GIORNO IN CUI SONO FALLITE TUTTE E QUATTRO LE COSE INSIEME:
video corrotto (atomo moov mancante), token Google scaduto, sessione
NotebookLM scaduta, Anki chiuso.

INVARIANTE DA CONSERVARE — i check NON bloccano mai.
Avvisano e la pipeline degrada: token Google scaduto -> lo Step 1 diventa una
stringa vuota; Anki chiuso -> la fase resta aperta e si ritenta al run
successivo. L'unica eccezione e' un video irrecuperabile, dove non c'e' niente
da elaborare. Questa architettura di degradazione e' la parte piu' matura del
progetto: non va sostituita con dei check bloccanti.

Il parser binario dell'atomo moov e il recupero via untrunc sono conservati
identici: sono codice pagato con un guasto reale.

DUE CORREZIONI RISPETTO ALLA v1
1. `_riferimento_sano()` cercava `"Classroom with Stefanie*.mp4"` — lo stesso
   pattern morto che rendeva inerte watch.py. Le registrazioni oggi si
   chiamano `"Deutsch mit Kevin - 2026_07_22 ... Recording.mp4"` o
   `"ipk-ufvr-cxr (2026-07-21 11_05 GMT+2).mp4"`, quindi il recupero untrunc
   non trovava mai un riferimento. Ora considera qualunque video in AUDIO.
2. Niente import da doc_reader / anki_feeder: gli scope Google vengono da
   base.config e il check Anki e' una probe HTTP diretta. Il preflight non
   deve dipendere da moduli che stiamo archiviando.
"""

from __future__ import annotations

import struct
import subprocess
from pathlib import Path

import requests

from .config import ANKI_URL, GOOGLE_SCOPES
from .paths import AUDIO, GOOGLE_TOKEN, UNTRUNC

ESTENSIONI_VIDEO = (".mp4", ".m4a", ".mov", ".mkv", ".webm")


# ------------------------------------------------------------------ video / moov
def ha_moov(path: Path) -> bool:
    """True se l'MP4 ha un atomo 'moov', cioe' e' stato finalizzato.

    Una registrazione interrotta male non ha moov e nessun decoder la legge.
    In caso di dubbio ritorna True: meglio far provare la pipeline che
    bloccarla su un falso positivo.
    """
    try:
        with open(path, "rb") as f:
            off = 0
            size = path.stat().st_size
            for _ in range(40):
                hdr = f.read(8)
                if len(hdr) < 8:
                    break
                box_size, tipo = struct.unpack(">I4s", hdr)
                if tipo.decode("latin1", "replace") == "moov":
                    return True
                if box_size == 1:                      # dimensione a 64 bit
                    box_size = struct.unpack(">Q", f.read(8))[0]
                elif box_size == 0:                    # si estende fino a EOF
                    break
                if box_size < 8:
                    break
                off += box_size
                if off >= size:
                    break
                f.seek(off)
    except Exception:
        return True
    return False


def _riferimento_sano(rotto: Path) -> Path | None:
    """Un video finalizzato da usare come riferimento per untrunc.

    CORRETTO rispetto alla v1: qualunque video in AUDIO, non piu' solo quelli
    con prefisso "Classroom with Stefanie" (pattern morto da giugno).
    Il piu' grande per primo: piu' probabile che contenga tutte le tracce.
    """
    candidati = sorted(
        (p for p in AUDIO.iterdir()
         if p.is_file() and p.suffix.lower() in ESTENSIONI_VIDEO),
        key=lambda p: p.stat().st_size,
        reverse=True,
    )
    for c in candidati:
        if c.resolve() == rotto.resolve() or "fixed" in c.name.lower():
            continue
        if ha_moov(c):
            return c
    return None


def recupera_video(rotto: Path) -> Path | None:
    """Ricostruisce il moov con untrunc usando un riferimento sano."""
    if not UNTRUNC.exists():
        print(f"   [preflight] untrunc assente ({UNTRUNC}) — impossibile recuperare.")
        return None

    rif = _riferimento_sano(rotto)
    if not rif:
        print("   [preflight] nessun video di riferimento sano per untrunc.")
        return None

    print(f"   [preflight] recupero con untrunc (riferimento: {rif.name})...")
    subprocess.run([str(UNTRUNC), "-n", str(rif), str(rotto)], check=False)

    prodotto = rotto.parent / f"{rotto.name}_fixed.mp4"
    if prodotto.exists():
        pulito = rotto.parent / f"{rotto.stem}-fixed.mp4"
        prodotto.replace(pulito)
        print(f"   [preflight] recuperato: {pulito.name}")
        return pulito

    print("   [preflight] untrunc non ha prodotto output.")
    return None


def controlla_video(percorso: str) -> str:
    """Ritorna il path da usare: l'originale, o quello recuperato."""
    p = Path(percorso)
    if p.suffix.lower() not in ESTENSIONI_VIDEO:
        return percorso            # trascrizione esterna: niente da controllare
    if ha_moov(p):
        return percorso

    print(f"   [preflight] '{p.name}' senza atomo moov (registrazione non finalizzata).")
    recuperato = recupera_video(p)
    if recuperato:
        return str(recuperato)

    # L'unico caso bloccante: non c'e' nulla da elaborare.
    raise RuntimeError(
        f"Video corrotto e non recuperabile: {p.name}. "
        f"Serve una copia pulita o un video di riferimento sano in {AUDIO.name}/."
    )


# ------------------------------------------------------------------ credenziali
def controlla_token_google() -> bool:
    """Valida/rinnova token.json SENZA mai aprire il browser.

    Il flow interattivo bloccherebbe la pipeline in attesa di un click. Qui
    si avvisa e basta: lo Step 1 degradera' da solo.
    """
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        if not GOOGLE_TOKEN.exists():
            print("   [preflight] token.json assente -> serve il login Google.")
            return False

        creds = Credentials.from_authorized_user_file(str(GOOGLE_TOKEN), GOOGLE_SCOPES)
        if creds and creds.valid:
            return True
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            GOOGLE_TOKEN.write_text(creds.to_json(), encoding="utf-8")
            return True
        return False
    except Exception as e:
        print(f"   [preflight] token Google non valido: {str(e)[:60]} "
              f"-> rifai il login (lo Step Doc fallira').")
        return False


def controlla_anki() -> bool:
    """Probe diretta su AnkiConnect. Nessun auto-avvio qui: il preflight
    osserva, non agisce. L'avvio lo tenta la fase Anki se serve."""
    try:
        r = requests.post(ANKI_URL, json={"action": "version", "version": 6}, timeout=5)
        ok = r.json().get("result") is not None
    except Exception:
        ok = False
    if not ok:
        print("   [preflight] Anki non raggiungibile -> la fase carte verra' ritentata.")
    return ok


def esegui(percorso_audio: str) -> tuple[str, dict]:
    """Health-check completo. Ritorna (path da usare, report)."""
    print("\nPREFLIGHT — health check")
    print("-" * 30)

    nuovo = controlla_video(percorso_audio)      # puo' sollevare se irrecuperabile
    report = {
        "video_ok": True,
        "video_recuperato": nuovo != percorso_audio,
        "token_google": controlla_token_google(),
        "anki": controlla_anki(),
    }

    ok, ko = "OK", "!!"
    print(f"   Google token {ok if report['token_google'] else ko}   "
          f"Anki {ok if report['anki'] else ko}")
    if report["video_recuperato"]:
        print("   Video recuperato automaticamente con untrunc")

    return nuovo, report
