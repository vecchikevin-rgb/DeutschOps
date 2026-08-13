"""DeutschOps — entry point unico.

Sostituisce main.py + watch.py + DeutschOps.bat + i 15 script standalone che
si lanciavano ognuno a modo suo. Un comando, sottocomandi espliciti.

    py -3 deutschops.py lezione <file> [data]   elabora una lezione (pipeline completa)
    py -3 deutschops.py lezione --auto          elabora i video non ancora fatti
    py -3 deutschops.py studia            l'app di studio (browser, localhost)
    py -3 deutschops.py briefing          il riquadro di avvio (lo chiama l'hook)
    py -3 deutschops.py stato             rigenera stato/stato-tedesco.md
    py -3 deutschops.py esame             gap analysis B2 (1 chiamata LLM)
    py -3 deutschops.py drill [-n 10]     esercizi dai tuoi errori reali
    py -3 deutschops.py esercizi --coda   su cosa si allenerebbe l'app, e perche'
    py -3 deutschops.py frasi [-n 20]     frasi i+1 dai transcript (gratis)
    py -3 deutschops.py carte <data>      carica le carte di una lezione in Anki
    py -3 deutschops.py vocabolario       backfill traduzioni inglesi delle frasi d'esempio
    py -3 deutschops.py libro [-n 15]     OCR del Kursbuch, a lotti (abbonamento, riprendibile)
    py -3 deutschops.py anki-audit        difetti del mazzo
    py -3 deutschops.py anki-ripara       li corregge da fonti verificabili
    py -3 deutschops.py ponte             check verso il motore condiviso
    py -3 deutschops.py pendenti          lezioni con run non completati
    py -3 deutschops.py confronta <data>  rielabora e confronta col vecchio (S1)
"""

from __future__ import annotations

import argparse
import json
import os
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
    # Vale per ogni sottocomando: e' la scelta di CHI paga, non di cosa si fa.
    # `claude` passa da Claude Code in modalita' non interattiva e il conto va
    # sull'abbonamento invece che sui token API.
    ap.add_argument("--motore", choices=("anthropic", "claude", "ollama"),
                    default=None, metavar="NOME",
                    help="anthropic (a consumo) | claude (abbonamento) | ollama (locale). "
                         "Senza questo flag vale LLM_BACKEND in .env.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("motore", help="quale backend LLM e' attivo, e una prova che risponde")

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

    p = sub.add_parser("studia", help="l'app di studio nel browser")
    p.add_argument("--porta", type=int, default=7800)
    p.add_argument("--non-aprire", action="store_true",
                   help="avvia il server senza aprire il browser")

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

    p = sub.add_parser("componi", help="frasi costruite, quando il corpus non basta")
    p.add_argument("-n", type=int, default=24)

    p = sub.add_parser("esercizi", help="ricarica il deposito dell'allenamento")
    p.add_argument("-n", type=int, default=20)
    p.add_argument("--coda", action="store_true",
                   help="mostra solo su cosa si allenerebbe, senza generare")
    p.add_argument("--traduci", action="store_true",
                   help="aggiunge la traduzione a chi ne e' privo, senza generare")
    p.add_argument("--libreria", type=int, metavar="N",
                   help="costruisce N esercizi in piu' chiamate, su tutta la coda")
    p.add_argument("--tetto", type=float, default=None, metavar="EUR",
                   help="con --libreria: si ferma superata questa spesa misurata")
    p.add_argument("--verifica", action="store_true",
                   help="controlla che traduzione, glossa e soluzione concordino")

    p = sub.add_parser("vocabolario", help="backfill traduzioni inglesi delle frasi d'esempio")
    p.add_argument("-n", type=int, default=80, metavar="N",
                   help="quanti vocaboli tradurre in questo lotto")

    p = sub.add_parser("libro", help="OCR del Kursbuch, a lotti (abbonamento)")
    p.add_argument("-n", type=int, default=15, metavar="N",
                   help="quante pagine fare in questo lotto")
    p.add_argument("--fonte", choices=("kursbuch", "book_transcriptions", "transkriptionen_a1"),
                   default=None, help="limita il lotto a una sola fonte")
    p.add_argument("--risolvi-tracce", action="store_true",
                   help="collega le pagine con icona audio alle trascrizioni gia' OCR'ate, poi esce")

    p = sub.add_parser("carte", help="carica le carte di una lezione in Anki")
    p.add_argument("data", help="es. 2026-07-23-stefanie")
    p.add_argument("--prova", action="store_true", help="non tocca Anki")

    p = sub.add_parser("doc-immagini",
                       help="scarica in locale le immagini del Doc di Stefanie")
    p.add_argument("--forza", action="store_true", help="riscarica anche quelle gia' salvate")

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

    # Prima di qualunque import che costruisca una LLMConfig: llm_config()
    # legge LLM_BACKEND dall'ambiente, quindi il flag si applica scrivendolo li'.
    if a.motore:
        os.environ["LLM_BACKEND"] = a.motore

    # ------------------------------------------------------------------
    if a.cmd == "motore":
        import time

        from do.base.config import CLAUDE_CLI, llm_config
        from do.base.llm import chiama

        cfg = llm_config()
        paga = {"anthropic": "token API, a consumo",
                "claude": f"abbonamento Claude Code ({CLAUDE_CLI})",
                "ollama": f"locale ({cfg.ollama_host})"}[cfg.backend]
        print(f"\n  backend  : {cfg.backend}  —  {paga}")
        print(f"  modello  : {cfg.model}")
        t = time.time()
        try:
            testo, uso = chiama("Reply with the single German word only. No article.",
                                "German for 'bridge'?", cfg)
        except Exception as e:
            print(f"\n  NON RISPONDE: {e}\n")
            return 1
        ok = "Brücke" in testo
        print(f"  prova    : {testo.strip()[:60]!r}  {'ok' if ok else '<- inatteso'}")
        print(f"  token    : in={uso.input_tokens} out={uso.output_tokens}")
        print(f"  addebito : {uso.costo_eur:.4f} EUR", end="")
        print(f"   (a consumo sarebbero {uso.costo_nozionale_eur:.4f} EUR)"
              if uso.costo_nozionale_eur else "")
        print(f"  durata   : {time.time() - t:.1f} s\n")
        return 0 if ok else 1

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

    elif a.cmd == "studia":
        from do.uscite import web
        return web.avvia(porta=a.porta, apri=not a.non_aprire)

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

    elif a.cmd == "componi":
        from do.studio import composte
        r = composte.componi(a.n)
        print(f"\n  {r['aggiunte']}/{r['chieste']} frasi aggiunte "
              f"| {r['in_deposito']} in deposito "
              f"| {r['costo_eur']:.4f} EUR"
              f"{' (stimato)' if r['costo_stimato'] else ''}\n")

    elif a.cmd == "esercizi":
        from do.studio import allenamento

        if a.coda:
            voci = allenamento.coda(a.n)
            pronti = len(allenamento.disponibili())
            chiuse = len(allenamento.padroneggiate())
            print(f"\n  {len(voci)} in coda | {pronti} esercizi pronti "
                  f"| {chiuse} regole chiuse\n")
            for v in voci:
                print(f"  [{v['livello']}] {v['motivo']:<34s} {v['regola'][:44]}")
            print()
            return 0

        if a.verifica:
            r = allenamento.verifica()
            print(f"\n  {r['controllati']} controllati | {r['rotti']} incoerenti "
                  f"| {r['costo_eur']:.4f} EUR")
            print(f"     {r.get('pronti', 0)} pronti da servire\n")
            return 0

        if a.libreria:
            print(f"\n  Costruisco {a.libreria} esercizi. Ogni blocco si salva "
                  f"appena arriva: interrompere non perde il fatto.\n")
            r = allenamento.libreria(a.libreria, al_massimo=a.tetto)
            print(f"\n  {r['generati']} generati in {r['blocchi']} blocchi "
                  f"| {r['costo_eur']:.4f} EUR misurati")
            if r["falliti"]:
                print(f"     {r['falliti']} blocchi falliti: {r['motivi']}")
            print(f"     {r['in_deposito']} in deposito · {r['pronti']} pronti\n")
            return 0

        if a.traduci:
            r = allenamento.traduci(a.n)
            print(f"\n  {r['tradotti']}/{r.get('chiesti', 0)} tradotti "
                  f"| {r['costo_eur']:.4f} EUR"
                  f"{' (stimato)' if r['costo_stimato'] else ''}")
            print(f"     {len(allenamento.disponibili())} pronti da servire\n")
            return 0

        r = allenamento.prepara(a.n)
        print(f"\n  {r['aggiunti']}/{r['chiesti']} esercizi aggiunti "
              f"| {r['in_deposito']} in deposito "
              f"| {r['costo_eur']:.4f} EUR"
              f"{' (stimato)' if r['costo_stimato'] else ''}")
        for motivo, n in r["motivi"]:
            print(f"     {n} scartati: {motivo}")
        print(f"     {len(allenamento.disponibili())} pronti da servire\n")

    elif a.cmd == "vocabolario":
        from do.sapere import vocaboli
        r = vocaboli.backfill_example_en(a.n)
        print(f"\n  {r['tradotti']} tradotti | {r['rimasti']} rimasti "
              f"| {r['file_toccati']} lezioni toccate "
              f"| {r['costo_eur']:.4f} EUR")
        if r["rimasti"]:
            print("  Rilancia lo stesso comando per continuare il lotto successivo.\n")
        else:
            print()

    elif a.cmd == "libro":
        from do.sapere import libro

        if a.risolvi_tracce:
            r = libro.risolvi_tracce()
            print(f"\n  {r['tracce_trovate']} tracce trovate nelle trascrizioni "
                  f"| {r['pagine_collegate']} pagine collegate\n")
            return 0

        st = libro.stato()
        for nome, s in st.items():
            bandiera = "" if s["presente"] else "  (file non trovato)"
            print(f"  {nome:22s} {s['fatte']:4d}/{s['totali']:4d}{bandiera}")

        r = libro.estrai(a.n, fonte=a.fonte)
        if r["fatte"] == 0 and r["rimaste"] == 0:
            print("\n  Niente da fare: tutte le pagine sono gia' OCR'ate.\n")
            return 0
        print(f"\n  {r['fatte']} pagine fatte in questo lotto "
              f"| {r['falliti']} fallite | {r['rimaste']} rimaste su {r['totale_pagine']}")
        if r["costo_nozionale_eur"]:
            print(f"  ~{r['costo_nozionale_eur']:.2f} EUR nozionali (abbonamento: 0 in fattura)")
        if r["fermato_da_quota"]:
            print("  Fermato dalla quota dell'abbonamento — rilancia lo stesso comando piu' tardi.")
        elif r["rimaste"]:
            print("  Rilancia lo stesso comando per il lotto successivo "
                  "(pensato per piu' sessioni — vedi CLAUDE.md).")
        print()

    elif a.cmd == "carte":
        from do.studio import carte
        lez = _lezione_json(a.data)
        r = carte.alimenta(lez.get("vocabulary", []), a.data, prova=a.prova)
        print(json.dumps(r, ensure_ascii=False, indent=2))

    elif a.cmd == "doc-immagini":
        from do.lezione import doc

        r = doc.salva_immagini(forza=a.forza)
        print(f"\n  {r['nel_doc']} immagini nel Doc")
        print(f"     {r['scaricate']:4d} scaricate ora")
        print(f"     {r['gia_presenti']:4d} gia' in locale")
        if r["senza_uri"]:
            print(f"     {r['senza_uri']:4d} senza contentUri (disegni o incorporate)")
        if r["fallite"]:
            print(f"     {r['fallite']:4d} FALLITE")
        print(f"  -> {r['cartella']}")

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

        # Deck a parte, controllo a parte: vedi manutenzione.analizza_cloze().
        schede_cloze = manutenzione.analizza_cloze()
        rc = manutenzione.ripara_cloze(schede_cloze, prova=True)
        print(f"\n  Cloze: {rc['note']} carte | {rc['da_aggiornare']} senza traduzione "
              f"(riparabili ora) | {rc['gia_a_posto']} gia' a posto")
        if rc["senza_traduzione_disponibile"]:
            print(f"     {rc['senza_traduzione_disponibile']} in attesa del backfill: "
                  f"'deutschops.py vocabolario'")

    elif a.cmd == "anki-ripara":
        from do.studio import manutenzione
        schede, _ = manutenzione.analizza()
        r = manutenzione.ripara(schede, prova=not a.applica)
        if not a.applica:
            print("  PROVA A SECCO — rilancia con --applica per scrivere davvero\n")
        for k, n in r["dettaglio"]:
            print(f"   {n:6d}  {k}")

        schede_cloze = manutenzione.analizza_cloze()
        rc = manutenzione.ripara_cloze(schede_cloze, prova=not a.applica)
        print(f"\n  Cloze: {rc['da_aggiornare']} da aggiornare "
              f"| {rc['gia_a_posto']} gia' a posto "
              f"| {rc['senza_traduzione_disponibile']} senza traduzione disponibile")
        if a.applica:
            print(f"     {rc.get('applicate', 0)} applicate")

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
