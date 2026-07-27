# Scadenze — rotta verso il Goethe-Zertifikat B2

> **L'UNICO file di stato scritto a mano.** Tutto il resto in `stato/` e' generato
> da script (`deutschops.py stato`) e si sovrascrive.
> Il semaforo NON e' scritto qui: lo ricalcola `do/motore/scadenze.py` confrontando
> la data con oggi. Aggiorna solo le righe, mai i colori.

**Obiettivo:** Goethe-Zertifikat **B2** entro ottobre 2026.
**Deciso il:** 2026-07-26 · **Da:** Kevin

---

## Il vincolo, in chiaro

Alla prima finestra utile di ottobre mancano **10 settimane**; a fine ottobre, 14.
Il sistema oggi non sa a che punto sei davvero: `vocab_db` conta 1.048 parole di cui
2 marcate B2, ma quel numero misura **cosa la pipeline ha estratto da 10 settimane di
lezioni**, non cosa sai. Finche' non c'e' un punteggio esterno, ogni piano e' a occhio.

Per questo la scadenza piu' urgente non e' l'esame: e' il **Modellsatz di prova**.

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
| 2026-08-02 | **Modellsatz B2 completo sotto tempo** — misura di partenza | gate | aperto | I 4 moduli, cronometrati, senza aiuti. Senza questo numero tutto il resto e' congettura. Materiale: il PDF Modellsatz Erwachsene + audio dal sito Goethe. |
| 2026-08-04 | Verificare date e **scadenza iscrizioni** al proprio Goethe-Institut | milestone | aperto | ⚠️ **Da confermare a mano — non ho la data reale.** Le finestre di iscrizione sono per-istituto e chiudono tipicamente settimane prima dell'esame. E' la scadenza piu' facile da perdere e l'unica che rende irrilevanti tutte le altre. |
| 2026-08-09 | Decidere **quali moduli** dare a ottobre | decisione | aperto | Sulla base del punteggio Modellsatz per modulo. Non serve darli tutti. |
| 2026-09-06 | Modellsatz #2 — verifica di meta' percorso | gate | aperto | Stesso formato, per misurare la pendenza reale, non la sensazione. |
| 2026-10-?? | **Esame Goethe-Zertifikat B2** (moduli scelti) | esame | aperto | Data esatta da fissare col passo del 2026-08-04. |

### Soglie di allarme (kill-criteria)

Non sono obiettivi: sono segnali che il piano va rivisto, non spinto piu' forte.

- Modellsatz #1 sotto il **50%** in un modulo → quel modulo non e' da ottobre, si sposta.
- Piu' di **2 settimane senza lezione** con Stefanie → la cadenza attuale e' 3/settimana,
  perderla ora costa piu' che a marzo.
- `error_db` che non cala su una categoria dopo **4 lezioni** che la coprono → il modo
  di studiarla non funziona, non serve ripeterla uguale.

---

## Perche' il gate e' un Modellsatz e non `esame.py`

`do/studio/esame.py` calcola la copertura del curriculum B2 dai tuoi dati. Ma e' una
metrica **auto-prodotta dallo stesso sistema che genera le lezioni**: misura cosa hai
incontrato, non cosa sai produrre sotto pressione in 90 minuti.

E' lo stesso ragionamento per cui il motore condiviso non promuove un'idea a progetto
sul punteggio interno e pretende un'evidenza esterna. Qui l'evidenza esterna sono due:
il **punteggio Modellsatz** e il **giudizio di Stefanie**, che e' fuori dal sistema.
