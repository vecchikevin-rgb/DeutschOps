# doc_writer.py v4 — testo ricco con emoji, niente API styling

import json
import shutil
from pathlib import Path
from datetime import date, datetime
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

STEFANIE_DOC_ID = "165S8CsHT3TrCpr6Se3l3VYakb7r16_bgg81l5ygJvpc"
KPI_TAB_ID      = "t.wjmdnwq7d6ek"

PDF_DRIVE_FOLDER = Path(
    r"C:\Users\vecch\Il mio Drive (vecchi.kevin@gmail.com)"
    r"\Portatile Dati\Documenti Kevin\Deutsch\Audiolezioni\KPI + pdf lezioni"
)

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents"
]

KPI_MARKER_START = "%%KPI_START%%"
KPI_MARKER_END   = "%%KPI_END%%"
LESSONS_MARKER   = "%%LESSONS_START%%"

SEP  = "━" * 52
SEP2 = "─" * 52


# ─── AUTH ─────────────────────────────────────────────────────────────────────
def get_service():
    creds = None
    token_path = Path("token.json")
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json())
    return build("docs", "v1", credentials=creds)


def get_drive_service():
    creds = Credentials.from_authorized_user_file(
        str(Path("token.json")), SCOPES)
    return build("drive", "v3", credentials=creds)


# ─── BACKUP ───────────────────────────────────────────────────────────────────
def backup_doc(label: str = None) -> str:
    if label is None:
        label = datetime.now().strftime("%Y-%m-%d_%H-%M")
    backup_dir = Path("doc_snapshots/backups")
    backup_dir.mkdir(parents=True, exist_ok=True)
    drive_svc = get_drive_service()
    copy = drive_svc.files().copy(
        fileId=STEFANIE_DOC_ID,
        body={"name": f"Kevin_BACKUP_{label}"}
    ).execute()
    copy_url = f"https://docs.google.com/document/d/{copy['id']}/edit"
    (backup_dir / f"backup_{label}.json").write_text(json.dumps({
        "label": label, "url": copy_url,
        "created_at": datetime.now().isoformat()
    }, indent=2))
    print(f"💾 Backup: {copy_url}")
    return copy_url


# ─── PDF → DRIVE ──────────────────────────────────────────────────────────────
def copy_pdf_to_drive(pdf_path: str) -> str:
    pdf_path = Path(pdf_path)
    PDF_DRIVE_FOLDER.mkdir(parents=True, exist_ok=True)
    dest = PDF_DRIVE_FOLDER / pdf_path.name
    shutil.copy2(str(pdf_path), str(dest))
    print(f"📄 PDF → Drive: {dest.name}")
    return str(dest)


# ─── TAB HELPERS ──────────────────────────────────────────────────────────────
def get_tab_content(service) -> tuple[list, int]:
    doc = service.documents().get(
        documentId=STEFANIE_DOC_ID,
        includeTabsContent=True
    ).execute()
    for tab in doc.get("tabs", []):
        if tab.get("tabProperties", {}).get("tabId") == KPI_TAB_ID:
            content = (tab.get("documentTab", {})
                          .get("body", {})
                          .get("content", []))
            end_idx = content[-1].get("endIndex", 1) if content else 1
            return content, end_idx
    content = doc.get("body", {}).get("content", [])
    return content, content[-1].get("endIndex", 1) if content else 1


def find_marker(content: list, marker: str) -> int | None:
    for el in content:
        for e in el.get("paragraph", {}).get("elements", []):
            if marker in e.get("textRun", {}).get("content", ""):
                return e.get("startIndex")
    return None


def insert_text(service, index: int, text: str):
    service.documents().batchUpdate(
        documentId=STEFANIE_DOC_ID,
        body={"requests": [{
            "insertText": {
                "location": {"index": index, "tabId": KPI_TAB_ID},
                "text": text
            }
        }]}
    ).execute()


def delete_range(service, start: int, end: int):
    service.documents().batchUpdate(
        documentId=STEFANIE_DOC_ID,
        body={"requests": [{
            "deleteContentRange": {
                "range": {
                    "startIndex": start,
                    "endIndex": end,
                    "tabId": KPI_TAB_ID
                }
            }
        }]}
    ).execute()


# ─── KPI TEXT ─────────────────────────────────────────────────────────────────
def build_kpi_text(registry: dict, vocab_stats: dict) -> str:
    lessons       = registry.get("lessons", [])
    stats         = registry.get("stats", {})
    now           = datetime.now().strftime("%d %b %Y  %H:%M")
    total_lessons = stats.get("total", 0)
    total_minutes = stats.get("total_minutes", 0)
    total_cost    = stats.get("total_cost_eur", 0)
    total_words   = vocab_stats.get("total_words", 0)
    by_level      = vocab_stats.get("by_level", {})
    by_cat        = vocab_stats.get("by_category", {})

    lines = [
        KPI_MARKER_START,
        "",
        "⚡  DEUTSCHOPS — PROGRESS DASHBOARD",
        f"    Last updated: {now}",
        "",
        SEP,
        "📊  OVERALL PROGRESS",
        SEP,
        f"   🎓  Lessons completed       {total_lessons}",
        f"   ⏱️   Audio studied           {total_minutes:.0f} min  "
        f"({total_minutes/60:.1f}h)",
        f"   📚  Total vocabulary        {total_words} words",
        f"   💶  Total API cost          €{total_cost:.2f}",
        "",
        SEP,
        "📈  VOCABULARY BREAKDOWN",
        SEP,
        f"   A1  {'█' * min(by_level.get('A1',0)//10, 20)}  "
        f"{by_level.get('A1',0)} words",
        f"   A2  {'█' * min(by_level.get('A2',0)//10, 20)}  "
        f"{by_level.get('A2',0)} words",
        f"   B1  {'█' * min(by_level.get('B1',0)//5, 20)}  "
        f"{by_level.get('B1',0)} words",
        "",
    ]

    cat_labels = {
        "noun":           ("🔵", "Nouns"),
        "verb_regular":   ("🟢", "Regular verbs"),
        "verb_irregular": ("🟢", "Irregular verbs"),
        "verb_separable": ("🟩", "Separable verbs"),
        "verb_modal":     ("🟢", "Modal verbs"),
        "adjective":      ("🔴", "Adjectives"),
        "adverb":         ("🔷", "Adverbs"),
        "phrase":         ("⬜", "Phrases"),
        "expression":     ("⬜", "Expressions"),
    }
    for cat, (emoji, label) in cat_labels.items():
        count = by_cat.get(cat, 0)
        if count:
            lines.append(f"   {emoji}  {label:<22} {count}")

    lines += [
        "",
        SEP,
        "📋  RECENT LESSONS",
        SEP,
    ]

    for lesson in lessons[-10:]:
        topic = lesson.get("topic", "")[:48]
        d     = lesson.get("date", "")
        v     = lesson.get("vocabulary_count", 0)
        g     = lesson.get("grammar_count", 0)
        m     = lesson.get("duration_minutes", 0)
        lines.append(f"   [{d}]  {topic}")
        lines.append(f"           {v} words  ·  {g} grammar  ·  {m:.0f} min")

    last = lessons[-1] if lessons else None
    if last and last.get("homework"):
        lines += [
            "",
            f"   📌  Last homework:",
            f"       {last['homework'][:80]}",
        ]

    lines += [
        "",
        SEP,
        KPI_MARKER_END,
        "",
        LESSONS_MARKER,
        "",
    ]

    return "\n".join(lines)


# ─── LESSON TEXT ──────────────────────────────────────────────────────────────
def build_lesson_text(lesson_json_path: str,
                       lesson_date: str,
                       pdf_filename: str = "") -> str:
    data     = json.loads(Path(lesson_json_path).read_text(encoding="utf-8"))
    topic    = data.get("topic", "")
    summary  = data.get("summary_en", "")
    vocab    = data.get("vocabulary", [])
    grammar  = data.get("grammar_points", [])
    phrases  = data.get("phrases", [])
    homework = data.get("homework", "")
    sections = data.get("doc_sections_covered", [])

    # Emoji per categoria vocabolario
    cat_emoji = {
        "noun":           "🔵",
        "verb_regular":   "🟢",
        "verb_irregular": "🟢",
        "verb_separable": "🟩",
        "verb_modal":     "🟢",
        "adjective":      "🔴",
        "adverb":         "🔷",
        "phrase":         "⬜",
        "expression":     "⬜",
    }

    lines = [
        SEP,
        f"📖  LESSON  —  {lesson_date.upper()}",
        f"    {topic}",
    ]

    if sections:
        lines.append(f"    Sections: {', '.join(sections[:4])}")
    if pdf_filename:
        lines.append(f"    📄 PDF: {pdf_filename}")

    lines += ["", SEP2]

    # Summary
    if summary:
        lines += ["", "📋  SUMMARY", ""]
        # Wrap a 70 caratteri
        words = summary.split()
        line_buf = "    "
        for word in words:
            if len(line_buf) + len(word) > 72:
                lines.append(line_buf)
                line_buf = "    " + word + " "
            else:
                line_buf += word + " "
        if line_buf.strip():
            lines.append(line_buf)

    # Vocabolario
    lines += ["", SEP2, "📚  VOCABULARY", SEP2, ""]
    for w in vocab:
        cat     = w.get("category", "other")
        emoji   = cat_emoji.get(cat, "⬜")
        art     = w.get("article", "")
        german  = w.get("german", "")
        if art and german.lower().startswith(art.lower() + " "):
            german = german[len(art)+1:]
        eng     = w.get("english", "")
        lvl     = w.get("level", "")
        plural  = w.get("plural", "")
        ex      = w.get("example_de", "")

        word_line = f"   {emoji}  "
        if art:
            word_line += f"{art} {german}"
        else:
            word_line += german
        word_line += f"  —  {eng}"
        if lvl:
            word_line += f"  [{lvl}]"
        if plural:
            word_line += f"  (Pl: {plural})"
        lines.append(word_line)

        if ex:
            lines.append(f"         ↳  {ex}")

    # Grammatica
    lines += ["", SEP2, "📐  GRAMMAR POINTS", SEP2, ""]
    for i, g in enumerate(grammar, 1):
        rule = g.get("rule", "")
        exp  = g.get("explanation_en", "") or g.get("explanation_it", "")
        exs  = g.get("examples", [])
        lines.append(f"   {i}.  {rule}")
        if exp:
            lines.append(f"       {exp}")
        for ex in exs:
            lines.append(f"       →  {ex}")
        lines.append("")

    # Frasi utili
    if phrases:
        lines += [SEP2, "💬  USEFUL PHRASES", SEP2, ""]
        for p in phrases:
            german = p.get("german", "")
            eng    = p.get("english", "") or p.get("italian", "")
            ctx    = p.get("context", "")
            lines.append(f"   {german}  —  {eng}")
            if ctx:
                lines.append(f"       ↳  {ctx}")
        lines.append("")

    # Homework
    if homework:
        lines += [
            SEP2,
            f"📌  HOMEWORK",
            f"    {homework}",
            "",
        ]

    lines += [SEP, ""]
    return "\n".join(lines)


# ─── WRITE TO TAB ─────────────────────────────────────────────────────────────
def write_to_tab(service, registry: dict, vocab_stats: dict,
                  lesson_json_path: str, lesson_date: str,
                  pdf_filename: str = ""):
    """
    Strategia:
    1. Leggi tab corrente
    2. Se KPI block esiste → sostituiscilo
       Se non esiste → svuota tab e riscrivi tutto
    3. Appendi riassunto lezione se non già presente
    """
    content, end_idx = get_tab_content(service)

    kpi_start = find_marker(content, KPI_MARKER_START)
    kpi_end   = find_marker(content, KPI_MARKER_END)
    kpi_text  = build_kpi_text(registry, vocab_stats)

    if kpi_start is not None and kpi_end is not None:
        # Sostituisci solo il blocco KPI
        delete_end = kpi_end + len(KPI_MARKER_END) + 1
        delete_range(service, kpi_start, min(delete_end, end_idx - 1))
        insert_text(service, kpi_start, kpi_text)
        print("♻️  KPI aggiornato")
    else:
        # Prima volta — svuota e riscrivi
        if end_idx > 2:
            delete_range(service, 1, end_idx - 1)
        insert_text(service, 1, kpi_text)
        print("✨ KPI inserito per la prima volta")

    # Controlla se la lezione è già presente
    content, end_idx = get_tab_content(service)
    lesson_marker = f"LESSON  —  {lesson_date.upper()}"
    already = find_marker(content, lesson_marker)

    if not already:
        lesson_text = build_lesson_text(
            lesson_json_path, lesson_date, pdf_filename
        )
        insert_text(service, end_idx - 1, lesson_text)
        print(f"📝 Riassunto lezione {lesson_date} aggiunto")
    else:
        print(f"⏭️  Riassunto {lesson_date} già presente")


# ─── MAIN ─────────────────────────────────────────────────────────────────────
def append_lesson_summary(lesson_json_path: str,
                           lesson_date: str = None,
                           pdf_path: str = None):
    if lesson_date is None:
        lesson_date = date.today().isoformat()

    print("🔑 Connessione Google...")
    service = get_service()

    # 1. Backup
    backup_doc(label=lesson_date)

    # 2. PDF → Drive folder locale
    pdf_filename = ""
    if pdf_path and Path(pdf_path).exists():
        copy_pdf_to_drive(pdf_path)
        pdf_filename = Path(pdf_path).name
    else:
        print("⚠️  PDF non trovato, skip copia Drive")

    # 3. Carica dati
    registry = {"lessons": [], "stats": {}}
    if Path("lesson_registry.json").exists():
        registry = json.loads(
            Path("lesson_registry.json").read_text(encoding="utf-8"))

    vocab_stats = {"total_words": 0, "by_category": {}, "by_level": {}}
    if Path("data/vocab_db.json").exists():
        db = json.loads(Path("data/vocab_db.json").read_text(encoding="utf-8"))
        vocab_stats = db.get("stats", vocab_stats)

    # 4. Scrivi nel tab
    write_to_tab(service, registry, vocab_stats,
                 lesson_json_path, lesson_date, pdf_filename)

    tab_url = (f"https://docs.google.com/document/d/{STEFANIE_DOC_ID}"
               f"/edit?tab={KPI_TAB_ID}")
    print(f"\n✅ Aggiornato: {tab_url}")


if __name__ == "__main__":
    append_lesson_summary(
        lesson_json_path="data/lezione_2026-05-14-stefanie.json",
        lesson_date="2026-05-14",
        pdf_path="pdfs/lezione_2026-05-14-stefanie.pdf"
    )