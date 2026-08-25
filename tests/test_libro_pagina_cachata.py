from pathlib import Path

import pytest

from do.sapere import libro


def test_fonte_sconosciuta_torna_none():
    assert libro.pagina_cachata("non-esiste", 0) is None


def test_indice_fuori_range_torna_none():
    # kursbuch ha 307 pagine: 99999 non esiste
    assert libro.pagina_cachata("kursbuch", 99999) is None


def test_pagina_valida_produce_un_file_reale(tmp_path, monkeypatch):
    monkeypatch.setattr(libro, "BOOK", libro.BOOK)  # nessun cambio, per chiarezza
    cartella_cache = tmp_path / "pagine_render"
    monkeypatch.setattr(libro, "_CARTELLA_RENDER", cartella_cache)

    path = libro.pagina_cachata("kursbuch", 0)
    assert path is not None
    assert path.exists()
    assert path.suffix == ".png"
    assert path.stat().st_size > 1000  # non un file vuoto/corrotto


def test_seconda_chiamata_riusa_la_cache(tmp_path, monkeypatch):
    cartella_cache = tmp_path / "pagine_render"
    monkeypatch.setattr(libro, "_CARTELLA_RENDER", cartella_cache)

    p1 = libro.pagina_cachata("kursbuch", 0)
    mtime1 = p1.stat().st_mtime
    p2 = libro.pagina_cachata("kursbuch", 0)
    assert p1 == p2
    assert p2.stat().st_mtime == mtime1  # non ri-renderizzata
