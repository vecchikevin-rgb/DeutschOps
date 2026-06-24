# doc_reader.py
# Legge il Google Doc di Stefanie, salva snapshot locale,
# confronta con snapshot precedente per estrarre solo le novità.
# Estrae e analizza anche immagini embedded via Ollama (minicpm-v).

import base64
import os
import json
from pathlib import Path
from datetime import date
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import requests as _http

DOC_ID = "165S8CsHT3TrCpr6Se3l3VYakb7r16_bgg81l5ygJvpc"
KPI_TAB_ID = "t.wjmdnwq7d6ek"  # tab scritto da noi — escluso dal diff

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents"
]

SNAPSHOTS_DIR = Path("doc_snapshots")
SNAPSHOTS_DIR.mkdir(exist_ok=True)


OLLAMA_BASE = "http://localhost:11434"
_VISION_MODELS = ["minicpm-v:latest", "llava:7b"]

_DOC_IMAGE_PROMPT = (
    "This image is from a German language lesson document. "
    "Extract ALL visible German text: vocabulary words, grammar tables, "
    "example sentences, conjugation tables, exercise text. "
    "Copy the text exactly as written. "
    "If it is a decorative image with no readable German text, respond with: NO_TEXT"
)


def _ollama_vision_model() -> str | None:
    """Ritorna il primo vision model disponibile in Ollama, o None."""
    try:
        r = _http.get(f"{OLLAMA_BASE}/api/tags", timeout=3)
        if r.status_code != 200:
            return None
        loaded = [m["name"] for m in r.json().get("models", [])]
        for candidate in _VISION_MODELS:
            base = candidate.split(":")[0]
            if any(base in m for m in loaded):
                return candidate
        return None
    except Exception:
        return None


def _analyze_image_bytes(image_bytes: bytes, model: str) -> str:
    """Invia immagine a Ollama e ritorna testo estratto ('' se NO_TEXT o errore)."""
    img_b64 = base64.b64encode(image_bytes).decode()
    try:
        r = _http.post(f"{OLLAMA_BASE}/api/generate", json={
            "model": model,
            "prompt": _DOC_IMAGE_PROMPT,
            "images": [img_b64],
            "stream": False,
            "options": {"temperature": 0.1},
        }, timeout=120)
        if r.status_code == 200:
            text = r.json().get("response", "").strip()
            return "" if text.upper().startswith("NO_TEXT") else text
    except Exception as e:
        print(f"      ⚠️  Ollama errore: {e}")
    return ""


def _extract_doc_images(inline_objects: dict, creds: Credentials) -> dict[str, str]:
    """
    Scarica e analizza le immagini embedded nel doc.
    Ritorna {obj_id: description} per le immagini con testo rilevante.
    """
    if not inline_objects:
        return {}

    model = _ollama_vision_model()
    if not model:
        print("   ⚠️  Ollama non disponibile — skip analisi immagini doc")
        return {}

    # Assicura token fresco per il download
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())

    print(f"   📷 {len(inline_objects)} immagini nel doc → analisi con {model}")
    descriptions: dict[str, str] = {}

    for i, (obj_id, obj_data) in enumerate(inline_objects.items(), 1):
        try:
            img_props = (obj_data
                         .get("inlineObjectProperties", {})
                         .get("embeddedObject", {})
                         .get("imageProperties", {}))
            uri = img_props.get("contentUri", "")
            if not uri:
                continue

            resp = _http.get(uri,
                             headers={"Authorization": f"Bearer {creds.token}"},
                             timeout=30)
            if resp.status_code != 200:
                continue

            desc = _analyze_image_bytes(resp.content, model)
            if desc:
                descriptions[obj_id] = desc
                print(f"   [{i}/{len(inline_objects)}] ✓ testo trovato")
            else:
                print(f"   [{i}/{len(inline_objects)}] · nessun testo")

        except Exception as e:
            print(f"   [{i}/{len(inline_objects)}] ⚠️  {e}")

    return descriptions


def _get_creds() -> Credentials:
    creds = None
    token_path = Path("token.json")
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json", SCOPES
            )
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json())
        print("✅ Token salvato in token.json")
    return creds


def get_drive_service():
    return build("drive", "v3", credentials=_get_creds())


def read_doc() -> str:
    """
    Legge il documento via Docs API tab per tab.
    Esclude il tab KPI scritto da DeutschOps.
    Analizza immagini embedded con Ollama (minicpm-v) se disponibile.
    Restituisce testo con marcatori di tab + descrizioni immagini.
    """
    print(f"📄 Lettura Google Doc ({DOC_ID[:20]}...)")

    creds = _get_creds()
    docs_service = build("docs", "v1", credentials=creds)

    doc = docs_service.documents().get(
        documentId=DOC_ID,
        includeTabsContent=True
    ).execute()

    all_text = []
    all_inline_objects: dict = {}
    tabs = doc.get("tabs", [])

    if tabs:
        for tab in tabs:
            props     = tab.get("tabProperties", {})
            tab_title = props.get("title", "untitled")
            tab_id    = props.get("tabId", "")

            # Escludi il tab KPI — scritto da noi, non da Stefanie
            if tab_id == KPI_TAB_ID:
                continue

            doc_tab = tab.get("documentTab", {})

            # Raccoglie inline objects (immagini) di questo tab
            all_inline_objects.update(doc_tab.get("inlineObjects", {}))

            content = doc_tab.get("body", {}).get("content", [])

            tab_text = []
            for element in content:
                paragraph = element.get("paragraph", {})
                for el in paragraph.get("elements", []):
                    text = el.get("textRun", {}).get("content", "")
                    if text:
                        tab_text.append(text)

            tab_content = "".join(tab_text)
            if tab_content.strip():
                all_text.append(
                    f"\n=== TAB: {tab_title} (id:{tab_id}) ===\n"
                    f"{tab_content}"
                )
    else:
        # Fallback: body principale (doc senza tab)
        all_inline_objects.update(doc.get("inlineObjects", {}))
        content = doc.get("body", {}).get("content", [])
        for element in content:
            paragraph = element.get("paragraph", {})
            for el in paragraph.get("elements", []):
                text = el.get("textRun", {}).get("content", "")
                if text:
                    all_text.append(text)

    full_text = "\n".join(all_text)

    # Analisi immagini embedded (non-blocking)
    if all_inline_objects:
        try:
            descriptions = _extract_doc_images(all_inline_objects, creds)
            if descriptions:
                img_lines = ["\n\n=== IMMAGINI NEL DOC ==="]
                for obj_id, desc in descriptions.items():
                    img_lines.append(f"\n[img {obj_id[:16]}]\n{desc}")
                full_text += "\n".join(img_lines)
                print(f"   {len(descriptions)}/{len(all_inline_objects)} immagini con contenuto integrate nel doc")
        except Exception as e:
            print(f"   ⚠️  Analisi immagini fallita (non-blocking): {e}")

    n_imgs = len(all_inline_objects)
    print(f"✅ Doc letto: {len(full_text)} caratteri ({len(tabs)} tab, {n_imgs} immagini)")
    return full_text


def save_snapshot(text: str, label: str = None) -> Path:
    if label is None:
        label = date.today().isoformat()
    snapshot_path = SNAPSHOTS_DIR / f"snapshot_{label}.txt"
    snapshot_path.write_text(text, encoding="utf-8")
    print(f"💾 Snapshot salvato: {snapshot_path}")
    return snapshot_path


def get_latest_snapshot() -> tuple[Path | None, str]:
    snapshots = sorted(SNAPSHOTS_DIR.glob("snapshot_*.txt"))
    if not snapshots:
        return None, ""
    latest = snapshots[-1]
    return latest, latest.read_text(encoding="utf-8")


def extract_new_content(old_text: str, new_text: str) -> str:
    """
    Estrae righe genuinamente nuove usando diff riga per riga.
    Funziona per aggiunte in qualsiasi posizione del documento.
    """
    import difflib

    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()

    added = []
    current_section = ""

    matcher = difflib.SequenceMatcher(
        None, old_lines, new_lines, autojunk=False
    )

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("insert", "replace"):
            # Trova sezione corrente guardando le righe precedenti
            for line in new_lines[max(0, j1-10):j1]:
                stripped = line.strip()
                if stripped and (
                    (stripped[0].isdigit() and "." in stripped[:5])
                    or stripped.startswith("🚨")
                    or stripped.startswith("=== TAB:")
                ):
                    current_section = stripped

            block = [l for l in new_lines[j1:j2] if l.strip()]
            if block:
                if current_section and (
                    not added or added[-1] != f"[{current_section}]"
                ):
                    added.append(f"\n[Section: {current_section}]")
                added.extend(block)

    return "\n".join(added)


def read_and_diff(label: str = None, write_snapshot: bool = True) -> dict:
    """
    Legge il doc, confronta con snapshot precedente, restituisce diff.

    write_snapshot=False: calcola tutto ma non scrive il file snapshot.
    Il chiamante riceve snapshot_path e snapshot_content per poterli scrivere
    in un secondo momento (es. commit differito in task_tracker).
    """
    current_text = read_doc()

    prev_path, prev_text = get_latest_snapshot()

    if prev_path:
        print(f"📂 Snapshot precedente: {prev_path.name}")
        new_content = extract_new_content(prev_text, current_text)
        if new_content:
            print(f"🆕 Trovate {len(new_content.splitlines())} righe nuove nel doc")
        else:
            print("📋 Nessuna modifica rilevata rispetto allo snapshot precedente")
    else:
        print("📋 Primo snapshot — nessun confronto disponibile")
        new_content = current_text

    snap_label = label or date.today().isoformat()
    snapshot_path = SNAPSHOTS_DIR / f"snapshot_{snap_label}.txt"

    if write_snapshot:
        save_snapshot(current_text, snap_label)

    return {
        "full_text": current_text,
        "new_content": new_content,
        "had_previous": prev_path is not None,
        "previous_snapshot": str(prev_path) if prev_path else None,
        "snapshot_path": str(snapshot_path),
        "snapshot_content": current_text,
    }


if __name__ == "__main__":
    result = read_and_diff(label=date.today().isoformat())
    print("\n--- ANTEPRIMA CONTENUTO NUOVO ---")
    preview = result["new_content"][:500] if result["new_content"] else "(nessuna novità)"
    print(preview)
    print("...")
