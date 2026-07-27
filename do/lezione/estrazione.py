"""Transcript -> JSON strutturato. L'unico punto dove un LLM decide.

LO SCHEMA E' QUELLO VERO, NON QUELLO DOCUMENTATO
`CLAUDE.md` descrive `summary: {en, it}` e `vocabulary: [{word, gender,
plural, category, cefr}]`. Lo schema che extractor.py produce davvero e'
piatto: `summary_en`, `summary_it`, e vocabulary con `german`, `article`,
`level`. Chi scrive codice leggendo la documentazione ottiene campi vuoti in
silenzio — `notebooklm_export.py:346` aveva gia' un fallback difensivo per
entrambe le forme, prova che qualcuno ci era gia' inciampato.

Qui lo schema e' dichiarato in CAMPI, versionato, e `valida()` fallisce
rumorosamente se manca qualcosa. Nessun campo mancante che si propaga fino ad
Anki come stringa vuota.

IL RAMO MORTO CHE NON PORTO
extractor.py:224-230 importa `frame_extractor`, un modulo che non e' mai
esistito in git. Non esplode solo perche' nessuno passa `visual_context`.
Muore qui.

IL COSTO NON SI BUTTA PIU'
extract() calcolava il costo, lo stampava e ritornava solo `data`; main.py
scriveva `claude_cost = 0.10` al suo posto. Qui `estrai()` ritorna
`(dati, costo_eur)` e il registry scrive il numero misurato.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..base.config import llm_config
from ..base.llm import chiama, estrai_json
from ..base.paths import DATA

# Versione dello schema. Sale quando cambiano i CAMPI, non quando cambia il
# prompt. Finisce nel JSON: serve a capire con che forma e' stato estratto un
# file quando fra sei mesi lo schema sara' cambiato.
SCHEMA_VERSIONE = 2

# I campi che DEVONO esserci. Il tipo e' quello atteso al primo livello.
CAMPI: dict[str, type] = {
    "topic": str,
    "summary_en": str,
    "summary_it": str,
    "vocabulary": list,
    "grammar_points": list,
    "phrases": list,
    "comprehension_questions": list,
}

# Campi di un vocabolo. `german` e `level` sono gli unici obbligatori:
# l'articolo e' vuoto per i verbi, il plurale per i Singularetantum.
CAMPI_VOCABOLO = ("german", "article", "plural", "category",
                  "italian", "english", "example_de", "example_it", "level")


SISTEMA = """You are a German language tutor. Student: Kevin (Italian, A2 -> B2 target), lessons in English with native speaker Stefanie. Transcript: English + German examples + occasional Italian.

Return ONLY valid JSON — no backticks, no extra text.

{"lesson_number":"<int or ''>","topic":"<5 words>","summary_en":"<=120 words>","summary_it":"<Italian>","vocabulary":[{"german":"<base word>","article":"<der|die|das|''>","plural":"<or ''>","category":"<see below>","italian":"<str>","english":"<str>","example_de":"<str>","example_it":"<str>","level":"<A1|A2|B1|B2>"}],"grammar_points":[{"rule":"<str>","explanation_en":"<str>","examples":["<str>"],"full_rule":"","common_mistakes":"","exceptions":"","source_verified":false}],"phrases":[{"german":"<str>","english":"<str>","context":"<str>"}],"homework":"<str or ''>","comprehension_questions":[{"question_de":"<str>","answer_de":"<str>"}],"doc_sections_covered":["<str>"]}

Rules:
- vocabulary.german: base word ONLY, NEVER include article (ok "Sorge", wrong "die Sorge")
- category: verb_regular|verb_irregular|verb_separable|verb_modal|noun|adjective|adverb|phrase|expression
- article: der/die/das for nouns, "" otherwise; plural for nouns when deducible, "" otherwise
- plural: leave "" for Singularetantum (Milch, Zucker, Mathematik, month names, cardinal points). Do NOT invent a plural that does not exist.
- example_de: a full sentence USING the word, ideally taken from the transcript. This is what the Anki cloze card is built from — without it the word gets no production card.
- grammar_points: max 5, explicitly covered rules only
- vocabulary: ALL new A2 -> B2 words, no cap
- comprehension_questions: exactly 3
- phrases.english: English only, no Italian

Stefanie's corrections (apply strictly):
- sollen Praesens = "shall I?" (asking opinion), NEVER "should" (= Konjunktiv II sollte)
- verreisen = go on a trip (no destination); reisen nach [place] = travel to a specific place
- German AI = "die KI" not "AI"
- "keine Ahnung" -> phrases only: {"german":"Ich habe keine Ahnung","english":"I have no idea","context":"fixed phrase"}
- die Sorge = "concern" not "worry"
- egal -> phrases only: {"german":"Es ist mir egal","english":"It does not matter to me"}; NOT in grammar_points
- mindestens example: "Du brauchst mindestens 14 GB" """


SISTEMA_GRAMMATICA = (
    "You are a German grammar expert with web search access. All output in English.\n"
    "Search: dartmouth.edu/~deutsch, germanveryeasy.com, duden.de\n"
    "For each rule provide: complete forms/conjugation tables, mistakes typical of "
    "Italian speakers, 4 example sentences, exceptions.\n"
    'Return ONLY valid JSON, no backticks: {"grammar_points":[{"rule":"<exact input name>",'
    '"explanation_en":"<str>","full_rule":"<complete with tables>",'
    '"common_mistakes":"<Italian-speaker errors>","examples":["<str>","<str>","<str>","<str>"],'
    '"exceptions":"<str>","source_verified":true}]}'
)


class SchemaNonValido(ValueError):
    """L'estrazione non ha la forma attesa. Rumorosa di proposito."""


def valida(dati: dict) -> dict:
    """Verifica la forma. Solleva invece di riparare in silenzio.

    Un vocabolo senza `german` non e' recuperabile e diventerebbe una carta
    Anki con il fronte vuoto. Meglio fermarsi qui, dove si vede il perche'.
    """
    mancanti = [c for c in CAMPI if c not in dati]
    if mancanti:
        raise SchemaNonValido(
            f"Campi assenti nell'estrazione: {', '.join(mancanti)}. "
            f"Presenti: {', '.join(sorted(dati))}"
        )

    sbagliati = [f"{c} e' {type(dati[c]).__name__}, atteso {t.__name__}"
                 for c, t in CAMPI.items() if not isinstance(dati[c], t)]
    if sbagliati:
        raise SchemaNonValido("Tipi errati: " + "; ".join(sbagliati))

    senza_parola = [i for i, v in enumerate(dati["vocabulary"])
                    if not isinstance(v, dict) or not (v.get("german") or "").strip()]
    if senza_parola:
        raise SchemaNonValido(
            f"{len(senza_parola)} vocaboli senza campo `german` "
            f"(indici {senza_parola[:5]}). Diventerebbero carte con fronte vuoto."
        )

    # Normalizzazione non distruttiva: i campi opzionali mancanti diventano
    # stringa vuota, cosi' i consumatori non devono fare .get() ovunque.
    for v in dati["vocabulary"]:
        for c in CAMPI_VOCABOLO:
            v.setdefault(c, "")
    dati.setdefault("homework", "")
    dati.setdefault("doc_sections_covered", [])
    return dati


def _regole_gia_studiate() -> dict[str, dict]:
    """Regole grammaticali gia' arricchite in una lezione passata.

    Evita di ricercare due volte la stessa regola: la ricerca web e' di gran
    lunga la chiamata piu' cara della pipeline.
    """
    viste: dict[str, dict] = {}
    for f in sorted(DATA.glob("lezione_*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for gp in d.get("grammar_points", []):
            k = (gp.get("rule") or "").lower().strip()
            if k and gp.get("full_rule"):
                viste[k] = gp
    return viste


# Parole che compaiono in meta' dei nomi di regola e non distinguono niente.
_RUMORE = {
    "the", "a", "an", "of", "in", "with", "and", "or", "vs", "versus", "for",
    "to", "verb", "verbs", "rule", "form", "forms", "use", "using", "when",
    "clause", "sentence", "german", "expressed", "expression", "expressions",
}

# Sopra questa sovrapposizione di parole due nomi descrivono la stessa regola.
# 0,5 e' tarato sui casi veri visti nel corpus: "Superlative: am + -sten vs.
# article + -ste + noun" contro "Superlative: am -sten vs der/die/das -ste +
# noun" -> 0,57. "warten auf + accusative" contro "warten auf + dass-clause"
# -> 0,67. Sotto 0,4 si ricercherebbe due volte la stessa cosa; sopra 0,7 si
# scarterebbero regole davvero nuove.
SOGLIA_SIMILE = 0.5

# Freno di spesa. La ricerca su 5 regole e' costata 1,01 EUR misurati contro
# gli 0,07 di una lezione intera: senza tetto, un'estrazione che riformula i
# nomi delle regole spende quindici volte il dovuto senza che nessuno se ne
# accorga. Le regole in eccesso NON spariscono in silenzio: si stampano.
MAX_RICERCHE = 3


def _impronta(nome: str) -> frozenset[str]:
    """Le parole significative di un nome di regola, per confronto."""
    import re

    parole = re.findall(r"[a-zäöüß\-]+", (nome or "").lower())
    return frozenset(p for p in parole if len(p) > 1 and p not in _RUMORE)


def _somiglianza(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def da_ricercare(punti: list[dict]) -> tuple[list[dict], list[str]]:
    """Quali regole vanno cercate sul web. Ritorna (da_cercare, scartate).

    IL CONFRONTO NON PUO' ESSERE SUL NOME ESATTO
    La v1 usava `rule.lower()` come chiave. Funzionava per caso: finche' lo
    stesso modello riproduceva la stessa formulazione. Con Sonnet 5 i nomi
    cambiano a ogni estrazione — «Superlative: am + -sten vs. article + -ste +
    noun» diventa «Superlative: am -sten vs der/die/das -ste + noun» — e tutte
    e cinque le regole di una lezione risultano nuove. Misurato: 1,01 EUR di
    ricerca web su una lezione che ne costa 0,07 in tutto.
    """
    viste = _regole_gia_studiate()
    impronte = [(_impronta(k), gp) for k, gp in viste.items()]

    fuori: list[dict] = []
    for gp in punti:
        nome = (gp.get("rule") or "").strip()
        if not nome:
            continue
        mia = _impronta(nome)

        simile = max(
            ((_somiglianza(mia, altra), g) for altra, g in impronte),
            key=lambda x: x[0], default=(0.0, None),
        )
        punteggio, gemella = simile
        if punteggio >= SOGLIA_SIMILE and gemella and gemella.get("common_mistakes"):
            print(f"   gia' approfondita ({punteggio:.0%}): {nome}")
            continue
        fuori.append(gp)

    scartate = [(g.get("rule") or "") for g in fuori[MAX_RICERCHE:]]
    return fuori[:MAX_RICERCHE], scartate


def arricchisci_grammatica(punti: list[dict]) -> tuple[list[dict], float]:
    """Ricerca web sulle regole nuove. Degrada alla spiegazione base."""
    if not punti:
        return punti, 0.0
    try:
        testo, uso = chiama(
            SISTEMA_GRAMMATICA,
            "Research these grammar rules:\n" + json.dumps(punti, ensure_ascii=False, indent=2),
            llm_config(max_tokens=16000),
            ricerca_web=True,
        )
        arricchiti = estrai_json(testo).get("grammar_points", [])
    except Exception as e:                                  # noqa: BLE001
        # La ricerca e' un di piu': la lezione non deve fallire per questo.
        print(f"   Ricerca web non riuscita ({str(e)[:80]}) — tengo la spiegazione base.")
        return punti, 0.0

    if not arricchiti:
        print("   Ricerca web senza risultati utili — tengo la spiegazione base.")
        return punti, uso.costo_eur
    print(f"   {len(arricchiti)} regole arricchite | {uso.costo_eur:.4f} EUR")
    return arricchiti, uso.costo_eur


def estrai(transcript: str | Path, nome: str, *, doc_nuovo: str = "") -> tuple[dict, float]:
    """Estrae la struttura didattica. Ritorna (dati, costo_eur_totale).

    Idempotente: se il JSON esiste gia' lo rilegge invece di rispendere.
    Per forzare la rielaborazione, cancella il file o usa `rielabora()`.
    """
    tp = Path(transcript)
    if not tp.exists():
        raise FileNotFoundError(f"Transcript non trovato: {tp}")

    uscita = DATA / f"{nome}.json"
    if uscita.exists():
        print(f"   JSON gia' presente: {uscita.name} — non riestraggo.")
        return valida(json.loads(uscita.read_text(encoding="utf-8"))), 0.0

    return rielabora(tp, nome, doc_nuovo=doc_nuovo, scrivi_in=uscita)


def rielabora(transcript: str | Path, nome: str, *, doc_nuovo: str = "",
              scrivi_in: Path | None = None) -> tuple[dict, float]:
    """L'estrazione vera, senza il controllo di idempotenza.

    Separata da `estrai()` perche' serve al confronto di S1: rielaborare una
    lezione gia' fatta scrivendo altrove, per confrontare i due output.
    """
    tp = Path(transcript)
    testo_transcript = tp.read_text(encoding="utf-8")
    print(f"   Transcript: {tp.name} ({len(testo_transcript)} caratteri)")

    utente = f"=== TRANSCRIPT ===\n{testo_transcript}\n\n"
    if doc_nuovo.strip():
        pezzo = doc_nuovo[-8000:]
        utente += f"=== DOC NEW CONTENT ===\n{pezzo}\n\n"
        print(f"   Contesto dal Doc: {len(pezzo)} caratteri")

    testo, uso = chiama(SISTEMA, utente, llm_config(max_tokens=16000))
    dati = valida(estrai_json(testo))
    costo = uso.costo_eur
    print(f"   {len(dati['vocabulary'])} parole, {len(dati['grammar_points'])} regole "
          f"| {uso.input_tokens}->{uso.output_tokens} token | {costo:.4f} EUR")

    punti = dati["grammar_points"]
    if punti and uso.model.startswith("claude"):
        fuori, rimandate = da_ricercare(punti)
        if rimandate:
            # Niente tetti silenziosi: se il freno di spesa taglia qualcosa,
            # si vede. Rientreranno alla prossima lezione che le tocca.
            print(f"   Tetto di {MAX_RICERCHE} ricerche: rimandate "
                  f"{len(rimandate)} regole -> {'; '.join(rimandate)}")
        if fuori:
            print(f"   Ricerca web su {len(fuori)}/{len(punti)} regole nuove...")
            arricchiti, c2 = arricchisci_grammatica(fuori)
            mappa = {(g.get("rule") or "").lower(): g for g in arricchiti}
            dati["grammar_points"] = [mappa.get((g.get("rule") or "").lower(), g)
                                      for g in punti]
            costo += c2
        else:
            print("   Regole gia' tutte approfondite — nessuna ricerca.")

    dati["_schema"] = SCHEMA_VERSIONE
    dati["_costo_estrazione_eur"] = round(costo, 6)
    dati["_modello"] = uso.model

    destinazione = scrivi_in or (DATA / f"{nome}.json")
    destinazione.parent.mkdir(parents=True, exist_ok=True)
    destinazione.write_text(json.dumps(dati, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"   Scritto: {destinazione.name} | totale {costo:.4f} EUR")
    return dati, costo
