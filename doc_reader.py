# doc_reader.py
# Legge il Google Doc della lezione, salva snapshot locale,
# confronta con snapshot precedente per estrarre solo le novità

import os
import json
from pathlib import Path
from datetime import date
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# ID del tuo Google Doc (dalla URL)
DOC_ID = "165S8CsHT3TrCpr6Se3l3VYakb7r16_bgg81l5ygJvpc"

# Permessi richiesti — sola lettura per ora
SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/documents"
]

# Cartelle locali
SNAPSHOTS_DIR = Path("doc_snapshots")
SNAPSHOTS_DIR.mkdir(exist_ok=True)


def get_drive_service():
    """
    Autenticazione OAuth2 con Google.
    Al primo avvio apre il browser per il login.
    Salva il token in token.json per i lanci successivi.
    """
    creds = None
    token_path = Path("token.json")

    # Se esiste già un token salvato, caricalo
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    # Se non c'è token valido, avvia il flusso OAuth
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json", SCOPES
            )
            # Apre il browser per autenticarsi
            creds = flow.run_local_server(port=0)

        # Salva il token per la prossima volta
        token_path.write_text(creds.to_json())
        print("✅ Token salvato in token.json")

    return build("drive", "v3", credentials=creds)


def read_doc(service) -> str:
    """
    Scarica il contenuto del Google Doc come testo plain.
    """
    print(f"📄 Lettura Google Doc ({DOC_ID[:20]}...)")

    result = service.files().export(
        fileId=DOC_ID,
        mimeType="text/plain"
    ).execute()

    # Il risultato è bytes, decodifichiamo in UTF-8
    text = result.decode("utf-8")
    print(f"✅ Doc letto: {len(text)} caratteri")
    return text


def save_snapshot(text: str, label: str = None) -> Path:
    """
    Salva uno snapshot del doc con data/label.
    Restituisce il percorso del file salvato.
    """
    if label is None:
        label = date.today().isoformat()

    snapshot_path = SNAPSHOTS_DIR / f"snapshot_{label}.txt"
    snapshot_path.write_text(text, encoding="utf-8")
    print(f"💾 Snapshot salvato: {snapshot_path}")
    return snapshot_path


def get_latest_snapshot() -> tuple[Path | None, str]:
    """
    Trova lo snapshot più recente nella cartella.
    Restituisce (path, testo) oppure (None, '') se non esiste.
    """
    snapshots = sorted(SNAPSHOTS_DIR.glob("snapshot_*.txt"))
    if not snapshots:
        return None, ""

    latest = snapshots[-1]
    return latest, latest.read_text(encoding="utf-8")


def extract_new_content(old_text: str, new_text: str) -> str:
    """
    Estrae il contenuto genuinamente nuovo basandosi sulla lunghezza.
    Il Google Doc cresce sempre per append — il nuovo è sempre in fondo.
    Aggiunge un buffer del 10% per catturare eventuali edits vicino al confine.
    """
    old_len = len(old_text)
    new_len = len(new_text)
    
    if new_len <= old_len:
        return ""  # nessuna aggiunta
    
    # Caratteri aggiunti + buffer 10% per sicurezza
    chars_added = new_len - old_len
    buffer = max(500, int(chars_added * 0.1))
    start = max(0, old_len - buffer)
    
    new_content = new_text[start:].strip()
    
    print(f"   Doc cresciuto di {chars_added} caratteri ({old_len} → {new_len})")
    return new_content


def read_and_diff(label: str = None) -> dict:
    """
    Funzione principale: legge il doc, confronta con snapshot precedente,
    restituisce dizionario con contenuto completo e novità.
    """
    service = get_drive_service()
    current_text = read_doc(service)

    # Carica snapshot precedente
    prev_path, prev_text = get_latest_snapshot()

    if prev_path:
        print(f"📂 Snapshot precedente: {prev_path.name}")
        new_content = extract_new_content(prev_text, current_text)
        if new_content:
            print(f"🆕 Trovate {len(new_content.splitlines())} righe nuove nel doc")
        else:
            print("📋 Nessuna modifica rilevata nel doc rispetto allo snapshot precedente")
    else:
        print("📋 Primo snapshot — nessun confronto disponibile")
        new_content = current_text  # tutto è "nuovo" al primo avvio

    # Salva nuovo snapshot
    save_snapshot(current_text, label)

    return {
        "full_text": current_text,
        "new_content": new_content,
        "had_previous": prev_path is not None,
        "previous_snapshot": str(prev_path) if prev_path else None
    }


if __name__ == "__main__":
    result = read_and_diff(label=date.today().isoformat())

    print("\n--- ANTEPRIMA CONTENUTO NUOVO ---")
    preview = result["new_content"][:500] if result["new_content"] else "(nessuna novità)"
    print(preview)
    print("...")