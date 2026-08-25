"""`_pratica_pct` e' l'unica metrica nuova del piano "il Kursbuch nell'app" —
e quella che si e' rivelata sbagliata nella review finale: `rivelaAscolto()`
scriveva un record provvisorio E `avantiAscolto()` ne scriveva un altro per
lo stesso esercizio, raddoppiando ogni conteggio. Questi test fissano il
contratto giusto: una risposta = un record, e sotto soglia niente numero.
"""

from do.uscite.web import _pratica_pct


def _risposta(numero, corretta, zona="listening"):
    return {"zona": zona, "lektion": numero, "corretta": corretta}


def test_sotto_soglia_torna_none():
    """4 record sono sotto SOGLIA_MINIMA=5: nessun numero fragile."""
    risposte = [_risposta(1, True) for _ in range(4)]
    assert _pratica_pct(1, risposte) is None


def test_esattamente_alla_soglia_calcola():
    risposte = [_risposta(1, True) for _ in range(5)]
    assert _pratica_pct(1, risposte) == 100


def test_un_record_per_esercizio_percentuale_corretta():
    """Il contratto che il double-write violava: CINQUE esercizi svolti, UN
    record ciascuno (non due), quattro giusti e uno sbagliato deve dare 80%,
    non 40% (che e' quello che il bug — due record a esercizio, uno sempre
    `corretta: false` dalla reveal — avrebbe prodotto)."""
    risposte = ([_risposta(1, True) for _ in range(4)]
                + [_risposta(1, False)])
    assert _pratica_pct(1, risposte) == 80


def test_filtra_per_zona_e_lektion():
    risposte = ([_risposta(1, True) for _ in range(5)]
                + [_risposta(2, False) for _ in range(5)]
                + [_risposta(1, True, zona="practice") for _ in range(5)])
    assert _pratica_pct(1, risposte) == 100
    assert _pratica_pct(2, risposte) == 0


def test_double_write_produrrebbe_meta_del_valore_vero():
    """Documenta il bug che questi test avrebbero preso: se ogni esercizio
    lascia DUE record (il `corretta: false` provvisorio della reveal + il
    voto vero), un utente che fa tutto giusto legge 50%, non 100%."""
    un_record_a_esercizio = [_risposta(1, True) for _ in range(5)]
    due_record_a_esercizio = []
    for _ in range(5):
        due_record_a_esercizio.append(_risposta(1, False))  # reveal provvisorio
        due_record_a_esercizio.append(_risposta(1, True))   # voto vero

    assert _pratica_pct(1, un_record_a_esercizio) == 100
    assert _pratica_pct(1, due_record_a_esercizio) == 50
