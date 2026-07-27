"""Il riquadro di avvio sessione.

PRESO DAL MOTORE CONDIVISO (E03, segreteria), CON L'ENFORCEMENT CHE LI' MANCA
`shared start up/_engine/segreteria/README.md` descrive lo stesso riquadro e
poi dichiara il proprio limite: «il markdown non impone all'AI di generare il
briefing: e' una regola che l'AI segue, non un controllo del sistema.
L'enforcement reale richiederebbe un hook».

DeutschOps gli hook ce li ha gia' — `.claude/settings.json` ne monta due su
PreToolUse. Qui il briefing lo stampa un hook `SessionStart`, non la buona
volonta'. E' l'unico punto in cui questo progetto supera il modello da cui
copia.

QUATTRO BLOCCHI, NON OTTO
Del riquadro del motore cadono i blocchi multi-utente: "da approvare", "stato
ricezione team", "riunioni". Restano: lezioni, scadenze, dove sbagli, ponte.

IL BRIEFING LEGGE, NON SCRIVE — con un'eccezione dichiarata: il ponte salva la
propria impronta dopo un check, altrimenti ricontrollerebbe a ogni avvio.
"""

from __future__ import annotations

from datetime import date

from ..base.tracker import dettaglio_pendenti
from . import attivita, ponte, scadenze, stato as mod_stato

LARGH = 68


def _riga(testo: str = "") -> str:
    return f"  {testo}"


def genera(*, con_ponte: bool = True) -> str:
    """Il riquadro. Se non c'e' niente da dire, resta corto — e va bene cosi'."""
    d = mod_stato.raccogli()
    out: list[str] = ["", "  " + "=" * LARGH, _riga("DEUTSCHOPS — " + date.today().isoformat()),
                      "  " + "=" * LARGH]

    # ---------------------------------------------------------- 1. lezioni
    if d["ultima_lezione"]:
        g = d["giorni_da_ultima"]
        avviso = "   <-- oltre 3 settimane, e' la soglia di allarme" if (g or 0) > 21 else ""
        out.append(_riga(f"Ultima lezione: {d['ultima_lezione']} ({g}g fa){avviso}"))
    else:
        out.append(_riga("Nessuna lezione ancora elaborata."))

    pend = dettaglio_pendenti()
    if pend:
        out.append(_riga(f"Lezioni NON chiuse: {len(pend)}"))
        for p in pend[:4]:
            out.append(_riga(f"   {p['data']} — manca: {', '.join(p['mancanti'])}"))

    # ---------------------------------------------------------- 2. scadenze
    if righe := scadenze.righe_briefing():
        out += [_riga(), _riga("SCADENZE")]
        out += [_riga("   " + r) for r in righe]
    elif d["giorni_esame"] is not None:
        out.append(_riga(f"Esame B2 fra {d['giorni_esame']} giorni."))

    # ---------------------------------------------------------- 3. dove sbagli
    out += [_riga(), _riga("DOVE SBAGLI")]
    out.append(_riga(f"   {d['famiglia_casi']} errori su {d['errori']} "
                     f"({d['quota_casi']}%) sono Kasus/Genus/Präposition"))
    if d["errori_per_categoria"]:
        top = " · ".join(f"{c} {n}" for c, n in d["errori_per_categoria"][:4])
        out.append(_riga(f"   {top}"))
    out.append(_riga(f"   Vocaboli B2+: {d['b2_o_oltre']} su {d['vocaboli']}"))

    # ---------------------------------------------------------- 4. materiale fermo
    # Elaborare lezioni da' la sensazione di studiare: il sistema lavora, i
    # numeri salgono. Ma macinare non e' imparare — nella v1 la pipeline ha
    # fatto 30 lezioni mentre il loop di ripasso girava una volta sola.
    if righe := attivita.righe_briefing():
        out += [_riga(), _riga("MATERIALE FERMO")]
        out += [_riga("   " + r) for r in righe]

    # ---------------------------------------------------------- 5. ponte
    if con_ponte:
        if righe := ponte.righe_briefing():
            out += [_riga(), _riga("MOTORE CONDIVISO")]
            out += [_riga("   " + r) for r in righe]

    out += ["  " + "=" * LARGH, ""]
    return "\n".join(out)
