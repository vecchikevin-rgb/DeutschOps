"""Registro scadenze a semaforo.

Preso da `shared start up/_engine/scadenze/` (iniziativa E05), adattato a
mono-utente: niente owner, niente proposte, niente approvazioni — la colonna
"chi" e' sempre Kevin.

DIFFERENZA DELIBERATA RISPETTO AL MOTORE CONDIVISO
Li' il semaforo e' scritto a mano nella tabella e l'alert e' "una regola che
l'AI segue". Il file stesso lo ammette come limite: servirebbe un hook. Qui il
colore non e' mai scritto — si ricalcola sempre da oggi — e l'alert lo stampa
un hook SessionStart, non la buona volonta'. Nel motore condiviso ogni pattern
affidato alla disciplina e' fallito: log-loop.md ha una riga di cinque
settimane fa.

Il file `stato/scadenze.md` e' l'unico markdown di stato scritto a mano.
Questo modulo lo legge, non lo tocca.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from ..base.paths import STATO

SCADENZE_MD = STATO / "scadenze.md"

# Soglie del semaforo, in giorni.
IMMINENTE = 7          # il motore usa 3; qui 7, perche' una scadenza di studio
                       # richiede preparazione, non solo di ricordarsene.


@dataclass(frozen=True)
class Scadenza:
    data: date | None
    cosa: str
    tipo: str
    stato: str
    note: str

    @property
    def giorni(self) -> int | None:
        return None if self.data is None else (self.data - date.today()).days

    @property
    def semaforo(self) -> str:
        """rosso = scaduta · giallo = imminente · verde = c'e' tempo ·
        grigio = data non ancora fissata."""
        if self.chiusa:
            return "chiusa"
        g = self.giorni
        if g is None:
            return "grigio"
        if g < 0:
            return "rosso"
        if g <= IMMINENTE:
            return "giallo"
        return "verde"

    @property
    def chiusa(self) -> bool:
        return self.stato.strip().lower() in ("chiuso", "chiusa", "fatto", "fatta")


def _parse_data(cella: str) -> date | None:
    """Accetta 2026-10-15; ritorna None su 2026-10-?? (data non ancora fissata).

    Una data incompleta e' informazione, non un errore: significa "so che c'e',
    non so quando". Mostrarla in grigio e' meglio che ometterla.
    """
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", cella.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def leggi() -> list[Scadenza]:
    """Legge le righe della tabella Registro. Tollera l'assenza del file."""
    if not SCADENZE_MD.exists():
        return []

    out: list[Scadenza] = []
    for riga in SCADENZE_MD.read_text(encoding="utf-8").splitlines():
        riga = riga.strip()
        if not riga.startswith("|"):
            continue
        celle = [c.strip() for c in riga.strip("|").split("|")]
        if len(celle) < 4:
            continue
        # Salta intestazione e separatore.
        if celle[0].lower() in ("data", "") or set(celle[0]) <= set("-: "):
            continue
        out.append(Scadenza(
            data=_parse_data(celle[0]),
            cosa=re.sub(r"\*\*|`", "", celle[1]),
            tipo=celle[2],
            stato=celle[3],
            note=celle[4] if len(celle) > 4 else "",
        ))
    return out


def da_segnalare() -> list[Scadenza]:
    """Solo cio' che merita di comparire nel briefing: scadute o imminenti.

    Il silenzio quando non c'e' nulla e' un requisito, non un dettaglio: un
    blocco che compare a ogni avvio anche da vuoto smette di essere letto in
    due settimane.
    """
    aperte = [s for s in leggi() if not s.chiusa]
    urgenti = [s for s in aperte if s.semaforo in ("rosso", "giallo")]
    return sorted(urgenti, key=lambda s: (s.semaforo != "rosso", s.giorni or 9999))


def prossima_data_esame() -> date | None:
    for s in leggi():
        if s.tipo.strip().lower() == "esame" and s.data and not s.chiusa:
            return s.data
    return None


def giorni_all_esame() -> int | None:
    d = prossima_data_esame()
    return None if d is None else (d - date.today()).days


def righe_briefing() -> list[str]:
    """Le righe pronte per il riquadro di avvio. Lista vuota = niente da dire."""
    simbolo = {"rosso": "[SCADUTA]", "giallo": "[IMMINENTE]", "grigio": "[DATA DA FISSARE]"}
    righe = []
    for s in da_segnalare():
        g = s.giorni
        quando = "data da fissare" if g is None else (
            f"scaduta da {-g}g" if g < 0 else f"fra {g}g"
        )
        righe.append(f"{simbolo.get(s.semaforo, '')} {s.cosa} — {quando}")
    return righe
