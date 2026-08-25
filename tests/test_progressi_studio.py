"""`studio()` (do/studio/progressi.py) e' "dove sta il progresso vero", per
esplicita dichiarazione del CLAUDE.md del progetto: quanti esercizi chiudi
senza aiuto. La review finale ha trovato che i record Listening (senza
campo `aiuto`, perche' autovalutati e non gradinati) passavano per "chiusi
senza aiuto" — inquinando l'unica metrica che questo modulo si vanta di
prendere sul serio."""

from do.studio import progressi, sessione


def _risposta(zona, corretta, aiuto=None):
    voce = {"zona": zona, "corretta": corretta}
    if aiuto is not None:
        voce["aiuto"] = aiuto
    return voce


def test_risposte_listening_non_contano_come_senza_aiuto(monkeypatch):
    risposte = (
        [_risposta("practice", True, aiuto=0) for _ in range(3)]
        + [_risposta("listening", True) for _ in range(10)]  # niente 'aiuto'
    )
    monkeypatch.setattr(sessione, "risposte", lambda: risposte)
    monkeypatch.setattr(sessione, "riepilogo",
                        lambda: {"ultima": None, "totale": 0})

    out = progressi.studio()

    assert out["senza_aiuto"] == 3  # solo le Practice, non le 10 Listening
    # Le 10 Listening non devono nemmeno entrare nel gradino di aiuto: senza
    # il filtro, 3+10=13 record si avvicinerebbero a MINIME_PER_TENDENZA=20
    # solo per rumore Listening, e servono_ancora conterebbe 7 invece di 17.
    assert out["tendenza_aiuto"] is None
    assert out["servono_ancora"] == 17
    # Ma restano studio: il conteggio totale e "ultima" le vedono comunque.
    assert out["risposte"] == 13
