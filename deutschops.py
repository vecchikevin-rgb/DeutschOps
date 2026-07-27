"""DeutschOps — entry point unico.

Sostituisce main.py + watch.py + DeutschOps.bat + i 15 script standalone che
si lanciavano ognuno a modo suo. Un comando, sottocomandi espliciti.

    py -3 deutschops.py lezione <file> [data]   elabora una lezione (pipeline completa)
    py -3 deutschops.py lezione --auto          elabora i video non ancora fatti
    py -3 deutschops.py briefing          il riquadro di avvio (lo chiama l'hook)
    py -3 deutschops.py stato             rigenera stato/stato-tedesco.md
    py -3 deutschops.py esame             gap analysis B2 (1 chiamata LLM)
    py -3 deutschops.py drill [-n 10]     esercizi dai tuoi errori reali
    py -3 deutschops.py frasi [-n 20]     frasi i+1 dai transcript (gratis)
    py -3 deutschops.py carte <data>      carica le carte di una lezione in Anki
    py -3 deutschops.py anki-audit        difetti del mazzo
    py -3 deutschops.py anki-ripara       li corregge da fonti verificabili
    py -3 deutschops.py ponte             check verso il motore condiviso
    py -3 deutschops.py pendenti          lezioni con run non completati
    py -3 deutschops.py confronta <data>  rielabora e confronta col vecchio (S1)
"""

from __future__ import annotations

import argparse
import json
import sys

# UTF-8 sempre: la console Windows altrimenti rompe su umlaut ed emoji.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _lezione_json(data: str):
    from do.base.paths import DATA
    p = DATA / f"lezione_{data}.json"
    if not p.exists():
        disponibili = sorted(x.stem.replace("lezione_", "")
                             for x in DATA.glob("lezione_*.json"))
        raise SystemExit(
            f"Lezione non trovata: {p.name}\n"
            f"Ultime disponibili: {', '.join(disponibili[-5:])}"
        )
    return json.loads(p.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="deutschops", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("lezione", help="elabora una lezione")
    p.add_argument("sorgente", nargs="?", help="video/audio, o il .txt grezzo")
    p.add_argument("data", nargs="?", help="es. 2026-07-23-stefanie")
    p.add_argument("--auto", action="store_true",
                   help="cerca in Audiolessons/ i video senza transcript")
    p.add_argument("--senza-doc", action="store_true",
                   help="non tocca il Google Doc di Stefanie")

    p = sub.add_parser("confronta", help="rielabora una lezione e confronta (S1)")
    p.add_argument("data", help="es. 2026-07-23-stefanie")
    p.add_argument("--riusa", action="store_true",
                   help="non richiama l'LLM: confronta l'ultimo output di prova")

    sub.add_parser("briefing", help="riquadro di avvio sessione")
    sub.add_parser("stato", help="rigenera stato/stato-tedesco.md")
    p = sub.add_parser("pendenti", help="lezioni con run non completati")
    p.add_argument("--recupera", action="store_true",
                   help="esegue le fasi mancanti recuperabili e chiude i task")
    p.add_argument("--archivia", metavar="DATA",
                   help="chiude un task dichiarando irrecuperabile cio' che manca")
    p.add_argument("--motivo", default="",
                   help="perche' e' irrecuperabile (obbligatorio con --archivia)")
    p.add_argument("--prova", action="store_true", help="non scrive niente")
    sub.add_parser("esame", help="gap analysis verso il B2")

    p = sub.add_parser("drill", help="esercizi dagli errori reali")
    p.add_argument("-n", type=int, default=10)
    p.add_argument("--categoria", default=None)
    p.add_argument("--soluzioni", action="store_true")

    p = sub.add_parser("frasi", help="frasi i+1 dai transcript")
    p.add_argument("-n", type=int, default=20)

    p = sub.add_parser("carte", help="carica le carte di una lezione in Anki")
    p.add_argument("data", help="es. 2026-07-23-stefanie")
    p.add_argument("--prova", action="store_true", help="non tocca Anki")

    p = sub.add_parser("grammatica", help="approfondisce le regole rimaste indietro")
    p.add_argument("--applica", action="store_true",
                   help="senza questo flag elenca soltanto")
    p.add_argument("--web", action="store_true",
                   help="con ricerca sulle fonti: ~0,58 EUR a regola invece di 0,02")

    sub.add_parser("anki-audit", help="difetti del mazzo")
    p = sub.add_parser("anki-ripara", help="corregge il mazzo")
    p.add_argument("--applica", action="store_true",
                   help="senza questo flag e' solo una prova a secco")

    p = sub.add_parser("ponte", help="check verso il motore condiviso")
    p.add_argument("--forza", action="store_true", help="ignora la cadenza")

    a = ap.parse_args(argv)

    # ------------------------------------------------------------------
    if a.cmd == "lezione":
        from do.lezione import pipeline

        if a.auto:
            trovate = pipeline.da_elaborare()
            if not trovate:
                print("  Nessun video nuovo in Audiolessons/.")
                return 0
            print(f"  {len(trovate)} da elaborare: "
                  f"{', '.join(f.name for f in trovate)}")
            for f in trovate:
                d = pipeline._data_dal_nome(f.stem)
                pipeline.elabora(f, f"{d}-stefanie" if d else None,
                                 salta_doc=a.senza_doc)
        elif not a.sorgente:
            raise SystemExit("Serve un file sorgente, oppure --auto.")
        else:
            pipeline.elabora(a.sorgente, a.data, salta_doc=a.senza_doc)

    elif a.cmd == "confronta":
        from do.lezione import confronto

        return 0 if confronto.esegui(a.data, riusa=a.riusa) else 1

    elif a.cmd == "briefing":
        from do.motore import briefing
        print(briefing.genera())

    elif a.cmd == "stato":
        from do.motore import stato
        stato.genera()
        from do.base.paths import STATO
        print(f"Scritto: {STATO / 'stato-tedesco.md'}")

    elif a.cmd == "pendenti":
        from do.base import recupero
        from do.base.tracker import dettaglio_pendenti

        if a.archivia:
            if not a.motivo:
                raise SystemExit("--archivia richiede --motivo: chiudere un task "
                                 "senza dire perche' fa sparire l'informazione.")
            print(json.dumps(recupero.archivia(a.archivia, a.motivo),
                             ensure_ascii=False, indent=2))
            return 0

        if a.recupera:
            for r in recupero.tutti(prova=a.prova):
                print(json.dumps(r, ensure_ascii=False, indent=2))
            return 0

        pend = dettaglio_pendenti()
        if not pend:
            print("Nessun task pendente: tutte le pipeline sono chiuse.")
        for t in pend:
            print(f"\n  {t['data']}")
            print(f"    fatte    : {', '.join(t['fatte']) or '(nessuna)'}")
            print(f"    mancanti : {', '.join(t['mancanti'])}")
            if t["ultimo_errore"]:
                print(f"    errore   : {t['ultimo_errore']}")

    elif a.cmd == "esame":
        from do.studio import esame
        esame.stampa(esame.analizza())

    elif a.cmd == "drill":
        from do.studio import drill
        drill.stampa(drill.genera(a.categoria, a.n), soluzioni=a.soluzioni)

    elif a.cmd == "frasi":
        from do.studio import frasi
        st = frasi.statistiche()
        print(f"\n  Comprensibilita' del corpus: {st.get('comprensibilita')}% "
              f"su {st.get('frasi_analizzate')} frasi tedesche")
        print(f"  Parole note stimate: {st.get('parole_note')}\n")
        for f in frasi.estrai(limite=a.n):
            print(f"  [{f.frequenza}x] {f.nuova}")
            print(f"        {f.con_buco()}")

    elif a.cmd == "carte":
        from do.studio import carte
        lez = _lezione_json(a.data)
        r = carte.alimenta(lez.get("vocabulary", []), a.data, prova=a.prova)
        print(json.dumps(r, ensure_ascii=False, indent=2))

    elif a.cmd == "grammatica":
        from do.sapere import grammatica

        r = grammatica.completa(web=a.web, prova=not a.applica)
        if not a.applica:
            print(f"\n  {r['incomplete']} regole senza approfondimento"
                  f" — stima {r['incomplete'] * (0.58 if a.web else 0.022):.2f} EUR")
            for nome in r.get("regole", []):
                print(f"     {nome}")
            print("\n  Rilancia con --applica per farlo davvero.")
        else:
            print(f"\n  {r['approfondite']}/{r['incomplete']} approfondite "
                  f"| {r['costo_eur']:.4f} EUR misurati")

    elif a.cmd == "anki-audit":
        from do.studio import manutenzione
        _, r = manutenzione.analizza()
        print(f"\n  {r['note']} note, {r['sane']} senza difetti\n")
        for d, n in r["difetti"]:
            print(f"   {n:6d}  {d}")
        if r["generi_sospetti"]:
            print("\n  Generi da controllare a mano:")
            for _, forma, atteso in r["generi_sospetti"]:
                print(f"   {forma}  ->  il suffisso vuole {atteso}")

    elif a.cmd == "anki-ripara":
        from do.studio import manutenzione
        schede, _ = manutenzione.analizza()
        r = manutenzione.ripara(schede, prova=not a.applica)
        if not a.applica:
            print("  PROVA A SECCO — rilancia con --applica per scrivere davvero\n")
        for k, n in r["dettaglio"]:
            print(f"   {n:6d}  {k}")

    elif a.cmd == "ponte":
        from do.motore import ponte
        nov = ponte.controlla(forza=a.forza)
        if not nov:
            print("  Niente di nuovo nel motore condiviso.")
        for n in nov:
            print(f"\n  {n.sorgente}\n    {n.percorso}\n    {n.estratto}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
