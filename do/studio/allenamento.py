"""L'Allenamento — la zona dove il ciclo si chiude.

COSA FA CHE IL DRILL NON FACEVA
`drill.py` genera un foglio di esercizi e lo stampa. Cosa succeda dopo, nessuno
lo sa: `drill.json` porta il campo `generato`, non `svolto`. Qui l'esercizio
viene proposto, la risposta viene valutata, l'errore torna nel quaderno e la
regola rientra in coda. Senza questo pezzo il progetto sa tutto di cio' che
produce e niente di cio' che impari.

I TRE MECCANISMI, E PERCHE' SONO TRE

1. **La scala di aiuto (0-4).** Puoi salire quando vuoi, ma ogni gradino viene
   registrato. Un esercizio risolto al gradino 3 non vale come uno risolto al
   gradino 0, e il sistema non deve credersi piu' bravo di quanto sei. Il
   gradino 4 mostra la soluzione e conta come NON risolto.

2. **La valutazione ibrida.** Prima le regole, che costano zero: uguaglianza
   stretta, poi larga (maiuscole, ae/oe/ue/ss). Il modello entra solo quando le
   regole non decidono. Su un esercizio azzeccato non parte nessuna chiamata.

3. **La coda per recidiva.** L'ordine non e' casuale ne' cronologico: prima cio'
   che hai sbagliato nell'app e non hai ancora rifatto giusto, poi le regole
   recidive, poi la famiglia dei casi, poi l'ultima lezione, poi i buchi B2.

COSA HO MISURATO SULLA RECIDIVA, E PERCHE' LA SOGLIA E' 2
Il piano diceva «regole con recidiva >= 3». Sui 295 errori reali quel filtro
seleziona ZERO regole, perche' il nome della regola lo scrive il modello in
linguaggio libero: «Modalverb am Ende im Nebensatz» e «Nebensatz: Verb am Ende»
sono la stessa cosa e contano uno ciascuno — 288 nomi distinti su 295 errori.

`chiave_regola()` normalizza (minuscole, senza diacritici, parole vuote via,
token ordinati) e porta i nomi distinti a 283: recidiva >= 3 diventa 3 regole,
recidiva >= 2 diventa 8. Poche, ma vere. La CATEGORIA invece aggrega davvero —
e' la tassonomia canonica di `errori.CATEGORIE` — ed e' li' che sta il segnale
forte: Kasus 62, Wortwahl 57, Verbform 46, Wortstellung 44, Präposition 41.

Quindi: la soglia scende a 2 sulla chiave normalizzata, e la bacchettata conta
la recidiva su ENTRAMBI i piani — la regola specifica e la categoria — dicendo
quale sta contando. Un numero grosso senza dire cosa aggrega e' un numero falso.
"""

from __future__ import annotations

import contextlib
import json
import re
import threading
import unicodedata
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

from ..base.config import llm_config
from ..base.llm import chiama, estrai_json
from ..base.paths import DATA
from ..sapere import errori as quaderno
from ..sapere.errori import chiave_regola      # vive col record, non col drill
from . import drill

DEPOSITO = DATA / "esercizi.json"

# Sotto questa soglia di esercizi ancora da fare, il deposito si ricarica.
SCORTA_MINIMA = 8
QUANTI_PER_VOLTA = 20

# Una regola con almeno due occorrenze e' recidiva. Vedi il docstring: con la
# soglia a 3 del piano il filtro selezionava zero regole su 295 errori.
RECIDIVA_MIN = 2

# Quanto resta "caldo" un errore fatto nell'app. Oltre questa finestra smette di
# essere la priorita' assoluta e rientra nella graduatoria normale.
FINESTRA_CALDA_H = 48

# Quanta parte di un blocco va ai temi B2 mai coperti in lezione. Vedi `coda()`.
QUOTA_TEMI_B2 = 0.15

# Due risposte corrette al gradino 0, a distanza di almeno un giorno, e la
# regola esce dalla coda. Una sola non basta: potrebbe essere memoria a breve.
CORRETTE_PER_USCIRE = 2
GIORNI_FRA_LE_DUE = 1

_LUCCHETTO = threading.Lock()


# ------------------------------------------------------------------ chiavi

def recidiva(errori: list[dict] | None = None) -> tuple[Counter, Counter]:
    """Quante volte per regola e quante per categoria. Due piani, non uno."""
    errori = errori if errori is not None else quaderno.registrati(None)
    return (
        Counter(chiave_regola(e.get("rule")) for e in errori),
        Counter(e.get("category") or "?" for e in errori),
    )


def storico(errore: dict, errori: list[dict] | None = None) -> dict:
    """Il passato di una regola: quante volte, la prima, l'ultima, con chi.

    E' la meta' della bacchettata. «Sbagliato» non insegna niente; «e' la sesta
    volta su questa regola, la prima il 14 maggio con Stefanie» si': dice che
    non e' una svista ma un buco.
    """
    errori = errori if errori is not None else quaderno.registrati(None)
    k = chiave_regola(errore.get("rule"))
    cat = errore.get("category") or "?"

    simili = [e for e in errori if chiave_regola(e.get("rule")) == k] if k else []
    di_categoria = [e for e in errori if (e.get("category") or "?") == cat]

    def _quando(e: dict) -> str:
        return (e.get("lesson_date") or e.get("quando") or "")[:10]

    date_regola = sorted(d for d in (_quando(e) for e in simili) if d)
    return {
        "regola": errore.get("rule") or "",
        "categoria": cat,
        "volte_regola": len(simili),
        "volte_categoria": len(di_categoria),
        "prima": date_regola[0] if date_regola else None,
        "ultima": date_regola[-1] if date_regola else None,
        "in_lezione": sum(1 for e in simili
                          if quaderno.fonte_di(e) == quaderno.LEZIONE),
        "nell_app": sum(1 for e in simili
                        if quaderno.fonte_di(e) == quaderno.STUDIO),
    }


# ------------------------------------------------------------------ esiti passati

def esiti() -> dict[str, list[dict]]:
    """Cosa e' successo in allenamento, per chiave di regola.

    DUE FONTI, E LA PRIMA E' QUELLA CHE CONTA
    `risposte.json` si scrive a ogni risposta; `sessioni.json` solo quando la
    sessione arriva in fondo. Leggere solo la seconda ha gia' perso dati veri:
    al primo uso reale due esercizi sono stati svolti e il registro sessioni e'
    rimasto vuoto, quindi la coda non ha visto ne' cosa rifare ne' cosa era
    andato bene. Le sessioni restano lette per non buttare lo storico.
    """
    from . import sessione

    fuori: dict[str, list[dict]] = {}

    def _posa(e: dict, quando_difetto: str) -> None:
        k = e.get("chiave") or chiave_regola(e.get("regola"))
        if not k:
            return
        voce = {
            "quando": e.get("quando") or quando_difetto or "",
            "corretta": bool(e.get("corretta")),
            "aiuto": int(e.get("aiuto") or 0),
            "stimolo": e.get("stimolo") or "",
        }
        righe = fuori.setdefault(k, [])
        # Lo stesso esercizio arriva da entrambe le fonti: si tiene una volta.
        if any(r["stimolo"] == voce["stimolo"] and r["quando"][:16] == voce["quando"][:16]
               for r in righe):
            return
        righe.append(voce)

    for r in sessione.risposte():
        _posa(r, r.get("quando", ""))
    for s in sessione.tutte():
        if s.get("zona") != "practice":
            continue
        for e in s.get("esercizi", []):
            _posa(e, s.get("quando", ""))

    for v in fuori.values():
        v.sort(key=lambda x: x["quando"])
    return fuori


def padroneggiate(passati: dict[str, list[dict]] | None = None) -> set[str]:
    """Le regole uscite dalla coda: due volte giuste al gradino 0, a un giorno
    di distanza almeno.

    La distanza conta piu' del numero. Due risposte giuste nella stessa
    sessione dimostrano che la pagina e' ancora sullo schermo, non che la
    regola e' tua.
    """
    passati = passati if passati is not None else esiti()
    fuori = set()
    for k, righe in passati.items():
        pulite = sorted(r["quando"][:10] for r in righe
                        if r["corretta"] and r["aiuto"] == 0)
        if len(pulite) < CORRETTE_PER_USCIRE:
            continue
        try:
            prima = date.fromisoformat(pulite[0])
            ultima = date.fromisoformat(pulite[-1])
        except ValueError:
            continue
        if (ultima - prima).days >= GIORNI_FRA_LE_DUE:
            fuori.add(k)
    return fuori


def da_rifare(passati: dict[str, list[dict]] | None = None) -> set[str]:
    """Regole sbagliate nell'app di recente e non ancora rifatte giuste."""
    return _da_rifare(passati if passati is not None else esiti())


def _momento(t: str) -> datetime | None:
    """Timestamp -> datetime naive locale, o None.

    Il fuso si toglie, non si converte. Nel registro possono convivere orari
    scritti dal server (`datetime.now()`, naive) e dal browser (UTC con la Z):
    confrontarli direttamente solleva TypeError, e sarebbe un TypeError che
    rompe l'intera coda per un dettaglio di serializzazione.
    """
    try:
        d = datetime.fromisoformat(str(t))
    except (TypeError, ValueError):
        return None
    return d.replace(tzinfo=None) if d.tzinfo else d


def _da_rifare(passati: dict[str, list[dict]]) -> set[str]:
    """Regole sbagliate qui di recente e non ancora rifatte giuste.

    DUE PORTE, NON UNA
    Un errore fatto nell'app arriva da due strade: una risposta sbagliata in
    allenamento (che lascia una riga in `risposte.json`) oppure un errore
    trovato correggendo un testo scritto (che lascia solo un record nel
    quaderno). La seconda e' altrettanto fresca e altrettanto tua — anzi, viene
    da produzione libera, che e' la prova piu' severa — e guardare solo la
    prima le farebbe scivolare in fondo alla coda insieme agli errori di
    maggio.
    """
    limite = datetime.now() - timedelta(hours=FINESTRA_CALDA_H)
    calde = set()

    for k, righe in passati.items():
        for r in righe:
            q = _momento(r["quando"])
            if q is None:
                continue
            if r["corretta"]:
                calde.discard(k)            # l'ultimo esito vince
            elif q >= limite:
                calde.add(k)

    # Gli errori scritti nel quaderno dall'app: stessa finestra, stessa regola
    # dell'ultimo esito — una risposta giusta piu' recente li raffredda.
    for e in quaderno.registrati(quaderno.STUDIO):
        k = chiave_regola(e.get("rule"))
        q = _momento((e.get("quando") or ""))
        if not k or q is None or q < limite:
            continue
        buone = [r for r in passati.get(k, [])
                 if r["corretta"] and (_momento(r["quando"]) or datetime.min) > q]
        if not buone:
            calde.add(k)

    return calde


# ------------------------------------------------------------------ la coda

def _temi_b2() -> list[dict]:
    """I temi B2 dichiarati mancanti dalla gap analysis. Ultima priorita'.

    Non sono errori: non c'e' una frase sbagliata da cui partire. Entrano come
    voci di tipo `tema`, e il generatore costruisce l'esercizio dal tema.
    """
    try:
        d = json.loads((DATA / "esame_b2.json").read_text(encoding="utf-8"))
    except Exception:
        return []
    return [g for g in d.get("grammatica", [])
            if isinstance(g, dict) and g.get("stato") == "mancante"]


def coda(limite: int = QUANTI_PER_VOLTA) -> list[dict]:
    """Su cosa allenarsi, in ordine. Nessuna chiamata di rete.

    Cinque livelli di priorita', dal piano §4.3. Dentro ogni livello vince il
    piu' recente: un errore di ieri e' piu' vivo di uno di due mesi fa.
    """
    tutti = [e for e in quaderno.registrati(None) if e.get("correction")]
    passati = esiti()
    fuori_gioco = padroneggiate(passati)
    calde = _da_rifare(passati)
    rec_regola, _ = recidiva(tutti)

    date_lez = sorted({e.get("lesson_date") or "" for e in tutti} - {""})
    ultima_lezione = date_lez[-1] if date_lez else None

    voci = []
    for e in tutti:
        k = chiave_regola(e.get("rule"))
        if k and k in fuori_gioco:
            continue

        n = rec_regola.get(k, 0)
        if k and k in calde:
            liv, motivo = 0, "you got this wrong here recently"
        elif n >= RECIDIVA_MIN:
            liv, motivo = 1, f"{n}× on this rule"
        elif (e.get("category") or "") in drill.FAMIGLIA_CASI:
            liv, motivo = 2, f"{e.get('category')} — the case system"
        elif ultima_lezione and e.get("lesson_date") == ultima_lezione:
            liv, motivo = 3, "from your latest lesson"
        else:
            liv, motivo = 4, e.get("category") or "mixed"

        voci.append({
            "tipo": "errore",
            "livello": liv,
            "motivo": motivo,
            "chiave": k,
            "regola": e.get("rule") or "",
            "categoria": e.get("category") or "Sonstiges",
            "sbagliato": e.get("kevin_said") or "",
            "corretto": e.get("correction") or "",
            "spiegazione": e.get("explanation_en") or e.get("explanction_en") or "",
            "quando": (e.get("lesson_date") or e.get("quando") or "")[:10],
            "fonte": quaderno.fonte_di(e),
        })

    voci.sort(key=lambda v: (v["livello"], v["quando"] == "", _neg(v["quando"])))

    # Una regola sola non merita cinque esercizi di fila: dentro la stessa
    # chiave si tiene il record piu' recente e si passa alla successiva.
    viste, snella = set(), []
    for v in voci:
        if v["chiave"] and v["chiave"] in viste:
            continue
        viste.add(v["chiave"])
        snella.append(v)

    # I temi B2 hanno una QUOTA, non l'ultimo posto in graduatoria. Come ultima
    # priorita' su 283 regole non padroneggiate non uscirebbero mai — e sono
    # esattamente cio' che l'esame chiede e che le lezioni non hanno coperto
    # (Konjunktiv I, Nominalisierung: `esame_b2.json` ne elenca 22 mancanti).
    # Aspettare di aver chiuso tutti gli errori prima di toccarli non e' una
    # priorita' bassa, e' non farlo.
    temi = [t for t in _temi_b2() if chiave_regola(t.get("tema")) not in fuori_gioco]
    quota = min(len(temi), round(limite * QUOTA_TEMI_B2)) if temi else 0

    scelte = snella[: limite - quota]
    for t in temi[:quota]:
        scelte.append({
            "tipo": "tema",
            "livello": 5,
            "motivo": "B2 gap — never covered in your lessons",
            "chiave": chiave_regola(t.get("tema")),
            "regola": t.get("tema") or "",
            "categoria": "Sonstiges",
            "sbagliato": "",
            "corretto": "",
            "spiegazione": t.get("nota") or "",
            "quando": "",
            "fonte": "esame",
        })
    return scelte


def _neg(d: str) -> str:
    """Chiave di ordinamento decrescente su una data ISO, senza reverse."""
    return "".join(chr(255 - ord(c)) if ord(c) < 255 else c for c in d)


# ------------------------------------------------------------------ riferimento reale
# Kevin, 2026-08-13: "crea delle frasi davvero senza senso" — il modello
# costruiva ogni stimolo dal nulla, partendo solo dal nome della regola e dal
# suo errore. Qui si cerca prima una frase VERA che tocca la stessa area
# (libro, poi corpus lezioni) e la si passa come riferimento di tono e
# vocabolario — il modello continua a costruire un esercizio NUOVO (regola 2
# del prompt), ma ancorato invece che nel vuoto.
_PAROLA_CONTENUTO = re.compile(r"[a-zA-ZäöüÄÖÜß]{4,}")


def riferimento(v: dict) -> str:
    """Una frase reale da dare al modello come ancora, o "" se non se ne trova una.

    Non e' un requisito: l'esercizio si costruisce comunque senza, come prima.
    """
    from ..sapere import libro

    parole = _PAROLA_CONTENUTO.findall(f"{v.get('regola', '')} {v.get('corretto', '')}")
    if trovate := libro.cerca_riferimento(parole, quante=1):
        return trovate[0]

    # I temi B2 sono fuori dal libro per definizione (il Kursbuch arriva a
    # B1): l'unica fonte reale possibile e' la ricerca esterna.
    if v.get("tipo") == "tema":
        return _riferimento_web(v.get("regola", ""))
    return ""


def _riferimento_web(tema: str) -> str:
    """Una frase B1/B2 reale per un tema mai coperto in lezione, via la
    pipeline di ricerca esterna di `shared start up/` (CLAUDE.md root SS3.1:
    Perplexity -> Gemini -> Claude, mai WebSearch nativo qui). Query generica,
    nessun dato personale — solo il nome della regola grammaticale.

    Best-effort e silenzioso: se lo script manca, la chiave non e' configurata,
    o la chiamata fallisce, l'esercizio si costruisce senza riferimento — non
    e' un requisito, e' un aiuto quando c'e'.
    """
    import subprocess
    import tempfile

    from ..base.paths import SHARED, shared_disponibile

    if not tema or not shared_disponibile():
        return ""
    script = SHARED / "risorse-team" / "skills" / "interne" / "ricerca-esterna" / "ricerca_web.py"
    if not script.exists():
        return ""

    domanda = (f"One single natural German sentence at B1 or B2 level that "
               f"illustrates this grammar topic: {tema}. Reply with just the "
               f"sentence, nothing else.")
    out: str | None = None
    try:
        with tempfile.NamedTemporaryFile("r", suffix=".md", delete=False,
                                         encoding="utf-8") as f:
            out = f.name
        r = subprocess.run(
            ["py", "-3", str(script), domanda, "--out", out],
            capture_output=True, text=True, timeout=60,
            encoding="utf-8", errors="replace",
        )
        if r.returncode != 0:
            return ""
        testo = Path(out).read_text(encoding="utf-8", errors="replace")
        for riga in testo.splitlines():
            riga = riga.strip(" -*#\t")
            if re.search(r"[äöüßÄÖÜ]", riga) and 15 < len(riga) < 220:
                return riga
    except Exception:                                          # noqa: BLE001
        pass
    finally:
        if out:
            with contextlib.suppress(OSError):
                Path(out).unlink()
    return ""


# ------------------------------------------------------------------ generazione

SYSTEM = """You build German production exercises for Kevin: Italian native,
working towards Goethe B2, moving into the Swiss pharmaceutical sector.

Each ITEM you receive is either a mistake he really made (with his teacher's
correction) or a B2 topic his lessons never covered. Write ONE exercise per item.

Non-negotiable rules:

1. He must PRODUCE the German, never pick from options. Recognising is easy and
   gives the illusion of knowing; producing is what the exam measures.
2. Do NOT reuse his original wrong sentence. Build a NEW context that requires
   the same structure. If he recognises the sentence, he is remembering it, not
   applying the rule.
   Some items carry a "real German sentence for reference" — genuine text from
   his course book or the web, touching similar vocabulary. It is there so you
   are not inventing in a vacuum, not a template: use it only for register and
   plausibility, never copy its wording or structure into the exercise.
3. **The stimulus contains EXACTLY ONE gap, written `___`, and the answer is
   exactly what replaces it.** One box, one gap, one contiguous span. Two gaps
   with one answer is unanswerable — he cannot know which one you mean:
     BAD   "Das neue Werk liegt ___ der Schweiz, nicht ___ Süden."  -> im Norden
     BAD   "Der Zug ___ vor zehn Minuten ___ . (ankommen)"          -> ist angekommen
   Separable and compound verbs still work — put the gap where the rule lives:
     GOOD  "Der Zug ___ vor zehn Minuten angekommen."   -> ist   (gloss: "has")
     GOOD  "Vor zehn Minuten ist der Zug ___ ."         -> angekommen
   If a rule cannot be tested with one gap, choose a different angle on it.
4. **Every exercise MUST carry "traduzione": a natural English translation of
   the WHOLE sentence, as if the gap were already filled correctly.** Pure
   English, no German words in it. This does not give the answer away — the
   answer is the German FORM (case, ending, position, auxiliary), and a
   translation cannot express it. What it does give is the frame: without it a
   learner stares at a sentence he cannot parse and stops, and a stopped
   learner learns nothing. It is also the part worth re-reading afterwards.

   **The translation, the gloss and the solution must all say the same thing.**
   Write the solution first, then translate the sentence WITH it in place. An
   inconsistency here is worse than no translation, because it teaches the wrong
   word with confidence:
     BROKEN  "Er hat das Auto nicht kaufen ___."  -> wollen
             gloss "wanted to" · translation "He wasn't allowed to buy the car"
             ("wasn't allowed" is dürfen, not wollen — three fields, two meanings)
     FIXED   same gap, translation "He didn't want to buy the car"
   Re-read each finished item and check the three fields agree before returning.
5. **Every exercise MUST carry "gloss": the English of exactly what goes in the
   gap, and nothing else.** Not a translation of the sentence — of the gap.
   For an answer "im Norden" the gloss is "in the north"; for "den Preis" it is
   "the price (object)". This is not optional and not a hint: without it the
   exercise tests whether he can guess your intention, which is untestable.
   Compare:
     BAD   "Meine Firma hat eine neue Fabrik ___ gebaut."   -> im Norden
           (in the south? near Berlin? last year? nothing decides)
     GOOD  same sentence, gloss "in the north"
           (now the only question is the German form: in + dem -> im + Dativ)
   The gloss gives away the MEANING on purpose. What is being tested is the
   FORM — case, ending, gender, position — never whether he read your mind.
6. There must be exactly ONE right German answer for that gloss. List genuinely
   equivalent ones in "alternative".
7. The solution must be correct, natural German. If you are not sure of a form,
   pick a different angle on the same rule: a mistake here would be studied as
   if it were right.
8. Everyday or professional register. No proper names, no quotation marks.
9. **"livello" is the CEFR level of what the exercise ASKS FOR, not of the rule
   in the abstract.** The same rule can be tested at several levels, and the
   difference is the sentence around it: `Ich fahre ___ Schweiz` is A2,
   `Der Bericht, ___ Fertigstellung sich verzögert hat, liegt vor` is B2. Judge
   the vocabulary and the clause structure you actually wrote, and be honest —
   labelling a B1 sentence A2 makes the whole library unusable for choosing
   what to work on.

For each exercise also produce the HELP LADDER. He can climb it during the
exercise, and each step is recorded, so each step must give strictly more than
the one below:

  - "regola"     — the rule in 1-2 lines, in English. What governs the answer.
  - "struttura"  — the skeleton with the decisive part left open, e.g.
                   "aus + [dative feminine article] + Schweiz". It must make the
                   answer derivable without stating it.

Write instructions and explanations in ENGLISH. German content in German.
No Italian anywhere.

Reply with valid JSON only, no backticks:
{"esercizi":[{"consegna":"<what to do, in English, one line>",
              "stimolo":"<the German prompt: sentence with a gap, or the sentence to rewrite>",
              "traduzione":"<REQUIRED — natural English of the whole sentence, gap filled, no German>",
              "gloss":"<REQUIRED — the English of exactly what fills the gap>",
              "soluzione":"<the expected German answer, only the part he must write>",
              "alternative":["<other fully correct answers, or empty list>"],
              "regola":"<the rule, 1-2 lines, English>",
              "struttura":"<the skeleton, step 3 of the ladder>",
              "perche":"<one line, English: why the solution is right — shown after answering>",
              "categoria":"<one of: Genus, Wortstellung, Präposition, Kasus, Verbform, Wortwahl, Adjektivdeklination, Sonstiges>",
              "livello":"<A1|A2|B1|B2 — the CEFR level of what this exercise ASKS FOR>",
              "nome_regola":"<the rule name from the item, copied unchanged>",
              "tipo":"gap|rewrite|translate"}]}"""


def _carica() -> dict:
    try:
        d = json.loads(DEPOSITO.read_text(encoding="utf-8"))
        if isinstance(d, dict) and isinstance(d.get("esercizi"), list):
            return d
    except Exception:
        pass
    return {"esercizi": [], "costo_totale_eur": 0.0}


def utilizzabile(e: dict) -> str:
    """"" se l'esercizio si puo' proporre, altrimenti il motivo per cui no.

    TRE CONTROLLI, E LI HA DETTATI KEVIN, USANDO L'APP

    0. **Senza traduzione ci si blocca.** Una frase tedesca che non si riesce a
       leggere non e' un esercizio difficile, e' un muro: ci si ferma e basta.
       L'inglese dell'intera frase non rivela niente, perche' cio' che si deve
       produrre e' la FORMA tedesca — caso, desinenza, posizione, ausiliare — e
       una traduzione non la esprime. In piu' e' la parte che resta utile dopo,
       quando la frase si rilegge.

    1. **Senza glossa non e' una domanda, e' un indovinello.** «Meine Firma hat
       eine neue Fabrik ___ gebaut» ammette im Norden, im Süden, in Berlin,
       letztes Jahr: niente nella frase decide quale. L'inglese di cio' che va
       nel buco regala il SIGNIFICATO di proposito, perche' cio' che si allena
       e' la FORMA.
    2. **Un buco solo.** Con due `___` e una risposta sola non si sa cosa
       scrivere dove: «Das neue Werk liegt ___ der Schweiz, nicht ___ Süden»
       con soluzione «im Norden» e' irrisolvibile per costruzione.

    Vale in generazione E in servizio: gli esercizi gia' in deposito quando la
    regola e' cambiata smettono di uscire da soli, senza migrazioni.
    """
    if not (e.get("stimolo") or "").strip():
        return "senza stimolo"
    if not (e.get("soluzione") or "").strip():
        return "senza soluzione"
    if not (e.get("consegna") or "").strip():
        return "senza consegna"
    # Il numero di buchi si controlla PRIMA della traduzione: chi ha due buchi
    # non viene nemmeno tradotto (`traduci()` lo salta), e riportarlo come
    # «senza traduzione» nasconderebbe il difetto vero dietro il suo effetto.
    if e["stimolo"].count("___") != 1:
        return f"{e['stimolo'].count('___')} buchi invece di 1"
    if not (e.get("gloss") or "").strip():
        return "senza glossa"
    if not (e.get("traduzione") or "").strip():
        return "senza traduzione"
    # Una traduzione che contiene la soluzione tedesca non e' una traduzione:
    # e' la risposta scritta in un altro riquadro.
    if e["soluzione"].strip().lower() in e["traduzione"].lower():
        return "la traduzione contiene la soluzione"
    # Bocciato dal controllo di coerenza: traduzione e soluzione dicono cose
    # diverse. Vedi `verifica()`. `None` significa mai controllato, non rotto.
    if e.get("coerente") is False:
        return "incoerente: " + (e.get("incoerenza") or "traduzione e soluzione discordano")
    return ""


LIVELLI = ("A1", "A2", "B1", "B2")


def prepara(quanti: int = QUANTI_PER_VOLTA, *, voci: list[dict] | None = None,
            livello: str | None = None) -> dict:
    """Genera un blocco di esercizi dalla coda. Una chiamata LLM.

    A blocchi e non su richiesta: l'app deve aprirsi in un secondo, e una
    chiamata ogni venti esercizi costa una frazione di quanto costerebbe una
    chiamata a esercizio.

    `voci` permette di passare una fetta di coda gia' scelta — lo usa
    `libreria()` per camminare su tutta la coda invece di ripescare sempre le
    stesse prime N regole. `livello` chiede al modello di mirare a una banda
    CEFR: la stessa regola a A2 e a B2 sono due esercizi diversi, ed e' cosi'
    che una libreria arriva a 500 senza ripetersi.
    """
    voci = voci if voci is not None else coda(quanti)
    if not voci:
        raise RuntimeError(
            "Nessun errore su cui allenarsi. Il quaderno si popola "
            "elaborando le lezioni: deutschops.py lezione --auto"
        )

    fatti = {(e.get("stimolo") or "").strip() for e in _carica()["esercizi"]}

    righe = []
    for i, v in enumerate(voci, 1):
        if v["tipo"] == "tema":
            riga = f"{i}. [B2 TOPIC · {v['regola']}] never covered — {v['spiegazione']}"
        else:
            riga = (
                f"{i}. [{v['categoria']} · {v['regola']}] he said: {v['sbagliato']!r}\n"
                f"   corrected to: {v['corretto']!r}\n"
                f"   why: {v['spiegazione'][:220]}"
            )
        if rif := riferimento(v):
            riga += f"\n   real German sentence for tone/vocabulary only — do NOT reuse it or its structure: {rif!r}"
        righe.append(riga)
    mira = ""
    if livello:
        mira = (f"\n\nTARGET LEVEL for this batch: **{livello}**. Build the "
                f"sentence around the gap at that level — vocabulary and clause "
                f"structure. The rule stays the same; the difficulty of getting "
                f"to it changes. If a rule genuinely cannot be tested at "
                f"{livello}, write it at the nearest level that works and label "
                f"it honestly.")
    user = (
        f"ITEMS ({len(voci)}):\n" + "\n".join(righe) +
        "\n\nWrite one exercise per item, in the same order." + mira
    )

    testo, uso = chiama(SYSTEM, user, llm_config(max_tokens=16000))
    dati = estrai_json(testo)

    quando = datetime.now().isoformat(timespec="seconds")
    aggiunti, scartati = [], []
    for i, e in enumerate(dati.get("esercizi", [])):
        stimolo = (e.get("stimolo") or "").strip()
        # Chiedere una regola nel prompt non e' ottenerla: si ricontrolla qui.
        # Un esercizio indovinabile insegna a indovinare.
        if motivo := utilizzabile({**e, "stimolo": stimolo}):
            scartati.append(motivo)
            continue
        if stimolo in fatti:
            continue
        v = voci[i] if i < len(voci) else {}
        aggiunti.append({
            "id": f"{quando}-{i}",
            "consegna": e["consegna"].strip(),
            "stimolo": stimolo,
            "traduzione": e["traduzione"].strip(),
            "gloss": e["gloss"].strip(),
            "soluzione": e["soluzione"].strip(),
            "alternative": [a.strip() for a in (e.get("alternative") or [])
                            if isinstance(a, str) and a.strip()],
            "regola_testo": (e.get("regola") or "").strip(),
            "struttura": (e.get("struttura") or "").strip(),
            "perche": (e.get("perche") or "").strip(),
            "categoria": e.get("categoria") if e.get("categoria") in quaderno.CATEGORIE
                         else v.get("categoria", "Sonstiges"),
            "livello": e.get("livello") if e.get("livello") in LIVELLI
                       else (livello or "B1"),
            "regola": (e.get("nome_regola") or v.get("regola") or "").strip(),
            "chiave": v.get("chiave") or chiave_regola(e.get("nome_regola")),
            "motivo": v.get("motivo", ""),
            "tipo": e.get("tipo") or "gap",
            "generato": quando,
        })

    deposito = _carica()
    deposito["esercizi"].extend(aggiunti)
    deposito["costo_totale_eur"] = round(
        deposito.get("costo_totale_eur", 0.0) + uso.costo_eur, 4)
    deposito["ultimo_costo_eur"] = uso.costo_eur
    deposito["costo_stimato"] = uso.stimato
    deposito["generato"] = quando

    DEPOSITO.parent.mkdir(parents=True, exist_ok=True)
    DEPOSITO.write_text(json.dumps(deposito, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    return {
        "aggiunti": len(aggiunti),
        "scartati": len(scartati),
        "motivi": Counter(scartati).most_common(),
        "chiesti": len(voci),
        "in_deposito": len(deposito["esercizi"]),
        "costo_eur": uso.costo_eur,
        "costo_nozionale_eur": uso.costo_nozionale_eur,
        "costo_stimato": uso.stimato,
    }


# Le bande su cui si costruisce la libreria, in ordine. Si parte da A2 e non da
# A1: il livello dichiarato di Kevin e' A2->B1, e riempire mezza libreria di
# esercizi sotto il suo livello sarebbe tempo speso a confermare cio' che sa.
# A1 resta disponibile come etichetta — il modello puo' marcare cosi' cio' che
# scrive davvero semplice — ma non e' una banda su cui si genera apposta.
PASSATE = ("A2", "B1", "B2")


def libreria(totale: int = 500, per_blocco: int = 25,
             livelli: tuple[str, ...] = PASSATE,
             al_massimo: float | None = None) -> dict:
    """Costruisce la libreria in piu' chiamate, camminando su tutta la coda.

    PERCHE' NON BASTA CHIAMARE `prepara()` PIU' VOLTE
    `coda()` deduplica per regola: chiamarla di nuovo restituisce le stesse
    prime N regole, e il secondo blocco chiederebbe di nuovo cio' che il primo
    ha gia' fatto. Qui la coda si prende INTERA una volta, si affetta, e ogni
    fetta va a un blocco. Finita la coda si ricomincia da capo alla banda
    successiva: la stessa regola a A2 e a B2 sono due esercizi diversi, ed e'
    cosi' che si arriva a 500 senza ripetersi.

    E' RIPRENDIBILE, PERCHE' VENTI CHIAMATE FALLISCONO
    Ogni blocco scrive il deposito appena arriva. Se la rete cade alla
    diciassettesima, i sedici blocchi prima restano, e rilanciare riparte da
    dove serve invece che da zero. Un errore su un blocco non ferma gli altri:
    viene contato e si prosegue.

    `al_massimo` e' un tetto di spesa in euro, misurata non stimata. Superato,
    si ferma e lo dice.
    """
    tutta = coda(2000)
    if not tutta:
        raise RuntimeError("Coda vuota: il quaderno errori si popola elaborando le lezioni.")

    partenza = len(_carica()["esercizi"])
    speso, blocchi, falliti, motivi = 0.0, 0, 0, []
    # Sull'abbonamento `speso` resta zero per tutti i blocchi: stampare venti
    # righe di «0.0000 EUR» sembrerebbe un contatore rotto invece di un conto
    # giusto. Il nozionale e' quanto lo stesso lotto sarebbe costato a consumo.
    nozionale = 0.0

    for banda in livelli:
        for i in range(0, len(tutta), per_blocco):
            fatti = len(_carica()["esercizi"]) - partenza
            if fatti >= totale:
                break
            if al_massimo is not None and speso >= al_massimo:
                break
            fetta = tutta[i:i + per_blocco]
            try:
                r = prepara(len(fetta), voci=fetta, livello=banda)
            except Exception as e:
                falliti += 1
                motivi.append(f"{type(e).__name__}: {e}")
                continue
            speso += r["costo_eur"]
            nozionale += r.get("costo_nozionale_eur", 0.0)
            blocchi += 1
            conto = (f"{speso:.4f} EUR" if speso or not nozionale
                     else f"abbonamento · {nozionale:.4f} EUR risparmiati")
            print(f"  {banda} · blocco {blocchi:2d} · "
                  f"{r['aggiunti']:2d}/{r['chiesti']:2d} "
                  f"· {len(_carica()['esercizi']) - partenza:3d} totali "
                  f"· {conto}", flush=True)
        else:
            continue
        break

    return {
        "generati": len(_carica()["esercizi"]) - partenza,
        "blocchi": blocchi,
        "falliti": falliti,
        "motivi": motivi[:3],
        "costo_eur": round(speso, 4),
        "costo_nozionale_eur": round(nozionale, 4),
        "in_deposito": len(_carica()["esercizi"]),
        "pronti": len(disponibili()),
    }


SYSTEM_COERENZA = """You check German gap-fill exercises for internal consistency.

Each item has: the German sentence with a gap, the German that fills the gap,
an English gloss of the gap, and an English translation of the whole sentence.

Your ONLY question per item: **do the three English/German pieces describe the
same sentence?** Specifically:
  - does the translation match the sentence WITH that solution in it?
  - does the gloss match the solution?

Example of a FAIL: gap "wollen", gloss "wanted to", translation "He wasn't
allowed to buy the car" — "wasn't allowed" is dürfen, so translation and
solution disagree.

Do NOT judge difficulty, style, usefulness or level. Do not rewrite anything.
Only flag genuine contradictions — a loose but compatible translation is fine.

**Decide before you write.** If you work through an item and conclude it is
actually consistent, LEAVE IT OUT. Do not list it with a note saying it turned
out fine — a flagged item is removed from the learner's library, so listing one
you have just cleared throws away a good exercise.

Reply with valid JSON only, no backticks. List ONLY the failing items:
{"rotti":[{"n":<number>,"perche":"<one short line, English>"}]}
If every item is consistent, return {"rotti":[]}."""

# Un controllore che elenca un problema e poi si smentisce nella stessa riga sta
# dicendo «nessun problema». Misurato: 4 degli 8 scarti del primo giro erano di
# questo tipo, e ognuno costava un esercizio buono.
#
# Le frasi sono poche e inequivocabili di proposito. Provata una lista piu'
# larga (con «is fine» e «matches,» dentro) riabilitava anche casi dove
# l'assoluzione riguardava un pezzo e il rilievo vero un altro: un filtro
# testuale non sa distinguere la conclusione dalla subordinata. Meglio lasciare
# scartato qualche esercizio buono — su 500 non si sente — che riammetterne uno
# storto. La regola sta anche nel prompt, dove il modello puo' deciderlo
# davvero invece che farlo indovinare a un `in`.
_SI_SMENTISCE = ("fine actually", "no contradiction", "gloss matches",
                 "consistent but check", "this is correct")


def verifica(per_blocco: int = 40) -> dict:
    """Controlla che traduzione, glossa e soluzione dicano la stessa cosa.

    PERCHE' UN GIRO IN PIU' SU UNA LIBRERIA GIA' FATTA
    Il prompt chiede la coerenza, ma chiederla non e' ottenerla — e' la stessa
    lezione della glossa e del buco singolo. Qui pero' il difetto e' semantico:
    nessuna regola sintattica vede che «wollen» glossato «wanted to» e tradotto
    «wasn't allowed» sono due verbi diversi. Serve un lettore.

    Costa poco perche' la domanda e' chiusa e l'uscita e' minuscola: si
    elencano solo i rotti, non si riscrive niente. Su una libreria che dura
    mesi e' un'assicurazione a buon mercato — e un esercizio incoerente non e'
    inutile, e' dannoso: insegna la parola sbagliata con sicurezza.
    """
    deposito = _carica()
    # Solo quelli mai controllati e con una traduzione da controllare.
    da_vedere = [e for e in deposito["esercizi"]
                 if e.get("coerente") is None and (e.get("traduzione") or "").strip()]
    if not da_vedere:
        return {"controllati": 0, "rotti": 0, "costo_eur": 0.0}

    rotti, speso = 0, 0.0
    for i in range(0, len(da_vedere), per_blocco):
        fetta = da_vedere[i:i + per_blocco]
        righe = "\n".join(
            f"{n}. {e['stimolo']}\n"
            f"   gap: {e['soluzione']}\n"
            f"   gloss: {e.get('gloss','')}\n"
            f"   translation: {e.get('traduzione','')}"
            for n, e in enumerate(fetta, 1)
        )
        try:
            testo, uso = chiama(SYSTEM_COERENZA, f"ITEMS ({len(fetta)}):\n{righe}",
                                llm_config(max_tokens=2000, effort="low"))
            esito = estrai_json(testo)
        except Exception:
            continue                      # un blocco perso non blocca gli altri
        speso += uso.costo_eur

        cattivi = {}
        for r in esito.get("rotti", []):
            if not str(r.get("n", "")).strip().isdigit():
                continue
            perche = (r.get("perche") or "").strip()
            if any(s in perche.lower() for s in _SI_SMENTISCE):
                continue                  # si e' assolto da solo: non e' uno scarto
            cattivi[int(r["n"])] = perche
        for n, e in enumerate(fetta, 1):
            if n in cattivi:
                e["coerente"] = False
                e["incoerenza"] = cattivi[n]
                rotti += 1
            else:
                e["coerente"] = True
        print(f"  controllati {i + len(fetta):3d}/{len(da_vedere)} "
              f"· {rotti} rotti · {speso:.4f} EUR", flush=True)
        DEPOSITO.write_text(json.dumps(deposito, ensure_ascii=False, indent=2),
                            encoding="utf-8")

    deposito["costo_totale_eur"] = round(
        deposito.get("costo_totale_eur", 0.0) + speso, 4)
    DEPOSITO.write_text(json.dumps(deposito, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    return {"controllati": len(da_vedere), "rotti": rotti,
            "costo_eur": round(speso, 4), "pronti": len(disponibili())}


SYSTEM_TRADUZIONE = """You translate German gap-fill exercise sentences into English.

For each numbered German sentence you receive the intended answer for its gap.
Return a natural English translation of the WHOLE sentence, as if the gap were
already filled with that answer.

- Pure English. Not a single German word in the output.
- Natural, not word-for-word. It should read like something a person would say.
- Keep the register of the original.
- Do not explain, do not comment, do not mark the gap. Just the sentence.

Reply with valid JSON only, no backticks:
{"traduzioni":[{"n":<the number>,"testo":"<the English sentence>"}]}"""


def traduci(quanti: int = 40) -> dict:
    """Aggiunge la traduzione agli esercizi che ne sono privi. Una chiamata LLM.

    PERCHE' UNA FUNZIONE A PARTE INVECE DI RIGENERARE
    Quando la traduzione e' diventata obbligatoria c'erano gia' 31 esercizi
    buoni — con glossa, un buco solo, soluzione corretta. Rigenerarli
    costerebbe piu' che tradurli (una traduzione e' un decimo dei token di un
    esercizio) e butterebbe lavoro valido. Le regole nuove non devono per forza
    distruggere cio' che rispettava gia' quelle vecchie.
    """
    deposito = _carica()
    manca = [e for e in deposito["esercizi"]
             if not (e.get("traduzione") or "").strip()
             and (e.get("gloss") or "").strip()
             and (e.get("stimolo") or "").count("___") == 1][:quanti]
    if not manca:
        return {"tradotti": 0, "costo_eur": 0.0, "costo_stimato": False}

    righe = "\n".join(
        f"{i}. {e['stimolo']}   [gap = {e['soluzione']}]"
        for i, e in enumerate(manca, 1)
    )
    testo, uso = chiama(SYSTEM_TRADUZIONE, f"SENTENCES ({len(manca)}):\n{righe}",
                        llm_config(max_tokens=4000, effort="low"))
    per_numero = {int(t.get("n", 0)): (t.get("testo") or "").strip()
                  for t in estrai_json(testo).get("traduzioni", [])
                  if str(t.get("n", "")).strip().isdigit()}

    fatti = 0
    for i, e in enumerate(manca, 1):
        t = per_numero.get(i, "")
        # Una traduzione che contiene la soluzione tedesca non serve a niente.
        if not t or e["soluzione"].strip().lower() in t.lower():
            continue
        e["traduzione"] = t
        fatti += 1

    deposito["costo_totale_eur"] = round(
        deposito.get("costo_totale_eur", 0.0) + uso.costo_eur, 4)
    DEPOSITO.write_text(json.dumps(deposito, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    return {"tradotti": fatti, "chiesti": len(manca),
            "costo_eur": uso.costo_eur, "costo_stimato": uso.stimato}


# ------------------------------------------------------------------ scala

# NIENTE AGGANCIO AUTOMATICO A grammar_db, ED E' UNA SCELTA MISURATA
# Il gradino 2 doveva portare in piu' la scheda di `grammar_db` (296 regole con
# `full_rule`, `common_mistakes`, `exceptions`). Il collegamento pero' va fatto
# per nome, e i nomi non combaciano: `error_db` li ha in tedesco libero
# («Präposition 'in' + Dativ»), `grammar_db` ha titoli suoi.
#
# Misurato sul deposito da 20: a sovrapposizione di token aggancia 4 regole, di
# cui **3 sbagliate** — «Präposition 'in' + Dativ» finiva su «Präposition mit +
# Dativ», che e' un'altra preposizione, cioe' esattamente il contenuto in esame.
# Stringendo fino a togliere i falsi positivi resta 1 aggancio su 20.
#
# Una funzione che spara il 75% di falsi positivi su materiale di studio non e'
# un aiuto parziale: mostra la regola sbagliata a chi sta studiando proprio
# quella, ed e' il difetto che il CLAUDE.md di progetto descrive sull'audit del
# mazzo — «il rumore fa smettere di leggere». Il gradino 2 usa `regola_testo`,
# scritto per QUELL'esercizio da chi l'ha costruito: e' corretto e mirato.
# La consultazione vera di `grammar_db` e' F3, con un indice, non con un
# confronto di stringhe.

# Cosa dice il gradino 1: la categoria, in una riga. Non la regola — solo il
# lato del sistema da cui guardare l'esercizio.
GLOSSA = {
    "Kasus": "Which case does this take — Nominativ, Akkusativ, Dativ or Genitiv?",
    "Genus": "This is about grammatical gender: der, die or das.",
    "Präposition": "The preposition decides the case here. Which one, and what does it govern?",
    "Verbform": "Look at the verb: tense, conjugation, auxiliary, participle.",
    "Wortstellung": "This is word order — V2, verb-final, or TeKaMoLo.",
    "Wortwahl": "The grammar may be fine: it is the word choice that is off.",
    "Adjektivdeklination": "Adjective endings — they follow the article and the case.",
    "Aussprache": "This is about pronunciation.",
    "Sonstiges": "Read the sentence again before reaching for the rule.",
}


def scala(es: dict) -> list[dict]:
    """I gradini 1-3 della scala di aiuto, che viaggiano con l'esercizio.

    Il gradino 4 NON e' qui, ed e' deliberato. Gli altri tre aiutano a ricavare
    la risposta; il quarto la da'. Se partisse col resto, la soluzione sarebbe
    nella pagina prima ancora della domanda e la scala diventerebbe decorativa.
    Il 4 e' una resa, e si chiede: passa da `/api/risposta` con `aiuto: 4`,
    dove viene registrato come non risolto — vedi `resa()`.
    """
    return [
        {"grado": 1, "nome": "The area",
         "testo": GLOSSA.get(es.get("categoria"), GLOSSA["Sonstiges"])},
        {"grado": 2, "nome": "The rule",
         "testo": es.get("regola_testo") or es.get("regola") or ""},
        {"grado": 3, "nome": "The structure",
         "testo": es.get("struttura") or ""},
    ]


# ------------------------------------------------------------------ valutazione

_APICI = str.maketrans({"‘": "'", "’": "'", "“": '"',
                        "”": '"', "–": "-", "—": "-"})


def _stretta(t: str) -> str:
    """Confronto stretto: solo cio' che non e' mai una differenza di tedesco.

    Spazi, apici tipografici, punteggiatura finale, e i puntini con cui il
    modello segna un secondo buco («ist ... angekommen»): nessuna risposta
    tedesca contiene «...», e nessuno la digita. Senza toglierli, chi scrive
    «ist angekommen» — cioe' giusto — finirebbe dal giudice a pagamento.

    Maiuscole e umlaut NO: in tedesco sono ortografia, e passarci sopra in
    silenzio insegnerebbe a ignorarli.
    """
    t = unicodedata.normalize("NFC", (t or "").translate(_APICI))
    t = t.replace("…", " ").replace("...", " ").replace("___", " ")
    return " ".join(t.split()).strip(" .!?").strip()


def _larga(t: str) -> str:
    """Confronto largo: in piu' maiuscole e traslitterazione ae/oe/ue/ss.

    Serve a NON dire «sbagliato» a chi ha capito la regola e ha scritto
    «aus der schweiz» dalla tastiera senza umlaut. La risposta passa, con una
    nota — e la nota e' il punto: si vede l'ortografia senza perdere il segno.
    """
    t = _stretta(t).casefold()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        t = t.replace(a, b)
    return t


SYSTEM_GIUDICE = """You are marking one short German answer. Be strict and precise.

You get the task, the expected answer, and what the student wrote. Decide whether
his answer is acceptable German for that task.

- Accept a different but fully correct formulation. Reject anything with a
  grammatical error, even a small one.
- If it is wrong, say exactly WHAT is wrong — the case, the ending, the position,
  the word — not that it "sounds unnatural".
- Write in English. Two short lines maximum. No praise, no encouragement, no
  exclamation marks: he is here to find the holes, not to feel good.

Reply with valid JSON only, no backticks:
{"corretta": true|false,
 "categoria": "<Genus|Wortstellung|Präposition|Kasus|Verbform|Wortwahl|Adjektivdeklination|Sonstiges>",
 "cosa": "<what is wrong, or what he got right — one short line>",
 "perche": "<the rule that decides it — one short line>",
 "forma_corretta": "<the correct German; if his answer was already correct, repeat his>"}"""


def resa(es: dict) -> dict:
    """Gradino 4: la soluzione, e l'esercizio conta come non risolto.

    Non e' un aiuto piu' grande degli altri, e' un'altra cosa. Ha la stessa
    forma di un esito valutato perche' il seguito e' identico: la bacchettata
    con lo storico, e il record nel quaderno.
    """
    return {
        "corretta": False, "esatta": False, "giudicata_da": "resa",
        "categoria": es.get("categoria", "Sonstiges"),
        "cosa": "You asked for the answer.",
        "perche": es.get("perche") or es.get("regola_testo") or "",
        "forma_corretta": es.get("soluzione") or "",
        "costo_eur": 0.0, "costo_stimato": False,
    }


def valuta(risposta: str, es: dict) -> dict:
    """Ibrida: prima le regole (gratis), il modello solo se non decidono.

    Su una sessione da dieci, gli esercizi azzeccati non costano niente. Paga
    solo cio' che e' davvero dubbio — ed e' li' che serve un giudizio.
    """
    r = (risposta or "").strip()
    attese = [es.get("soluzione") or ""] + list(es.get("alternative") or [])

    if not r:
        return {
            "corretta": False, "esatta": False, "giudicata_da": "regole",
            "categoria": es.get("categoria", "Sonstiges"),
            "cosa": "Nothing written.",
            "perche": es.get("perche") or es.get("regola_testo") or "",
            "forma_corretta": es.get("soluzione") or "",
            "costo_eur": 0.0, "costo_stimato": False,
        }

    for a in attese:
        if _stretta(r) == _stretta(a):
            return {
                "corretta": True, "esatta": True, "giudicata_da": "regole",
                "categoria": es.get("categoria", "Sonstiges"),
                "cosa": "Exact.",
                "perche": es.get("perche") or "",
                "forma_corretta": a,
                "costo_eur": 0.0, "costo_stimato": False,
            }

    for a in attese:
        if _larga(r) == _larga(a):
            return {
                "corretta": True, "esatta": False, "giudicata_da": "regole",
                "categoria": es.get("categoria", "Sonstiges"),
                "cosa": "Right, but check the spelling.",
                "perche": f"Expected “{a}”. Capitalisation and umlauts are part of "
                          f"the word in German — the exam marks them.",
                "forma_corretta": a,
                "costo_eur": 0.0, "costo_stimato": False,
            }

    user = (
        f"TASK: {es.get('consegna','')}\n"
        f"PROMPT: {es.get('stimolo','')}\n"
        f"EXPECTED: {es.get('soluzione','')}\n"
        + (f"ALSO ACCEPTABLE: {'; '.join(es.get('alternative') or [])}\n"
           if es.get("alternative") else "")
        + f"RULE: {es.get('regola_testo','')}\n\n"
        f"STUDENT WROTE: {r}"
    )
    # `effort` basso: il giudizio e' un compito piccolo e chiuso — due stringhe
    # tedesche da confrontare con una regola nota. Le regole hanno gia' scartato
    # i casi facili; qui serve precisione, non elaborazione.
    testo, uso = chiama(SYSTEM_GIUDICE, user,
                        llm_config(max_tokens=1200, effort="low"))
    g = estrai_json(testo)
    return {
        "corretta": bool(g.get("corretta")),
        "esatta": False,
        "giudicata_da": "modello",
        "categoria": g.get("categoria") if g.get("categoria") in quaderno.CATEGORIE
                     else es.get("categoria", "Sonstiges"),
        "cosa": (g.get("cosa") or "").strip(),
        "perche": (g.get("perche") or "").strip(),
        "forma_corretta": (g.get("forma_corretta") or es.get("soluzione") or "").strip(),
        "costo_eur": uso.costo_eur,
        "costo_stimato": uso.stimato,
    }


# ------------------------------------------------------------------ l'esito

def registra_esito(es: dict, risposta: str, aiuto: int, esito: dict) -> dict:
    """Chiude il giro: valuta, bacchetta con lo storico, e scrive nel quaderno.

    Un esercizio risolto al gradino 4 conta come NON risolto anche se la
    risposta e' identica alla soluzione: al gradino 4 la soluzione era sullo
    schermo. Registrarlo come sapere sarebbe l'unico modo di rendere inutile
    tutta la scala.
    """
    from . import sessione

    risolto = bool(esito.get("corretta")) and aiuto < 4

    # Si posa SUBITO, non a fine sessione: una sessione che non arriva in fondo
    # e' la norma, non l'eccezione. Vedi `sessione.annota_risposta`.
    sessione.annota_risposta({
        "chiave": es.get("chiave") or chiave_regola(es.get("regola")),
        "regola": es.get("regola") or "",
        "categoria": esito.get("categoria") or es.get("categoria") or "",
        "stimolo": es.get("stimolo") or "",
        "corretta": risolto,
        "aiuto": aiuto,
        "costo_eur": esito.get("costo_eur", 0.0),
    })

    finto = {"rule": es.get("regola"), "category": esito.get("categoria")
             or es.get("categoria")}
    passato = storico(finto)

    if not risolto:
        with _LUCCHETTO:
            quaderno.annota({
                "category": esito.get("categoria") or es.get("categoria"),
                "kevin_said": (risposta or "").strip() or "(no answer)",
                "correction": esito.get("forma_corretta") or es.get("soluzione", ""),
                "rule": es.get("regola") or "",
                "explanation_en": " ".join(x for x in (esito.get("cosa"),
                                                       esito.get("perche")) if x),
                "example_correct": es.get("soluzione") or "",
                "aiuto": aiuto,
                "esercizio": es.get("stimolo") or "",
            })
        # Lo storico appena scritto e' quello che l'utente deve vedere: se ha
        # gia' sbagliato cinque volte, la sesta deve dire sei.
        passato = storico(finto)

    return {
        **esito,
        "risolto": risolto,
        "aiuto": aiuto,
        "storico": passato,
    }


# ------------------------------------------------------------------ la sessione

def disponibili() -> list[dict]:
    """Gli esercizi in deposito ancora da fare.

    Fuori: quelli gia' svolti, quelli su una regola nel frattempo padroneggiata,
    quelli segnalati come rotti, e quelli che `utilizzabile()` boccia. Il
    deposito non si svuota — resta come storico di cosa non funzionava — ma
    quello che e' chiuso non torna davanti.

    L'ultimo filtro e' quello che fa lavorare le regole nuove sul vecchio: i
    venti esercizi generati prima che la glossa fosse obbligatoria smettono di
    uscire da soli, senza migrazioni e senza cancellare niente.
    """
    from . import sessione

    passati = esiti()
    fuori_gioco = padroneggiate(passati)
    svolti = {r["stimolo"] for righe in passati.values() for r in righe if r["stimolo"]}
    rotti = sessione.stimoli_segnalati()

    return [e for e in _carica()["esercizi"]
            if not utilizzabile(e)
            and (e.get("stimolo") or "").strip() not in svolti
            and " ".join((e.get("stimolo") or "").split()) not in rotti
            and (e.get("chiave") or "") not in fuori_gioco]


# Cosa NON esce dal server insieme alla domanda. `perche` e' il meno ovvio e il
# piu' pericoloso: e' la spiegazione da mostrare DOPO, e contiene la risposta
# per costruzione — «'Ankommen' expresses a change of location, so it takes
# 'sein' + 'angekommen'». Serviva insieme allo stimolo, la risposta era nella
# pagina prima della domanda. `struttura` invece esce, ma solo dentro `scala`
# al gradino 3, dove aprirlo viene registrato.
RISERVATI = ("soluzione", "alternative", "perche", "struttura")


def sessione_da(n: int, livello: str | None = None) -> dict:
    """N esercizi pronti da servire, con i gradini 1-3 della scala di aiuto.

    `livello` filtra per banda CEFR. Non e' una preferenza estetica: la stessa
    regola a A2 e a B2 sono due esercizi diversi, e poter scegliere serve sia a
    consolidare le fondamenta (dove sta il 44% degli errori) sia a spingere
    verso l'esame senza mescolare le due cose nella stessa sessione.
    """
    pronti = disponibili()
    per_livello = _conta_livelli(pronti)
    if livello:
        scelti = [e for e in pronti if e.get("livello") == livello]
    else:
        scelti = pronti
    return {
        "esercizi": [
            {**{k: v for k, v in e.items() if k not in RISERVATI},
             "scala": scala(e)}
            for e in scelti[:n]
        ],
        "in_deposito": len(pronti),
        "per_livello": per_livello,
        "livello": livello,
        "scorta_bassa": len(scelti) < SCORTA_MINIMA,
    }


def _conta_livelli(pronti: list[dict]) -> dict[str, int]:
    fuori: dict[str, int] = {}
    for e in pronti:
        l = e.get("livello") or "?"
        fuori[l] = fuori.get(l, 0) + 1
    return {l: fuori[l] for l in LIVELLI if l in fuori} | (
        {"?": fuori["?"]} if "?" in fuori else {})


def per_id(id_es: str) -> dict | None:
    for e in _carica()["esercizi"]:
        if e.get("id") == id_es:
            return e
    return None
