"""Test della pipeline: validazione dello schema, rilevamento, sapere.

Niente rete, niente Anki, niente LLM. Quello che si puo' rompere in silenzio
sono la validazione dello schema (produce carte vuote), l'idempotenza dei DB
(gonfia i conteggi) e il diff del Doc (riproponde righe gia' viste).
"""

from __future__ import annotations

import json

import pytest

from do.lezione import doc, estrazione
from do.lezione import pipeline
from do.sapere import registro, vocaboli


def _lezione_valida() -> dict:
    return {
        "topic": "Einkaufen",
        "summary_en": "Shopping vocabulary.",
        "summary_it": "Vocabolario della spesa.",
        "vocabulary": [
            {"german": "Milch", "article": "die", "plural": "", "category": "noun",
             "italian": "latte", "english": "milk",
             "example_de": "Ich kaufe die Milch.", "example_it": "Compro il latte.",
             "level": "A1"},
        ],
        "grammar_points": [{"rule": "Akkusativ", "explanation_en": "Direct object.",
                            "examples": ["Ich kaufe den Apfel."]}],
        "phrases": [],
        "comprehension_questions": [],
    }


# ----------------------------------------------------------------- schema
def test_schema_valido_passa():
    d = estrazione.valida(_lezione_valida())
    assert d["vocabulary"][0]["german"] == "Milch"


def test_campo_mancante_solleva():
    d = _lezione_valida()
    del d["summary_it"]
    with pytest.raises(estrazione.SchemaNonValido, match="summary_it"):
        estrazione.valida(d)


def test_tipo_sbagliato_solleva():
    d = _lezione_valida()
    d["vocabulary"] = "non una lista"
    with pytest.raises(estrazione.SchemaNonValido, match="vocabulary"):
        estrazione.valida(d)


def test_vocabolo_senza_parola_solleva():
    """Il caso che diventerebbe una carta Anki con il fronte vuoto."""
    d = _lezione_valida()
    d["vocabulary"].append({"article": "der", "italian": "cosa"})
    with pytest.raises(estrazione.SchemaNonValido, match="senza campo"):
        estrazione.valida(d)


def test_dedup_regole_regge_la_riformulazione(monkeypatch):
    """Il caso misurato: 1,01 EUR di ricerca web perche' il modello aveva
    riformulato i nomi di cinque regole gia' approfondite."""
    gia_viste = {
        "superlative: am + -sten vs. article + -ste + noun": {
            "rule": "Superlative: am + -sten vs. article + -ste + noun",
            "full_rule": "...", "common_mistakes": "...",
        },
        "verb 'warten' + auf + accusative": {
            "rule": "Verb 'warten' + auf + accusative",
            "full_rule": "...", "common_mistakes": "...",
        },
    }
    monkeypatch.setattr(estrazione, "_regole_gia_studiate", lambda: gia_viste)

    riformulate = [
        {"rule": "Superlative: am -sten vs der/die/das -ste + noun"},
        {"rule": "warten auf + dass-clause"},
        {"rule": "hier vs hierher / dort vs dorthin"},     # davvero nuova
    ]
    fuori, rimandate = estrazione.da_ricercare(riformulate)
    assert [g["rule"] for g in fuori] == ["hier vs hierher / dort vs dorthin"]
    assert rimandate == []


def test_regola_incompleta_viene_ricercata(monkeypatch):
    """Nome uguale ma senza common_mistakes: va comunque approfondita."""
    monkeypatch.setattr(estrazione, "_regole_gia_studiate", lambda: {
        "dativ nach helfen": {"rule": "Dativ nach helfen", "full_rule": "x"},
    })
    fuori, _ = estrazione.da_ricercare([{"rule": "Dativ nach helfen"}])
    assert len(fuori) == 1


def test_tetto_ricerche_non_taglia_in_silenzio(monkeypatch):
    monkeypatch.setattr(estrazione, "_regole_gia_studiate", dict)
    punti = [{"rule": f"Regola completamente distinta numero {i}"} for i in range(6)]
    fuori, rimandate = estrazione.da_ricercare(punti)
    assert len(fuori) == estrazione.MAX_RICERCHE
    assert len(rimandate) == 6 - estrazione.MAX_RICERCHE
    assert all(isinstance(r, str) and r for r in rimandate)


def test_campi_opzionali_normalizzati():
    d = _lezione_valida()
    d["vocabulary"].append({"german": "Brot"})
    v = estrazione.valida(d)["vocabulary"][1]
    assert v["plural"] == "" and v["example_de"] == ""
    assert v["german"] == "Brot"


# ------------------------------------------------------------- diff del Doc
def test_diff_trova_righe_in_mezzo():
    """Stefanie inserisce anche a meta' documento, non solo in coda."""
    vecchio = "riga uno\nriga due\nriga tre"
    nuovo = "riga uno\nriga NUOVA\nriga due\nriga tre"
    assert "riga NUOVA" in doc.righe_nuove(vecchio, nuovo)
    assert "riga uno" not in doc.righe_nuove(vecchio, nuovo)


def test_diff_vuoto_se_identico():
    t = "=== TAB: Lektion ===\nfoo\nbar"
    assert doc.righe_nuove(t, t) == ""


# ------------------------------------------------------------- rilevamento
@pytest.mark.parametrize(("stem", "atteso"), [
    ("Deutsch mit Kevin - 2026_07_22 10-03", "2026-07-22"),
    ("Classroom with Stefanie 2026-05-25", "2026-05-25"),
    ("lezione senza data", None),
])
def test_data_dal_nome(stem, atteso):
    """Il glob della v1 cercava 'Classroom with Stefanie*.mp4' e i file oggi
    si chiamano 'Deutsch mit Kevin - ...': watch.py non ha mai trovato nulla."""
    assert pipeline._data_dal_nome(stem) == atteso


def test_video_riconosciuto_per_estensione():
    from do.lezione import audio

    assert audio.e_video("x.mp4") and audio.e_video("X.MKV")
    assert not audio.e_video("trascrizione.txt")


# ------------------------------------------------------- vocaboli idempotenti
def test_vocaboli_non_duplica_occorrenze(tmp_path, monkeypatch):
    db = tmp_path / "vocab.json"
    monkeypatch.setattr(vocaboli, "VOCAB_DB", db)

    vocaboli.aggiorna_da_lezione(_lezione_valida(), "2026-01-01")
    vocaboli.aggiorna_da_lezione(_lezione_valida(), "2026-01-01")

    voce = json.loads(db.read_text(encoding="utf-8"))["words"]["milch"]
    assert voce["occurrences"] == 1
    assert voce["seen_in_lessons"] == ["2026-01-01"]


def test_vocaboli_conta_lezioni_diverse(tmp_path, monkeypatch):
    db = tmp_path / "vocab.json"
    monkeypatch.setattr(vocaboli, "VOCAB_DB", db)

    vocaboli.aggiorna_da_lezione(_lezione_valida(), "2026-01-01")
    vocaboli.aggiorna_da_lezione(_lezione_valida(), "2026-01-08")

    assert json.loads(db.read_text(encoding="utf-8"))["words"]["milch"]["occurrences"] == 2


# ----------------------------------------------------------------- registro
def test_registro_marca_il_costo_stimato(tmp_path, monkeypatch):
    """La costante 0,10 di main.py:230 va etichettata, non riscritta."""
    reg = tmp_path / "registry.json"
    monkeypatch.setattr(registro, "REGISTRY", reg)
    reg.write_text(json.dumps({
        "lessons": [
            {"id": "a", "cost_claude_eur": 0.10, "cost_total_eur": 0.28,
             "duration_minutes": 50},
            {"id": "b", "cost_claude_eur": 0.0731, "cost_total_eur": 0.0731,
             "duration_minutes": 55},
        ],
        "stats": {},
    }), encoding="utf-8")

    assert registro.marca_storico() == 2
    voci = {l["id"]: l for l in registro.carica()["lessons"]}
    assert voci["a"]["cost_estimated"] is True
    assert voci["b"]["cost_estimated"] is False
    # Le cifre non si toccano: inventare i costi veri sarebbe peggio.
    assert voci["a"]["cost_claude_eur"] == 0.10


def test_registro_non_duplica_la_stessa_lezione(tmp_path, monkeypatch):
    reg = tmp_path / "registry.json"
    monkeypatch.setattr(registro, "REGISTRY", reg)
    for _ in range(2):
        registro.registra(data_lezione="2026-01-01-stefanie", audio="x.mp4",
                          dati=_lezione_valida(), costo_trascrizione=0.0,
                          costo_llm=0.05, minuti=50)
    r = registro.carica()
    assert r["stats"]["total"] == 1
    assert r["stats"]["total_cost_eur"] == 0.05
