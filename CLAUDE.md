# DeutschOps

Pipeline AI per l'apprendimento del tedesco (A2→B1). Automatizza il ciclo completo da lezione audio con l'insegnante Stefanie a materiali di studio strutturati: trascrizione, estrazione AI, flashcard Anki, PDF, aggiornamento Google Doc.

## Come eseguire

```batch
# Attivare venv e lanciare (o usare DeutschOps.bat)
# NB: l'ambiente reale e' venv/ (NON .venv/). Imposta sempre UTF-8.
venv\Scripts\activate
set PYTHONIOENCODING=utf-8
set WHISPER_MODE=local         REM trascrizione locale (faster-whisper), niente costi API
python main.py "Audiolessons/Classroom with Stefanie 2026-05-25.mp4" 2026-05-25-stefanie

# Rilevare ed elaborare lezioni nuove in Audiolessons/ automaticamente
python watch.py --process

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
| PREFLIGHT | `preflight.py` | Check video (moov→auto-untrunc), token Google, sessione NBLM, Anki |
| PREP | `transcriber.py` | Compressione audio con ffmpeg se >20MB |
| 1 | `doc_reader.py` | Lettura Google Doc Stefanie (diff tracking) |
| 2 | `transcriber.py` | Trascrizione OpenAI Whisper → `transcripts/lezione_{date}.txt` |
| 3 | `extractor.py` | Estrazione strutturata via Claude → `data/lezione_{date}.json` |
| 4 | `anki_feeder.py` | Creazione flashcard in deck "Deutsch::DeutschOps" |
| 5 | `pdf_gen.py` | Generazione PDF lezione → `pdfs/lezione_{date}.pdf` |
| 6 | `doc_writer.py` | Append riepilogo + KPI su Google Doc, backup locale del Doc |

**Post-pipeline automatico:** `lesson_registry.py`, `vocab_db.py`, `grammar_book.py`, `error_extractor.py` (quaderno errori), `generate_astra_prompts.py`, `notebooklm_export.py`, `archive_cleanup.py` (staging input a scadenza)

## Staging input a scadenza (`Audiolessons/_processed/`)

A fine di ogni elaborazione **riuscita**, `main.py` sposta il **file sorgente consumato** (il video originale ~140MB, oppure il `.txt` grezzo di una trascrizione esterna) in `Audiolessons/_processed/` con `archive_cleanup.archive_inputs()`, timbrando l'mtime a quel momento. Il cleanup è **opportunistico**: `archive_cleanup.cleanup_expired()` gira all'avvio di ogni run e cancella ciò che ha superato i **20 giorni**. Nessun Task Scheduler necessario.

- **Cosa ci va:** solo input consumati e ridondanti (trascritto + output canonici esistono già).
- **Cosa NON ci va mai:** i file canonici (`transcripts/`, `data/`, `pdfs/`) e l'audio compresso `lezione_*-compressed.mp4` (referenziato dal registry, riusato nei re-run). `archive_cleanup` li protegge esplicitamente. Per le lezioni senza audio il transcript canonico è **irrecuperabile** — non deve mai finire in un percorso a scadenza.
- **A mano:** `python archive_cleanup.py --cleanup` (elimina gli scaduti) · `python archive_cleanup.py <file>...` (archivia) · `python archive_cleanup.py` (stato + giorni residui).

## Lezione senza video (solo trascrizione esterna)

Quando una lezione arriva **senza audio/video** (es. solo la trascrizione Gemini di una call), non c'è nulla da trascrivere: si inietta il transcript già pronto e la pipeline salta lo Step 2 (in `main.py` Step 2 fa skip se `transcripts/lezione_{date}.txt` esiste già).

1. Copia il testo grezzo (verbatim, UTF-8, **senza ripulirlo** — pulire rischia di perdere il tedesco) in `transcripts/lezione_{date}-stefanie.txt`.
2. Scrivi `transcripts/lezione_{date}-stefanie.meta.json` = `{"duration_minutes": <minuti reali dalla lezione>, "cost_eur": 0}` — la trascrizione esterna è gratuita e senza questo file il registry/dashboard registrerebbe una lezione di durata ~0.
3. Lancia `main.py` passando **il `.txt` grezzo come dummy audio arg**: `check_video` lo ignora (suffisso non video), `prepare_audio` lo lascia com'è (<20MB), lo Step 2 salta perché il transcript canonico esiste. A fine run il `.txt` grezzo viene archiviato in `_processed/` come qualsiasi input consumato.

L'estrazione (Step 3) su un dialogo grezzo con chiacchiere fuori tema è inerentemente più rumorosa: è un limite della fonte, non un bug.

## Miglioramento continuo (feedback loop)

Chiudono l'anello di apprendimento — usano ciò che Kevin *fa* per decidere cosa studiare:

| Tool | Ruolo |
|------|-------|
| `error_extractor.py` | Mina gli errori di Kevin + correzioni di Stefanie dai transcript → `data/error_db.json` + pattern ricorrenti. `--all` / `--lesson <date>` / `--report` |
| `error_pdf.py` | PDF "Quaderno degli Errori" → `pdfs/Quaderno_Errori.pdf` |
| `weak_cards.py` | Carte Anki più deboli (lapses/ease) → ripasso mirato. `--practice` genera esercizi |
| `b1_gap.py` | Gap analysis vs curriculum B1 → argomenti concreti da proporre a Stefanie |
| `pharma_glossary.py` | Glossario professionale (Basilea/pharma) + dialogo workplace |
| `preflight.py` | Health-check pre-pipeline (video/token/NBLM/Anki) |
| `watch.py` | Rileva ed elabora lezioni nuove in `Audiolessons/` |

**Cadenza consigliata:** `error_extractor` gira in post-pipeline ad ogni lezione; `weak_cards` + `b1_gap` settimanali (Task Scheduler); `pharma_glossary` mensile.

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
| `notebooklm_export.py` | Sincronizzazione automatica e formattazione per Google NotebookLM |
| `lesson_registry.py` | Registro JSON persistente di tutte le lezioni |
| `vocab_db.py` | Database vocabolario cumulativo |
| `export_to_obsidian.py` | Export verso Obsidian |
| `book_reader.py` / `book_extractor.py` | Import da libri PDF di corso (pdfplumber) |
| `bulk_import.py` / `bulk_import_book.py` | Import bulk lezioni/libri |
| `archive_cleanup.py` | Staging a scadenza degli input consumati → `Audiolessons/_processed/`, TTL 20 giorni |

## Struttura dati

```
transcripts/     lezione_{date}.txt + .meta.json (durata, costo API)
data/            lezione_{date}.json (struttura estratta) + grammar_db.json
pdfs/            lezione_{date}.pdf
astra_prompts/   PDF prompt per caricamento su vector DB Astra
Audiolessons/    File audio originali + compressi
Audiolessons/_processed/   Input consumati (video originale, .txt grezzi esterni) — auto-eliminati 20g dopo l'elaborazione
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
| Runtime | Python 3.14, venv in `venv/` (non usare `.venv/`) |
| Trascrizione | Whisper locale (faster-whisper, `WHISPER_MODE=local`) |
| Estrazione AI | Anthropic Claude API (default) oppure Ollama locale (`LLM_BACKEND=ollama`, vedi sezione dedicata) |
| Google | Google Docs/Drive API (OAuth2), Google NotebookLM (via notebooklm-py) |
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

## Regole operative per Claude

- **Elaborare una lezione = far girare `main.py` (o `watch.py --process`).** La sequenza dei 6 step è già scritta in Python — non eseguire gli step manualmente uno a uno, non riscrivere logica già presente nei moduli.
- **Tutto ciò che riguarda il progetto resta dentro questa cartella.** Nessuno script deve scrivere file in `Il mio Drive`, `OneDrive` o altri percorsi personali dell'utente fuori da `DeutschOps/`. Il backup del Google Doc (`doc_writer.backup_doc`) esporta un `.docx` locale in `doc_snapshots/backups/`, non crea più copie nel Drive personale di Kevin. Se serve un nuovo output "verso l'esterno", chiedere prima.
- **File temporanei o script one-off vanno rimossi subito dopo l'uso** (sia lo script che gli eventuali output generati), non lasciati nella root del progetto. Non creare file `_tmp_*`, `test_*` improvvisati e dimenticarli.
- **Verificare periodicamente `.tmp.driveupload/`** nella root: non è generato da nessuno script del progetto — è lo staging locale di Google Drive per Desktop, segno che questa cartella (o una superiore) è inclusa nel backup automatico "Il mio computer" di Drive. Va escluso dalle impostazioni di Google Drive per Desktop, non da qui.

## Elaborazione locale con Ollama (PC fisso)

Sul PC fisso (Intel i7 4 core, GTX 980) l'estrazione strutturata (step 3, `extractor.py`) e il quaderno errori (`error_extractor.py`) possono girare su un LLM locale via Ollama invece che sull'API Anthropic a pagamento.

**Modello scelto:** `qwen2.5:7b-instruct` — miglior compromesso su questo hardware per estrazione JSON strutturata multilingua (tedesco/italiano/inglese); quantizzato Q4_K_M di default in Ollama (~4.7GB, gira con offload parziale GPU+CPU sulla GTX 980 da 4GB VRAM — lento ma accettabile per un job settimanale, non realtime).
Fallback più leggero/veloce se il 7B risulta troppo lento: `llama3.2:3b-instruct` (entra interamente in 4GB VRAM, qualità di estrazione inferiore).

**Setup una tantum sul PC fisso:**
```powershell
winget install Ollama.Ollama
ollama pull qwen2.5:7b-instruct
ollama pull llama3.2:3b-instruct   REM fallback opzionale, più veloce
```
Ollama parte come servizio locale su `http://localhost:11434` dopo l'installazione.

**Attivazione nel progetto** — impostare in `.env` (solo su quel PC):
```
LLM_BACKEND=ollama
OLLAMA_MODEL=qwen2.5:7b-instruct
OLLAMA_HOST=http://localhost:11434
```
Senza `LLM_BACKEND=ollama` il progetto usa Anthropic Claude come sempre (default).

**Limiti noti del backend Ollama:**
- L'arricchimento grammaticale via web search (Call 2 in `extractor.py`, ricerca su dartmouth/germanveryeasy/duden) resta solo Anthropic — Ollama non ha web search; con `LLM_BACKEND=ollama` viene saltato e i grammar_points restano alla spiegazione base.
- `grammar_book.py`, `pharma_glossary.py`, `b1_gap.py`, `weak_cards.py`, `book_extractor.py`/`book_reader.py`, `bulk_import*.py` usano ancora direttamente Claude e non sono collegati a `LLM_BACKEND` — girano solo quando eseguiti esplicitamente (non fanno parte della chiamata automatica per-lezione di `main.py`, tranne `grammar_book.update_from_lesson` che però non chiama l'AI, solo rigenera il PDF da dati già estratti).
- La trascrizione (`transcriber.py`) resta separata da Ollama: usa già `WHISPER_MODE=local` (faster-whisper, CPU, gratis) — nessuna modifica necessaria lì.

## Contesto progetto

Kevin (manager di produzione in transizione verso pharma svizzero, area Basilea) usa questo sistema per le lezioni settimanali con Stefanie, insegnante nativa. Obiettivo: A2→B1 in preparazione al mercato del lavoro svizzero tedesco.
