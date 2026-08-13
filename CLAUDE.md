# DeutschOps

Pipeline AI per l'apprendimento del tedesco, obiettivo **Goethe-Zertifikat B2** (primavera 2027).
Automatizza il ciclo dalla lezione con l'insegnante Stefanie ai materiali di studio: trascrizione,
estrazione, flashcard Anki a tre direzioni, PDF, aggiornamento del Google Doc condiviso — e il
livello che chiude l'anello: esercizi generati dagli errori reali, gap analysis verso il B2,
promemoria di cosa non sta girando.

## Come eseguire

Un entry point solo. Non ci sono più script standalone da lanciare a mano.

```powershell
venv\Scripts\activate
$env:PYTHONIOENCODING = "utf-8"

py -3 deutschops.py lezione "Audiolessons\Deutsch mit Kevin - 2026_07_28.mp4" 2026-07-28-stefanie
py -3 deutschops.py lezione --auto        # elabora i video senza transcript
```

| Comando | Cosa fa | Costo |
|---|---|---|
| `lezione <file> [data]` | La pipeline completa | ~0,25 € |
| `lezione --auto` | Rileva ed elabora i video nuovi | ~0,25 €/lezione |
| `briefing` | Il riquadro di avvio (lo stampa l'hook) | 0 |
| `stato` | Rigenera `stato/stato-tedesco.md` | 0 |
| `pendenti` | Run non completati · `--recupera` · `--archivia` | 0 |
| `esame` | Gap analysis verso il curriculum B2 | ~0,05 € |
| `drill [-n 10]` | Esercizi di produzione dai tuoi errori | ~0,03 € |
| `frasi [-n 20]` | Frasi i+1 dal tuo corpus | 0 |
| `carte <data>` | Carica in Anki le carte di una lezione | 0 |
| `doc-immagini` | Salva in locale le immagini del Doc | 0 |
| `grammatica --applica` | Approfondisce le regole rimaste indietro | ~0,02 €/regola |
| `anki-audit` / `anki-ripara` | Difetti del mazzo e correzione | 0 |
| `ponte` | Check verso il motore di `shared start up/` | 0 |
| `confronta <data>` | Rielabora e confronta con la v1 | ~0,15 € |

**Prerequisiti:** Anki aperto con AnkiConnect su `localhost:8765` · `.env` con le chiavi ·
`credentials.json` + `token.json` (Google OAuth2).

## La pipeline

| Passo | Modulo | Operazione |
|---|---|---|
| preflight | `do/base/preflight.py` | Video corrotto (moov → auto-`untrunc`), token Google, Anki. **Non blocca mai**: avvisa e la pipeline degrada. |
| prep | `do/lezione/audio.py` | Backup audio **permanente** dal video grezzo (mai cancellato) — vedi § *Backup audio permanente* |
| prep | `do/lezione/audio.py` | Compressione ffmpeg se sopra i 20 MB (per Whisper, non per l'archivio) |
| 1 | `do/lezione/doc.py` | Google Doc di Stefanie, diff contro l'ultimo snapshot |
| 2 | `do/lezione/audio.py` | Whisper (locale di default) → `transcripts/lezione_{data}.txt` |
| 3 | `do/lezione/estrazione.py` | LLM → `data/lezione_{data}.json`, schema validato |
| 4 | `do/studio/carte.py` | Flashcard, tre direzioni |
| 5 | `do/uscite/pdf.py` | PDF lezione → `pdfs/` |
| 6 | `do/sapere/*` + `do/lezione/doc.py` | Database cumulativi, quaderno errori, riepilogo sul Doc |

### Degradazione: cosa succede quando qualcosa non c'è

È la parte più matura del progetto e non va toccata.

- **Anki chiuso** → la fase non viene marcata, il task resta aperto, il run dopo riparte da lì.
  Il resto della lezione (PDF, database, riepilogo) prosegue.
- **Token Google scaduto** → il passo 1 degrada a stringa vuota. Il diff è contesto ausiliario.
- **Snapshot del Doc** → commit **differito**, scritto solo a pipeline completa. Scriverlo prima e
  poi fallire sposterebbe il punto di riferimento del diff, perdendolo per sempre.
- **Fase completata** → non si rifà mai.

### Run rimasti aperti

`pendenti` li elenca; `pendenti --recupera` esegue ciò che manca ed è rifacibile (oggi: Anki);
`pendenti --archivia <data> --motivo "..."` chiude un task dichiarando irrecuperabile ciò che manca
— serve per il diff del Doc di una lezione vecchia, che non esiste più.

## Il metodo di studio

### Carte: tre direzioni, non una

| Direzione | Fronte | Perché |
|---|---|---|
| Riconoscimento | la parola tedesca, colorata per genere | com'era |
| **Produzione** | l'italiano + `(f.)`, **non** `die` | dare l'articolo svelerebbe proprio ciò che sbaglia: 27 errori di Genus |
| **Cloze** | una frase vera di Stefanie con un buco | il contesto, non la parola isolata |

Sottodeck separati (`::Riconoscimento`, `::Produzione`, `::Cloze`): FSRS pianifica ogni direzione
per conto suo. FSRS attivo, retention desiderata 90%.

### Gli errori sono il curriculum

`data/error_db.json` ha 284 errori reali con la correzione di Stefanie accanto. `drill` ci
costruisce sopra esercizi di **produzione** in contesti nuovi — se riconosci la frase originale non
stai imparando.

**Il dato che orienta tutto: 127 errori su 284 (45%) sono Kasus, Genus, Präposition.** Tre facce
dello stesso sistema, e sono fondamenta A2/B1.

### Il promemoria

`do/motore/attivita.py` misura in **lezioni**, non in giorni: due settimane senza lezioni non sono
un problema, tre lezioni elaborate senza un drill sì. Se `drill` salta 3 lezioni o `esame` ne salta
8, compare nel briefing sotto **MATERIALE FERMO**.

Nella v1 questo mancava: la pipeline ha macinato 30 lezioni mentre il loop di ripasso girava **una
volta**, l'11 giugno. Nessuno se n'è accorto per 45 giorni.

## Lezione senza video

Quando arriva solo una trascrizione esterna:

1. Copia il testo grezzo, verbatim e senza ripulirlo, in `transcripts/lezione_{data}.txt`.
2. Scrivi `transcripts/lezione_{data}.meta.json` = `{"duration_minutes": <minuti reali>, "cost_eur": 0}`.
   Senza, il registro segna una lezione di durata zero.
3. Lancia `deutschops.py lezione <il .txt> {data}`: il passo 2 salta perché il transcript esiste.

## Struttura

```
deutschops.py          entry point unico
do/
  base/      paths · config · llm · tracker · preflight · staging · recupero
  lezione/   audio · estrazione · doc · pipeline · confronto
  sapere/    vocaboli · grammatica · errori · registro
  studio/    carte · frasi · drill · esame · manutenzione · singolari
  motore/    stato · briefing · scadenze · attivita · ponte
  uscite/    pdf (adattatori sui generatori ReportLab)
stato/
  scadenze.md          l'UNICO markdown di stato scritto a mano
  stato-tedesco.md     GENERATO — non editare
_archivio/             la v1 e i 15 orfani. Vedi _archivio/LEGGIMI.md
```

I quattro moduli rimasti in root (`pdf_gen`, `grammar_book`, `error_pdf`, `doc_writer`) sono il
layer di uscita non ancora consolidato: 1.900 righe di ReportLab e di aritmetica sugli indici della
Docs API, che nessun test può verificare. Resi path-safe, consolidazione rimandata.

### Schema di `data/lezione_*.json`

Lo schema **reale**, non quello che la documentazione vecchia descriveva. È piatto:

```json
{
  "topic": "...",
  "summary_en": "...", "summary_it": "...",
  "vocabulary": [{"german": "Sorge", "article": "die", "plural": "Sorgen",
                  "category": "noun", "italian": "...", "english": "...",
                  "example_de": "...", "example_it": "...", "level": "B1"}],
  "grammar_points": [{"rule": "...", "explanation_en": "...", "examples": [],
                      "full_rule": "", "common_mistakes": "", "exceptions": ""}],
  "phrases": [], "comprehension_questions": [], "homework": "",
  "_schema": 2, "_costo_estrazione_eur": 0.0731, "_modello": "claude-sonnet-5"
}
```

`do/lezione/estrazione.py` lo **valida e fallisce rumorosamente**. Un vocabolo senza `german`
diventerebbe una carta con il fronte vuoto: meglio fermarsi dove si vede il perché.

## Stack

| Cosa | Con cosa |
|---|---|
| Runtime | Python 3.14, venv in `venv/` (**non** `.venv/`) |
| Trascrizione | faster-whisper locale, modello `small` (`WHISPER_MODE=local`, gratis) |
| Estrazione | Anthropic `claude-sonnet-5`, oppure Ollama locale (`LLM_BACKEND=ollama`) |
| Flashcard | AnkiConnect · der=blu, die=rosso, das=verde |
| PDF | ReportLab · Google Docs API (OAuth2) |
| Audio | `ffmpeg.exe` locale |

Il pensiero adattivo è **attivo di default** su Sonnet 5 quando `thinking` viene omesso, e
`max_tokens` limita pensiero e risposta **insieme**. Per l'estrazione JSON `do/base/llm.py` lo
disattiva esplicitamente: lasciarlo implicito con un `max_tokens` stretto tronca il JSON a metà.

## Regole operative

- **Elaborare una lezione = `deutschops.py lezione`.** Non eseguire i passi a mano, non
  riscrivere logica che è già nei moduli.
- **Tutto resta dentro questa cartella.** Nessuno script scrive in `Il mio Drive`, `OneDrive` o
  altri percorsi personali. Se serve un output verso l'esterno, chiedere prima.
- **File temporanei e script one-off si rimuovono subito dopo l'uso**, script e output.
- **`.tmp.driveupload/` nella root** non è generato da questo progetto: è lo staging di Google
  Drive per Desktop. Va escluso dalle impostazioni di Drive, non da qui.
- **La ricerca web è spenta di default.** Misurato sulle stesse regole: 0,5815 € a regola con
  ricerca, 0,0222 € senza, per un testo equivalente. L'approfondimento grammaticale resta — quello
  che cade è il giro sui siti esterni, che gonfia il contesto a ogni ricerca. Si perde solo
  `source_verified`. Per accenderla su una lezione: `RICERCA_WEB=1 py -3 deutschops.py lezione ...`
- **Il backup .docx del Doc di Stefanie non esiste e non può esistere:** il documento supera il
  limite di export di Drive (112.000 caratteri, 108 immagini). Al suo posto ci sono due cose, e
  bastano: il testo in `doc_snapshots/snapshot_*.txt` a ogni lezione, e le immagini in
  `doc_snapshots/immagini/` — scaricate una per una (l'export in blocco fallisce, le singole no),
  in modo incrementale, dalla pipeline stessa. Resta fuori solo l'impaginazione.
- **Il costo si misura, non si stima.** `do/base/llm.py` restituisce il costo reale da
  `response.usage`; il registro marca `cost_estimated` su ciò che misurato non è. Nella v1
  `main.py` scriveva `claude_cost = 0.10` costante: 2,95 € dei 4,82 € storici sono quella costante
  moltiplicata per 30.
- **Prima di dichiarare un difetto del mazzo, verificarlo.** L'audit ha prodotto quattro falsi
  positivi in fila — tag letti da `cardsInfo` (che ritorna sempre `None`), generi dedotti da
  suffissi senza eccezioni, plurali pretesi da Singularetantum, colori di genere cercati su carte
  che il tedesco davanti non ce l'hanno. Una regola senza le sue eccezioni produce rumore, e il
  rumore fa smettere di leggere.

## Staging degli input (`Audiolessons/_processed/`)

A fine di ogni elaborazione **riuscita** l'input consumato (il video originale, o il `.txt` grezzo)
va in `Audiolessons/_processed/`, e viene cancellato dopo **20 giorni**. Il cleanup è
opportunistico, gira all'avvio di ogni run: nessuno scheduler.

Non ci finiscono mai i file canonici (`transcripts/`, `data/`, `pdfs/`) né i
`lezione_*-compressed.mp4`, referenziati dal registro. `do/base/staging.py` li protegge
esplicitamente. Per le lezioni senza audio il transcript è **irrecuperabile**.

## Backup audio permanente (`Audiolessons/_archivio_audio/`)

Ad ogni lezione con video, **prima** di qualunque compressione o staging,
`do/lezione/audio.py:archivia_audio_grezzo()` estrae l'audio dal video grezzo e lo salva **per
sempre** in `Audiolessons/_archivio_audio/lezione_{data}.m4a`.

Non è il `-compressed.mp4` dello step "prep" sopra: quello è scarnificato per Whisper (16kHz mono
32k) e ottimizzato per la trascrizione, non per la qualità. Questo backup tiene il flusso audio
il più vicino possibile all'originale — copia bit-esatta del flusso audio se il codec sorgente lo
permette (`-acodec copy`), altrimenti ricodifica AAC 128k stereo 44,1kHz — e serve a poter
rielaborare la lezione in futuro (un modello diverso, un Whisper più grosso, un errore scoperto
tardi nell'estrazione) anche dopo che il video originale — che va in staging e scade in 20 giorni,
vedi sopra — non c'è più.

- **Non scade mai.** `do/base/staging.py:_protetto()` esclude esplicitamente `_archivio_audio/`,
  come già faceva per `-compressed.mp4`. Nessun cleanup lo tocca.
- **Peso trascurabile rispetto al video**: un m4a a ~128kbps di una lezione da 60' pesa qualche MB
  contro le centinaia (fino a >1 GB) del video sorgente in `_processed/` — lo spazio non è un
  problema anche tenendolo per sempre.
- **Idempotente**: se `lezione_{data}.m4a` esiste già non lo rifà.
- **Non blocca mai la pipeline**: un fallimento nell'estrazione stampa un avviso e la lezione
  prosegue — non è un requisito, è un'assicurazione.
- Esclusa da graphify come tutto `Audiolessons/` (media, vedi `.graphifyignore`).

## Il ponte con `shared start up/`

`do/motore/ponte.py` controlla ogni 14 giorni se nel motore condiviso è comparso qualcosa di
riusabile qui. **Sola lettura, a senso unico.** Importa metodo — skill, prompt, protocolli — mai
dati. Nulla di DeutschOps esce da questa cartella: vedi il firewall di privacy nel `CLAUDE.md` della
root del workspace. Se Drive è offline, tace.

## Contesto

Kevin (manager di produzione in transizione verso il pharma svizzero, area Basilea) fa lezione
settimanale con Stefanie, insegnante madrelingua. Obiettivo: **B2 entro la primavera 2027**, con il
Modellsatz come misura esterna invece di una metrica che il sistema si autoproduce.
