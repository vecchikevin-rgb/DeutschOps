"""L'indice di consultazione — cercare in cio' che il progetto sa gia'.

COSA INDICIZZA
Quattro popolazioni, che oggi vivono in quattro file che nessuno apre:

    301 regole      data/grammar_db.json    con esempi, errori tipici, eccezioni
    295 correzioni  data/error_db.json      cosa hai detto, cosa andava detto
  1.069 vocaboli    data/vocab_db.json      con esempio e lezione d'origine
 ~9.000 passi       transcripts/*.txt       cio' che Stefanie ha detto davvero

L'ultima riga e' quella che non si trova altrove: 27 ore di lezione trascritte,
oggi consultabili solo con Ctrl-F su un file alla volta.

PERCHE' UN INDICE IN MEMORIA E NON UN DATABASE
700 KB di transcript e tre JSON. Un motore di ricerca vero (sqlite FTS5,
whoosh) risolverebbe un problema di scala che qui non esiste, e aggiungerebbe
o una dipendenza o un file di indice da tenere in sincrono. Un dizionario
invertito costruito all'avvio costa qualche decimo di secondo e non ha stato su
disco da invalidare — sbaglia solo finche' il processo vive, e il processo e'
il server dell'app.

LA LEZIONE DI F2, APPLICATA QUI
In F2 avevo agganciato le regole di `grammar_db` agli errori per somiglianza di
nome, e sbagliava 3 volte su 4: «Präposition 'in' + Dativ» finiva su
«Präposition mit + Dativ». La causa non era la soglia — era la FORMA della
risposta. Una funzione che sceglie in silenzio il miglior candidato e lo
presenta come «la regola» non ha modo di dire «non lo so».

Qui la stessa informazione fuzzy viene presentata come cio' che e':
- **collegamento esatto** dove esiste davvero — fra errori, via
  `chiave_regola()`: stessa chiave normalizzata = stessa regola, per
  costruzione. Questo si puo' affermare.
- **risultati di ricerca** dove non esiste — fra una regola e le correzioni.
  Sono ordinati, mostrati in lista e etichettati per quello che sono. Una
  lista di tre risultati mediocri e' onesta; un singolo risultato sbagliato
  presentato con sicurezza no.
"""

from __future__ import annotations

import bisect
import json
import math
import re
import threading
import unicodedata
from dataclasses import dataclass, field

from ..base.paths import ERROR_DB, GRAMMAR_DB, TRANSCRIPTS, VOCAB_DB

# Un passo di transcript: frasi consecutive della stessa lezione fino a questa
# lunghezza. Le singole frasi non bastano — Whisper produce anche «Indirekte.»,
# che come risultato di ricerca non dice niente. Serve il contorno.
PASSO_MAX = 260

_TOKEN = re.compile(r"[A-Za-zÄÖÜäöüß]+", re.UNICODE)
_FRASE = re.compile(r"(?<=[.!?])\s+")

# Quanto pesa un riscontro, per campo e per popolazione. Le regole e i vocaboli
# stanno sopra i passi di transcript: cercando «Konjunktiv» la regola e' una
# risposta migliore di una frase che per caso contiene la parola.
PESO_GENERE = {"regola": 3.0, "vocabolo": 2.5, "errore": 2.0, "passo": 1.0}
PESO_TITOLO = 3.0
PESO_TESTO = 1.0

# Sotto questo numero di risultati la ricerca stretta si allarga. Vedi `cerca()`.
MIN_UTILE = 5

# Quanto deve valere un risultato allargato rispetto al migliore, per entrare.
FRAZIONE_MIN = 0.35


def _rarita(quanti: int, totale: int) -> float:
    """Quanto vale trovare un token, in funzione di quanto e' comune.

    E' la frequenza inversa di documento, senza sofisticazioni: un token in 4
    schede su 4.082 pesa circa 6, uno in 1.500 pesa circa 1. Serve perche' le
    query vere contengono `sein`, `bei`, `der` — parole che stanno ovunque e non
    dicono niente su cosa stai cercando.
    """
    return math.log(totale / (1 + quanti)) + 1.0


@dataclass
class Documento:
    genere: str
    id: str
    titolo: str
    testo: str
    meta: dict = field(default_factory=dict)


# --------------------------------------------------------------- tokenizzazione

# La tokenizzazione gira su ~500.000 occorrenze in fase di costruzione, ma le
# forme distinte sono poche migliaia: memorizzata, la normalizzazione si paga
# una volta per forma invece che una volta per occorrenza.
_MEMO: dict[str, tuple[str, ...]] = {}


def _piatto(t: str) -> str:
    """Forma confrontabile: minuscole, diacritici via, ss al posto di ss."""
    t = unicodedata.normalize("NFKD", t.lower().replace("ß", "ss"))
    return "".join(c for c in t if not unicodedata.combining(c))


def _varianti(t: str) -> tuple[str, ...]:
    """Le forme sotto cui un token va indicizzato e cercato.

    DUE, non una, e la ragione e' la tastiera. In tedesco l'umlaut si scioglie
    ufficialmente in `ae/oe/ue` («Präposition» → «Praeposition»), ma chi digita
    di fretta su tastiera italiana scrive «praposition», senza la e. Indicizzare
    una sola delle due forme fa fallire l'altra: misurato, cercare
    «praposition dativ» restituiva 109 risultati invece di 15, perche' il primo
    token non agganciava niente e la ricerca ripiegava sull'OR di «dativ».

    Entrambe le forme, in indice e in query. Costa qualche migliaio di chiavi.
    """
    if (v := _MEMO.get(t)) is not None:
        return v
    piatto = _piatto(t)
    disteso = t.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        disteso = disteso.replace(a, b)
    disteso = _piatto(disteso)
    v = (piatto,) if disteso == piatto else (piatto, disteso)
    _MEMO[t] = v
    return v


def _token(testo: str) -> list[str]:
    fuori = []
    for t in _TOKEN.findall(testo or ""):
        fuori.extend(_varianti(t))
    return fuori


# --------------------------------------------------------------- le popolazioni

def _leggi(p, difetto):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return difetto


def _regole() -> list[Documento]:
    r = _leggi(GRAMMAR_DB, {}).get("rules", {})
    valori = r.items() if isinstance(r, dict) else ((str(i), x) for i, x in enumerate(r))
    fuori = []
    for chiave, v in valori:
        if not isinstance(v, dict):
            continue
        nome = (v.get("rule") or chiave).strip()
        corpo = " ".join(x for x in (
            v.get("explanation_en"), v.get("full_rule"),
            v.get("common_mistakes"), v.get("exceptions"),
            " ".join(x for x in (v.get("examples") or []) if isinstance(x, str)),
        ) if x)
        fuori.append(Documento("regola", chiave, nome, corpo, {
            "livello": v.get("level") or "",
            "esempi": [x for x in (v.get("examples") or []) if isinstance(x, str)][:4],
            "spiegazione": v.get("full_rule") or v.get("explanation_en") or "",
            "errori_tipici": v.get("common_mistakes") or "",
            "eccezioni": v.get("exceptions") or "",
            "verificata": bool(v.get("source_verified")),
        }))
    return fuori


def _errori() -> list[Documento]:
    from . import errori as quaderno
    from .errori import chiave_regola

    fuori = []
    for i, e in enumerate(quaderno.registrati(None)):
        detto = (e.get("kevin_said") or "").strip()
        giusto = (e.get("correction") or "").strip()
        fuori.append(Documento("errore", f"e{i}", giusto or detto, " ".join(x for x in (
            detto, giusto, e.get("rule"), e.get("explanation_en"),
            e.get("explanction_en"), e.get("example_correct"),
        ) if x), {
            "detto": detto,
            "giusto": giusto,
            "regola": e.get("rule") or "",
            "chiave": chiave_regola(e.get("rule")),
            "categoria": e.get("category") or "Sonstiges",
            "spiegazione": e.get("explanation_en") or e.get("explanction_en") or "",
            "esempio": e.get("example_correct") or "",
            "quando": (e.get("lesson_date") or e.get("quando") or "")[:10],
            "fonte": quaderno.fonte_di(e),
        }))
    return fuori


def _vocaboli() -> list[Documento]:
    v = _leggi(VOCAB_DB, {})
    parole = v.get("words", v) if isinstance(v, dict) else v
    valori = list(parole.values()) if isinstance(parole, dict) else list(parole or [])
    fuori = []
    for w in valori:
        if not isinstance(w, dict) or not (w.get("german") or "").strip():
            continue
        de = w["german"].strip()
        fuori.append(Documento("vocabolo", de, de, " ".join(x for x in (
            w.get("english"), w.get("italian"), w.get("example_de"),
            w.get("plural"), w.get("category"),
        ) if x), {
            "articolo": w.get("article") or "",
            "plurale": w.get("plural") or "",
            "inglese": w.get("english") or "",
            "italiano": w.get("italian") or "",
            "esempio": w.get("example_de") or "",
            "livello": w.get("level") or "",
            "categoria": w.get("category") or "",
            "volte": w.get("occurrences") or 0,
            "lezioni": [x for x in (w.get("seen_in_lessons") or []) if isinstance(x, str)],
        })
    )
    return fuori


def _passi() -> list[Documento]:
    """I transcript, spezzati in passi leggibili.

    Non per riga: le righe di Whisper qui sono lunghe in media 630 caratteri,
    e un risultato di ricerca lungo mezza pagina non si legge. Non per frase:
    ce ne sono 25.000 e molte sono frammenti di una parola. Frasi consecutive
    fino a `PASSO_MAX`, che e' l'unita' in cui si rilegge una lezione.
    """
    if not TRANSCRIPTS.is_dir():
        return []

    fuori = []
    for f in sorted(TRANSCRIPTS.glob("lezione_*.txt")):
        lezione = f.stem.replace("lezione_", "")
        testo = f.read_text(encoding="utf-8", errors="replace")
        blocco, n = [], 0
        for frase in _FRASE.split(testo):
            frase = " ".join(frase.split())
            if not frase:
                continue
            blocco.append(frase)
            if sum(len(x) + 1 for x in blocco) >= PASSO_MAX:
                fuori.append(Documento("passo", f"{lezione}#{n}", lezione,
                                       " ".join(blocco), {"lezione": lezione}))
                blocco, n = [], n + 1
        if blocco:
            fuori.append(Documento("passo", f"{lezione}#{n}", lezione,
                                   " ".join(blocco), {"lezione": lezione}))
    return fuori


# --------------------------------------------------------------- l'indice

def _firma() -> tuple:
    """Identita' leggera delle fonti: se cambia, l'indice si ricostruisce.

    Stesso meccanismo di `frasi._firma_corpus()`, esteso ai tre database. Copre
    il caso reale: una lezione elaborata mentre il server dell'app e' aperto.
    """
    def _m(p):
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0

    file = list(TRANSCRIPTS.glob("lezione_*.txt")) if TRANSCRIPTS.is_dir() else []
    return (len(file), max((f.stat().st_mtime for f in file), default=0.0),
            _m(GRAMMAR_DB), _m(ERROR_DB), _m(VOCAB_DB))


_STATO: dict = {"firma": None, "doc": [], "inv": {}, "ordinati": []}

# La costruzione costa circa un secondo e puo' partire da due punti insieme: il
# thread di preriscaldamento all'avvio del server e la prima ricerca. Senza
# lucchetto due thread costruirebbero in parallelo (spreco) e un lettore
# potrebbe vedere `doc` nuovo e `inv` vecchio (rotto).
_LUCCHETTO = threading.Lock()


def _costruisci() -> tuple[list[Documento], dict[str, list[int]], list[str]]:
    doc = _regole() + _vocaboli() + _errori() + _passi()

    # Dizionario invertito. Il valore e' una lista invece di un set perche'
    # l'ordine di inserimento e' gia' quello dei generi pesanti per primi, e
    # serve a rendere stabile l'ordinamento a parita' di punteggio.
    inv: dict[str, list[int]] = {}
    for i, d in enumerate(doc):
        # Il titolo entra due volte, nella sua chiave: e' il segnale piu' forte.
        for t in set(_token(d.titolo)):
            inv.setdefault("^" + t, []).append(i)
        for t in set(_token(d.testo)) | set(_token(d.titolo)):
            inv.setdefault(t, []).append(i)
    return doc, inv, sorted(t for t in inv if not t.startswith("^"))


def _indice() -> tuple[list[Documento], dict[str, list[int]], list[str]]:
    firma = _firma()
    if _STATO["firma"] != firma:
        with _LUCCHETTO:
            if _STATO["firma"] != firma:          # un altro thread puo' averlo gia' fatto
                doc, inv, ordinati = _costruisci()
                _STATO.update(firma=firma, doc=doc, inv=inv, ordinati=ordinati)
    return _STATO["doc"], _STATO["inv"], _STATO["ordinati"]


def prepara() -> None:
    """Costruisce l'indice adesso, per non farlo alla prima ricerca.

    Lo chiama il server in un thread all'avvio: un secondo speso mentre si
    guarda la home non si vede, lo stesso secondo speso dopo aver digitato
    nella casella di ricerca sembra un'app che non risponde.
    """
    _indice()


def _per_prefisso(ordinati: list[str], p: str, tetto: int = 40) -> list[str]:
    """I token che iniziano per `p`. Serve alla ricerca mentre si digita."""
    i = bisect.bisect_left(ordinati, p)
    fuori = []
    while i < len(ordinati) and ordinati[i].startswith(p) and len(fuori) < tetto:
        fuori.append(ordinati[i])
        i += 1
    return fuori


# --------------------------------------------------------------- la ricerca

def cerca(q: str, generi: list[str] | None = None, limite: int = 40,
          modo: str = "stretta") -> dict:
    """Cerca in tutto. Nessuna chiamata di rete, nessun costo.

    DUE MODI, perche' sono due domande diverse.

    `stretta` — la casella di ricerca. Tutti i token devono comparire (AND):
    chi digita «konjunktiv passiv» vuole i documenti che parlano di entrambi,
    non di uno dei due. Se l'AND non trova niente si ripiega sull'OR invece di
    mostrare una schermata vuota. L'ULTIMO token vale anche come prefisso,
    perche' la ricerca riparte a ogni battuta e «präpos» deve gia' dire qualcosa.

    `larga` — «cosa c'entra con questo». La query e' un documento intero (il
    nome di una regola, il testo di una correzione) e pretendere che TUTTI i
    suoi token compaiano non trova mai niente: misurato su «Reflexive Verben
    brauchen Reflexivpronomen», l'AND dava zero regole. Si ordina per quanti
    token combaciano, chiedendone almeno due — sotto i due e' rumore.

    Il filtro per genere si applica PRIMA di decidere se ripiegare: altrimenti
    l'AND trova qualcosa del genere sbagliato, il ripiego non scatta, e la
    lista resta vuota pur avendo risultati buoni un gradino sotto.
    """
    doc, inv, ordinati = _indice()
    token = list(dict.fromkeys(_token(q)))
    if not token:
        return {"risultati": [], "totale": 0, "documenti": len(doc),
                "per_genere": {}}

    ammessi = None if not generi else {g for g in generi}
    totale_doc = max(len(doc), 1)

    punteggi: list[dict[int, float]] = []
    for i, t in enumerate(token):
        punti: dict[int, float] = {}
        chiavi = [t]
        if modo == "stretta" and i == len(token) - 1 and t not in inv:
            chiavi = _per_prefisso(ordinati, t)
        for k in chiavi:
            # Quanto vale trovare QUESTO token. Un token che compare in mezzo
            # archivio non distingue niente: senza pesarlo, cercare «Perfekt mit
            # 'sein' bei Bewegungsverben» faceva vincere qualunque scheda con
            # «perfekt» e «sein» dentro — misurati 105 risultati con i primi tre
            # sbagliati. Con il peso, «bewegungsverben» conta sei volte «sein».
            peso = _rarita(len(inv.get(k, ())), totale_doc)
            for n in inv.get("^" + k, ()):
                if ammessi is None or doc[n].genere in ammessi:
                    punti[n] = max(punti.get(n, 0.0), PESO_TITOLO * peso)
            for n in inv.get(k, ()):
                if ammessi is None or doc[n].genere in ammessi:
                    punti.setdefault(n, PESO_TESTO * peso)
        punteggi.append(punti)

    def _voto(n: int) -> float:
        return sum(p.get(n, 0.0) for p in punteggi) * PESO_GENERE.get(doc[n].genere, 1.0)

    def _larghi() -> set[int]:
        """Chi combacia abbastanza, misurato sul migliore.

        Una soglia sul NUMERO di token combacianti non regge: con «sein» e
        «bei» dentro la query, due token si toccano per caso. Una soglia sul
        punteggio si adatta da sola, perche' il punteggio e' gia' pesato per
        rarita'.
        """
        tutti = set().union(*(set(p) for p in punteggi)) if punteggi else set()
        if not tutti:
            return set()
        migliore = max(_voto(n) for n in tutti)
        return {n for n in tutti if _voto(n) >= migliore * FRAZIONE_MIN}

    if modo == "larga":
        candidati = _larghi()
    else:
        candidati = set(punteggi[0])
        for p in punteggi[1:]:
            candidati &= set(p)
        # L'AND da solo si strozza sulle query lunghe, e le query lunghe
        # arrivano davvero: il tasto «Look it up» dell'allenamento passa il nome
        # intero di una regola. Misurato su «Reflexive Verben brauchen
        # Reflexivpronomen»: l'AND dava zero regole, perche' i quattro token non
        # stanno mai tutti nella stessa scheda. Sotto MIN_UTILE si completa,
        # e il punteggio mette comunque sopra chi combacia su tutto.
        if len(candidati) < MIN_UTILE:
            candidati |= _larghi()

    voti = sorted(((_voto(n), n) for n in candidati), key=lambda x: (-x[0], x[1]))

    return {
        "risultati": [_riga(doc[n], punto, token) for punto, n in voti[:limite]],
        "totale": len(voti),
        "documenti": len(doc),
        "per_genere": _conta_generi([doc[n] for _, n in voti]),
    }


def _conta_generi(doc: list[Documento]) -> dict[str, int]:
    fuori: dict[str, int] = {}
    for d in doc:
        fuori[d.genere] = fuori.get(d.genere, 0) + 1
    return fuori


def _riga(d: Documento, punto: float, token: list[str]) -> dict:
    return {
        "genere": d.genere,
        "id": d.id,
        "titolo": d.titolo,
        "estratto": _estratto(d, token),
        "punteggio": round(punto, 2),
        "meta": d.meta,
    }


def _estratto(d: Documento, token: list[str], intorno: int = 130) -> str:
    """Il pezzo di testo attorno al primo riscontro.

    Su un passo di transcript da 260 caratteri sembra un dettaglio; su una
    regola con `full_rule` + `common_mistakes` + `exceptions` no — senza,
    la riga di risultato mostrerebbe sempre l'inizio, che spesso non e' la
    parte che hai cercato.
    """
    testo = d.testo
    if not testo:
        return ""
    piatto = _piatto(testo)
    pos = min((piatto.find(t) for t in token if t and piatto.find(t) >= 0),
              default=-1)
    if pos < 0 or len(testo) <= intorno * 2:
        return testo[: intorno * 2].strip()
    a = max(0, pos - intorno // 2)
    b = min(len(testo), a + intorno * 2)
    return ("… " if a else "") + testo[a:b].strip() + (" …" if b < len(testo) else "")


# --------------------------------------------------------------- il dettaglio

def dettaglio(genere: str, id_doc: str) -> dict:
    """Un documento con i suoi collegamenti, distinti per affidabilita'.

    `esatti` sono relazioni che si possono affermare; `simili` sono risultati
    di ricerca, e l'interfaccia deve dirlo. Vedi il perche' in cima al modulo.
    """
    doc, _, _ = _indice()
    trovato = next((d for d in doc if d.genere == genere and d.id == id_doc), None)
    if not trovato:
        return {"errore": "documento sconosciuto"}

    esatti: list[dict] = []
    simili: list[dict] = []

    if genere == "errore":
        chiave = trovato.meta.get("chiave")
        cat = trovato.meta.get("categoria")
        # Stessa chiave normalizzata = stessa regola, per costruzione. Questo
        # si puo' affermare senza ricerca e senza soglie.
        esatti = [_riga(d, 0.0, []) for d in doc
                  if d.genere == "errore" and d is not trovato
                  and chiave and d.meta.get("chiave") == chiave]
        simili = cerca(trovato.meta.get("regola") or trovato.titolo,
                       generi=["regola"], limite=5, modo="larga")["risultati"]
        contorno = {"categoria": cat,
                    "nella_categoria": sum(1 for d in doc if d.genere == "errore"
                                           and d.meta.get("categoria") == cat)}

    elif genere == "regola":
        # Qui NON c'e' una relazione esatta: i nomi delle regole in error_db
        # sono testo libero in tedesco, i titoli di grammar_db sono altro.
        # Si mostrano risultati di ricerca, e si dice che lo sono.
        simili = cerca(f"{trovato.titolo} {trovato.meta.get('spiegazione','')[:120]}",
                       generi=["errore"], limite=6, modo="larga")["risultati"]
        contorno = {"livello": trovato.meta.get("livello")}

    elif genere == "vocabolo":
        from ..studio import frasi
        esatti = [{"genere": "passo", "id": "", "titolo": c.get("lezione", ""),
                   "estratto": c.get("testo", ""), "punteggio": 0.0, "meta": c}
                  for c in frasi.contesti(trovato.titolo, limite=6)]
        contorno = {"volte": trovato.meta.get("volte")}

    else:                                        # passo
        simili = cerca(trovato.testo[:120], generi=["vocabolo"], limite=5,
                       modo="larga")["risultati"]
        contorno = {"lezione": trovato.meta.get("lezione")}

    return {
        "documento": _riga(trovato, 0.0, []),
        "testo": trovato.testo,
        "esatti": esatti,
        "simili": simili,
        "contorno": contorno,
    }


def statistiche() -> dict:
    doc, inv, _ = _indice()
    return {
        "documenti": len(doc),
        "per_genere": _conta_generi(doc),
        "token": sum(1 for t in inv if not t.startswith("^")),
    }
