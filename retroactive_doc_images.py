# retroactive_doc_images.py
"""
Back-fill analisi immagini del Google Doc per le lezioni già elaborate.

Per ogni tab del doc:
  - scarica le immagini embedded (OAuth)
  - analizza con minicpm-v (Ollama locale)
  - mappa il tab alla lezione via doc_sections_covered nei JSON

Risultato: aggiunge campo "doc_images" a ogni data/lezione_*.json
           e salva data/doc_images_audit.json con il report completo.

Uso:
    python retroactive_doc_images.py          # analizza tutto
    python retroactive_doc_images.py --report # solo report (niente analisi)
    python retroactive_doc_images.py --force  # rifa anche già fatto
"""
import base64
import json
import sys
from pathlib import Path

import requests
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# ── Configurazione ────────────────────────────────────────────────────────────
DOC_ID     = "165S8CsHT3TrCpr6Se3l3VYakb7r16_bgg81l5ygJvpc"
KPI_TAB_ID = "t.wjmdnwq7d6ek"
DATA_DIR   = Path("data")
OLLAMA     = "http://localhost:11434"
MODELS     = ["minicpm-v:latest", "llava:7b"]

IMAGE_PROMPT = (
    "This image is from a German language lesson document. "
    "Extract ALL visible German text: vocabulary words, grammar tables, "
    "example sentences, conjugation tables, exercise text. "
    "Copy the text exactly as written. "
    "If it is a decorative image with no readable German text, respond with: NO_TEXT"
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _vision_model() -> str | None:
    try:
        r = requests.get(f"{OLLAMA}/api/tags", timeout=3)
        loaded = [m["name"] for m in r.json().get("models", [])]
        for m in MODELS:
            if any(m.split(":")[0] in x for x in loaded):
                return m
    except Exception:
        pass
    return None


def _analyze(image_bytes: bytes, model: str) -> str:
    b64 = base64.b64encode(image_bytes).decode()
    try:
        r = requests.post(f"{OLLAMA}/api/generate", json={
            "model": model, "prompt": IMAGE_PROMPT,
            "images": [b64], "stream": False,
            "options": {"temperature": 0.1},
        }, timeout=300)
        if r.status_code == 200:
            t = r.json().get("response", "").strip()
            return "" if t.upper().startswith("NO_TEXT") else t
    except Exception as e:
        print(f"      ⚠️  Ollama: {e}")
    return ""


# ── Lettura doc + analisi immagini per tab ────────────────────────────────────

def read_doc_images_by_tab(creds, model: str) -> dict[str, list[dict]]:
    """
    Ritorna { tab_title: [ {"obj_id": ..., "description": ...} ] }
    solo per i tab che hanno immagini con testo rilevante.
    """
    docs_service = build("docs", "v1", credentials=creds)
    doc = docs_service.documents().get(
        documentId=DOC_ID, includeTabsContent=True
    ).execute()

    # Assicura token fresco
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())

    tabs = doc.get("tabs", [])
    result: dict[str, list[dict]] = {}
    total_imgs = sum(
        len(t.get("documentTab", {}).get("inlineObjects", {}))
        for t in tabs
        if t.get("tabProperties", {}).get("tabId") != KPI_TAB_ID
    )
    print(f"  {len(tabs)} tab, {total_imgs} immagini totali nel doc")

    done = 0
    for tab in tabs:
        props  = tab.get("tabProperties", {})
        tab_id = props.get("tabId", "")
        title  = props.get("title", "?")
        if tab_id == KPI_TAB_ID:
            continue

        doc_tab      = tab.get("documentTab", {})
        inline_objs  = doc_tab.get("inlineObjects", {})
        if not inline_objs:
            continue

        tab_results: list[dict] = []
        for obj_id, obj_data in inline_objs.items():
            done += 1
            img_props = (obj_data
                         .get("inlineObjectProperties", {})
                         .get("embeddedObject", {})
                         .get("imageProperties", {}))
            uri = img_props.get("contentUri", "")
            if not uri:
                continue
            try:
                resp = requests.get(
                    uri,
                    headers={"Authorization": f"Bearer {creds.token}"},
                    timeout=30
                )
                if resp.status_code != 200:
                    continue
                desc = _analyze(resp.content, model)
                marker = "✓" if desc else "·"
                print(f"  [{done:3d}/{total_imgs}] {marker}  {title[:40]}")
                if desc:
                    tab_results.append({"obj_id": obj_id, "description": desc})
            except Exception as e:
                print(f"  [{done:3d}/{total_imgs}] ⚠  {e}")

        if tab_results:
            result[title] = tab_results

    return result


# ── Mapping tab → lezione ─────────────────────────────────────────────────────

def _tab_number(s: str) -> int | None:
    """
    Estrae il numero dal titolo tab o da una sezione doc.
    Gestisce entrambi i formati:
      - "10. Dativ mit Präpositionen"          → 10
      - "TAB: 10. Dativ mit Präpositionen - X" → 10
    """
    s = s.strip()
    if s.upper().startswith("TAB:"):
        s = s[4:].strip()
    try:
        return int(s.split(".")[0].strip())
    except Exception:
        return None


def _lesson_dates_with_json() -> list[tuple[str, dict]]:
    results = []
    for f in sorted(DATA_DIR.glob("lezione_*-stefanie.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            results.append((f.stem.replace("lezione_", ""), d))
        except Exception:
            pass
    return results


def _tab_matches_lesson(tab_title: str, lesson_data: dict) -> bool:
    """Vero se il tab è citato nei doc_sections_covered della lezione."""
    sections = lesson_data.get("doc_sections_covered", [])
    tab_num  = _tab_number(tab_title)
    for sec in sections:
        sec_num = _tab_number(sec)
        if tab_num and sec_num and tab_num == sec_num:
            return True
        # fallback: substring match sul titolo
        if tab_title.lower()[:20] in sec.lower():
            return True
    return False


# ── Aggiornamento JSON lezioni ────────────────────────────────────────────────

def enrich_lessons(tab_images: dict[str, list[dict]], force: bool = False) -> dict:
    """
    Aggiunge doc_images ai JSON lezione dove il tab matcha.
    Ritorna report { lesson_date: { tabs_matched, images_added } }.
    """
    lessons   = _lesson_dates_with_json()
    report    = {}
    enriched  = 0

    for lesson_date, lesson_data in lessons:
        json_path = DATA_DIR / f"lezione_{lesson_date}.json"

        existing = lesson_data.get("doc_images", [])
        if existing and not force:
            report[lesson_date] = {
                "tabs_matched": "già presente",
                "images_added": len(existing)
            }
            continue

        matched_images: list[dict] = []
        matched_tabs: list[str]    = []

        for tab_title, imgs in tab_images.items():
            if _tab_matches_lesson(tab_title, lesson_data):
                for img in imgs:
                    matched_images.append({
                        "tab": tab_title,
                        "description": img["description"]
                    })
                matched_tabs.append(tab_title)

        if matched_images:
            lesson_data["doc_images"] = matched_images
            json_path.write_text(
                json.dumps(lesson_data, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            enriched += 1
            print(f"  ✅ {lesson_date}: {len(matched_images)} immagini da {matched_tabs}")
        else:
            print(f"  —  {lesson_date}: nessun tab con immagini trovato")

        report[lesson_date] = {
            "tabs_matched": matched_tabs,
            "images_added": len(matched_images)
        }

    print(f"\n  Lezioni arricchite: {enriched}/{len(lessons)}")
    return report


# ── Report ────────────────────────────────────────────────────────────────────

def print_report(report: dict):
    print(f"\n{'Lezione':<30} {'Tab trovati':<50} {'Immagini'}")
    print("-" * 90)
    for date_str, info in sorted(report.items()):
        tabs  = info.get("tabs_matched", [])
        nimgs = info.get("images_added", 0)
        if isinstance(tabs, list):
            tabs_str = ", ".join(t[:25] for t in tabs) if tabs else "—"
        else:
            tabs_str = str(tabs)
        print(f"{date_str:<30} {tabs_str:<50} {nimgs}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main(force: bool = False, report_only: bool = False):
    if report_only:
        # Solo report da JSON esistenti
        lessons = _lesson_dates_with_json()
        for date_str, data in lessons:
            imgs = data.get("doc_images", [])
            tabs = list({i["tab"] for i in imgs}) if imgs else []
            print(f"  {date_str}: {len(imgs)} immagini | {tabs}")
        return

    model = _vision_model()
    if not model:
        print("❌ Nessun vision model disponibile in Ollama.")
        print("   Avvia Ollama con: ollama run minicpm-v")
        return

    print(f"Vision model: {model}")
    print(f"\n--- Analisi immagini Google Doc ---")

    # Credenziali OAuth (riusa token esistente)
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from doc_reader import _get_creds
    creds = _get_creds()

    tab_images = read_doc_images_by_tab(creds, model)
    print(f"\nTab con immagini rilevanti: {len(tab_images)}")
    total_relevant = sum(len(v) for v in tab_images.values())
    print(f"Immagini con contenuto tedesco: {total_relevant}")

    print(f"\n--- Mapping tab → lezioni ---")
    report = enrich_lessons(tab_images, force=force)

    # Salva audit completo
    audit_path = DATA_DIR / "doc_images_audit.json"
    audit_path.write_text(
        json.dumps({
            "tab_images": {k: [{"description": i["description"][:200]} for i in v]
                           for k, v in tab_images.items()},
            "lesson_report": report,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"\n📄 Audit salvato: {audit_path}")

    print_report(report)


if __name__ == "__main__":
    args = sys.argv[1:]
    main(
        force="--force" in args,
        report_only="--report" in args,
    )
