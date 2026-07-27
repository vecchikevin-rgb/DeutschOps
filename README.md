# DeutschOps 🇩🇪

> Dalla lezione di tedesco al materiale di studio, in un comando — e poi il pezzo
> che di solito manca: quello che ti fa esercitare sugli errori che hai fatto davvero.

Costruito da un manager di produzione in transizione verso il pharma svizzero (area Basilea),
mentre studia per il **Goethe-Zertifikat B2**.

---

## Cosa fa

```
lezione audio ──▶ trascrizione ──▶ estrazione ──▶ ┬─▶ Anki (3 direzioni)
                                                   ├─▶ PDF
                                                   ├─▶ Google Doc condiviso
                                                   └─▶ database cumulativi
                                                          │
                       ┌──────────────────────────────────┘
                       ▼
        quaderno errori ──▶ drill di produzione ──▶ gap analysis B2
```

Un entry point: `deutschops.py`.

```powershell
py -3 deutschops.py lezione "Audiolessons\lezione.mp4" 2026-07-28-stefanie
py -3 deutschops.py drill          # esercizi dai tuoi 284 errori reali
py -3 deutschops.py esame          # dove sei rispetto al curriculum B2
```

## Le tre idee che lo rendono diverso da un generatore di flashcard

**1. Tre direzioni, non una.** Riconoscere una parola è facile e dà l'illusione di saperla. Ogni
vocabolo produce anche una carta di **produzione** (italiano → tedesco, con l'articolo da
indovinare e non da leggere) e una **cloze** su una frase vera dell'insegnante.

**2. Gli errori sono il curriculum.** Il sistema mina dalle trascrizioni i momenti in cui
l'insegnante corregge, li accumula, e ci costruisce sopra esercizi in contesti nuovi. Non un
curriculum generico: i tuoi 284 errori, con le sue correzioni accanto.

**3. Misura invece di accumulare.** Il briefing all'avvio sessione dice dove sbagli, cosa scade, e
soprattutto **cosa non sta girando**: se elabori lezioni senza mai fare un drill, te lo dice.
Elaborare dà la sensazione di studiare — i numeri salgono, i file crescono — ma macinare non è
imparare.

## Installazione

```powershell
py -3 -m venv venv
venv\Scripts\activate
py -3 -m pip install -e ".[dev]"
```

Servono: Anki con AnkiConnect su `localhost:8765`, un `.env` con `ANTHROPIC_API_KEY`, e le
credenziali Google OAuth2 se vuoi la sincronizzazione col Doc.

Dettagli operativi, architettura e regole in [`CLAUDE.md`](CLAUDE.md).
La v1 e i moduli ritirati sono in [`_archivio/`](_archivio/LEGGIMI.md), spostati e non cancellati.
