import json

import pytest

from do.sapere import libro


def test_lezioni_per_lektion_legge_la_mappa_salvata(tmp_path, monkeypatch):
    mappa = {
        "2026-07-28-stefanie": [{"lektion": 12, "motivo": "Perfekt"}],
        "2026-08-11-stefanie": [],
    }
    p = tmp_path / "libro_lezioni_mappa.json"
    p.write_text(json.dumps(mappa), encoding="utf-8")
    monkeypatch.setattr(libro, "LIBRO_LEZIONI_MAPPA", p)

    out = libro.lezioni_per_lektion(12)
    assert out == [{"data_lezione": "2026-07-28-stefanie", "motivo": "Perfekt"}]


def test_lezioni_per_lektion_nessuna_mappa_torna_vuoto(tmp_path, monkeypatch):
    monkeypatch.setattr(libro, "LIBRO_LEZIONI_MAPPA", tmp_path / "non-esiste.json")
    assert libro.lezioni_per_lektion(1) == []


def test_lezioni_per_lektion_numero_senza_match(tmp_path, monkeypatch):
    mappa = {"2026-07-28-stefanie": [{"lektion": 12, "motivo": "x"}]}
    p = tmp_path / "libro_lezioni_mappa.json"
    p.write_text(json.dumps(mappa), encoding="utf-8")
    monkeypatch.setattr(libro, "LIBRO_LEZIONI_MAPPA", p)
    assert libro.lezioni_per_lektion(99) == []
