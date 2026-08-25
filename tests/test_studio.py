"""Test sul livello didattico.

Come per test_base, coprono le regole la cui violazione fa danno — qui il
danno e' una carta sbagliata che entra in Anki e si consolida in memoria.
"""

from __future__ import annotations

import pytest

from do.studio import carte, frasi


# ------------------------------------------------------------------ carte
def _v(**kw):
    base = {"german": "Rechnung", "article": "die", "plural": "Rechnungen",
            "category": "noun", "italian": "fattura", "english": "invoice",
            "example_de": "Ich habe die Rechnung bezahlt.", "level": "B1"}
    return base | kw


def test_tre_direzioni_da_un_vocabolo():
    """Il fix centrale: la v1 faceva una carta sola, DE->IT."""
    c = carte.costruisci(_v(), "2026-07-23")
    direzioni = {t.split("::")[1] for n in c.note for t in n["tags"]
                 if t.startswith("direzione::")}
    assert direzioni == {"riconoscimento", "produzione", "cloze"}


def test_produzione_non_regala_il_genere():
    """Il fronte mostra 'f.', non 'die': dare l'articolo nella domanda
    regalerebbe la parte che Kevin sbaglia (27 errori di Genus)."""
    fronte = carte._fronte_produzione(_v())
    assert "f." in fronte
    assert "die" not in fronte.lower().split(">")[-1]


def test_niente_cloze_se_la_parola_non_e_nell_esempio():
    """Non si inventa una frase: si rinuncia alla carta."""
    assert carte._cloze(_v(example_de="Das kostet zu viel.")) is None
    c = carte.costruisci(_v(example_de="Das kostet zu viel."), "2026-07-23")
    assert len(c.note) == 2


def test_niente_produzione_senza_significato():
    c = carte.costruisci(_v(italian="", english=""), "2026-07-23")
    direzioni = {t.split("::")[1] for n in c.note for t in n["tags"]
                 if t.startswith("direzione::")}
    assert "produzione" not in direzioni
    assert any("produzione" in s for s in c.saltate)


@pytest.mark.parametrize("v,atteso", [
    (_v(), None),
    (_v(article=""), "sostantivo senza articolo"),
    (_v(plural=""), "sostantivo senza plurale"),
    (_v(article="den"), "articolo anomalo"),
])
def test_marcatura_anti_allucinazione(v, atteso):
    """Un genere sbagliato in Anki si ripassa per mesi e si impara bene:
    e' l'unico errore irreversibile del progetto."""
    motivo = carte.da_verificare(v)
    if atteso is None:
        assert motivo is None
    else:
        assert motivo and atteso in motivo


def test_carta_dubbia_e_marcata_non_scartata():
    c = carte.costruisci(_v(plural=""), "2026-07-23")
    assert c.note, "la carta va comunque creata"
    assert all("da-verificare" in n["tags"] for n in c.note)


def test_chiave_dedup_ignora_la_formattazione():
    """La v1 deduplicava sulla stringa HTML col colore dentro: bastava
    cambiare una tinta e il duplicato non veniva piu' visto."""
    assert carte.chiave(_v()) == carte.chiave(_v(level="A2", category="altro"))


def test_articolo_duplicato_rimosso():
    assert carte._pulisci("die Rechnung", "die") == "Rechnung"
    assert carte._pulisci("Rechnung", "die") == "Rechnung"


# ------------------------------------------------------------------ frasi i+1
@pytest.mark.parametrize("frase,tedesca", [
    ("Das ist der einzige, den ich nicht kenne.", True),
    ("Hast du dich schon daran gewöhnt?", True),
    ("I go for a walk, right?", False),
    ("Yeah, so it's indirect.", False),
    ("In a written, it's not like that.", False),
])
def test_filtro_lingua(frase, tedesca):
    """I transcript sono bilingui: senza filtro 'walk' diventava un vocabolo
    tedesco nuovo."""
    assert frasi.e_tedesca(frase) is tedesca


def test_cloze_buca_solo_la_parola_nuova():
    f = frasi.FraseIPiuUno("Das ist die teuerste Möglichkeit.", "teuerste", 6, "x")
    buco = f.con_buco()
    assert "_____" in buco and "teuerste" not in buco
    assert "Möglichkeit" in buco


def test_esposizione_del_corpus_conta_come_conoscenza():
    """Il fix della morfologia: una forma flessa vista molte volte e' nota,
    anche se il lemma non e' in vocab_db."""
    poche = frasi.parole_note(soglia=99999)
    molte = frasi.parole_note(soglia=3)
    assert len(molte) > len(poche)
