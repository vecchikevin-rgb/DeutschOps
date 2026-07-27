"""Sostantivi tedeschi senza plurale (Singularetantum).

PERCHE' ESISTE
L'audit del mazzo segnalava 37 "sostantivi senza plurale" da chiedere a
Stefanie. Guardando la lista: Milch, Mehl, Zucker, Pfeffer, Senf, Mathematik,
Physik, Philosophie, November, Süden, Ruhe, Zukunft... Non sono carte
incomplete: sono sostantivi che il plurale NON CE L'HANNO. Chiedere a
un'insegnante il plurale di "Milch" e' una domanda senza risposta.

Terzo falso positivo dello stesso audit, dopo quello sui tag e quello sui
generi da suffisso. Il tema e' sempre lo stesso: una regola applicata senza
le sue eccezioni produce rumore, e il rumore fa smettere di leggere.

COME E' FATTA LA LISTA
Due parti. Le CLASSI sono chiuse e sicure (mesi, giorni, punti cardinali):
si riconoscono per appartenenza, non serve verificarle una per una. Le altre
sono elencate: sono i Singularetantum effettivamente presenti nel mazzo di
Kevin, non un tentativo di coprire il tedesco.

Verifica: `Restmüll` controllato su de.wiktionary.org il 2026-07-27 — maschile,
"kein Plural", categorizzato Singularetantum. Il mazzo aveva "die Restmüll":
genere sbagliato E plurale preteso a torto, sulla stessa carta.

QUANDO UNA PAROLA NON E' QUI
Non si assume nulla: resta segnalata. Meglio una domanda in piu' a Stefanie
che un plurale inventato che finisce in Anki.
"""

from __future__ import annotations

MESI = {
    "januar", "februar", "märz", "april", "mai", "juni", "juli",
    "august", "september", "oktober", "november", "dezember",
}

GIORNI = {
    "montag", "dienstag", "mittwoch", "donnerstag",
    "freitag", "samstag", "sonnabend", "sonntag",
}

PUNTI_CARDINALI = {"norden", "süden", "osten", "westen"}

# Materie di studio e discipline: in tedesco non pluralizzano.
DISCIPLINE = {
    "mathematik", "physik", "chemie", "biologie", "philosophie", "medizin",
    "informatik", "wirtschaft", "politik", "musik", "geschichte", "kunst",
}

# Stoffnamen — sostanze e materiali.
MATERIE = {
    "milch", "mehl", "zucker", "pfeffer", "senf", "salz", "butter", "öl",
    "reis", "fleisch", "rindfleisch", "schweinefleisch", "hackfleisch",
    "wolle", "seide", "baumwolle", "viskose", "polyester", "leder",
    "mayonnaise", "tiefkühlkost", "waschpulver", "waschmittel",
    "müll", "restmüll", "biomüll", "papier", "wasser", "kaffee", "tee",
    "obst", "gemüse", "gepäck", "geld",
}

# Astratti e collettivi che nel tedesco d'uso non pluralizzano.
ASTRATTI = {
    "ruhe", "zukunft", "vergangenheit", "gegenwart", "lärm", "hunger",
    "durst", "glück", "pech", "wetter", "verkehr", "sport", "urlaub",
    "mittelstand", "zuhause", "wäsche", "hilfe", "arbeit", "freizeit",
    "gesundheit", "hitze", "kälte", "regen", "schnee", "nebel",
}

# Gia' plurali (Pluraletantum): pretenderne un altro non ha senso.
PLURALIA = {
    "teigwaren", "lebensmittel", "eltern", "leute", "ferien", "kosten",
    "möbel", "geschwister", "spaghetti", "nudeln",
}

_TUTTI = MESI | GIORNI | PUNTI_CARDINALI | DISCIPLINE | MATERIE | ASTRATTI | PLURALIA


def senza_plurale(parola: str) -> bool:
    """True se il sostantivo non ha (o non richiede) una forma plurale.

    Conservativo: una parola sconosciuta ritorna False e resta segnalata.
    """
    p = (parola or "").strip().lower()
    if not p:
        return False
    if p in _TUTTI:
        return True
    # Composti: "Vollkornbrot" no (Brote esiste), ma "Bio-Restmüll" si'.
    # Si guarda solo la testa del composto, cioe' l'ultimo elemento.
    for base in _TUTTI:
        if len(base) >= 4 and p.endswith(base):
            return True
    return False


def motivo(parola: str) -> str | None:
    """Perche' questa parola non ha plurale — per spiegarlo, non solo saltarla."""
    p = (parola or "").strip().lower()
    for insieme, etichetta in (
        (MESI, "nome di mese"),
        (GIORNI, "giorno della settimana"),
        (PUNTI_CARDINALI, "punto cardinale"),
        (DISCIPLINE, "disciplina di studio"),
        (MATERIE, "Stoffname (sostanza/materiale)"),
        (ASTRATTI, "astratto o collettivo"),
        (PLURALIA, "Pluraletantum (e' gia' plurale)"),
    ):
        if p in insieme or any(len(b) >= 4 and p.endswith(b) for b in insieme):
            return etichetta
    return None
