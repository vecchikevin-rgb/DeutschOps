"""L'orchestratore della lezione. Sostituisce main.py.

COSA RESTA IDENTICO (ed e' la parte migliore del progetto)
L'architettura di degradazione della v1 e' matura e non si tocca:

  Anki chiuso        -> la fase non viene marcata, il task resta aperto,
                        al prossimo run riparte da li'.
  Token Google morto -> lo step Doc degrada a stringa vuota e la lezione
                        prosegue: il diff e' contesto ausiliario, non un
                        requisito.
  Snapshot del Doc   -> commit DIFFERITO. Si scrive solo a pipeline completa,
                        altrimenti un fallimento a meta' lascerebbe il
                        confronto puntato a un documento gia' aggiornato e il
                        diff andrebbe perso per sempre.
  Fase completata    -> non si rifa' mai. E' cio' che ha salvato i run
                        interrotti a meta' trascrizione.

COSA CAMBIA
1. `generate_astra_prompts()` non c'e' piu'. Era l'UNICO step post-pipeline
   non protetto da try/except (main.py:252) e rigenerava tutti e 31 i PDF a
   ogni lezione. Astra non e' mai esistito come integrazione: nessun astrapy,
   nessuna credenziale, nessun retrieval. Vedi §1.4 del piano.
2. NotebookLM non c'e' piu'. Chiuso il 2026-07-26.
3. Il costo LLM e' quello misurato, non `claude_cost = 0.10`.
4. Le carte Anki passano da do/studio/carte.py: tre direzioni invece di una.
5. Il quaderno errori gira DENTRO la pipeline, non come coda opzionale.

L'ORDINE DEGLI STEP E' QUELLO VECCHIO, DI PROPOSITO
Doc -> trascrizione -> estrazione -> Anki -> PDF -> riepilogo. Cambiarlo
mentre si migra significherebbe non poter piu' dire se una differenza
nell'output viene dal codice nuovo o dall'ordine nuovo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from ..base import preflight, staging
from ..base.paths import DATA, TRANSCRIPTS, ensure_dirs
from ..base.tracker import Task
from ..sapere import errori, grammatica, registro, vocaboli
from . import audio, doc, estrazione


@dataclass
class Esito:
    data_lezione: str
    json: Path | None = None
    pdf: Path | None = None
    transcript: Path | None = None
    anki: dict = field(default_factory=dict)
    costo_eur: float = 0.0
    minuti: float = 0.0
    completa: bool = False
    saltati: list[str] = field(default_factory=list)


def _titolo(t: str) -> None:
    print(f"\n{t}\n" + "-" * 30)


def elabora(sorgente: str | Path, data_lezione: str | None = None,
            *, salta_doc: bool = False) -> Esito:
    """Elabora una lezione dall'inizio alla fine. Riprendibile."""
    ensure_dirs()
    data_lezione = data_lezione or date.today().isoformat()
    nome = f"lezione_{data_lezione}"
    esito = Esito(data_lezione=data_lezione)

    print(f"\n{'=' * 60}\n  DeutschOps — lezione {data_lezione}\n{'=' * 60}")

    # Il path com'e' stato passato: e' l'input consumato da archiviare a fine
    # run. Va catturato ORA, prima che `prepara` lo riassegni al compresso.
    input_originale = str(sorgente)
    task = Task(data_lezione)

    staging.pulisci_scaduti()
    percorso, _diagnosi = preflight.esegui(str(sorgente))

    _titolo("PREP — audio")
    percorso = audio.prepara(percorso, data_lezione)

    try:
        # ---------------------------------------------------------- 1. Doc
        _titolo("1/6 — Google Doc di Stefanie")
        doc_nuovo = ""
        if salta_doc:
            print("   Saltato su richiesta (--senza-doc).")
            esito.saltati.append("doc")
        elif task.fatta("doc"):
            print("   Gia' fatto in un run precedente — riuso il diff.")
            doc_nuovo = task.risultato("doc").get("nuovo", "")
        else:
            try:
                lettura = doc.leggi_e_confronta(etichetta=f"pre_{data_lezione}")
                doc_nuovo = lettura.nuovo
                task.salva_fase("doc", {"nuovo": doc_nuovo})
                # Snapshot solo a fine pipeline, e solo se il doc e' cambiato.
                if not lettura.identico_al_precedente:
                    task.differisci("snapshot", {"path": str(lettura.snapshot),
                                                 "contenuto": lettura.testo})
            except Exception as e:                          # noqa: BLE001
                # Non marchiamo la fase: un rilancio con token valido la
                # ritentera'. La lezione prosegue senza contesto dal Doc.
                print(f"   Saltato (token Google?): {str(e)[:80]}")
                esito.saltati.append("doc")

        # ---------------------------------------------------- 2. trascrizione
        _titolo("2/6 — trascrizione")
        t = audio.trascrivi(percorso, nome)
        esito.transcript = t.percorso
        esito.minuti = t.minuti
        task.salva_fase("transcript", {"path": str(t.percorso)})

        # ------------------------------------------------------ 3. estrazione
        _titolo("3/6 — estrazione")
        dati, costo_llm = estrazione.estrai(t.percorso, nome, doc_nuovo=doc_nuovo)
        esito.json = DATA / f"{nome}.json"
        esito.costo_eur = costo_llm
        task.salva_fase("estrazione", {"path": str(esito.json)})

        # ------------------------------------------------------------ 4. Anki
        _titolo("4/6 — Anki")
        if task.fatta("anki"):
            print("   Gia' fatto in un run precedente.")
        else:
            from ..studio import carte

            try:
                esito.anki = carte.alimenta(dati.get("vocabulary", []), data_lezione)
                task.salva_fase("anki", esito.anki)
            except RuntimeError as e:
                # Anki chiuso. NON marchiamo la fase: il task resta aperto e al
                # prossimo run riparte da qui. La lezione continua: PDF,
                # riepilogo e database non dipendono da Anki.
                print(f"   {e}")
                esito.saltati.append("anki")

        # ------------------------------------------------------------- 5. PDF
        _titolo("5/6 — PDF")
        from ..uscite import pdf as uscite_pdf

        esito.pdf = uscite_pdf.lezione(nome)
        task.salva_fase("pdf", {"path": str(esito.pdf)})

        # -------------------------------------- 6. riepilogo, DB, errori
        _titolo("6/6 — riepilogo, database, quaderno errori")
        if not task.fatta("doc_update"):
            if not salta_doc:
                try:
                    doc.aggiorna_riepilogo(esito.json, data_lezione, esito.pdf)
                except Exception as e:                      # noqa: BLE001
                    print(f"   Riepilogo sul Doc non riuscito: {str(e)[:80]}")
                    esito.saltati.append("riepilogo-doc")

                # Le immagini che Stefanie aggiunge al Doc non stanno da
                # nessun'altra parte: l'export .docx del documento non puo'
                # riuscire (troppo grande per Drive) e gli snapshot salvano
                # solo il testo. Qui si scaricano una per una — incrementale,
                # quindi dopo la prima volta scende a zero o poche.
                try:
                    im = doc.salva_immagini()
                    if im["scaricate"]:
                        print(f"   Immagini dal Doc: +{im['scaricate']} nuove "
                              f"({im['nel_doc']} totali)")
                except Exception as e:                      # noqa: BLE001
                    print(f"   Immagini dal Doc non salvate: {str(e)[:80]}")
                    esito.saltati.append("immagini-doc")

            vocaboli.aggiorna_da_lezione(dati, data_lezione)
            if grammatica.aggiorna_da_lezione(dati):
                try:
                    uscite_pdf.libro_grammatica()
                except Exception as e:                      # noqa: BLE001
                    print(f"   Libro grammatica non rigenerato: {str(e)[:80]}")

            try:
                _err, costo_err = errori.aggiorna_da_lezione(t.percorso, data_lezione)
                esito.costo_eur += costo_err
                uscite_pdf.quaderno_errori()
            except Exception as e:                          # noqa: BLE001
                print(f"   Quaderno errori non aggiornato: {str(e)[:80]}")
                esito.saltati.append("quaderno-errori")

            registro.registra(
                data_lezione=data_lezione,
                audio=str(percorso),
                dati=dati,
                costo_trascrizione=t.costo_eur,
                costo_llm=esito.costo_eur,
                minuti=t.minuti,
                costo_stimato=False,
            )
            task.salva_fase("doc_update", {})

        # ------------------------------------------------------ commit finale
        nucleo = ["transcript", "estrazione", "pdf", "doc_update"]
        esito.completa = all(task.fatta(f) for f in nucleo) and task.fatta("anki")

        if esito.completa:
            task.chiudi(handler={"snapshot": _scrivi_snapshot})
            _titolo("ARCHIVIO — input consumato")
            staging.archivia([input_originale])
        else:
            # Lo snapshot si scrive comunque: il doc E' stato letto e usato.
            # Tenerlo differito significherebbe rileggere lo stesso diff al
            # rilancio e riproporre righe gia' elaborate.
            if task.ha_differito("snapshot"):
                _scrivi_snapshot(task.dati["differiti"]["snapshot"])
                task.dati["differiti"].pop("snapshot", None)
                task._flush()
            print("   Task lasciato aperto: manca Anki.")

    except Exception as e:
        task.interrompi(str(e))
        raise

    _riepilogo(esito)
    return esito


def _scrivi_snapshot(payload: dict) -> None:
    doc.scrivi_snapshot(Path(payload["path"]), payload["contenuto"])


def _riepilogo(e: Esito) -> None:
    print(f"\n{'=' * 60}")
    print(f"  Lezione {e.data_lezione} — {'completa' if e.completa else 'INCOMPLETA'}")
    print(f"  Transcript : {e.transcript}")
    print(f"  Dati       : {e.json}")
    print(f"  PDF        : {e.pdf}")
    if e.anki:
        print(f"  Anki       : {e.anki.get('aggiunte', 0)} carte su "
              f"{e.anki.get('proposte', 0)} proposte "
              f"({e.anki.get('duplicate', 0)} gia' presenti)")
    print(f"  Costo LLM  : {e.costo_eur:.4f} EUR (misurato)")
    if e.saltati:
        print(f"  Saltati    : {', '.join(e.saltati)}")
    print(f"{'=' * 60}\n")


# --------------------------------------------------------------------- rileva
# Rinasce watch.py, con il pattern che funziona. Il vecchio cercava
# "Classroom with Stefanie*.mp4"; i file oggi si chiamano
# "Deutsch mit Kevin - 2026_07_22...". Stampava sempre "nessuna lezione nuova".
def da_elaborare() -> list[Path]:
    """Video in Audiolessons/ senza un transcript corrispondente."""
    from ..base.paths import AUDIO

    fatte = {p.stem.replace("lezione_", "") for p in TRANSCRIPTS.glob("lezione_*.txt")}
    fuori: list[Path] = []
    for f in sorted(AUDIO.iterdir()):
        if not f.is_file() or not audio.e_video(f) or "-compressed" in f.stem:
            continue
        if not any(d in f.stem for d in fatte) and not any(
            _data_dal_nome(f.stem) and _data_dal_nome(f.stem) in d for d in fatte
        ):
            fuori.append(f)
    return fuori


def _data_dal_nome(stem: str) -> str | None:
    """Estrae una data ISO da un nome tipo `Deutsch mit Kevin - 2026_07_22`."""
    import re

    m = re.search(r"(20\d{2})[-_](\d{2})[-_](\d{2})", stem)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None
