# Il Kursbuch dentro l'app — design

Data: 2026-08-24
Stato: approvato in chat, in scrittura del piano

## Perché

Il Kursbuch è stato trascritto e risolto per intero (629/730 esercizi, 86%,
committato su `worktree-deutschops-libro-cloze`). Finora vive solo come dati
grezzi (`data/libro_pagine.json`) usati indirettamente per le carte Cloze e il
grounding degli esercizi drill. Kevin ha chiesto di portarlo dentro l'app di
studio in modo visibile — "renderla più seria" — e di collegare le lezioni
vere con Stefanie ai temi che il libro tratta sugli stessi argomenti.

## Cosa cambia, in breve

1. Una zona nuova **Kursbuch**: le 30 Lektionen come percorso lineare, due
   barre di completamento per Lektion (pratica tua nell'app / copertura con
   Stefanie), pagine vere del libro, esercizi risolti.
2. La zona **Listening** (oggi un placeholder vuoto, `pronta: false`) si
   riempie con gli esercizi del libro legati a una traccia audio — la
   sorgente naturale, dato che il libro li ha già risolti dal transcript.
3. La zona **Exam** guadagna un puntatore "vedi Lektion N" quando la gap
   analysis B2 segnala una regola mancante che il libro copre.
4. Un collegamento lezione↔Lektion, per sapere quali tue lezioni vere con
   Stefanie hanno toccato temi simili a una Lektion del libro (e viceversa).

## Componenti

### `do/sapere/libro.py` — nuove funzioni

- `lektioni() -> list[dict]`
  Aggrega le pagine `kursbuch` per numero di Lektion (campo `lezione` già
  presente in ogni pagina OCR). Per ognuna: numero, titolo (dedotto dal
  `testo` della prima pagina — l'intestazione tipo "27 Geschichten und
  Gesichter Berlins"), livello dominante, conteggio pagine/frasi/esercizi,
  quanti esercizi hanno `soluzione`.

- `lektion(numero: int) -> dict | None`
  Il dettaglio completo di una Lektion: tutte le sue pagine (testo, frasi,
  esercizi con soluzione e fonte), in ordine di indice pagina.

- `classifica_lezioni_per_lektion() -> dict`
  Il collegamento lezione↔Lektion. **Non lessicale** — il progetto ha già la
  prova che il matching per somiglianza di nome sui contenuti grammaticali
  produce ~75% di falsi positivi (`do/sapere/indice.py`, tentativo simile fra
  `error_db` e `grammar_db`, poi abbandonato per liste "esatti"/"simili"
  separate). Un giro LLM economico (backend abbonamento, `effort: low`), una
  chiamata per lezione non ancora classificata: riceve il `topic` e i
  `grammar_points` della lezione, i titoli delle 30 Lektionen, risponde con
  0-3 Lektionen candidate + una riga di motivazione ciascuna. Salvato in
  `data/libro_lezioni_mappa.json` (gitignored come il resto di `data/*`),
  incrementale — rilanciare aggiunge solo le lezioni nuove, non richiama su
  quelle già mappate. Schema:

  ```json
  {
    "2026-07-28-stefanie": [
      {"lektion": 12, "motivo": "Perfekt mit Modalverben, stesso punto della lezione"}
    ],
    "2026-08-11-stefanie": []
  }
  ```

  Lista vuota se il modello non trova una Lektion pertinente — non e' un
  errore, e' un dato onesto (lezioni fuori programma, temi B2 non nel libro).

- Rendering pagina con cache su disco
  `_rendi_pagina()` esiste già ma renderizza in una cartella temporanea a
  ogni chiamata. Nuova `pagina_cachata(fonte, indice) -> Path`: stessa resa,
  ma scritta in `Book/pagine_render/{fonte}_{indice:04d}.png` e riusata se
  già presente — l'app la richiede spesso (ogni apertura di una Lektion),
  non ha senso renderizzare la stessa pagina ogni volta.

### `do/uscite/web.py` — endpoint nuovi

| Endpoint | Cosa fa |
|---|---|
| `GET /api/libro/lektioni` | Lista delle 30 Lektionen con le due percentuali (pratica tua, copertura Stefanie) |
| `GET /api/libro/lektion/<n>` | Dettaglio: pagine, frasi, esercizi risolti, lezioni collegate |
| `GET /api/libro/pagina/<fonte>/<indice>` | L'immagine PNG della pagina (cachata) |
| `GET /api/libro/listening?n=` | Una sessione di pratica dagli esercizi audio del libro — nasconde `soluzione`, la restituisce solo dopo la risposta (stesso pattern di `RISERVATI` in `allenamento.py`) |
| `POST /api/libro/risposta` | Registra un tentativo (corretto/sbagliato) su un esercizio Listening — alimenta "pratica tua" |

**Il calcolo di "pratica tua"**: per ogni Lektion, denominatore = esercizi di
quella Lektion con `traccia_audio` risolto (il pool Listening reale);
numeratore = quanti risposti giusti nel log tentativi. Sotto una soglia
minima (coerente con `progressi.py`: "meno di 20 risposte non e' un
segnale") la barra dice "non abbastanza dati" invece di un numero fragile.

**"Copertura con Stefanie"**: % di pagine/temi della Lektion presenti in
`libro_lezioni_mappa.json` per almeno una lezione vera.

### `web/app.js` — zone

- `ZONE`: `kursbuch` nuova zona (icona da aggiungere, `pronta: true`);
  `listening` passa da `pronta: false` a `true`.
- `disegnaKursbuch()`: percorso lineare confermato nel companion visivo —
  Lektionen completate/in corso/future, la corrente espansa con le due
  barre, le altre compatte.
- `disegnaLektionDettaglio(n)`: pagine vere (immagine), frasi, esercizi
  risolti con soluzione rivelabile, lezioni vere collegate.
- Sessione Listening: stesso flusso domanda→rivelazione già in Practice
  (`disegnaRisposta`), sorgente `/api/libro/listening` invece di
  `/api/esercizi`.

### `do/studio/esame.py` — puntatore al libro

Quando `analizza()` segnala una regola B2 mancante, cerca nel libro (stessa
ricerca lessicale di `libro.esempio_esercizio`, non nuovo codice) se una
Lektion la tratta. Se trovata, il record del gap guadagna `"lektion_libro": N`
— un puntatore a dove studiarla, non un voto nuovo. Nessuna misura
autoprodotta: resta fedele alla regola del progetto ("l'esame si misura da
fuori, sempre").

## Cosa NON fa

- Non tocca `Practice` (drill dagli errori): resta guidato dai tuoi errori
  reali, non da una Lektion specifica. Il libro lo grounda già in formato
  (Task A4), non serve altro qui.
- Non genera nuovi esercizi per il libro: usa quelli già risolti. Generare
  esercizi *aggiuntivi* in stile libro per Lektion resta scope di A4/futuro,
  non di questa integrazione UI.
- Non aggiunge un punteggio o una certificazione: le due barre misurano
  esposizione e pratica, non "sai il B2" — coerente con la regola gia'
  scritta in CLAUDE.md sulla differenza fra esposizione e progresso.

## Testing

Verifica manuale in browser quando disponibile (non lo era in questa
sessione — Claude in Chrome non connesso). In sua assenza: verifica via
chiamate dirette agli endpoint (`urllib`/`curl`), come gia' fatto per
`/api/frasi` ed `/api/esercizi` in questa stessa sessione, e ispezione a
occhio dei dati serviti.
