"""Test sulle invarianti delle fondamenta.

Non testano "che il codice giri": testano le poche regole la cui violazione
costa dati o soldi. Nella v1 non esisteva nessun test (gli unici due, test_api
e test_backup, sono stati cancellati nel commit ea02255).
"""

from __future__ import annotations

import json
import time

import pytest

from do.base import llm, paths, tracker
from do.base.staging import _protetto


# ------------------------------------------------------------------ percorsi
def test_root_non_dipende_dalla_cwd(tmp_path, monkeypatch):
    """La regressione piu' insidiosa della v1: path relativi alla cwd che
    creavano cartelle nel posto sbagliato in silenzio."""
    monkeypatch.chdir(tmp_path)
    import importlib

    importlib.reload(paths)
    assert paths.ROOT.name == "DeutschOps"
    assert paths.VOCAB_DB.is_absolute()


# ------------------------------------------------------------------ staging
@pytest.mark.parametrize("nome", [
    "lezione_2026-07-22-compressed.mp4",
    "LEZIONE_2026-07-22-COMPRESSED.MP4",
])
def test_audio_compresso_mai_archiviato(nome):
    """E' referenziato dal registry e riusato nei re-run. Se finisce in
    staging, sparisce dopo 20 giorni e il re-run non ha piu' l'audio."""
    assert _protetto(paths.AUDIO / nome)


def test_video_originale_archiviabile():
    assert not _protetto(paths.AUDIO / "Deutsch mit Kevin - 2026_07_22.mp4")


# ------------------------------------------------------------------ tracker
def test_fase_completata_non_si_rifa(tmp_path, monkeypatch):
    monkeypatch.setattr(tracker, "TASKS", tmp_path)
    t = tracker.Task("2026-01-01-test")
    assert not t.fatta("transcript")
    t.salva_fase("transcript", {"path": "x.txt"})

    t2 = tracker.Task("2026-01-01-test")          # simula un rilancio
    assert t2.ripreso and t2.fatta("transcript")
    assert t2.risultato("transcript")["path"] == "x.txt"


def test_effetto_irreversibile_solo_a_fine_run(tmp_path, monkeypatch):
    """Il bug originale: lo snapshot del Doc committato allo Step 1 faceva
    perdere il contenuto del Doc se la pipeline crashava dopo."""
    monkeypatch.setattr(tracker, "TASKS", tmp_path)
    applicati = []

    t = tracker.Task("2026-01-02-test")
    t.differisci("snapshot", {"testo": "..."})
    t.interrompi("crash simulato")
    assert applicati == []                        # NON applicato
    assert t.path.exists()                        # task conservato per il resume

    t2 = tracker.Task("2026-01-02-test")
    assert t2.ha_differito("snapshot")
    t2.chiudi(handler={"snapshot": applicati.append})
    assert len(applicati) == 1
    assert not t2.path.exists()                   # chiuso = cancellato


def test_legge_i_task_v1(tmp_path, monkeypatch):
    """Senza la migrazione delle chiavi, un task v1 risulta 'niente fatto' e
    il resume rifa' trascrizione ed estrazione — lavoro gia' pagato."""
    monkeypatch.setattr(tracker, "TASKS", tmp_path)
    (tmp_path / "2026-06-29-stefanie.json").write_text(json.dumps({
        "lesson_date": "2026-06-29-stefanie",
        "stages": {
            "doc": {"status": "done", "result": {"diff": "x"}, "at": "2026-06-29T10:00:00+00:00"},
            "extraction": {"status": "done", "result": {}, "at": "2026-06-29T10:05:00+00:00"},
        },
        "deferred_commits": {"snapshot": {"path": "s.txt"}},
        "last_error": {"reason": "Anki chiuso", "at": "2026-06-29T10:06:00+00:00"},
    }), encoding="utf-8")

    t = tracker.Task("2026-06-29-stefanie")
    assert t.fatta("doc")
    assert t.fatta("estrazione")                  # rinominata da "extraction"
    assert not t.fatta("anki")
    assert t.ha_differito("snapshot")
    assert t.risultato("doc")["diff"] == "x"

    d = tracker.dettaglio_pendenti()[0]
    assert d["ultimo_errore"] == "Anki chiuso"


# ------------------------------------------------------------------ costi
def test_costo_reale_non_e_una_costante():
    """main.py:230 della v1 scriveva `claude_cost = 0.10` fisso: 2,95 dei
    4,82 euro del registry sono quella costante x 30 lezioni."""
    piccolo, _ = llm._costo_eur("claude-sonnet-5", 1_000, 200)
    grande, _ = llm._costo_eur("claude-sonnet-5", 50_000, 8_000)
    assert piccolo < grande
    assert piccolo > 0


def test_modello_sconosciuto_marcato_stimato():
    """Un costo non calcolabile deve dichiararsi tale, non spacciarsi per
    misurato: e' esattamente il debito che rende falsi i KPI storici."""
    costo, stimato = llm._costo_eur("modello-mai-visto", 1000, 100)
    assert stimato and costo == 0.0


def test_lettura_da_cache_costa_meno():
    pieno, _ = llm._costo_eur("claude-opus-5", 10_000, 0)
    cache, _ = llm._costo_eur("claude-opus-5", 0, 0, cache_read=10_000)
    assert cache < pieno / 5


# ------------------------------------------------------------------ parsing
@pytest.mark.parametrize("grezzo", [
    '{"a": 1}',
    '```json\n{"a": 1}\n```',
    'Ecco il risultato:\n{"a": 1}\nSpero sia utile.',
])
def test_estrai_json_tollera_il_contorno(grezzo):
    assert llm.estrai_json(grezzo) == {"a": 1}


def test_estrai_json_non_ritorna_dict_vuoto_in_silenzio():
    """Un JSON malformato deve sollevare: se diventa {} si propaga fino ad
    Anki come 'lezione senza vocaboli' senza che nessuno se ne accorga."""
    with pytest.raises((ValueError, json.JSONDecodeError)):
        llm.estrai_json("nessun json qui")
