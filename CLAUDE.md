# DeutschOps

Pipeline AI per l'apprendimento del tedesco, obiettivo **Goethe-Zertifikat B2** (primavera 2027).
Automatizza il ciclo dalla lezione con l'insegnante Stefanie ai materiali di studio: trascrizione,
estrazione, flashcard Anki a tre direzioni, PDF, aggiornamento del Google Doc condiviso — e il
livello che chiude l'anello: esercizi generati dagli errori reali, gap analysis verso il B2,
promemoria di cosa non sta girando.

## Come eseguire

Un entry point solo. Non ci sono più script standalone da lanciare a mano.

```powershell
$env:PYTHONIOENCODING = "utf-8"

venv\Scripts\python.exe deutschops.py lezione "Audiolessons\Deutsch mit Kevin - 2026_07_28.mp4" 2026-07-28-stefanie
venv\Scripts\python.exe deutschops.py lezione --auto        # elabora i video senza transcript
```

> ⚠️ **Usa `venv\Scripts\python.exe`, NON `py -3`.** Su questa macchina il launcher `py -3` ignora
> il venv anche dopo `venv\Scripts\activate` e gira sul Python di sistema, che **non** ha
> `anthropic`/`google-*`: la pipeline crasha a fase 3 con `No module named 'anthropic'`. Le fasi
> completate non si rifanno, quindi basta rilanciare lo stesso comando col python del venv (resume
> automatico). Verificato 2026-08-10.

| Comando | Cosa fa | Costo |
|---|---|---|
| `lezione <file> [data]` | La pipeline completa | ~0,25 € |
| `lezione --auto` | Rileva ed elabora i video nuovi | ~0,25 €/lezione |
| `briefing` | Il riquadro di avvio (lo stampa l'hook) | 0 |
| `stato` | Rigenera `stato/stato-tedesco.md` | 0 |
| `pendenti` | Run non completati · `--recupera` · `--archivia` | 0 |
| `esame` | Gap analysis verso il curriculum B2 | ~0,05 € |
| `drill [-n 10]` | Esercizi di produzione dai tuoi errori | ~0,03 € |
| `esercizi [-n 20]` | Ricarica il deposito dell'app · `--coda` = anteprima · `--traduci` = solo traduzioni | ~0,09 € · 0 · ~0,02 € |
| `frasi [-n 20]` | Frasi i+1 dal tuo corpus | 0 |
| `carte <data>` | Carica in Anki le carte di una lezione | 0 |
| `vocabolario [-n 80]` | Backfill traduzione inglese delle frasi d'esempio (storiche) | 0 (abbonamento) |
| `libro [-n 15]` | OCR del Kursbuch, a lotti riprendibili | 0 (abbonamento) |
| `doc-immagini` | Salva in locale le immagini del Doc | 0 |
| `grammatica --applica` | Approfondisce le regole rimaste indietro | ~0,02 €/regola |
| `anki-audit` / `anki-ripara` | Difetti del mazzo e correzione | 0 |
| `ponte` | Check verso il motore di `shared start up/` | 0 |
| `confronta <data>` | Rielabora e confronta con la v1 | ~0,15 € |
| `motore` | Quale backend LLM è attivo, e una prova che risponde | 0 |

I costi in tabella sono quelli **a consumo**. `--motore claude` li porta a zero mettendo il
lavoro sull'abbonamento Claude Code — vale per ogni comando, dettagli in § *Chi paga*:

```powershell
venv\Scripts\python.exe deutschops.py --motore claude esercizi --libreria 200
```

**Prerequisiti:** Anki aperto con AnkiConnect su `localhost:8765` · `.env` con le chiavi ·
`credentials.json` + `token.json` (Google OAuth2). Per `--motore claude` serve invece Claude Code
installato e **autenticato in interattivo almeno una volta** su questa macchina.

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
| **Cloze** | una frase con un buco — libro prima, lezione filtrata dopo | il contesto, non la parola isolata |

Sottodeck separati (`::Riconoscimento`, `::Produzione`, `::Cloze`): FSRS pianifica ogni direzione
per conto suo. FSRS attivo, retention desiderata 90%.

### Il libro come fonte di frasi vere (dal 2026-08-13)

Le frasi Cloze **non sono più solo dal transcript**. `do/sapere/libro.py` fa OCR del Kursbuch
(`Book/daf-kompakt-neu-a1-b1-kursbuch.pdf`, 307 pagine, più le due appendici di trascrizione audio,
43 + 14) via `deutschops.py libro [-n 15]` — a lotti, riprendibile, **sempre backend abbonamento**
(mai API): un lotto grosso urta la quota dell'abbonamento e si ferma pulito, si rilancia più tardi.
Vision via il tool `Read` di Claude Code (`do/base/llm.py:chiama_visione`), non l'API — verificato
che l'estrazione naive della sola immagine incorporata in una pagina PDF (pypdf) perde il testo
vettoriale sovrapposto: serve il rendering composito di PyMuPDF (`pymupdf`, ora dipendenza diretta).

`carte.py:_cloze()` cerca prima nel libro (`libro.cerca(parola)`); se la parola non c'è, usa
`example_de` della lezione ma solo se `_frase_utilizzabile()` — un controllo leggero, apposta
**diverso** da `frasi.completabile()` — dice che la frase basta a se stessa. Non riusare
`completabile()` qui: è tarato sul parlato spontaneo dei transcript (soglia 8 token), e applicato a
`example_de` (già curato dall'estrazione) scartava 44 frasi buone su 48 in una prova reale, solo
perché corte. Frasi diverse, filtri diversi.

`allenamento.prepara()` (esercizi drill) ora cerca anche lei una frase reale — libro, poi corpus
lezioni per somiglianza lessicale (`libro.cerca_riferimento`) — e la passa al modello come
riferimento di tono, non come stimolo da copiare: prima costruiva ogni frase dal nulla partendo solo
dal nome della regola, ed è lì che uscivano frasi senza senso. Per i temi B2 (fuori dal libro, che
si ferma a B1) prova la pipeline `ricerca_web.py` di `shared start up/` (CLAUDE.md root §3.1) —
best-effort, silenziosa se le chiavi non sono configurate.

`deutschops.py vocabolario [-n 80]` fa il backfill di `example_en` (traduzione inglese dell'intera
frase d'esempio, non solo della parola) sui `data/lezione_*.json` storici — sempre backend
abbonamento. `anki-audit`/`anki-ripara` includono ora un controllo dedicato per le Cloze già in Anki
prive di questa traduzione (`manutenzione.analizza_cloze()`/`ripara_cloze()`).

### Gli errori sono il curriculum

`data/error_db.json` ha 295 errori reali con la correzione di Stefanie accanto. `drill` ci
costruisce sopra esercizi di **produzione** in contesti nuovi — se riconosci la frase originale non
stai imparando.

**Il dato che orienta tutto: 130 errori su 294 (44%) sono Kasus, Genus, Präposition.** Tre facce
dello stesso sistema, e sono fondamenta A2/B1.

**Il quaderno ha due popolazioni, e non vanno mai sommate in silenzio.** Il campo `fonte` distingue
`"lezione"` (una forma che Stefanie ha corretto a voce — campo assente = lezione, per i record
storici) da `"studio"` (una risposta sbagliata nell'app, giudicata da un modello). Stesso file,
perché la coda dell'allenamento deve vederle entrambe; ma **ogni statistica filtra su `lezione`**:
`drill.carica_errori()`, `errori.pattern()`, `stato.py`, `esame.py`, il briefing dell'app. Senza
il filtro il numero di errori crescerebbe *studiando*, e la quota Kasus/Genus/Präposition
deriverebbe senza che nessuno se ne accorga. Chi aggiunge un consumatore nuovo usa
`errori.registrati()`, che ha già il default giusto.

`error_db.json` si scrive in modo **atomico e sotto lucchetto** (`errori.salva()`): da quando esiste
l'app non lo tocca più solo la pipeline a fine lezione, ma anche una richiesta web a ogni risposta
sbagliata. Non scriverlo mai con `write_text` diretto.

**Un esercizio dell'app deve avere un buco solo, la glossa e la traduzione.**
`allenamento.utilizzabile()` lo verifica in generazione **e** in servizio: chiedere una regola nel
prompt non è ottenerla, e un deposito generato prima di una regola nuova deve smettere di uscire da
solo, senza migrazioni.

| Campo | Cos'è | Perché |
|---|---|---|
| un solo `___` | il buco | con due buchi e una risposta non si sa cosa scrivere dove |
| `gloss` | l'inglese di **esattamente** ciò che va nel buco | *«Meine Firma hat eine neue Fabrik ___ gebaut»* ammette *im Norden*, *im Süden*, *in Berlin*: senza, misura se hai indovinato l'intenzione di chi l'ha scritto |
| `traduzione` | l'inglese dell'intera frase | senza, una frase illeggibile è un muro davanti a cui ci si ferma — e resta la riga utile per rileggerla dopo |

Nessuno dei due rivela la risposta, perché la risposta è la **forma tedesca** e una traduzione non
la esprime. Che non la contengano è comunque controllato in codice.

Tradurre non è rigenerare: `esercizi --traduci` aggiunge la traduzione a chi ne è privo per un
decimo del costo di rifare l'esercizio.

`errori.ritira(esercizio)` toglie dal quaderno gli errori nati da un esercizio segnalato come rotto.
Tocca **solo** i record `fonte: "studio"`: le correzioni di Stefanie non si ritirano.

`errori.chiave_regola()` normalizza il nome della regola. Serve perché quel nome lo scrive un
modello in linguaggio libero: sui 295 record ci sono **288 nomi distinti**, cioè la recidiva non
esisterebbe. Normalizzati scendono a 283, e due chiavi uguali sono la stessa regola **per
costruzione** — è l'unica relazione fra errori che si possa affermare invece che stimare.

### L'esame si misura da fuori, sempre

**Non costruire un simulatore d'esame con un punteggio.** Una prova inventata da un modello e
corretta dallo stesso modello produce un numero che assomiglia a un voto Goethe senza esserlo, ed è
proprio ciò che `stato/scadenze.md` esclude: l'evidenza esterna sono il **Modellsatz** e il
**giudizio di Stefanie**. `do/studio/modellsatz.py` registra i punteggi del PDF ufficiale, per
modulo, e calcola il delta fra tentativi — la derivata, che è quello che serve. I moduli non
tentati restano vuoti, mai zero.

`do/studio/prova.py` fa l'altra metà: compiti di scrittura in formato Goethe, **senza voto**, con
commento sulle quattro dimensioni della griglia e gli errori concreti che finiscono nel quaderno
come `fonte: "studio"`. È allenamento, non misura, e lì il valore non è il commento — è che quegli
errori tornano come esercizi per settimane.

### Cosa non è una misura di progresso

Le **correzioni per lezione** non lo sono, e la zona Progress lo dice invece di nasconderlo:
misurato, 9,0 a lezione nella prima metà del periodo e 10,0 nella seconda, e comunque quel numero
dipende da quanto Kevin ha parlato e da quanto Stefanie ha corretto. Misura **esposizione**, come
la copertura del curriculum in `esame.py`. Il progresso lo misura ciò che l'app osserva
direttamente — quanti esercizi chiudi **senza aiuto**, e a che gradino ti fermi — e sotto le 20
risposte `progressi.py` dichiara che non basta invece di disegnare una tendenza.

Regola generale del progetto, già valida per il costo e per l'audit del mazzo: **prima di mostrare
un numero, verificare che dica quello che sembra dire.**

### Cercare, e cosa si può affermare

`do/sapere/indice.py` indicizza in memoria le quattro popolazioni — regole, vocaboli, correzioni e
i transcript spezzati in passi da 260 caratteri. 4.082 documenti, costruzione ~1 s all'avvio del
server in un thread, ricerca sotto i 30 ms. Nessuna dipendenza e nessun file di indice su disco da
tenere in sincrono: sbaglia solo finché il processo vive.

**La regola che governa questo modulo:** i nomi delle regole in `error_db` sono testo libero in
tedesco, quelli di `grammar_db` sono titoli in inglese. Fra le due popolazioni **non esiste una
relazione esatta**, e in F2 provare a costruirla per somiglianza di nome ha prodotto il 75% di falsi
positivi. Quindi `dettaglio()` restituisce due liste distinte — `esatti` (affermabili, via
`chiave_regola`) e `simili` (risultati di ricerca ordinati) — e **l'interfaccia deve dire quale
sta mostrando**. Un singolo risultato sbagliato presentato con sicurezza è peggio di tre risultati
mediocri presentati come tali.

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
  sapere/    vocaboli · grammatica · errori · indice · registro
  studio/    carte · frasi · composte · drill · allenamento · esame · sessione ·
             progressi · modellsatz · prova · manutenzione · singolari
  motore/    stato · briefing · scadenze · attivita · ponte
  uscite/    pdf (adattatori ReportLab) · web (l'app di studio)
web/         index.html · app.js · stile.css — l'interfaccia, vanilla e offline
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
| Estrazione | `claude-sonnet-5` — a consumo, su abbonamento, o Ollama locale (§ Chi paga) |
| Flashcard | AnkiConnect · der=blu, die=rosso, das=verde |
| PDF | ReportLab · Google Docs API (OAuth2) |
| Audio | `ffmpeg.exe` locale |

Il pensiero adattivo è **attivo di default** su Sonnet 5 quando `thinking` viene omesso, e
`max_tokens` limita pensiero e risposta **insieme**. Per l'estrazione JSON `do/base/llm.py` lo
disattiva esplicitamente: lasciarlo implicito con un `max_tokens` stretto tronca il JSON a metà.

### Chi paga: tre backend, uno strozzo

Ogni chiamata al modello passa da `llm.chiama()` — nessun modulo parla direttamente col client.
Il backend si sceglie con `--motore` (vale per ogni sottocomando) o con `LLM_BACKEND` in `.env`:

| `--motore` | Chi paga | Quando |
|---|---|---|
| `anthropic` (default) | token API, a consumo | percorsi **interattivi**: giudice delle risposte, correzione dal vivo |
| `claude` | **abbonamento** Claude Code | lavoro **a lotti**: libreria esercizi, estrazione lezione, verifica |
| `ollama` | niente, gira in locale | offline, o quando la qualità non conta |

`deutschops.py motore` dice quale è attivo e verifica che risponda davvero.

Misurato il 2026-07-31, stesso blocco di 8 esercizi B1, stesso prompt, 8/8 utilizzabili da
entrambi: **API 34,0 s e 0,0448 €** · **abbonamento 31,6 s e 0,0000 €** (0,0591 € nozionali).

Quattro cose che rendono il backend `claude` diverso da una semplice sostituzione, tutte
imparate rompendolo:

- **Una chiave API in ambiente vince sempre sull'abbonamento, in silenzio.** Con
  `ANTHROPIC_API_KEY` presente la CLI la usa e non ripiega mai su OAuth. E `config._carica_env()`
  mette quella chiave in `os.environ` all'import, quindi ogni sottoprocesso l'erediterebbe:
  le chiamate «sull'abbonamento» finirebbero sulla fattura, con il costo misurato che dice zero.
  `_ambiente_abbonamento()` la toglie prima di lanciare.
- **Niente testo su `argv`.** Su Windows `claude` è uno shim `.CMD`, quindi passa da `cmd.exe`,
  che **rianalizza** la riga di comando. Il prompt di sistema dell'allenamento (5.863 caratteri,
  con dentro `< > | "`) veniva riscritto e tutto ciò che seguiva — `--output-format json`
  compreso — spariva: la CLI rispondeva in prosa, exit 0, nessun errore. Prompt di sistema su
  **file**, prompt utente su **stdin**, su `argv` solo flag fisse.
- **`usage` non è la fonte del conteggio token:** su risposte a più iterazioni torna tutto a zero
  (visto su un transcript da 44 KB: 0,166 € nozionali e `usage` a zero). Si somma `modelUsage`.
- **La CLI non riprova da sola.** L'SDK ha `max_retries=5`; la CLI lascia uscire il primo 529 e
  ammazzerebbe un lotto di 20 blocchi a metà. `_RIPROVABILI` copre 500/502/503/504/529 — non 401
  (autenticazione, non migliora aspettando) e non 429 (quota finita, insistere la brucia).

E due limiti che restano, da tenere presenti quando si sceglie dove instradare cosa:

- **~1.000 token fissi di impianto a chiamata** (5.974 senza `--safe-mode` e `--system-prompt-file`),
  più ~0,7 s di avvio processo: **nessuna chiamata scende sotto i ~7 s**. Su un lotto da 25 si
  diluisce; sul giudice interattivo è il costo dominante e si sente a ogni risposta.
- **`max_tokens` e `thinking: disabled` non sono esponibili.** Il guardrail sul troncamento
  diventa un controllo su `stop_reason`, e al posto del pensiero spento c'è `--effort low` — che
  lo accorcia invece di spegnerlo. Senza quel flag lo stesso blocco costava 56,8 s invece di 31,6.

La quota dell'abbonamento è la **stessa** delle sessioni interattive di Claude Code: un lotto
grosso mangia la finestra di lavoro. È il vero prezzo di questo backend, e non compare in nessun
conto in euro — per questo `Uso.costo_nozionale_eur` esiste.

## Regole operative

- **Elaborare una lezione = `deutschops.py lezione`.** Non eseguire i passi a mano, non
  riscrivere logica che è già nei moduli.
- **Backend dell'estrazione = `claude` (abbonamento, NO API).** Elabora le lezioni con
  `deutschops.py --motore claude lezione <file> <data>`: qualità claude-sonnet a **€0** sull'abbonamento
  (consuma la finestra di quota, non la fattura API). Senza `--motore` il default è `anthropic` (API, a
  consumo) → passarlo sempre esplicito. **ollama è stato scartato per l'estrazione** (benchmark 2026-08-11:
  su questa macchina, 15,8 GB no GPU, il 7B sotto-estrae e i 14B/12B vengono uccisi al load per RAM). ollama
  **resta** per la vision (`qwen2.5vl`, OCR immagini Doc + salute kevin-os) e per altri ambienti (`llama3.2:3b`):
  non disinstallarlo né rimuovere modelli usati fuori da DeutschOps. I fix ollama in `do/base/llm.py`
  (structured-output, `num_ctx`, timeout) restano inerti sugli altri backend, utili se un giorno ci sarà
  RAM/GPU per riprovare il locale.
- **Tutto resta dentro questa cartella.** Nessuno script scrive in `Il mio Drive`, `OneDrive` o
  altri percorsi personali. Se serve un output verso l'esterno, chiedere prima.
- **File temporanei e script one-off si rimuovono subito dopo l'uso**, script e output.
- **`.tmp.driveupload/` nella root** non è generato da questo progetto: è lo staging di Google
  Drive per Desktop. Va escluso dalle impostazioni di Drive, non da qui.
- **La ricerca web è spenta di default.** Misurato sulle stesse regole: 0,5815 € a regola con
  ricerca, 0,0222 € senza, per un testo equivalente. L'approfondimento grammaticale resta — quello
  che cade è il giro sui siti esterni, che gonfia il contesto a ogni ricerca. Si perde solo
  `source_verified`. Per accenderla su una lezione: `$env:RICERCA_WEB=1; venv\Scripts\python.exe deutschops.py lezione ...`
- **Il backup .docx del Doc di Stefanie non esiste e non può esistere:** il documento supera il
  limite di export di Drive (112.000 caratteri, 108 immagini). Al suo posto ci sono due cose, e
  bastano: il testo in `doc_snapshots/snapshot_*.txt` a ogni lezione, e le immagini in
  `doc_snapshots/immagini/` — scaricate una per una (l'export in blocco fallisce, le singole no),
  in modo incrementale, dalla pipeline stessa. Resta fuori solo l'impaginazione.
- **Il costo si misura, non si stima.** `do/base/llm.py` restituisce il costo reale da
  `response.usage`; il registro marca `cost_estimated` su ciò che misurato non è. Nella v1
  `main.py` scriveva `claude_cost = 0.10` costante: 2,95 € dei 4,82 € storici sono quella costante
  moltiplicata per 30. Sul backend `claude` il costo è **zero davvero**, non stimato a zero — ma
  `costo_nozionale_eur` conserva quanto sarebbe costato a consumo, altrimenti non si può più
  rispondere a «quanto sta assorbendo l'abbonamento?» né accorgersi che un lotto è cresciuto fino
  a mangiare la finestra di quota.
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

## Graphify — knowledge graph (query-first, fallback grep) — dal 2026-08-07

Portato dal motore di `shared start up/` (regola **E27**). Metodo/doc completa:
`shared start up/risorse-team/skills/ricerca-e-analisi/graphify/scheda.md` + `roadmap-mappatura.md`.

- **Comportamento query-first (automatico, ogni richiesta):** prima di grep-are o leggere i file
  per rispondere a una domanda sul contenuto di DeutschOps (cosa si è coperto in una lezione, dove
  sta una regola, come funziona un pezzo di pipeline), **prova prima**
  `graphify query "<domanda>"` / `explain` / `path` sul grafo in `graphify-out/graph.json` — gratis
  (traversal locale BFS, zero token LLM), individua subito i file giusti.
- **Fallback silenzioso e automatico, sempre:** se il grafo non risponde, il tool non è installato,
  o il corpus è cambiato dall'ultimo build → procedi **subito** con grep/Read come sempre, **senza
  errori e senza chiedere**. È un'istruzione di comportamento, non un hook tecnico (deliberatamente
  NON `graphify claude install --project`: scriverebbe un `.claude/` hook in una cartella
  Drive-sincronizzata e si romperebbe dove graphify manca; il fallback qui funziona anche
  disinstallato).
- **Copertura (build 2026-08-07):** `graphify-out/graph.json` = **965 nodi, 2030 archi, 54
  community** — 54 file di codice (`do/`, `deutschops.py`, `tools/`, AST) + i **31 transcript
  lezione** (`transcripts/*.txt`, mappati come doc) + i doc `.md`. **Esclusi** (`.graphifyignore`):
  segreti (`.env`, `credentials.json`, `token.json`), i ~5 MB di JSON dati-macchina (`data/`,
  word-timing — si leggono diretti con Read), i PDF generati (`Book/`), media (`Audiolessons/`),
  binari (`ffmpeg.exe`). `graph.html` navigabile, `GRAPH_REPORT.md` leggibile.
- **⚠️ Rebuild richiede due flag non ovvi** (imparati sul primo build): il `.gitignore` di
  DeutschOps esclude `transcripts/`, `data/`, `Book/`, `tools/` → serve **`--no-gitignore`** perché
  graphify li veda (dà priorità a `.graphifyignore`); e i transcript sono `.txt`, che graphify non
  tratta come doc → nello scratch vanno **rinominati `.txt`→`.md`** prima dell'estrazione. Comando
  completo: `graphify extract <scratch> --backend claude-cli --no-gitignore --force`.
- **Rebuild manuale e costoso** (~1M token in via `claude-cli`, i transcript sono densi). Non
  agganciato a git. `graphify check-update .` è gratis (0 token) — dice N file cambiati; rilancia
  con `graphify update .` solo quando conviene. Serve il workaround Google Drive (copia corpus
  fuori-Drive → estrai → ricopia `graphify-out/` → ri-punta `.graphify_root` a questo dominio),
  perché i reparse-point di Drive bloccano `Path.resolve()`.
- **PRIVACY / firewall (non negoziabile):** il grafo contiene contenuti privati delle lezioni e
  note su Stefanie. Resta **dentro DeutschOps** — output mai fuori dal dominio, mai in
  `shared start up/`. **MAI** `graphify global add` / `merge-graphs` tra domini. Backend semantico
  **solo `claude-cli`** (nessuna API key, `claude` locale); **mai `--backend gemini`** — spedirebbe
  il contenuto delle lezioni a un servizio esterno.
