"""Sta funzionando? — i numeri, e cosa NON dicono.

LA DOMANDA E' ONESTA, LA RISPOSTA FACILE E' FALSA
La cosa piu' semplice da disegnare qui sarebbe la curva delle correzioni per
lezione, con una linea di tendenza. Misurata sui dati reali: **9,0 correzioni a
lezione nella prima meta' del periodo, 10,0 nella seconda**. Piatta, e rumorosa.

E anche se scendesse non vorrebbe dire quasi niente, perche' quel numero dipende
da quanto hai parlato, da quanto Stefanie ha corretto, dalla durata della
lezione e da quanto bene Whisper ha trascritto. Misura **esposizione**, non
padronanza — lo stesso limite che `esame.py` dichiara sulla copertura del
curriculum: e' una metrica auto-prodotta dal sistema che genera le lezioni.

Quindi la curva si mostra, perche' e' un dato vero e vederla piatta e' esso
stesso informativo, ma etichettata per cio' che e'. La metrica che misura
davvero il progresso e' un'altra, e viene dall'app: **quanti esercizi risolvi
senza aiuto, e a che gradino ti fermi**. Quella non dipende da quanto hai
parlato in lezione. Oggi ha pochi dati, e questa zona lo dice invece di
disegnarci sopra una tendenza.

NIENTE METRICHE DI VANITA'
Nessuno streak, nessun punteggio, nessun badge. Fatti sul comportamento:
quando hai studiato l'ultima volta, quanti esercizi hai chiuso senza aiuto,
quante regole sono uscite dalla coda, quante carte Anki ti aspettano.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime

from ..base.config import ANKI_DECK
from ..sapere import errori as quaderno

FAMIGLIA_CASI = ("Kasus", "Genus", "Präposition")

# Sotto questo numero di risposte, il gradino di aiuto non e' una tendenza: e'
# un aneddoto. Meglio dire «non ancora» che disegnare una curva su tre punti.
MINIME_PER_TENDENZA = 20


def per_lezione() -> list[dict]:
    """Correzioni per lezione, separando la famiglia dei casi dal resto.

    Due serie e non nove: nove categorie su un grafico nel tempo sono
    illeggibili, e la storia qui e' gia' nota — il 44% degli errori sono
    Kasus, Genus e Präposition. E' un grafico a enfasi: una serie e' il punto,
    l'altra e' contesto.
    """
    per: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for e in quaderno.registrati(quaderno.LEZIONE):
        d = (e.get("lesson_date") or "")[:10]
        if not d:
            continue
        per[d][0 if e.get("category") in FAMIGLIA_CASI else 1] += 1
    return [{"data": d, "casi": c, "altri": a, "totale": c + a}
            for d, (c, a) in sorted(per.items())]


def per_categoria() -> list[dict]:
    """Quante correzioni per categoria. Categorie nominali: un colore solo.

    Colorarle a gradiente per valore rifarebbe con la tinta cio' che la
    lunghezza della barra dice gia', sprecando l'unico canale libero.
    """
    c = Counter(e.get("category") or "Sonstiges"
                for e in quaderno.registrati(quaderno.LEZIONE))
    return [{"nome": n, "quante": q} for n, q in c.most_common()]


def _media(valori: list[float]) -> float | None:
    return round(sum(valori) / len(valori), 2) if valori else None


def studio() -> dict:
    """Cosa dice l'app di se stessa. E' qui che sta il progresso vero."""
    from . import allenamento, sessione

    risposte = [r for r in sessione.risposte()]
    # Il gradino di aiuto esiste solo in Practice: Listening (do/uscite/web.py:
    # libro_risposta) e' autovalutato e non ha mai `aiuto`, quindi ogni suo
    # record entrerebbe qui come "aiuto 0" — falsando la media, la tendenza e
    # la soglia MINIME_PER_TENDENZA sotto. `risposte` resta intera (serve per
    # "ultima" e per il conteggio totale: Listening e' comunque studio), ma le
    # metriche sul gradino filtrano su zona.
    pratica = [r for r in risposte if r.get("zona") != "listening"]
    aiuti = [int(r.get("aiuto") or 0) for r in pratica]
    # "chiuso senza aiuto" e' la definizione di progresso vero di questo
    # modulo (vedi CLAUDE.md "il progresso lo misura... quanti esercizi
    # chiudi senza aiuto") — stesso filtro di zona di `pratica` sopra.
    pulite = [r for r in pratica if r.get("corretta") and not r.get("aiuto")]

    ses = sessione.riepilogo()
    # Anche una sessione mai chiusa conta come studio: le risposte si posano
    # subito, e ignorarle direbbe «mai studiato» a chi ha appena studiato.
    ultima = ses["ultima"]
    if risposte:
        ultima_risposta = max((r.get("quando") or "")[:10] for r in risposte)
        ultima = max(ultima or "", ultima_risposta) or None

    giorni = None
    if ultima:
        try:
            giorni = (date.today() - date.fromisoformat(ultima)).days
        except ValueError:
            pass

    # La tendenza del gradino: prima meta' contro seconda. Solo con abbastanza
    # dati — su tre risposte sarebbe un aneddoto con una freccia sopra.
    tendenza = None
    if len(aiuti) >= MINIME_PER_TENDENZA:
        meta = len(aiuti) // 2
        tendenza = {"prima": _media(aiuti[:meta]), "dopo": _media(aiuti[meta:])}

    return {
        "risposte": len(risposte),
        "senza_aiuto": len(pulite),
        "aiuto_medio": _media([float(a) for a in aiuti]),
        "tendenza_aiuto": tendenza,
        "servono_ancora": max(0, MINIME_PER_TENDENZA - len(aiuti)),
        "regole_chiuse": len(allenamento.padroneggiate()),
        "regole_in_coda": len(allenamento.coda(500)),
        "da_rifare": len(allenamento.da_rifare()),
        "sessioni": ses["totale"],
        "ultima": ultima,
        "giorni_da_ultima": giorni,
        "errori_dallo_studio": len(quaderno.registrati(quaderno.STUDIO)),
    }


def anki() -> dict:
    """Le carte in scadenza. Se Anki e' chiuso, sparisce e basta.

    Stessa degradazione della pipeline: una zona che non si apre perche' un
    programma esterno non e' in esecuzione non viene riaperta.

    UNA CHIAMATA SOLA, ED E' MISURATA
    AnkiConnect paga circa 2 secondi fissi a richiesta, indipendentemente dalla
    query: `is:due` su 24 carte e il conteggio di tutte e 1.076 costano lo
    stesso. Tre domande separate facevano 6,2 secondi; impacchettate in `multi`
    ne fanno 2,08. Il resto — non far aspettare la pagina — lo risolve il
    frontend, che chiede questo riquadro a parte.
    """
    from .carte import anki as chiama_anki

    domande = [f'deck:"{ANKI_DECK}" is:due', f'deck:"{ANKI_DECK}"',
               f'deck:"{ANKI_DECK}" is:new']
    try:
        r = chiama_anki("multi", timeout=6, actions=[
            {"action": "findCards", "params": {"query": q}} for q in domande
        ])
        scadenza, totali, nuove = (len(x) for x in r)
    except Exception:
        return {"disponibile": False}
    return {
        "disponibile": True,
        "mazzo": ANKI_DECK,
        "in_scadenza": scadenza,
        "nuove": nuove,
        "totali": totali,
        # Quante ne hai davvero in circolo: le nuove non sono studio arretrato,
        # sono materiale mai iniziato, e sommarle allo scaduto farebbe paura
        # senza motivo.
        "in_studio": totali - nuove,
    }


def tutto() -> dict:
    lez = per_lezione()
    n = len(lez)
    meta = n // 2
    confronto = None
    if n >= 8:
        confronto = {
            "prima": round(sum(x["totale"] for x in lez[:meta]) / meta, 1),
            "dopo": round(sum(x["totale"] for x in lez[meta:]) / (n - meta), 1),
        }
    # `anki()` NON e' qui: costa 2 secondi anche quando va bene, e sono 2
    # secondi di pagina bianca per un riquadro che e' contesto, non contenuto.
    # Il frontend lo chiede a parte, a pagina gia' disegnata.
    return {
        "per_lezione": lez,
        "per_categoria": per_categoria(),
        "confronto_lezioni": confronto,
        "studio": studio(),
        "generato": datetime.now().isoformat(timespec="seconds"),
    }
