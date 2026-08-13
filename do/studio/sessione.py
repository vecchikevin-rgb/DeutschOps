"""Il registro di cosa hai davvero fatto.

PERCHE' ESISTE
Fino a qui il sistema sapeva tutto di cio' che PRODUCE — lezioni elaborate,
esercizi generati, carte create — e niente di cio' che CONSUMI. `drill` scriveva
un foglio di esercizi in `drill.json` e finiva li': nessuno registrava se quel
foglio fosse mai stato aperto.

Il buco si vede meglio in `do/motore/attivita.py`: misurava l'ultima esecuzione
leggendo il campo `generato` dentro `drill.json`, cioe' quando il foglio era
stato CREATO. Il briefing poteva dire "in pari" con dieci esercizi mai visti.

E c'e' un precedente che dimostra quanto conti: `_archivio/pages/1_Exercises.py`
(603 righe di Streamlit) importava `save_session_result()` per registrare i
risultati. Il file che quella funzione avrebbe scritto — `exercise_results.json`
— non esiste in nessun commit: nemmeno una sessione portata a termine. Un
registro vuoto e' l'unico dato onesto sull'uso reale di uno strumento.

COSA REGISTRA, E COSA NO
Fatti, non giudizi: quando, quale zona, quanto e' durata, quanti elementi, come
sono andati. Nessun punteggio aggregato, nessuno streak, nessun badge — le
metriche di vanita' fanno sentire bene e non insegnano niente.
"""

from __future__ import annotations

import json
import threading
from datetime import date, datetime, timedelta

from ..base.paths import DATA

REGISTRO = DATA / "sessioni.json"


def _carica() -> dict:
    try:
        d = json.loads(REGISTRO.read_text(encoding="utf-8"))
        if isinstance(d, dict) and isinstance(d.get("sessioni"), list):
            return d
    except Exception:
        pass
    return {"sessioni": []}


def registra(voce: dict) -> dict:
    """Aggiunge una sessione. Non fallisce mai rumorosamente: perdere il
    registro e' spiacevole, ma far fallire uno studio riuscito e' peggio."""
    d = _carica()
    voce = dict(voce)
    voce["quando"] = datetime.now().isoformat(timespec="seconds")
    d["sessioni"].append(voce)
    try:
        REGISTRO.parent.mkdir(parents=True, exist_ok=True)
        REGISTRO.write_text(json.dumps(d, ensure_ascii=False, indent=2),
                            encoding="utf-8")
    except OSError:
        pass
    return voce


def tutte() -> list[dict]:
    return _carica()["sessioni"]


# ------------------------------------------------------------------ risposte

RISPOSTE = DATA / "risposte.json"

# Il lucchetto serve davvero: qui scrive una richiesta web, e il server e' un
# ThreadingHTTPServer.
_LUCCHETTO = threading.Lock()


def annota_risposta(voce: dict) -> dict:
    """Registra UNA risposta, subito.

    PERCHE' NON BASTA IL RECORD DI FINE SESSIONE
    Il riepilogo si scrive quando la sessione arriva in fondo. Ma una sessione
    puo' benissimo non arrivarci — si chiude la scheda, si passa ad altro — e
    misurato sul primo uso reale e' successo esattamente questo: due esercizi
    svolti, `sessioni.json` vuoto. Gli errori erano nel quaderno (li scrive
    `registra_esito` a ogni risposta), ma la coda dell'allenamento legge le
    SESSIONI, quindi non ha visto niente: ne' le regole da rifare, ne' quelle
    padroneggiate. Due esercizi fatti e zero imparato dal sistema.

    Qui ogni risposta si posa appena data. Il riepilogo di fine sessione resta
    — serve al briefing e alle cifre della home — ma non e' piu' l'unica fonte
    di cio' che hai fatto.
    """
    voce = dict(voce)
    voce.setdefault("quando", datetime.now().isoformat(timespec="seconds"))
    with _LUCCHETTO:
        d = _carica_risposte()
        d["risposte"].append(voce)
        try:
            RISPOSTE.parent.mkdir(parents=True, exist_ok=True)
            tmp = RISPOSTE.with_name(RISPOSTE.name + ".tmp")
            tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            tmp.replace(RISPOSTE)
        except OSError:
            pass
    return voce


def _carica_risposte() -> dict:
    try:
        d = json.loads(RISPOSTE.read_text(encoding="utf-8"))
        if isinstance(d, dict) and isinstance(d.get("risposte"), list):
            return d
    except Exception:
        pass
    return {"risposte": []}


def risposte() -> list[dict]:
    return _carica_risposte()["risposte"]


def scarta_risposte(stimolo: str) -> int:
    """Toglie le risposte a un esercizio dichiarato rotto."""
    chiave = " ".join((stimolo or "").split())
    if not chiave:
        return 0
    with _LUCCHETTO:
        d = _carica_risposte()
        prima = len(d["risposte"])
        d["risposte"] = [r for r in d["risposte"]
                         if " ".join((r.get("stimolo") or "").split()) != chiave]
        tolte = prima - len(d["risposte"])
        if tolte:
            try:
                tmp = RISPOSTE.with_name(RISPOSTE.name + ".tmp")
                tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2),
                               encoding="utf-8")
                tmp.replace(RISPOSTE)
            except OSError:
                pass
        return tolte


# ------------------------------------------------------------------ segnalazioni

SEGNALATE = DATA / "frasi_segnalate.json"


def segnala(voce: dict) -> dict:
    """Qualcosa che non funziona: contesto insufficiente, testo rotto, parola
    sbagliata, esercizio indovinabile invece che deducibile.

    PERCHE' SERVE UN CANALE MANUALE
    `completabile()` filtra su regole verificabili — punteggiatura, lunghezza,
    esitazioni, contesto bilaterale — e prende il grosso. Ma la deducibilita'
    vera dipende dal significato, e li' nessuna regola sintattica arriva:
    "Das ist der _____, den ich denke, du weißt nicht." passa tutti i controlli
    ed e' comunque indeducibile. L'unico giudice affidabile e' chi studia.

    Vale per le frasi di lettura come per gli esercizi di allenamento: il campo
    `tipo` dice quale delle due, e le due liste si filtrano separatamente. Senza
    questo canale, in allenamento un esercizio rotto non solo ritorna, ma lascia
    anche un errore nel quaderno — vedi `errori.ritira()`.
    """
    d = _carica_segnalate()
    voce = dict(voce)
    voce["quando"] = datetime.now().isoformat(timespec="seconds")
    voce.setdefault("tipo", "frase")

    # Segnalare due volte la stessa cosa resta una segnalazione sola.
    chiave = (voce.get("testo") or "").strip()
    d["frasi"] = [f for f in d["frasi"] if (f.get("testo") or "").strip() != chiave]
    d["frasi"].append(voce)

    try:
        SEGNALATE.parent.mkdir(parents=True, exist_ok=True)
        SEGNALATE.write_text(json.dumps(d, ensure_ascii=False, indent=2),
                             encoding="utf-8")
    except OSError:
        pass
    return voce


def _carica_segnalate() -> dict:
    try:
        d = json.loads(SEGNALATE.read_text(encoding="utf-8"))
        if isinstance(d, dict) and isinstance(d.get("frasi"), list):
            return d
    except Exception:
        pass
    return {"frasi": []}


def segnalate() -> list[dict]:
    return _carica_segnalate()["frasi"]


def testi_segnalati() -> set[str]:
    """Le frasi di lettura da non riproporre. Testo normalizzato."""
    return {" ".join((f.get("testo") or "").split())
            for f in segnalate() if f.get("tipo", "frase") == "frase"}


def stimoli_segnalati() -> set[str]:
    """Gli esercizi da non riproporre. Confronto sullo stimolo normalizzato."""
    return {" ".join((f.get("testo") or "").split())
            for f in segnalate() if f.get("tipo") == "esercizio"}


def ultima() -> dict | None:
    s = tutte()
    return s[-1] if s else None


def ultima_data() -> date | None:
    u = ultima()
    if not u:
        return None
    try:
        return datetime.fromisoformat(u["quando"]).date()
    except (KeyError, ValueError):
        return None


def negli_ultimi(giorni: int = 7) -> list[dict]:
    limite = date.today() - timedelta(days=giorni)
    fuori = []
    for s in tutte():
        try:
            if datetime.fromisoformat(s["quando"]).date() >= limite:
                fuori.append(s)
        except (KeyError, ValueError):
            continue
    return fuori


def riepilogo() -> dict:
    """Il quadro per il briefing e per la home. Nessuna chiamata di rete."""
    s = tutte()
    u = ultima_data()
    return {
        "totale": len(s),
        "ultimi_7_giorni": len(negli_ultimi(7)),
        "ultima": u.isoformat() if u else None,
        "giorni_da_ultima": (date.today() - u).days if u else None,
    }
