"""L'app di studio — server locale.

COS'E'
Un `http.server` della libreria standard su 127.0.0.1. Serve i file statici di
`web/` e quattro endpoint JSON che espongono cio' che i moduli di `do/` gia'
sanno fare. Non contiene logica didattica: e' un adattatore, come `pdf.py` lo e'
sui generatori ReportLab.

PERCHE' STDLIB E NON FLASK
`pyproject.toml` ha appena portato le dipendenze dirette da 186 a 6. Aggiungerne
una per servire quattro pagine su localhost andrebbe contro quella decisione, e
`http.server` fa esattamente cio' che serve.

PERCHE' SOLO 127.0.0.1
Nessuna autenticazione, nessun HTTPS, e i dati sono personali. Il bind e'
cablato sul loopback: non e' una impostazione, e' un vincolo.

DEGRADAZIONE
Come la pipeline: se una fonte manca, l'endpoint restituisce la sua parte vuota
invece di rompere la pagina. Un'app che non si apre perche' un JSON e' assente
non viene riaperta.
"""

from __future__ import annotations

import json
import threading
import webbrowser
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ..base.paths import REGISTRY, ROOT, VOCAB_DB

WEB = ROOT / "web"
PORTA = 7800

# Quanta parte di una sessione di lettura viene da frasi costruite invece che
# dal corpus.
#
# ERA 0,4, E LA MISURA HA DETTO CHE ERA POCO
# Il ragionamento di partenza era che l'autenticita' di una frase davvero detta
# in lezione valesse meta' del valore della zona. Regge in astratto; all'uso no.
# Il corpus rende **93 frasi completabili su 861 candidate**: il resto e'
# parlato spontaneo, dove il buco non si deduce ma si indovina. E anche fra
# quelle 93 ne sono state segnalate a mano — «Hast du dich schon daran gewöhnt,
# nicht zu arbeiten?» ha passato tutti i filtri sintattici ed e' comunque
# indeducibile.
#
# Le composte non sono un ripiego: sono costruite per essere deducibili, il
# lessico bersaglio viene comunque da `vocab_db` (parole passate nelle sue
# lezioni), e parlano del suo dominio. Kevin le ha approvate esplicitamente:
# «puoi utilizzare anche frasi non dette durante la lezione, ma frasi che
# aiutino a imparare il tedesco». L'autenticita' resta, non sparisce — un terzo
# della sessione viene ancora da cio' che Stefanie ha davvero detto.
QUOTA_COMPOSTE = 0.65

TIPI = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".json": "application/json; charset=utf-8",
}


# ------------------------------------------------------------------ dati

def _json(percorso: Path, difetto):
    try:
        return json.loads(percorso.read_text(encoding="utf-8"))
    except Exception:
        return difetto


def _lezioni() -> list[dict]:
    reg = _json(REGISTRY, {})
    lez = reg if isinstance(reg, list) else reg.get("lessons", [])
    return [l for l in lez if isinstance(l, dict)]


def briefing() -> dict:
    """Lo stato per la home: le cifre, gli avvisi, e il suggerimento.

    Il suggerimento e' l'unica cosa che conta davvero. Un menu costringe a
    decidere; una raccomandazione toglie l'attrito che a maggio e' bastato a
    non far aprire mai la dashboard Streamlit.
    """
    from ..motore import attivita
    from ..studio import allenamento, sessione

    lez = _lezioni()
    date_lez = sorted((l.get("date") or "")[:10] for l in lez if l.get("date"))
    ultima_lez = date_lez[-1] if date_lez else None

    from ..sapere import errori as quaderno

    vocaboli = _json(VOCAB_DB, {}).get("stats", {}).get("total_words", 0)
    # Solo quelli di lezione: "Corrections" e' una cifra su cio' che Stefanie ha
    # corretto. Sommarci gli errori fatti nell'app la farebbe salire studiando,
    # cioe' esattamente al contrario di quello che significa.
    errori = quaderno.registrati(quaderno.LEZIONE)
    ses = sessione.riepilogo()
    ses["da_rifare"] = len(allenamento.da_rifare())
    pronti = len(allenamento.disponibili())

    avvisi = []
    for a in attivita.stato():
        if a["in_ritardo"]:
            quando = f"last run {a['ultima']}" if a["ultima"] else "never run"
            avvisi.append({
                "titolo": f"{a['nome']} — {a['lezioni_dopo']} lessons behind",
                "dettaglio": f"{a['descrizione']} · {quando}",
            })

    # Il suggerimento, in ordine di urgenza.
    if ses["totale"] == 0:
        sugg = {
            "titolo": "Start with reading",
            "motivo": "Sentences pulled from your own lessons, one new word each. "
                      "No API calls, nothing to set up.",
            "zona_consigliata": "reading",
            "azione": "Start reading",
        }
    elif ses["da_rifare"]:
        # Precede tutto: un errore fatto qui e non ancora rifatto giusto e' la
        # cosa piu' fresca che il sistema sappia su di te.
        sugg = {
            "titolo": f"{ses['da_rifare']} rule"
                      f"{'s' if ses['da_rifare'] > 1 else ''} to close",
            "motivo": "You got these wrong here in the last two days and haven't "
                      "got them right since. They come first.",
            "zona_consigliata": "practice",
            "azione": "Work on those",
        }
    elif ses["giorni_da_ultima"] is not None and ses["giorni_da_ultima"] >= 3:
        sugg = {
            "titolo": f"{ses['giorni_da_ultima']} days since your last session",
            "motivo": "Short and frequent beats long and rare. A few sentences "
                      "is enough to keep the thread.",
            "zona_consigliata": "reading",
            "azione": "Pick it back up",
        }
    elif avvisi:
        sugg = {
            "titolo": "Lessons processed, not digested",
            "motivo": avvisi[0]["dettaglio"],
            "zona_consigliata": "reading",
            "azione": "Start reading",
        }
    else:
        sugg = {
            "titolo": "Keep going",
            "motivo": f"{ses['ultimi_7_giorni']} sessions in the last 7 days.",
            "zona_consigliata": "reading",
            "azione": "Start reading",
        }

    giorni_da_lezione = None
    if ultima_lez:
        try:
            giorni_da_lezione = (date.today() - date.fromisoformat(ultima_lez)).days
        except ValueError:
            pass

    return {
        **sugg,
        "lezioni": len(lez),
        "vocaboli": vocaboli,
        "errori": len(errori),
        "ultima_lezione": ultima_lez,
        "esercizi_pronti": pronti,
        "cifre": [
            {"etichetta": "Lessons", "valore": len(lez),
             "nota": f"· last {giorni_da_lezione}d ago" if giorni_da_lezione is not None else ""},
            {"etichetta": "Words tracked", "valore": vocaboli},
            {"etichetta": "Corrections", "valore": len(errori),
             "nota": "· from Stefanie"},
            {"etichetta": "Sessions", "valore": ses["totale"],
             "nota": f"· {ses['ultimi_7_giorni']} this week"},
        ],
        "avvisi": avvisi,
    }


def _memoria_parole() -> tuple[set[str], set[str]]:
    """Cosa sai gia' e cosa ti e' costato, dalle sessioni precedenti.

    Senza questo il registro sarebbe solo contabilita': ogni sessione
    ripartirebbe dalle stesse parole piu' frequenti, comprese quelle marcate
    "Easy" tre volte di fila. Le sapute si tolgono, le difficili tornano prima.
    """
    from ..studio import sessione

    sapute: set[str] = set()
    faticose: set[str] = set()
    for s in sessione.tutte():
        for p in s.get("parole", []):
            parola, voto = (p.get("parola") or "").lower(), p.get("voto")
            if not parola or not voto:
                continue
            if voto >= 3:
                sapute.add(parola)
                faticose.discard(parola)
            else:
                faticose.add(parola)
                sapute.discard(parola)      # l'ultimo voto vince
    return sapute, faticose


def frasi(n: int) -> dict:
    """Frasi i+1 dai transcript, con i contesti per lo scoprimento.

    Deterministico, nessuna chiamata di rete. I contesti sono le altre frasi
    reali in cui la parola compare: al momento di scoprire la risposta valgono
    piu' di una traduzione, e mostrano come la parola vive davvero.

    L'ordine tiene conto delle sessioni passate: prima cio' su cui hai faticato,
    poi il nuovo, e cio' che hai marcato come saputo resta fuori finche' c'e'
    altro da fare.
    """
    from ..studio import composte, sessione
    from ..studio import frasi as mod

    sapute, faticose = _memoria_parole()
    scartate = sessione.testi_segnalati()

    def rango(parola: str, frequenza: int) -> tuple:
        p = parola.lower()
        # 0 = da rivedere, 1 = mai vista, 2 = gia' saputa (riempitivo di coda)
        return (0 if p in faticose else 2 if p in sapute else 1, -frequenza)

    # Le due popolazioni si mescolano a quota fissa invece di essere in
    # sequenza. In sequenza le composte non si vedevano mai: con 93 frasi reali
    # completabili servivano sessioni da piu' di 93 per arrivarci. Ma le
    # composte non sono un ripiego — sono costruite per essere deducibili e
    # parlano del suo dominio (pharma, produzione), mentre le reali sono
    # parlato spontaneo. Entrambe servono: le reali per autenticita', le
    # composte per qualita' del contesto.
    reali = [{"testo": f.testo, "nuova": f.nuova, "frequenza": f.frequenza,
              "lezione": f.lezione, "fonte": "lezione"}
             for f in mod.estrai(limite=400)
             if " ".join(f.testo.split()) not in scartate]

    de, _ = mod._per_lingua()
    fatte = [{"testo": c["testo"], "nuova": c["parola"],
              "frequenza": de.get(c["parola"].lower(), 0),
              "lezione": "composed", "fonte": "composta",
              "perche": c.get("perche", "")}
             for c in composte.disponibili(scartate)]

    for gruppo in (reali, fatte):
        gruppo.sort(key=lambda f: rango(f["nuova"], f["frequenza"]))

    quota = round(n * QUOTA_COMPOSTE)
    scelte = reali[: n - quota] + fatte[:quota]
    # Se una delle due non basta, l'altra riempie: mai servire meno del dovuto.
    if len(scelte) < n:
        resto = [f for f in reali + fatte if f not in scelte]
        scelte += resto[: n - len(scelte)]
    scelte.sort(key=lambda f: rango(f["nuova"], f["frequenza"]))

    for f in scelte:
        f["buco"] = mod.buca(f["testo"], f["nuova"])
        f["contesti"] = mod.contesti(f["nuova"], escludi=f["testo"], limite=2)
        f["opzioni"] = mod.opzioni(f["nuova"], frase=f["testo"], quante=4)

    # Traduzione SOLO sulle frasi davvero servite (poche), mai sul pool intero
    # da 400: e' la ragione per cui questo passo vive qui e non in estrai().
    traduzioni = mod.traduci_lotto([f["testo"] for f in scelte])
    for f in scelte:
        f["traduzione"] = traduzioni.get(f["testo"], "")

    return {"frasi": scelte, "composte": len(composte.disponibili())}


def esercizi(n: int, livello: str | None = None) -> dict:
    """Una sessione di allenamento. Nessuna chiamata di rete se c'e' scorta.

    Il deposito si ricarica da solo quando scende sotto la soglia, e la ricarica
    e' UNA chiamata per venti esercizi. Se anche cosi' non basta, si serve
    quello che c'e' invece di fallire: meglio sei esercizi che una schermata di
    errore su un'app che deve aprirsi in tre secondi.
    """
    from ..studio import allenamento

    d = allenamento.sessione_da(n, livello)
    if len(d["esercizi"]) >= n or not d["scorta_bassa"]:
        return {**d, "generati": 0, "costo_eur": 0.0}

    try:
        r = allenamento.prepara(max(allenamento.QUANTI_PER_VOLTA, n),
                                livello=livello)
    except Exception as e:
        # Chiave assente, rete gia', quaderno vuoto: si degrada come la
        # pipeline. Chi chiama vede quanti esercizi ha e perche' non di piu'.
        return {**d, "generati": 0, "costo_eur": 0.0,
                "avviso": f"{type(e).__name__}: {e}"}

    return {**allenamento.sessione_da(n, livello),
            "generati": r["aggiunti"], "costo_eur": r["costo_eur"]}


def esame() -> dict:
    """Il quadro B2: i temi, la prontezza per modulo, i Modellsatz registrati.

    I temi e la prontezza vengono da `esame_b2.json`, che e' una gap analysis
    fatta sui dati del sistema: dice cosa hai INCONTRATO. Il punteggio vero
    viene dai Modellsatz, che sono esterni. Le due cose stanno nella stessa
    pagina ma non si sommano, e l'interfaccia deve tenerle separate.
    """
    from ..studio import modellsatz, prova

    g = _json(ROOT / "data" / "esame_b2.json", {})
    temi = [t for t in g.get("grammatica", []) if isinstance(t, dict)]
    ordine = {"mancante": 0, "parziale": 1, "coperto": 2}
    temi.sort(key=lambda t: (ordine.get(t.get("stato"), 9), t.get("tema", "")))

    return {
        "temi": temi,
        "conteggio_temi": {
            s: sum(1 for t in temi if t.get("stato") == s)
            for s in ("mancante", "parziale", "coperto")
        },
        "moduli_gap": [m for m in g.get("moduli", []) if isinstance(m, dict)],
        "priorita": [p for p in g.get("priorita", []) if isinstance(p, dict)],
        "fattibilita": g.get("fattibilita_ottobre", ""),
        "gap_generato": g.get("generato"),
        "modellsatz": modellsatz.quadro(),
        "scritte": prova.storico()[:6],
        "tipi_prova": [{"id": k, **v} for k, v in prova.TIPI.items()],
    }


def risposta(voce: dict) -> dict:
    """Valuta una risposta e chiude il giro. L'unico endpoint che puo' costare.

    Gratis quando le regole decidono — cioe' su tutto quello che azzecchi.
    """
    from ..studio import allenamento

    es = allenamento.per_id(str(voce.get("id") or ""))
    if not es:
        return {"errore": "esercizio sconosciuto"}

    aiuto = max(0, min(4, int(voce.get("aiuto") or 0)))
    testo = str(voce.get("risposta") or "")
    esito = allenamento.resa(es) if aiuto >= 4 else allenamento.valuta(testo, es)
    return allenamento.registra_esito(es, testo, aiuto, esito)


# ------------------------------------------------------------------ libro

def _pratica_pct(numero: int, risposte: list[dict]) -> float | None:
    """% di esercizi Listening di questa Lektion risposti giusti, o None
    sotto la soglia minima — coerente con progressi.py: un numero fragile
    non e' meglio di nessun numero."""
    SOGLIA_MINIMA = 5
    rilevanti = [r for r in risposte
                if r.get("zona") == "listening" and r.get("lektion") == numero]
    if len(rilevanti) < SOGLIA_MINIMA:
        return None
    giuste = sum(1 for r in rilevanti if r.get("corretta"))
    return round(100 * giuste / len(rilevanti))


def libro_lektioni() -> dict:
    from ..sapere import libro
    from ..studio import sessione

    risposte = sessione.risposte()
    fuori = []
    for l in libro.lektioni():
        collegate = libro.lezioni_per_lektion(l["numero"])
        fuori.append({
            **l,
            "pratica_pct": _pratica_pct(l["numero"], risposte),
            # Prima versione grezza: 0 o 100 a seconda che esista almeno una
            # lezione collegata. Il design voleva "% di temi coperti", ma
            # richiede sapere quanti temi ha una Lektion in totale — non
            # estratto da questo piano. Definire "tema" prima di affinarla.
            "copertura_pct": round(100 * min(1, len(collegate) / 1)) if collegate else 0,
        })
    return {"lektioni": fuori}


def libro_lektion(numero: int) -> dict:
    from ..sapere import libro

    d = libro.lektion(numero)
    if d is None:
        return {"errore": f"Lektion {numero} non trovata"}
    d["lezioni_collegate"] = libro.lezioni_per_lektion(numero)
    return d


# ------------------------------------------------------------------ server

def _decodifica(grezzo: bytes) -> str:
    """Il corpo di una POST, tollerante sull'encoding.

    Il browser manda UTF-8 e non c'e' altro da dire. Ma il tedesco e' pieno di
    umlaut e di ss, e un client che sbaglia charset — PowerShell 5.1 lo fa di
    default — farebbe fallire la registrazione di una sessione gia' svolta.
    Perdere il lavoro fatto per un byte e' il tipo di errore che fa chiudere
    l'app e non riaprirla.
    """
    for codifica in ("utf-8", "cp1252", "latin-1"):
        try:
            return grezzo.decode(codifica)
        except UnicodeDecodeError:
            continue
    return grezzo.decode("utf-8", errors="replace")


class Gestore(BaseHTTPRequestHandler):
    server_version = "DeutschOps"

    def log_message(self, *_):
        """Silenzio. Il log di accesso su una app locale e' solo rumore."""

    # -------------------------------------------------------------- invio

    def _invia(self, corpo: bytes, tipo: str, codice: int = 200) -> None:
        self.send_response(codice)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        # Niente cache: i dati cambiano a ogni lezione elaborata.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def _json(self, dati, codice: int = 200) -> None:
        self._invia(json.dumps(dati, ensure_ascii=False, default=str).encode("utf-8"),
                    TIPI[".json"], codice)

    # -------------------------------------------------------------- GET

    def do_GET(self) -> None:
        rotta = urlparse(self.path)
        percorso = rotta.path

        try:
            if percorso == "/api/stato":
                return self._json(briefing())
            if percorso == "/api/frasi":
                q = parse_qs(rotta.query)
                n = max(1, min(60, int(q.get("n", ["15"])[0])))
                return self._json(frasi(n))
            if percorso == "/api/esercizi":
                from ..studio.allenamento import LIVELLI
                q = parse_qs(rotta.query)
                n = max(1, min(40, int(q.get("n", ["10"])[0])))
                liv = q.get("livello", [""])[0]
                return self._json(esercizi(n, liv if liv in LIVELLI else None))
            if percorso == "/api/esame":
                return self._json(esame())
            if percorso == "/api/compito":
                from ..studio import prova
                q = parse_qs(rotta.query)
                return self._json(prova.compito(q.get("tipo", ["forum"])[0]))
            if percorso == "/api/progressi":
                from ..studio import progressi
                return self._json(progressi.tutto())
            if percorso == "/api/anki":
                from ..studio import progressi
                return self._json(progressi.anki())
            if percorso == "/api/cerca":
                from ..sapere import indice
                q = parse_qs(rotta.query)
                generi = [g for g in q.get("genere", []) if g]
                return self._json(indice.cerca(
                    q.get("q", [""])[0], generi=generi or None,
                    limite=max(1, min(80, int(q.get("n", ["40"])[0])))))
            if percorso == "/api/dettaglio":
                from ..sapere import indice
                q = parse_qs(rotta.query)
                return self._json(indice.dettaglio(q.get("genere", [""])[0],
                                                   q.get("id", [""])[0]))
            if percorso == "/api/libro/lektioni":
                return self._json(libro_lektioni())
            if percorso.startswith("/api/libro/lektion/"):
                try:
                    n = int(percorso.rsplit("/", 1)[-1])
                except ValueError:
                    return self._json({"errore": "numero Lektion non valido"}, 400)
                return self._json(libro_lektion(n))
            if percorso.startswith("/api/"):
                return self._json({"errore": "endpoint sconosciuto"}, 404)
        except Exception as e:                       # degrada, non rompe
            return self._json({"errore": f"{type(e).__name__}: {e}"}, 500)

        self._statico(percorso)

    def _statico(self, percorso: str) -> None:
        nome = "index.html" if percorso in ("/", "") else percorso.lstrip("/")
        f = (WEB / nome).resolve()
        # Nessuna uscita da web/: il path traversal si chiude qui.
        if not f.is_file() or WEB.resolve() not in f.parents:
            return self._invia(b"not found", "text/plain; charset=utf-8", 404)
        self._invia(f.read_bytes(), TIPI.get(f.suffix, "application/octet-stream"))

    # -------------------------------------------------------------- POST

    def do_POST(self) -> None:
        percorso = urlparse(self.path).path
        try:
            n = int(self.headers.get("Content-Length") or 0)
            voce = json.loads(_decodifica(self.rfile.read(n)) or "{}")

            if percorso == "/api/risposta":
                return self._json(risposta(voce))
            if percorso == "/api/correggi":
                from ..studio import prova
                return self._json(prova.correggi(voce.get("compito") or {},
                                                 voce.get("testo") or ""))
            if percorso == "/api/modellsatz":
                from ..studio import modellsatz
                return self._json(modellsatz.registra(voce))

            from ..studio import sessione
            if percorso == "/api/sessione":
                return self._json(sessione.registra(voce))
            if percorso == "/api/segnala":
                r = sessione.segnala(voce)
                # Un esercizio dichiarato rotto non deve lasciare traccia nel
                # quaderno: la risposta sbagliata a una domanda indovinabile non
                # dice niente su cosa Kevin sa, e sposterebbe il profilo
                # d'errore verso una regola che non ha violato.
                if voce.get("tipo") == "esercizio":
                    from ..sapere import errori as quaderno
                    r["ritirati"] = quaderno.ritira(voce.get("testo") or "")
                    r["risposte_scartate"] = sessione.scarta_risposte(
                        voce.get("testo") or "")
                return self._json(r)
            return self._json({"errore": "endpoint sconosciuto"}, 404)
        except Exception as e:
            return self._json({"errore": f"{type(e).__name__}: {e}"}, 500)


def avvia(porta: int = PORTA, apri: bool = True) -> int:
    if not WEB.is_dir():
        raise SystemExit(f"Manca la cartella {WEB}: l'interfaccia non e' installata.")

    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", porta), Gestore)
    except OSError as e:
        raise SystemExit(
            f"Porta {porta} non disponibile ({e}).\n"
            f"Probabilmente l'app e' gia' aperta: http://127.0.0.1:{porta}\n"
            f"Altrimenti scegli un'altra porta con --porta."
        )

    url = f"http://127.0.0.1:{porta}"
    print(f"\n  DeutschOps — {url}")
    print(f"  {datetime.now():%H:%M} · Ctrl-C per chiudere\n")

    # Indice di consultazione e corpus si costruiscono subito, in disparte.
    # Circa un secondo su 4.000 documenti piu' 0,3 per i transcript: spesi
    # adesso non si vedono, spesi alla prima ricerca sembrano un'app che non
    # risponde. Se falliscono, si ricostruiranno su richiesta — il
    # preriscaldamento non deve poter impedire l'avvio.
    def _scalda():
        try:
            from ..sapere import indice
            from ..studio import frasi
            indice.prepara()
            frasi._corpus()
        except Exception:
            pass

    threading.Thread(target=_scalda, daemon=True).start()

    if apri:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Chiuso.\n")
    finally:
        httpd.server_close()
    return 0
