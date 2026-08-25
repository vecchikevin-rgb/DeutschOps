# \_archivio — il codice della v1, spostato non cancellato

Contiene i moduli che la riscrittura v2 ha sostituito o chiuso. Sono qui e non
in `git rm` per un motivo pratico: se un giorno serve capire *come* la v1
faceva una certa cosa, leggerla e' piu' veloce che scavare nella cronologia.

**Niente qui dentro viene importato dal codice vivo.** Il pacchetto `do/`
dipende solo da quattro moduli rimasti in root — `pdf_gen`, `grammar_book`,
`error_pdf`, `doc_writer` — che sono la parte di uscite/Google Docs non ancora
consolidata.

## Sostituiti dal pacchetto `do/`

| Archiviato | Sostituto |
|---|---|
| `main.py` | `do/lezione/pipeline.py` |
| `transcriber.py` | `do/lezione/audio.py` |
| `extractor.py` | `do/lezione/estrazione.py` |
| `doc_reader.py` | `do/lezione/doc.py` |
| `anki_feeder.py` | `do/studio/carte.py` (una carta -> tre direzioni) |
| `task_tracker.py` | `do/base/tracker.py` |
| `preflight.py` | `do/base/preflight.py` |
| `archive_cleanup.py` | `do/base/staging.py` |
| `lesson_registry.py` | `do/sapere/registro.py` |
| `vocab_db.py` | `do/sapere/vocaboli.py` |
| `error_extractor.py` | `do/sapere/errori.py` |
| `b1_gap.py`, `weak_cards.py`, `pharma_glossary.py` | `do/studio/esame.py` |
| `watch.py` | `deutschops.py lezione --auto` |
| `DeutschOps.bat`, `settings.json` | `deutschops.py` |

## Chiusi

| Archiviato | Perche' |
|---|---|
| `generate_astra_prompts.py` | Astra non e' mai esistito come integrazione: nessun `astrapy`, nessuna credenziale, nessun retrieval. Era un generatore di PDF da caricare a mano su un chatbot. Gli esercizi che conteneva rinascono in `do/studio/drill.py`, alimentati dai 284 errori reali invece che da un PDF. |
| `notebooklm_export.py` | Chiuso il 2026-07-26. |
| `dashboard.py`, `pages/` , `save_results.py` | Streamlit, mai aperto. Sostituito da `stato/stato-tedesco.md` e dal briefing all'avvio sessione. |
| `speaker_analysis.py` | 595 righe, una sola esecuzione, `speaker_stats.json` contiene `speaker_stats={}`: la funzione principale non ha mai funzionato. |
| `book_reader.py`, `book_extractor.py` | One-off gia' eseguiti. Il valore e' `data/book_db.json`, non lo script. |
| `bulk_import.py`, `bulk_import_book.py` | One-off dichiarati. Il secondo scriveva su Anki all'import, senza `if __name__`. |
| `retroactive_doc_images.py`, `enrich_lesson_pdfs.py` | Backfill gia' fatti. Il secondo scriveva `book_ref` nei JSON e rigenerava 31 PDF che non lo mostrano: `pdf_gen.py` non contiene quella stringa. |
| `export_to_obsidian.py` | 668 righe orfane, con default a `C:\Users\vecch\ObsidianVault\`. Scrivere fuori da `DeutschOps/` viola le regole del progetto. Se l'export verso il secondo cervello serve, si decide in `kevin-os/`. |

## Come tornare indietro

```
git mv _archivio/<file>.py .
```

La cronologia e' intatta: `git log --follow _archivio/<file>.py`.
