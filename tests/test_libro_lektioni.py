import json
from pathlib import Path

import pytest

from do.sapere import libro


@pytest.fixture
def pagine_finte(monkeypatch, tmp_path):
    """Due pagine finte, Lektion 1 e Lektion 2, per non dipendere dal
    corpus vero (364 pagine, lento da caricare in un test)."""
    dati = {
        "kursbuch:10": {
            "fonte": "kursbuch", "indice": 10, "tipo": "vocabolario",
            "lezione": "1", "livello": "A1",
            "testo": "1 Alles auf einen Blick\nWortschatz...",
            "frasi": ["Ich komme aus der Schweiz."],
            "esercizi": [
                {"consegna": "Fill the gap", "stimolo": "Ich ___ aus der Schweiz.",
                 "soluzione": "komme"},
                {"consegna": "Fill the gap", "stimolo": "Du ___ Deutsch.",
                 "soluzione": ""},  # non risolto
            ],
        },
        "kursbuch:25": {
            "fonte": "kursbuch", "indice": 25, "tipo": "esercizio",
            "lezione": "2", "livello": "A1",
            "testo": "2 Alltag\nÜbungen...",
            "frasi": [], "esercizi": [
                {"consegna": "Fill the gap", "stimolo": "Er ___ jeden Tag.",
                 "soluzione": "arbeitet"},
            ],
        },
    }
    p = tmp_path / "libro_pagine.json"
    p.write_text(json.dumps(dati), encoding="utf-8")
    monkeypatch.setattr(libro, "LIBRO_PAGINE", p)
    return dati


def test_lektioni_aggrega_per_numero(pagine_finte):
    out = libro.lektioni()
    numeri = [l["numero"] for l in out]
    assert numeri == [1, 2]  # ordinate


def test_lektioni_conta_esercizi_risolti(pagine_finte):
    out = libro.lektioni()
    l1 = next(l for l in out if l["numero"] == 1)
    assert l1["esercizi_totali"] == 2
    assert l1["esercizi_risolti"] == 1


def test_lektioni_titolo_dalla_prima_riga(pagine_finte):
    out = libro.lektioni()
    l1 = next(l for l in out if l["numero"] == 1)
    assert l1["titolo"] == "Alles auf einen Blick"


def test_lektion_dettaglio_pagine_in_ordine(pagine_finte):
    d = libro.lektion(1)
    assert d is not None
    assert d["numero"] == 1
    assert len(d["pagine"]) == 1
    assert d["pagine"][0]["chiave"] == "kursbuch:10"


def test_lektion_inesistente_torna_none(pagine_finte):
    assert libro.lektion(99) is None
