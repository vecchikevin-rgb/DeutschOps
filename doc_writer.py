# doc_writer.py v4 — testo ricco con emoji, niente API styling

import json
from pathlib import Path
from datetime import date, datetime
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# DOC_ID e KPI_TAB_ID arrivano da do/base/config.py: erano hardcoded in TRE
# file (qui, doc_reader.py:17, retroactive_doc_images.py:29). Stessa cosa per i
# path, che erano relativi alla cwd. Questo modulo resta il writer Google Docs
# finche' non viene consolidato — vedi la nota in do/lezione/doc.py.
from do.base.config import DOC_ID as STEFANIE_DOC_ID  # noqa: E402
from do.base.config import GOOGLE_SCOPES, KPI_TAB_ID  # noqa: E402
from do.base.paths import (  # noqa: E402
    DOC_SNAPSHOTS, GOOGLE_CREDENTIALS, GOOGLE_TOKEN, REGISTRY, VOCAB_DB,
)

SCOPES = GOOGLE_SCOPES

KPI_MARKER_START = "%%KPI_START%%"
KPI_MARKER_END   = "%%KPI_END%%"
LESSONS_MARKER   = "%%LESSONS_START%%"

SEP  = "━" * 52
SEP2 = "─" * 52


# ─── AUTH ─────────────────────────────────────────────────────────────────────
def get_service():
    creds = None
    token_path = GOOGLE_TOKEN
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(GOOGLE_CREDENTIALS), SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json())
    return build("docs", "v1", credentials=creds)


def get_drive_service():
    creds = Credentials.from_authorized_user_file(str(GOOGLE_TOKEN), SCOPES)
    return build("drive", "v3", credentials=creds)


# ─── BACKUP (locale, niente copie sul Drive personale) ────────────────────────
def backup_doc(label: str = None) -> str | None:
    """Prova l'export .docx del Doc di Stefanie. Oggi NON puo' riuscire.

    STATO REALE, verificato il 2026-07-27
    In `doc_snapshots/backups/` non esiste NESSUN .docx. Ci sono 25 file .json
    da 183 byte, prodotti da una versione precedente di questa funzione che
    creava copie DENTRO il Drive (il campo `url` punta a un documento diverso)
    — cioe' proprio il comportamento che CLAUDE.md dichiara rimosso. Quelle
    copie sono presumibilmente ancora nel Drive di Kevin.

    La versione attuale esporta .docx e fallisce sempre con
    `exportSizeLimitExceeded`: il Doc ha 112.000 caratteri e 108 immagini, e
    supera il limite di export dell'API Drive. Non e' un errore transitorio,
    e' strutturale: crescendo, non tornera' sotto il limite.

    COSA C'E' DAVVERO AL POSTO SUO
    `doc_snapshots/snapshot_*.txt` — 30 file, l'ultimo da 119 KB, scritto a
    ogni lezione dalla pipeline. Copre il TESTO, che e' cio' che serve al diff
    e all'estrazione.

    COSA RESTA SCOPERTO, e va detto invece che nascosto sotto un try/except:
    le 108 immagini e la formattazione. Se il Doc sparisse, quelle non ci sono
    da nessuna parte. Un export manuale (File > Scarica) le salverebbe.
    """
    del label                                   # firma tenuta per i chiamanti
    print("   Backup .docx non disponibile: il Doc supera il limite di export "
          "di Drive (strutturale, non transitorio).")
    print("   Il testo e' comunque salvato in doc_snapshots/snapshot_*.txt. "
          "Immagini e formattazione no: per quelle serve File > Scarica a mano.")
    return None


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

    # 1. Backup locale del Doc (nessuna copia sul Drive personale)
    # Non-blocking: il Doc puo' superare il limite di export di Drive
    # (docx troppo grande) senza che questo impedisca l'aggiornamento vero e proprio.
    try:
        backup_doc(label=lesson_date)
    except Exception as e:
        print(f"⚠️ Backup locale saltato (non-blocking): {e}")

    # 2. PDF già salvato localmente in pdfs/ da pdf_gen.py (step 5)
    pdf_filename = Path(pdf_path).name if pdf_path and Path(pdf_path).exists() else ""

    # 3. Carica dati
    registry = {"lessons": [], "stats": {}}
    if REGISTRY.exists():
        registry = json.loads(REGISTRY.read_text(encoding="utf-8"))

    vocab_stats = {"total_words": 0, "by_category": {}, "by_level": {}}
    if VOCAB_DB.exists():
        db = json.loads(VOCAB_DB.read_text(encoding="utf-8"))
        vocab_stats = db.get("stats", vocab_stats)

    # 4. Scrivi nel tab
    write_to_tab(service, registry, vocab_stats,
                 lesson_json_path, lesson_date, pdf_filename)

    tab_url = (f"https://docs.google.com/document/d/{STEFANIE_DOC_ID}"
               f"/edit?tab={KPI_TAB_ID}")
    print(f"\n✅ Aggiornato: {tab_url}")


if __name__ == "__main__":
    append_lesson_summary(
        lesson_json_path="data/lezione_2026-05-18-stefanie.json",
        lesson_date="2026-05-18-stefanie",
        pdf_path="pdfs/lezione_2026-05-18-stefanie.pdf"
    )