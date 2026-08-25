# Piano di riscrittura — DeutschOps v2

> **Data:** 2026-07-26 · **Stato:** in esecuzione, S0 completato (`6eb2c66`)
> **Base:** audit automatico su 32 moduli Python + estrazione pattern da `shared start up/_engine`
> **Decisioni già prese:** riscrittura da zero · ponte via hook `SessionStart` · sicurezza dati fatta (`1ca4ed5`)

---

## ⚠️ Aggiornamento 2026-07-26 — l'obiettivo è cambiato, e con lui le priorità

Kevin ha fissato l'obiettivo: **Goethe-Zertifikat B2 entro ottobre 2026**. Non B1.
Sono **10 settimane** alla prima finestra utile, 14 all'ultima.

**Cosa cambia nel piano.** Era calibrato su un progetto senza scadenza, e in quella
forma metteva 3-4 sessioni di infrastruttura (S0→S3) prima di toccare il metodo (S4).
Con una data d'esame a 10 settimane quell'ordine è sbagliato: l'architettura non fa
guadagnare un punto all'esame. **Il metodo passa davanti all'infrastruttura.**

| Prima | Adesso |
|---|---|
| S0 → S1 → S2 → S3 → S4 | S0 ✅ → **scadenze + gap B2** ✅ → **S4 metodo** → S1/S2/S3 quando c'è tempo |

`main.py` continua a elaborare le lezioni per tutto il periodo: la migrazione
dell'infrastruttura può aspettare novembre, l'esame no.

**Cosa dicono i dati, onestamente.** Il `vocab_db` conta 1.048 parole di cui **3 a
livello B2 o oltre**, e le categorie d'errore più frequenti sono Kasus (60),
Wortwahl (55), Verbform (44), Wortstellung (42), Präposition (40), Genus (27) —
cioè casi, generi e preposizioni, che sono fondamenta A2/B1, non materiale B2.

Quei numeri **non misurano Kevin**: misurano cosa la pipeline ha estratto da 10
settimane di lezioni. Sono un limite inferiore, non una valutazione. Ma sono anche
l'unica cosa che il sistema sa — ed è il motivo per cui la prima scadenza in
`stato/scadenze.md` non è l'esame, è un **Modellsatz cronometrato entro il 2 agosto**.
Senza quel numero, ogni stima su ottobre è congettura, mia e sua.

**La leva strategica:** il B2 Goethe è **modulare**. Lesen, Hören, Schreiben e
Sprechen si sostengono separatamente e si superano uno per uno. Con 10 settimane non
serve essere pronti su tutto a ottobre: si danno i moduli che il Modellsatz dice
pronti, gli altri dopo.

### Le due scelte che Kevin ha delegato a me

**NotebookLM → si chiude.** Non è una riparazione che vale 10 settimane prima di un
esame: è fallito 12 volte di fila dal 12 giugno dentro un `try/except` che stampa e
prosegue, dipende da una sessione browser Playwright che scade, viene invocato come
sottoprocesso perché il wrapper console dell'installazione è rotto, e trascina 107 MB
di dipendenza. La funzione che serviva — un cervello esterno con cui ripassare —
passa all'agente `tutor-tedesco` locale, che legge gli stessi JSON senza rete, senza
login e senza scadere.

**Dashboard Streamlit → si chiude.** Kevin non l'ha mai aperta. Ferma da 66 giorni
mentre tutto il resto veniva rifattorizzato, con un KPI finto (il costo) e cieca
proprio su `error_db`, che è il dato più utile che ha. Muore con `pages/1_Exercises.py`
e `save_results.py`, e porta via `streamlit`, `plotly`, `pandas`, `altair`, `pydeck`.
La sostituisce `stato/stato-tedesco.md`, generato da script e mostrato dal briefing
all'avvio — senza doverlo aprire, che è esattamente il motivo per cui la dashboard
non veniva aperta.

---

---

## 0. In una pagina

DeutschOps non è rotto: è **cresciuto per accumulo**. Il cuore gira bene (30 lezioni, 1.048 vocaboli,
296 regole, 284 errori, ultima run 3 giorni fa) ma solo **17 moduli su 32 sono raggiungibili** da
`main.py`. Gli altri 15 sono script one-off eseguiti una volta a maggio-giugno e mai più, che però
continuano a costare: `speaker_analysis.py` da solo trascina torch + pyannote + speechbrain +
lightning, ~40 pacchetti, per un output di 548 byte del 22 maggio.

Il problema vero però non è il codice morto. È che **il sistema archivia le lezioni invece di
farti imparare**. La prova sta in `anki_feeder.py:114-161`: ogni carta è tedesco → italiano, note
type `Basilare`, una direzione sola. Nessuna produzione, nessun cloze, nessun audio. Il sistema ti
allena a *riconoscere* il tedesco, mai a *produrlo* — che è esattamente ciò che ti serve per lavorare
a Basilea, e ciò che l'esame B1 misura.

Il piano: riscrittura in un package pulito (~20 moduli), il layer di orchestrazione preso dal motore
condiviso ma **generato da script e non affidato alla disciplina**, e il metodo di studio ricostruito
attorno alla produzione attiva.

---

## 1. L'architettura scelta

### 1.1 Il principio

Tre livelli, con una regola sola: **ogni livello superiore può leggere quello sotto, mai il contrario.**

| Livello | Cos'è | Chi lo scrive |
|---|---|---|
| **Sapere** | i 3 DB cumulativi + registro. L'asset di valore. | solo la pipeline, mai a mano |
| **Braccio** | la pipeline che macina la lezione | codice deterministico |
| **Cervello** | cosa studiare, quando, e come si sta andando | script + skill Claude Code |

Il motore condiviso mette in guardia proprio qui: nel suo caso il "cervello" è markdown scritto a
mano, e **è fallito**. `log-loop.md` ha una sola riga di 5 settimane fa. `stato-sistema.md` è vecchio
di 20 giorni e lo ammette da solo. La stessa patologia esiste già da te: `/weekly-maintenance` ha
`disable-model-invocation: true` e non è mai partito in 45 giorni.

**Conclusione operativa, che vale per tutto il documento: se una cosa deve girare, la fa scattare un
hook o uno script. Mai una regola scritta in un markdown.**

### 1.2 L'albero

```
DeutschOps/
├─ deutschops.py              UNICO entry point CLI. Sottocomandi: lezione, studio,
│                             stato, briefing, ponte, migra. Sostituisce main.py +
│                             watch.py + DeutschOps.bat + i 15 script standalone.
├─ pyproject.toml             Sostituisce requirements.txt (oggi è un pip freeze da
│                             186 pacchetti, ~600 MB fra torch e playwright).
├─ CLAUDE.md                  Riscritto: schema JSON corretto, zero Astra.
├─ README.md                  Riscritto (oggi dice ancora "A2 to B2").
│
├─ do/
│  ├─ base/
│  │  ├─ paths.py             Tutti i path ancorati a Path(__file__).parent.
│  │  │                       Oggi sono relativi alla cwd: lanci da un'altra cartella
│  │  │                       e il progetto crea directory nel posto sbagliato in silenzio.
│  │  ├─ config.py            .env + DOC_ID + KPI_TAB_ID. Oggi il DOC_ID di Stefanie
│  │  │                       è hardcoded in TRE file (doc_reader:17, doc_writer:11,
│  │  │                       retroactive_doc_images:29).
│  │  ├─ llm.py               UNICO client: backend anthropic|ollama, modello, pricing,
│  │  │                       retry, e restituisce il COSTO REALE. Oggi la logica è
│  │  │                       duplicata 2 volte e ignorata da 7 moduli.
│  │  ├─ tracker.py           ← PORTATO da task_tracker.py
│  │  ├─ preflight.py         ← PORTATO da preflight.py
│  │  └─ staging.py           ← PORTATO da archive_cleanup.py
│  │
│  ├─ lezione/
│  │  ├─ audio.py             UN solo modulo audio: probe + compress + transcribe.
│  │  │                       Oggi la compressione ffmpeg è implementata due volte con
│  │  │                       due soglie diverse (main 20MB / transcriber 24MB) e la
│  │  │                       versione di transcriber usa os.system, il bug che main.py
│  │  │                       documenta come già risolto.
│  │  ├─ estrazione.py        LLM → JSON. Schema VERSIONATO e validato.
│  │  └─ doc.py               Google Doc di Stefanie, con dedup per hash: 5 snapshot su
│  │                          30 sono byte-identici al precedente.
│  │
│  ├─ sapere/
│  │  ├─ vocaboli.py  grammatica.py  errori.py  registro.py
│  │
│  ├─ studio/                 ← IL LIVELLO NUOVO
│  │  ├─ carte.py             Generatore Anki multi-direzione (§3.2)
│  │  ├─ frasi.py             Sentence mining i+1 (§3.3) — deterministico
│  │  ├─ drill.py             Esercizi dagli errori reali (§3.4) — sostituisce Astra
│  │  ├─ tts.py               Audio sulle carte (§3.5)
│  │  └─ esame.py             Gap B1 + Modellsatz. Assorbe b1_gap + weak_cards +
│  │                          pharma_glossary in un comando solo.
│  │
│  ├─ uscite/
│  │  ├─ tema.py              UNA palette. Oggi gli stessi hex sono copiaincollati in
│  │  │                       4 generatori ReportLab (~200 righe replicate 4 volte).
│  │  └─ pdf_lezione.py  pdf_grammatica.py  pdf_errori.py
│  │
│  └─ motore/                 ← IL LAYER PRESO DA shared start up
│     ├─ stato.py             GENERA stato/stato-tedesco.md
│     ├─ briefing.py          Il riquadro di avvio sessione
│     └─ ponte.py             Il check periodico verso il motore condiviso (§4)
│
├─ stato/
│  ├─ stato-tedesco.md        GENERATO — non editare a mano
│  ├─ scadenze.md             L'UNICO markdown scritto a mano: data esame + milestone
│  └─ ponte-motore.json       Stato del check verso shared start up
│
├─ .claude/
│  ├─ settings.json           + hook SessionStart
│  ├─ hooks/                  briefing.ps1 (nuovo) + i 2 esistenti, invariati
│  ├─ agents/                 tutor-tedesco.md (nuovo) · pipeline-debugger.md (riscritto)
│  └─ skills/                 lezione/ · ponte-motore/
│
├─ data/ transcripts/ pdfs/ Audiolessons/     invariati
└─ _archivio/                 I 15 orfani. Spostati, non cancellati.
```

### 1.3 Cosa muore

**15 moduli** → `_archivio/`, non cancellati:

| Modulo | Perché |
|---|---|
| `speaker_analysis.py` | 595 righe, 1 esecuzione, `speaker_stats.json` ha `speaker_stats={}` e `identification={}` — la funzione principale non ha **mai** funzionato. Da solo giustifica ~40 dipendenze. |
| `book_reader.py` | Doppione di `book_extractor.py`, abbandonato 2 giorni dopo esserci nato. |
| `book_extractor.py` | One-off già eseguito. Il valore è `book_db.json` (2 MB), non lo script. |
| `bulk_import.py` · `bulk_import_book.py` | One-off dichiarati. Il secondo **esegue all'import**: nessun `if __name__`, scrive su Anki alla riga 13. |
| `retroactive_doc_images.py` | Backfill già fatto. Reimplementa la vision di `doc_reader` con prompt copiaincollato parola per parola. |
| `enrich_lesson_pdfs.py` | Scrive `book_ref` nei JSON e rigenera 31 PDF che **non lo mostrano** — `pdf_gen.py` non contiene la stringa `book_ref`. Lavoro invisibile. |
| `export_to_obsidian.py` | 668 righe orfane, default a `C:\Users\vecch\ObsidianVault\` — viola `CLAUDE.md:152` (niente scritture fuori da DeutschOps/). Se l'export verso il secondo cervello serve, si decide in `kevin-os/`, non qui. |
| `generate_astra_prompts.py` | Vedi §1.4. |
| `b1_gap.py` · `weak_cards.py` · `pharma_glossary.py` | Confluiscono in `studio/esame.py`. Tre script, tre client, tre prompt per un'unica domanda ("cosa devo studiare"). Fermi all'11 giugno. |
| `watch.py` | Cerca `"Classroom with Stefanie*.mp4"`, i file oggi si chiamano `"Deutsch mit Kevin - 2026_07_22..."`. Stampa sempre "nessuna lezione nuova". Il rilevamento serve — il pattern no. Rinasce come `deutschops.py lezione --auto`. |
| `dashboard.py` · `pages/1_Exercises.py` | Vedi §8, domanda aperta. |
| `save_results.py` | 977 byte, dipende solo dalla pagina Streamlit. |

Muoiono anche: `DeutschOps.bat` e `settings.json` (root) — puntano a `C:\Users\vecch\DeutschOps`,
cartella che **non esiste più**, il progetto è stato spostato sotto `Antigravity/`. Il `.bat` è
indicato dal README come metodo di lancio ed è inutilizzabile da quando l'hai spostato.

E muore il ramo `visual_context` di `extractor.py:195-225`, che importa `frame_extractor` — un file
mai esistito in git. Oggi non esplode solo perché nessuno passa quel parametro.

### 1.4 Astra: cosa va via davvero

Astra **non è mai esistito** come integrazione. Nessun `astrapy`, nessuna credenziale, nessun
retrieval, nessun chunking. `generate_astra_prompts.py` è un generatore ReportLab che produce PDF da
caricare a mano su un chatbot. La stringa "vector DB" compare una volta in tutto il progetto:
`CLAUDE.md:104`, ed è falsa.

Via: `generate_astra_prompts.py` + i 31 PDF di `astra_prompts/` (rigenerabili al 100% dai JSON —
niente da archiviare) + 6 punti di testo in `main.py`, `CLAUDE.md`, `pipeline-debugger.md`,
`book_reader.py`.

⚠️ `astra_prompts/` **non è in `.gitignore`** (a differenza di `pdfs/`, `data/`, `transcripts/`):
i 31 PDF sono versionati. Vanno rimossi dall'indice, non solo dal disco.

Due benefici collaterali non ovvi:

1. `generate_all_prompts()` a `main.py:252` è **l'unico step post-pipeline non protetto da
   try/except**. `doc_writer`, quaderno errori e NotebookLM sono tutti avvolti; questo è nudo. Un
   JSON malformato fra i 31 e la lezione fallisce *dopo* trascrizione, estrazione, Anki e PDF.
2. Rigenera **tutti** i 31 PDF a ogni lezione (tutti con mtime identico `2026-07-23 14:53`). È la
   causa principale per cui `git status` mostra 38 file modificati e non capisci più cosa è cambiato.

**Ma la funzione non muore.** Il PDF conteneva un blocco `EXERCISES TO GENERATE` con 6 tipi di drill
(fill-in-the-blank, DE→EN, EN→DE, completamento dialoghi, free writing, grammar drill sugli errori) e
5 regole di correzione. Di questi, solo il fill-in-the-blank è già coperto offline da
`pdf_gen.make_exercises`. Il resto rinasce in `studio/drill.py` + l'agente `tutor-tedesco`, che
consumano direttamente `error_db.json` — 138 KB di errori tuoi reali con le correzioni di Stefanie —
invece di un PDF da caricare a mano.

---

## 2. Il confine LLM / codice deterministico

È la sezione che impedisce al progetto di ridiventare quello di prima.

| Capacità | Chi la esegue | Perché |
|---|---|---|
| Trascrizione | **script** (faster-whisper) | deterministico, locale, gratis |
| Estrazione strutturata dalla lezione | **LLM** | è l'unico punto dove serve davvero comprensione |
| **Genere e plurale dei sostantivi** | **dizionario verificabile** | ⛔ mai dall'LLM — vedi §2.1 |
| Costruzione carte Anki | **script** | il JSON è già estratto, generare HTML non richiede un modello |
| Sentence mining i+1 | **script** | è aritmetica su insiemi, non creatività — vedi §3.3 |
| Selezione di cosa ripassare | **script** (FSRS di Anki) | Anki ha già lo scheduler; metterci un LLM sopra è peggio |
| Generazione esercizi/drill | **LLM** (skill) | serve varietà, qui il modello rende |
| Correzione produzione scritta | **LanguageTool poi LLM** | il primo è deterministico, offline e gratis; il secondo spiega il perché |
| Conversazione e correzione orale | **subagent** `tutor-tedesco` | |
| Stato e KPI | **script** | i numeri esistono già nei JSON |
| Briefing di avvio | **script** via hook | vedi §1.1 |
| Rilevamento novità nel motore condiviso | **script** | confronto di hash |
| Giudizio su cosa importare dal motore | **skill** | serve valutare, non contare |

### 2.1 La regola che vale più di tutte

Nel motore condiviso un output allucinato finisce in un report che rileggi. **Qui finisce in Anki**,
cioè in memoria a lungo termine con ripetizione spaziata. Un `der` al posto di `die`, o un plurale
inventato, te lo ripassi per mesi e lo impari *bene*. È l'unico punto del progetto dove l'errore è
irreversibile: puoi correggere un file, non puoi correggere una traccia mnemonica consolidata.

Il tuo `CLAUDE.md:179-181` documenta già l'esposizione: con `LLM_BACKEND=ollama` l'arricchimento
grammaticale via web search **viene saltato** e i `grammar_points` restano alla spiegazione base del
modello locale.

Quindi, come regola di architettura e non di buona volontà:

- Genere e plurale vengono da una **fonte verificabile** (dump Wiktionary tedesco o lista di
  sostantivi con articolo, locale e offline), non dall'estrazione LLM.
- Ciò che non è verificabile entra in Anki con **tag `da-verificare`** e un colore diverso, e finisce
  in una lista che porti a Stefanie. Non viene bloccato — viene *marcato*.
- Le carte prodotte in modalità Ollama-senza-enrichment sono taggate come tali, così sai cosa
  ricontrollare se un giorno emerge un problema.

---

## 3. Il metodo di studio automatizzato

### 3.1 Il problema, in una riga di codice

`anki_feeder.py:114` costruisce il fronte carta: parola tedesca, colorata per genere.
`anki_feeder.py:152` costruisce il retro: italiano, inglese, esempio.

Una direzione sola, DE→IT. È **riconoscimento**: vedi la parola, la riconosci, ti senti bravo.
Non è **richiamo attivo**: partire dal significato e produrre la forma tedesca corretta, con
l'articolo giusto, nella frase giusta. La seconda è più difficile, è quella che serve per parlare,
ed è quella che l'esame misura. Il tuo sistema non l'ha mai allenata.

### 3.2 Carte: da 1 direzione a 3

Da ogni vocabolo estratto, invece di 1 carta:

| Tipo | Fronte → Retro | Cosa allena |
|---|---|---|
| **Riconoscimento** | `die Rechnung` → fattura | quello che hai già (resta) |
| **Produzione** | fattura *(f.)* → `die Rechnung, -en` | **nuovo** — parlare e scrivere |
| **Cloze in contesto** | «Ich habe die ___ noch nicht bezahlt.» | **nuovo** — la parola nella frase reale della lezione |

La frase del cloze **non è inventata dall'LLM**: è presa dal transcript della lezione con Stefanie,
quindi è tedesco reale detto da una madrelingua nel tuo contesto.

Nota tecnica: oggi `add_vocabulary_cards` rileva i duplicati confrontando la stringa **HTML** del
primo campo (con gli `<span style=...>` dentro). È fragile: cambia un colore e il duplicato non viene
più visto. Il nuovo generatore usa un campo chiave pulito.

**FSRS.** Anki spedisce FSRS come scheduler dalla 23.12 e lo attiva di default sui **nuovi** profili;
i profili esistenti restano su SM-2 finché non lo cambi nelle opzioni del deck. I benchmark su ~500
milioni di ripetizioni indicano **20-30% di ripetizioni in meno a parità di ritenzione**, e FSRS-6
(fine 2025) è addestrato su ~700 milioni di review. Il tuo profilo è quasi certamente ancora su SM-2:
va verificato e attivato. È il singolo cambiamento con il miglior rapporto sforzo/beneficio di tutto
il piano — sono due click, e non richiede una riga di codice.

### 3.3 Sentence mining i+1 — e perché non serve un LLM

La ricerca sull'input comprensibile converge su una soglia: perché l'input produca acquisizione
serve che sia comprensibile al **95-98%**, cioè che tu conosca già il 90%+ di parole e strutture, con
i pochi elementi nuovi sostenuti dal contesto.

Tu hai già tutto per calcolarlo:

- `vocab_db.json` → l'insieme delle parole che conosci (1.048)
- `transcripts/` → 30 lezioni di tedesco reale nel tuo contesto
- quindi: per ogni frase del transcript, conta le parole **non** in `vocab_db`. Se sono esattamente 1
  → è una frase i+1. Ordinala per frequenza della parola nuova.

È un'operazione su insiemi. Un LLM qui non aggiunge nulla e può solo inventare. **`studio/frasi.py`
è deterministico.** Alimenta i cloze di §3.2 e i testi di ripasso.

### 3.4 Il quaderno errori come motore del curriculum

`error_db.json` ha 284 errori tuoi reali con la correzione di Stefanie, su 30/30 lezioni. È il dato
più prezioso del progetto e oggi produce solo un PDF che probabilmente non apri.

`studio/drill.py` lo trasforma nel curriculum: raggruppa gli errori per pattern ricorrente, e per
ogni pattern genera esercizi di **produzione** (non di riconoscimento) sulla struttura che sbagli.
È il testing effect applicato al tuo profilo di errore, non a un curriculum generico.

Qui l'LLM serve davvero — genera varietà — ma parte da dati reali, non da un tema astratto.

### 3.5 Audio: la dimensione che manca del tutto

Oggi non c'è **una sola carta con audio**, e il tedesco lo devi *sentire* e *dire*, non leggere.

- **Piper** — CPU-only, real time anche su hardware minimo (~0,03 RTF, primo audio in ~40 ms), file
  per-voce piccoli. Voce più piatta, ma gira sul portatile senza GPU. **Default consigliato.**
- **Kokoro-82M** — 82M parametri, Apache 2.0, ~2-3 GB VRAM (sta nella GTX 980) o anche CPU, qualità
  nettamente superiore, 54 voci in 8 lingue. Per quando lavori sul fisso.
- **F5-TTS / XTTS v2** — migliori per voice cloning ma licenza **CC-BY-NC** / non commerciale:
  irrilevante per uso personale, ma vale la pena saperlo.

Serve a tre cose: audio sulle carte, dettati, shadowing.

### 3.6 Il gate: quando sei pronto per il B1

`b1_gap.py` misura la copertura del curriculum, ma è una **metrica auto-prodotta dallo stesso
sistema che genera le lezioni** — l'equivalente esatto del "punteggio interno" che il motore
condiviso ha giudicato insufficiente per promuovere un'idea a progetto.

Il motore ha risolto chiedendo un'evidenza **esterna** (il primo euro incassato). L'equivalente qui:

> **Un Modellsatz Goethe-Zertifikat B1 ufficiale, svolto sotto tempo, con punteggio ≥60%** —
> più il giudizio di Stefanie, che è esterna al sistema.

Finché quel dato non esiste, la copertura calcolata è diagnostica, non è un verdetto.

### 3.7 La settimana tipo

| Quando | Cosa | Chi lo fa girare | Tuo tempo |
|---|---|---|---|
| Ogni giorno | Ripasso Anki (FSRS, 3 direzioni, con audio) | Anki | 10-15 min |
| Dopo ogni lezione | Pipeline completa + carte + drill sugli errori nuovi | `deutschops.py lezione` | 0 |
| Settimanale | Rigenera stato, gap, carte deboli, drill mirato | check a data scaduta nel briefing | 0 |
| Settimanale | Un esercizio di **produzione scritta** corretto | tu + LanguageTool + tutor | 15 min |
| Mensile | Glossario pharma/Basilea | check a data scaduta | 0 |
| Prima dell'esame | Modellsatz sotto tempo | tu | 3 ore |

Nota onesta: le prime due righe sono le uniche che cambiano qualcosa da sole. Il resto richiede te.
Nessuna automazione ti fa parlare tedesco al posto tuo.

---

## 4. Il ponte col motore shared-startup

### 4.1 Come scatta

Hook `SessionStart` in `.claude/settings.json` → `.claude/hooks/briefing.ps1` →
`py -3 deutschops.py briefing`. Il briefing include il blocco ponte solo quando c'è qualcosa da dire.

### 4.2 Come rileva senza rileggere 128 KB

`changelog-engine.md` pesa 128 KB: rileggerlo a ogni avvio di sessione è inaccettabile.
`stato/ponte-motore.json` tiene:

```json
{
  "ultimo_check": "2026-07-26",
  "cadenza_giorni": 14,
  "sorgenti": {
    "risorse-team/skills/INDICE.md":  { "sha256": "...", "mtime": "..." },
    "_engine/changelog-engine.md":    { "size": 127975, "coda_sha256": "..." },
    "_engine/sviluppo/roadmap-engine.md": { "sha256": "...", "mtime": "..." }
  },
  "importati": [
    { "data": "2026-07-26", "cosa": "scadenze E05 -> stato/scadenze.md" }
  ],
  "scartati": [
    { "cosa": "funzioni/mandati", "perche": "impalcatura multi-utente, 1 solo studente" }
  ]
}
```

L'algoritmo: se `oggi - ultimo_check < cadenza` → **esce subito**, costo zero. Altrimenti confronta
`mtime` e dimensione; solo se sono cambiati calcola l'hash; per il changelog legge **solo la coda**
(ultimi ~8 KB), che è dove finiscono le voci nuove. Il file completo non viene mai letto dallo script.

### 4.3 I tre casi

| Caso | Comportamento |
|---|---|
| Niente di nuovo | **silenzio totale**, nessuna riga nel briefing |
| Drive offline / path assente | silenzio, `ponte-motore.json` invariato, nessun errore |
| Novità rilevate | 2-3 righe nel briefing + suggerimento di lanciare `/ponte-motore` |

Il terzo caso è l'unico in cui interviene un LLM: la skill `/ponte-motore` legge cosa è cambiato e
propone se vale la pena importarlo. **Propone**, non applica — come l'ingest del motore, che ha come
regola d'oro «non esegue mai e non committa mai: produce proposte».

Il registro di ciò che è stato **scartato** conta quanto quello degli import: senza, ogni check
ripropone gli stessi pattern multi-utente che hai già valutato e rifiutato.

### 4.4 Il firewall

Il ponte è **a senso unico per costruzione**: `ponte.py` apre la cartella condivisa in sola lettura e
non ha nessun percorso di scrittura verso di essa. E c'è già una seconda barriera indipendente:
l'hook `block-outside-project-writes.ps1` blocca a livello di sistema ogni `Write`/`Edit` fuori da
`DeutschOps/`. Nulla di tuo può finire in `shared start up/` nemmeno per errore.

---

## 5. Piano di esecuzione a stadi

**Vincolo forte: hai lezione ogni settimana. La pipeline attuale deve restare capace di elaborarla
per tutta la migrazione.**

| # | Stadio | Cosa | Fatto quando | Stato |
|---|---|---|---|---|
| **S0** | Fondamenta | package `do/`, `paths`, `config`, `llm`, `pyproject.toml`. I 3 moduli maturi portati. | `py -3 -c "import do"` ok, i test sui moduli portati passano | ✅ 2026-07-26 |
| **S1** | Pipeline in parallelo | `deutschops.py lezione` completo, ma il vecchio `main.py` resta | rielabora `2026-07-23` e confronta l'output con quello esistente | ✅ 2026-07-27 |
| **S2** | Switch 🔴 | `main.py` e i 15 orfani → `_archivio/`. Astra via, anche da git. | una lezione **nuova** elaborata solo col nuovo | ✅ 2026-07-27 — *criterio non ancora soddisfatto: manca la lezione nuova* |
| **S3** | Layer motore | `stato.py`, `briefing.py`, `ponte.py`, `scadenze.md`, hook `SessionStart` | apri una sessione e vedi il briefing senza chiederlo | ✅ 2026-07-27 |
| **S4** | Metodo | carte 3 direzioni, sentence mining, drill, `esame.py` | il primo drill generato dai tuoi errori reali | ✅ 2026-07-27 · TTS rimandato |
| **S5** | Pulizia | `pyproject` minimo, doc riscritta, `.tmp.driveupload` risolto in Drive | `pip install` scarica <100 MB invece di ~600 | 🟡 parziale — vedi sotto |

🔴 **S2 è il punto di non ritorno.** Attraversato il 2026-07-27 con il cancello di S1 verde.

### Il criterio di S1, come è stato realmente applicato

Il piano diceva «JSON, PDF, carte devono coincidere», sottintendendo un confronto byte per byte.
**Non era esigibile**, e vale la pena scriverlo invece di far finta di averlo fatto: in mezzo alla
pipeline c'è un LLM, la stessa richiesta non ritorna mai lo stesso testo, e per giunta il modello
è cambiato (`claude-sonnet-4-5` → `claude-sonnet-5`).

`deutschops.py confronta` separa quindi due livelli:

- **deterministico** — a parità di JSON in ingresso, PDF / database / carte devono coincidere.
  Qui l'identità è esigibile e viene verificata esatta. Su `2026-07-23`: PDF 7 pagine testo
  identico (normalizzando la data in piedina), `vocab_db` e `grammar_db` idempotenti, 62 note
  deterministiche.
- **generativo** — la riestrazione si confronta per forma e sostanza: schema valido, 24 vocaboli
  v1 contro 22 v2, 14 in comune. Il numero si stampa, non si giudica.

Le carte **non possono** coincidere con la v1, ed è voluto: una direzione è diventata tre. Se
coincidessero, il cambio di metodo non sarebbe avvenuto.

### Cosa il cancello ha trovato (e che leggere il codice non aveva trovato)

1. **Ricerca web a 1,01 € per lezione**, contro gli 0,07 € di una lezione intera. Il dedup delle
   regole grammaticali confrontava il *nome esatto*, e Sonnet 5 lo riformula ogni volta. Ora è per
   sovrapposizione di parole significative, più un tetto di 3 ricerche che stampa cosa rimanda.
2. **`carte.alimenta` perdeva l'intero lotto al primo duplicato.** AnkiConnect aborta tutto invece
   di saltare le singole note. Ogni lezione con vocaboli già visti sarebbe fallita.
3. **`vocab_db` non idempotente** per una differenza fra `.get(k, d)` e `.get(k) or d` su dieci
   parole con `category: ""`.

### Cosa resta di S5

- `pyproject.toml` è a 6 dipendenze dirette, `requirements.txt` è stato rimosso. ✅
- `CLAUDE.md` e `README.md` riscritti. ✅
- **`.tmp.driveupload/` non è risolto.** Va escluso dalle impostazioni di Google Drive per Desktop:
  è una modifica alla configurazione di Drive, non a questo repository.
- **I quattro generatori ReportLab / Docs API restano in root**, resi path-safe ma non consolidati
  in `uscite/tema.py`. Sono ~1.900 righe di layout che nessun test può verificare: l'unico modo di
  sapere se un PDF è ancora giusto è aprirlo, e l'unico modo di provare `doc_writer` è scrivere sul
  documento vero di Stefanie. Rimandato, e dichiarato tale.

---

## 6. Migrazione dei dati

Si migrano: i 3 DB cumulativi, `lesson_registry.json`, i 40 `data/lezione_*.json`, `transcripts/`.

**Verifica obbligatoria dopo la migrazione** — conteggi attesi al 2026-07-23:

| Fonte | Atteso |
|---|---|
| `vocab_db.json` | 1.048 parole (A1 332 · A2 439 · B1 264 · B2 2 · C2 1 · 10 senza livello) |
| `grammar_db.json` | 296 regole |
| `error_db.json` | 284 errori, `lessons_processed` = 30 |
| `lesson_registry.json` | 30 lezioni, 1.630,9 minuti |

**La trappola.** `CLAUDE.md` documenta `summary: {en, it}` e `vocabulary: [{word, gender, plural,
category, cefr}]`. Lo schema **reale** prodotto da `extractor.py` è piatto: `summary_en`,
`summary_it`, e `vocabulary` con `german`, `article`, `level`. Chi scrive il migratore leggendo la
documentazione produce output vuoti **in silenzio** — nessun errore, solo campi mancanti.
`notebooklm_export.py:346-347` ha già un fallback difensivo per entrambe le forme: è la prova che
qualcuno ci è già inciampato.

Il migratore legge lo schema reale e **fallisce rumorosamente** se un campo atteso manca.

Da correggere anche: `main.py:230` scrive `claude_cost = 0.10` costante, mentre `extractor.py:50-52`
calcola il costo vero da `response.usage` e lo butta via. 2,95 € dei 4,82 € del registry sono una
costante moltiplicata per 30. I costi storici non sono recuperabili — vanno **marcati come stimati**,
non spacciati per misurati.

---

## 7. Cosa NON toccare

- **I 3 DB cumulativi.** 1,3 MB di conoscenza reale. Si leggono e si migrano, non si "puliscono".
- **`task_tracker`, `preflight`, `archive_cleanup`.** Portati come modello. Le loro invarianti:
  - *tracker*: una fase completata non si rifà mai; lo snapshot del Doc si scrive solo a pipeline
    completa. È ciò che ti ha salvato i run interrotti.
  - *preflight*: i check **non bloccano mai**. Avvisano e la pipeline degrada. Il parser binario
    dell'atomo `moov` con auto-recupero `untrunc` è nato da un giorno in cui sono fallite tutte e 4
    le cose insieme — quel codice è esperienza pagata.
  - *staging*: la lista di protezione è **esplicita** (`transcripts/`, `data/`, `pdfs/`, i
    `-compressed.mp4` non scadono mai). Per le lezioni senza audio il transcript è irrecuperabile.
- **L'architettura di degradazione.** Anki chiuso → task aperto, si ritenta. Token Google scaduto →
  Step 1 degrada a stringa vuota. È la parte più matura del progetto.
- **I due hook esistenti.** `block-secret-edits.ps1` e `block-outside-project-writes.ps1` funzionano.
- **Il flusso con Stefanie.** Il Google Doc è il vostro terreno comune. Non va reinventato.

---

## 8. Domande aperte

Tre risolte il 2026-07-26, due ancora aperte.

- ~~**C'è una data d'esame?**~~ → **B2 entro ottobre 2026.** Vedi il blocco in cima:
  cambia l'obiettivo (non più B1) e inverte l'ordine degli stadi.
- ~~**NotebookLM: riparare o chiudere?**~~ → **chiuso.** Motivazione in cima.
- ~~**La dashboard Streamlit serve?**~~ → **chiusa**, mai aperta. Sostituita da
  `stato-tedesco.md` + briefing.

Restano aperte:

1. **Stefanie accetterebbe un formato diverso?** Se fosse disposta a chiudere ogni lezione con 3
   frasi da correggere, o a validare una lista di 10 vocaboli dubbi, il gate anti-allucinazione di
   §2.1 avrebbe una fonte umana affidabile a costo quasi zero. Con l'esame a 10 settimane vale
   ancora di più: è l'unico giudizio esterno disponibile fra un Modellsatz e l'altro.
2. **I 40 `data/lezione_*.json` vanno versionati?** Il mio parere: **sì**. Sono ~1 MB di testo, sono
   la sorgente da cui i 3 DB si ricostruiscono, e oggi vivono in una copia sola. Ma raddoppiano i
   file tracciati nel repo: decidi tu.

E una nuova, che nasce dalla data d'esame:

3. **Presso quale Goethe-Institut, e quando chiudono le iscrizioni?** È la riga del 2026-08-04 in
   `stato/scadenze.md`, l'unica che non ho potuto compilare: le finestre di iscrizione sono
   per-istituto. È anche la scadenza più facile da perdere e l'unica che, se saltata, rende
   irrilevanti tutte le altre.

---

## Gate anti-allucinazione

**Perché questo piano potrebbe essere sbagliato.**

Tre punti deboli reali, e li dico prima che li scopra tu.

Primo: **la ricerca sul metodo è più sottile dell'audit**. L'audit del codice è verificato riga per
riga con evidenza (`file:riga`, output di comandi). La parte didattica di §3 poggia su ricerca web
fatta stasera, e su fonti che sono in buona parte blog di prodotto — non letteratura peer-reviewed. I
numeri di FSRS (20-30% di ripetizioni in meno) vengono da benchmark della community Anki, non da uno
studio indipendente. La direzione è solida; le cifre esatte prendile con le molle.

Secondo: **non ho misurato che il problema sia davvero la passività**. Ho osservato che le carte sono
solo DE→IT e ho concluso che ti alleni solo al riconoscimento. Ma non ho visto le tue statistiche
Anki (era chiuso), non so quanto ripassi davvero, e non so se il tuo blocco nel parlare venga dalle
carte o da qualcos'altro — ansia, poca pratica orale, o semplicemente 27 ore di lezione che sono
poche. Se ripassi poco, aggiungere carte peggiora le cose invece di migliorarle.

Terzo: **il piano aggiunge superficie mentre dice di ridurla**. Elimino 15 moduli ma ne introduco
~20, e aggiungo un layer di orchestrazione che oggi non c'è. Se qualcosa va storto, andrà storto qui:
`stato/`, `briefing`, `ponte` sono esattamente il tipo di impalcatura che nel motore condiviso è
stata costruita bene e poi non ha girato. Li ho voluti generati da script proprio per questo, ma è
una scommessa, non una garanzia.

**Quali condizioni servono perché funzioni davvero.**

1. **Una data d'esame.** Senza, §3.6 e `scadenze.md` sono decorazione. È la condizione più importante
   e non dipende da me.
2. **Che tu apra Anki quasi ogni giorno.** Tutto §3 poggia su questo. Se il ripasso quotidiano non
   c'è, il posto giusto dove intervenire non è la pipeline — è l'abitudine.
3. **Che S1 passi il confronto.** Se rielaborando `2026-07-23` il nuovo sistema non riproduce il
   vecchio, il piano si ferma lì e si indaga. Non si passa a S2 "tanto poi si sistema".
4. **Una fonte verificabile per genere e plurale.** Ho assunto che un dump Wiktionary tedesco sia
   praticabile offline. Non l'ho verificato. Se non lo fosse, §2.1 si riduce al solo tag
   `da-verificare` + revisione con Stefanie — più debole, ma non inutile.
5. **Che il ponte resti silenzioso.** Se il blocco ponte compare a ogni avvio anche quando non c'è
   niente, in due settimane smetti di leggerlo e il meccanismo muore come il `log-loop.md` del
   motore. Il silenzio quando non c'è nulla da dire non è un dettaglio: è il requisito.

---

### Fonti (parte didattica, §3)

- [FSRS in Anki — setup e stato 2026](https://medankigen.com/blog/fsrs-anki)
- [SM-2 vs FSRS vs Leitner — confronto 2026](https://smartrecallai.com/blog/sm2-vs-fsrs-vs-leitner-vs-anki-2026)
- [Spaced repetition nel 2026 — Migaku](https://migaku.com/blog/language-fun/spaced-repetition-in-2026-how-it-actually-works)
- [Perché l'input dev'essere comprensibile al 95-98% — teoria ed evidenza](https://gianfrancoconti.com/2025/02/27/why-the-input-we-give-our-learners-must-be-95-98-comprehensible-in-order-to-enhance-language-acquisition-the-theory-and-the-research-evidence/)
- [Sentence mining e i+1 — Clozemaster](https://www.clozemaster.com/blog/sentence-mining/)
- [Oltre l'input comprensibile: critica neuro-ecologica a Krashen](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12577063/)
- [Kokoro vs Piper vs XTTS — TTS locale 2026](https://contracollective.com/blog/kokoro-vs-piper-vs-xtts-local-text-to-speech-m5-max-2026)
- [Migliori modelli TTS locali 2026](https://localaimaster.com/blog/best-local-tts-models)
- [Modelli locali su 4 GB di VRAM — guida 2026](https://lmsa.app/blog/running-local-ai-on-a-4gb-vram-gpu-in-2026-the-real-world-guide-that-actually-works/)
- [Migliori modelli STT open source 2026 — benchmark](https://northflank.com/blog/best-open-source-speech-to-text-stt-model-in-2026-benchmarks)
