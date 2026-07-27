# Scadenze — rotta verso il Goethe-Zertifikat B2

> **L'UNICO file di stato scritto a mano.** Tutto il resto in `stato/` e' generato
> da script (`deutschops.py stato`) e si sovrascrive.
> Il semaforo NON e' scritto qui: lo ricalcola `do/motore/scadenze.py` confrontando
> la data con oggi. Aggiorna solo le righe, mai i colori.

**Obiettivo:** Goethe-Zertifikat **B2** nella primavera 2027.
**Deciso il:** 2026-07-26 · **Rivisto il:** 2026-07-26 (rinvio da ottobre) · **Da:** Kevin

---

## Perche' il rinvio, e cosa cambia

La gap analysis del 2026-07-26 e' stata netta: a ottobre mancavano 10 temi B2 interi
(Konjunktiv I, Nominalisierung, Funktionsverbgefüge, passivo avanzato) e il lessico
estratto era quasi tutto A1-B1. Il solo modulo con una prontezza plausibile era
Sprechen. Rinviare non e' una ritirata: e' smettere di pagare una tassa d'esame per
un modulo su quattro.

**Cosa cambia con 9-12 mesi invece di 10 settimane.** Il B2 pieno diventa realistico,
e conviene puntare a **tutti e quattro i moduli in una volta** invece di spezzarli.
Ma il tempo lungo ha un rischio opposto: senza una data, la pressione sparisce e il
piano scivola. Le scadenze intermedie qui sotto servono a quello — non all'esame.

Il primo passo resta identico e resta urgente: **un Modellsatz cronometrato**.
Il sistema non ti ha mai misurato, ha solo archiviato. Rinviare l'esame non toglie
il bisogno di sapere il punto di partenza — lo rende piu' utile, perche' adesso c'e'
tempo per agire sul risultato.

## Il B2 e' modulare — questa e' la leva

I quattro moduli (**Lesen · Hören · Schreiben · Sprechen**) si possono sostenere
**separatamente**, non per forza tutti nello stesso giorno, e ognuno si supera
per conto suo. Con 10 settimane questo cambia la strategia: non serve essere pronto
su tutto a ottobre. Si danno i moduli che il Modellsatz dice pronti, gli altri dopo.

Fonte: [Goethe-Institut — Goethe-Zertifikat B2](https://www.goethe.de/de/spr/prf/ueb/pb2.html) ·
[Modellsatz Erwachsene (PDF)](https://www.goethe.de/pro/relaunch/prf/materialien/B2/b2_modellsatz_erwachsene.pdf) ·
[Durchführungsbestimmungen (PDF)](https://www.goethe.de/pro/relaunch/prf/de/Durchfuehrungsbestimmungen_B2.pdf)

---

## Registro

| Data | Cosa | Tipo | Stato | Note |
|---|---|---|---|---|
| 2026-08-09 | **Modellsatz B2 completo sotto tempo** — misura di partenza | gate | aperto | I 4 moduli, cronometrati, senza aiuti. Senza questo numero ogni stima e' congettura. Materiale: PDF Modellsatz Erwachsene + audio dal sito Goethe. |
| 2026-09-30 | **Chiudere il buco sui casi** — Kasus/Genus/Präposition | gate | aperto | 127 errori sullo stesso sistema, il 45% di tutto `error_db`. Sono fondamenta A2/B1: finche' reggono cosi', ogni modulo B2 ne paga il prezzo. Verifica: la quota di questi errori sul totale scende sotto il 25%. |
| 2026-11-29 | Modellsatz #2 — pendenza reale a 4 mesi | gate | aperto | Stesso formato del #1. Serve a misurare la derivata, non il livello. |
| 2027-01-31 | Modellsatz #3 + **decidere data e istituto** | decisione | aperto | ⚠️ Le finestre di iscrizione sono per-istituto e chiudono settimane prima. Da qui in poi diventa la scadenza piu' facile da perdere. |
| 2027-02-28 | **Iscrizione formalizzata** | milestone | aperto | Data e sede confermate, tassa pagata. Da qui l'esame e' reale. |
| 2027-04-?? | **Esame Goethe-Zertifikat B2** — 4 moduli | esame | aperto | Data esatta dal passo del 2027-01-31. Con 9 mesi l'obiettivo torna il B2 pieno, non i singoli moduli. |

### Soglie di allarme (kill-criteria)

Non sono obiettivi: sono segnali che il piano va rivisto, non spinto piu' forte.

- **Piu' di 3 settimane senza lezione** con Stefanie → la cadenza attuale e' 3/settimana.
  Su un orizzonte lungo il rischio non e' l'intensita', e' l'interruzione.
- **Ripasso Anki sotto i 4 giorni su 7** per due settimane di fila → il collo di
  bottiglia non e' la pipeline, e' l'abitudine. Aggiungere carte peggiora le cose.
- **`error_db` che non cala su una categoria dopo 6 lezioni** che la coprono → il modo
  di studiarla non funziona, ripeterla uguale non serve.
- **Modellsatz #2 non migliore del #1** → il metodo non sta rendendo; si rivede il
  piano, non si aumenta il volume.

---

## Perche' il gate e' un Modellsatz e non `esame.py`

`do/studio/esame.py` calcola la copertura del curriculum B2 dai tuoi dati. Ma e' una
metrica **auto-prodotta dallo stesso sistema che genera le lezioni**: misura cosa hai
incontrato, non cosa sai produrre sotto pressione in 90 minuti.

E' lo stesso ragionamento per cui il motore condiviso non promuove un'idea a progetto
sul punteggio interno e pretende un'evidenza esterna. Qui l'evidenza esterna sono due:
il **punteggio Modellsatz** e il **giudizio di Stefanie**, che e' fuori dal sistema.
