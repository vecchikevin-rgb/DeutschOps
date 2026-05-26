# DeutschOps

Pipeline AI per l'apprendimento del tedesco (A2→B1). Automatizza il ciclo completo da lezione audio con l'insegnante Stefanie a materiali di studio strutturati: trascrizione, estrazione AI, flashcard Anki, PDF, aggiornamento Google Doc.

## Come eseguire

```batch
# Attivare venv e lanciare (o usare DeutschOps.bat)
.venv\Scripts\activate
python main.py "Audiolessons/Classroom with Stefanie 2026-05-25.mp4"

# Dashboard KPI
streamlit run dashboard.py
```

**Prerequisiti obbligatori:**
- Anki aperto con AnkiConnect attivo su `localhost:8765`
- `.env` compilato con le API key
- `credentials.json` + `token.json` presenti (Google OAuth2)
- Google Drive mappato localmente

## Pipeline (main.py — 6 step)

| Step | Modulo | Operazione |
|------|--------|-----------|
| PREP | `transcriber.py` | Compressione audio con ffmpeg se >20MB |
| 1 | `doc_reader.py` | Lettura Google Doc Stefanie (diff tracking) |
| 2 | `transcriber.py` | Trascrizione OpenAI Whisper → `transcripts/lezione_{date}.txt` |
| 3 | `extractor.py` | Estrazione strutturata via Claude → `data/lezione_{date}.json` |
| 4 | `anki_feeder.py` | Creazione flashcard in deck "Deutsch::DeutschOps" |
| 5 | `pdf_gen.py` | Generazione PDF lezione → `pdfs/lezione_{date}.pdf` |
| 6 | `doc_writer.py` | Append riepilogo + KPI su Google Doc, upload PDF su Drive |

**Post-pipeline automatico:** `lesson_registry.py`, `vocab_db.py`, `grammar_book.py`, `generate_astra_prompts.py`

## File chiave

| File | Ruolo |
|------|-------|
| `main.py` | Orchestratore — entry point principale |
| `transcriber.py` | Whisper API + compressione ffmpeg (limite 24MB) |
| `extractor.py` | Claude API — output JSON con vocab, grammar, frasi, domande |
| `anki_feeder.py` | AnkiConnect HTTP — colori genere: der=blu, die=rosso, das=verde |
| `pdf_gen.py` | PDF lezione (ReportLab) |
| `grammar_book.py` | Libro grammatica progressivo (ReportLab + Claude) |
| `doc_writer.py` | Google Docs API — append e KPI |
| `doc_reader.py` | Google Docs API — lettura per diff |
| `dashboard.py` | Streamlit — KPI interattivi con Plotly/Pandas |
| `lesson_registry.py` | Registro JSON persistente di tutte le lezioni |
| `vocab_db.py` | Database vocabolario cumulativo |
| `export_to_obsidian.py` | Export verso Obsidian |
| `book_reader.py` / `book_extractor.py` | Import da libri PDF di corso (pdfplumber) |
| `bulk_import.py` / `bulk_import_book.py` | Import bulk lezioni/libri |

## Struttura dati

```
transcripts/     lezione_{date}.txt + .meta.json (durata, costo API)
data/            lezione_{date}.json (struttura estratta) + grammar_db.json
pdfs/            lezione_{date}.pdf
astra_prompts/   PDF prompt per caricamento su vector DB Astra
Audiolessons/    File audio originali + compressi
Book/            PDF libri di corso
```

### Schema JSON estrazione (`data/lezione_*.json`)
```json
{
  "lesson_number": 42,
  "topic": "...",
  "summary": { "en": "...", "it": "..." },
  "vocabulary": [{ "word": "...", "gender": "der/die/das", "plural": "...", "category": "...", "cefr": "A2" }],
  "grammar_points": [{ "rule": "...", "explanation": "...", "examples": [] }],
  "phrases": [],
  "comprehension_questions": [],
  "doc_sections_covered": []
}
```

## Stack tecnologico

| Categoria | Tecnologia |
|-----------|-----------|
| Runtime | Python 3.14, venv in `.venv/` |
| Trascrizione | OpenAI Whisper API |
| Estrazione AI | Anthropic Claude API |
| Google | Google Docs/Drive API (OAuth2) |
| Flashcard | AnkiConnect (localhost:8765) |
| PDF | ReportLab |
| Dashboard | Streamlit + Plotly + Pandas |
| Audio | ffmpeg (binario standalone `ffmpeg.exe`) |
| PDF parsing | pdfplumber |

## Configurazione

**`.env`** (non in git):
```
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
HUGGINGFACE_TOKEN=...
```

**Google OAuth2:** `credentials.json` + `token.json` (non in git) — flow automatico al primo run.

## Contesto progetto

Kevin (manager di produzione in transizione verso pharma svizzero, area Basilea) usa questo sistema per le lezioni settimanali con Stefanie, insegnante nativa. Obiettivo: A2→B1 in preparazione al mercato del lavoro svizzero tedesco.
