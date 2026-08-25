import json

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


def test_classifica_lezioni_per_lektion_conta_solo_i_successi(tmp_path, monkeypatch):
    """Se una chiamata del lotto lancia un'eccezione (`continue`, nessuna
    scrittura in mappa), 'classificate' non deve contarla — vedi CLAUDE.md
    "prima di mostrare un numero, verificare che dica quello che sembra dire"."""
    import do.base.config as config
    import do.base.llm as llm
    import do.base.paths as paths

    monkeypatch.setattr(libro, "lektioni", lambda: [{"numero": 1, "titolo": "Ankommen"}])
    monkeypatch.setattr(paths, "DATA", tmp_path)
    (tmp_path / "lezione_2026-01-01-stefanie.json").write_text(
        json.dumps({"topic": "x", "grammar_points": []}), encoding="utf-8")
    (tmp_path / "lezione_2026-01-08-stefanie.json").write_text(
        json.dumps({"topic": "y", "grammar_points": []}), encoding="utf-8")

    mappa_path = tmp_path / "libro_lezioni_mappa.json"
    monkeypatch.setattr(libro, "LIBRO_LEZIONI_MAPPA", mappa_path)

    class _Uso:
        costo_nozionale_eur = 0.01

    chiamate = {"n": 0}

    def _chiama_fittizia(sistema, user, cfg):
        chiamate["n"] += 1
        if chiamate["n"] == 1:
            raise RuntimeError("simulated failure")
        return '{"lektionen": []}', _Uso()

    monkeypatch.setattr(llm, "chiama", _chiama_fittizia)
    monkeypatch.setattr(llm, "estrai_json", lambda testo: json.loads(testo))
    monkeypatch.setattr(config, "llm_config", lambda **kw: object())

    r = libro.classifica_lezioni_per_lektion(quante=10)

    assert r["classificate"] == 1          # una lezione fallita (continue), una riuscita
    assert r["rimaste"] == 0               # entrambe erano nel lotto tentato
    mappa_salvata = json.loads(mappa_path.read_text(encoding="utf-8"))
    assert len(mappa_salvata) == 1         # solo la lezione riuscita e' scritta su disco
