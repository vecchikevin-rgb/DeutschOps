"""libro_risposta() (do/uscite/web.py) e' l'endpoint dietro rivelaAscolto() +
avantiAscolto() nel frontend. La review finale ha trovato che entrambe le
chiamate scrivevano un record — la reveal con un `corretta: false`
provvisorio, il voto con quello vero — raddoppiando ogni esercizio nel
registro. Il contratto giusto: rivelare (senza `corretta` nel corpo) non
scrive, solo il voto vero scrive.
"""

import json

from do.sapere import libro
from do.studio import sessione
from do.uscite.web import libro_risposta


def _pagina_finta(tmp_path, monkeypatch):
    dati = {
        "kursbuch:10": {
            "fonte": "kursbuch", "indice": 10, "tipo": "esercizio",
            "lezione": "1", "livello": "A1", "testo": "...", "frasi": [],
            "esercizi": [
                {"consegna": "Listen and fill", "stimolo": "Ich ___ aus Basel.",
                 "traccia_audio": "traccia1.mp3", "soluzione": "komme",
                 "soluzione_fonte": "kursbuch:10"},
            ],
        },
    }
    p = tmp_path / "libro_pagine.json"
    p.write_text(json.dumps(dati), encoding="utf-8")
    monkeypatch.setattr(libro, "LIBRO_PAGINE", p)

    r = tmp_path / "risposte.json"
    monkeypatch.setattr(sessione, "RISPOSTE", r)
    return r


def test_rivela_senza_corretta_non_scrive(tmp_path, monkeypatch):
    """Corpo senza il campo `corretta` (la reveal) — nessun record."""
    percorso_risposte = _pagina_finta(tmp_path, monkeypatch)

    out = libro_risposta({
        "lektion": 1, "chiave_pagina": "kursbuch:10", "indice_esercizio": 0,
    })

    assert out["soluzione"] == "komme"
    assert not percorso_risposte.exists()  # nessuna scrittura sul registro


def test_voto_vero_scrive_un_record_solo(tmp_path, monkeypatch):
    """Reveal (nessun `corretta`) seguita dal voto vero (`corretta: True`) —
    UN record nel registro, non due."""
    percorso_risposte = _pagina_finta(tmp_path, monkeypatch)

    libro_risposta({"lektion": 1, "chiave_pagina": "kursbuch:10", "indice_esercizio": 0})
    libro_risposta({"lektion": 1, "chiave_pagina": "kursbuch:10",
                    "indice_esercizio": 0, "corretta": True})

    risposte = json.loads(percorso_risposte.read_text(encoding="utf-8"))["risposte"]
    assert len(risposte) == 1
    assert risposte[0]["corretta"] is True


def test_corretta_null_esplicito_non_scrive(tmp_path, monkeypatch):
    """Un `corretta: null` nel JSON (equivalente Python: None) deve
    comportarsi come "assente", non come voto vero — stessa ragione per cui
    il controllo e' `is not None`, non `"corretta" in voce`."""
    percorso_risposte = _pagina_finta(tmp_path, monkeypatch)

    libro_risposta({"lektion": 1, "chiave_pagina": "kursbuch:10",
                    "indice_esercizio": 0, "corretta": None})

    assert not percorso_risposte.exists()


def test_corretta_false_esplicito_scrive_comunque(tmp_path, monkeypatch):
    """`corretta: False` e' un voto vero (sbagliato), non "assente" — la
    distinzione e' su `"corretta" in voce`, non sulla verita' (falsy) del
    valore. Un controllo tipo `if voce.get("corretta")` confonderebbe questo
    caso con la reveal, e non registrerebbe mai un esercizio sbagliato."""
    percorso_risposte = _pagina_finta(tmp_path, monkeypatch)

    libro_risposta({"lektion": 1, "chiave_pagina": "kursbuch:10",
                    "indice_esercizio": 0, "corretta": False})

    risposte = json.loads(percorso_risposte.read_text(encoding="utf-8"))["risposte"]
    assert len(risposte) == 1
    assert risposte[0]["corretta"] is False
