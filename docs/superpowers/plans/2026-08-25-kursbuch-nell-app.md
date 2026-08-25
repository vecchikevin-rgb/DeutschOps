# Il Kursbuch nell'app di studio — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Portare il Kursbuch (già trascritto e risolto all'86%, 629/730 esercizi) dentro l'app di studio: una zona "Kursbuch" per sfogliarlo per Lektion, la zona "Listening" (oggi un placeholder vuoto) riempita dai suoi esercizi audio, e un puntatore dalla gap analysis Exam a dove nel libro studiare una regola mancante.

**Architecture:** Il dato esiste già in `data/libro_pagine.json` (364 pagine OCR'ate, gestite da `do/sapere/libro.py`). Questo piano aggiunge: (1) funzioni di aggregazione per Lektion in `libro.py`, (2) endpoint JSON in `do/uscite/web.py` che le espongono, (3) due zone nuove/completate in `web/app.js` che le consumano. Nessun nuovo store di dati per i tentativi — si riusa `do/studio/sessione.py:annota_risposta()`, già generico.

**Tech Stack:** Python 3.14 stdlib (`http.server`), vanilla JS (nessun framework, nessuna build), PyMuPDF per il rendering pagina (già dipendenza).

**Spec:** `docs/superpowers/specs/2026-08-24-libro-app-integration-design.md` — leggilo prima di iniziare, questo piano lo argomenta in task ma non ripete il "perché".

## Global Constraints

- **Backend LLM per lavoro a lotti = sempre `backend="claude"` esplicito**, mai delegato a `--motore`/`LLM_BACKEND`. Vedi CLAUDE.md "Chi paga" e il pattern già in `libro.py` (`llm_config(backend="claude")` in `risolvi_esercizi`, `associa_tracce_esercizi`).
- **Mai `py -3`** per questo progetto — usa sempre `venv\Scripts\python.exe` (Windows) risolto con path assoluto. Su questa macchina `py -3` gira sul Python di sistema, senza le dipendenze del progetto.
- **`PYTHONIOENCODING=utf-8`** prima di ogni comando `deutschops.py` da terminale — la console Windows rompe altrimenti su umlaut.
- **Server locale, solo 127.0.0.1**: nessun endpoint nuovo deve cambiare questo — vedi il vincolo già scritto in cima a `do/uscite/web.py`.
- **Degradazione, mai crash**: ogni endpoint nuovo segue il pattern esistente in `web.py` — un `try/except` nel router che torna `{"errore": ...}` con status 500, mai un'eccezione che rompe il server.
- **Codice e commit in italiano**, commenti solo dove il PERCHÉ non è ovvio dal codice — stile già stabilito in tutto il repo, non introdurre commenti che spiegano il COSA.
- **Niente browser disponibile in sessione headless**: ogni task backend si verifica con chiamate HTTP dirette (`urllib`/`curl`), non assumere un browser. I task frontend (7-9) vanno verificati a occhio in browser quando disponibile — dillo esplicitamente nel commit se non è stato possibile.

---

## Prerequisiti prima di iniziare

Il lavoro precedente vive sul branch `worktree-deutschops-libro-cloze`, pushato su `origin` (repo `vecchikevin-rgb/DeutschOps`). Prima di aprire il primo task:

```bash
git fetch origin
git checkout worktree-deutschops-libro-cloze
git pull
```

Verifica che `data/libro_pagine.json` esista e abbia contenuto (è gitignored, quindi non arriva col checkout — deve già esistere nella cartella di lavoro da cui parti; se non c'è, il lavoro di OCR/risoluzione dei task precedenti non è disponibile e questo piano non ha dati su cui lavorare):

```bash
venv\Scripts\python.exe -c "import json; d=json.load(open('data/libro_pagine.json',encoding='utf-8')); print(len(d), 'pagine')"
```

Atteso: `364 pagine`. Se il file manca, fermati e chiedi all'utente dove trovare la cartella `data/` più recente prima di procedere — non generare dati nuovi da zero, il lavoro di OCR è già stato fatto e costa credito reale rifarlo.

---

### Task 1: `libro.lektioni()` e `libro.lektion(n)` — dati aggregati per Lektion

**Files:**
- Modify: `do/sapere/libro.py`
- Test: `tests/test_libro_lektioni.py` (nuovo file)

**Interfaces:**
- Produce: `lektioni() -> list[dict]` con chiavi `numero, titolo, livello, pagine, frasi, esercizi_totali, esercizi_risolti`.
- Produce: `lektion(numero: int) -> dict | None` con chiavi `numero, titolo, livello, pagine` (lista di dict pagina, ognuno con `chiave, tipo, testo, frasi, esercizi`).

- [ ] **Step 1: Scrivi il test che fallisce**

```python
# tests/test_libro_lektioni.py
import json
from pathlib import Path

import pytest

from do.sapere import libro


@pytest.fixture
def pagine_finte(monkeypatch, tmp_path):
    """Due pagine finte, Lektion 1 e Lektion 2, per non dipendere dal
    corpus vero (364 pagine, lento da caricare in un test)."""
    dati = {
        "kursbuch:10": {
            "fonte": "kursbuch", "indice": 10, "tipo": "vocabolario",
            "lezione": "1", "livello": "A1",
            "testo": "1 Alles auf einen Blick\nWortschatz...",
            "frasi": ["Ich komme aus der Schweiz."],
            "esercizi": [
                {"consegna": "Fill the gap", "stimolo": "Ich ___ aus der Schweiz.",
                 "soluzione": "komme"},
                {"consegna": "Fill the gap", "stimolo": "Du ___ Deutsch.",
                 "soluzione": ""},  # non risolto
            ],
        },
        "kursbuch:25": {
            "fonte": "kursbuch", "indice": 25, "tipo": "esercizio",
            "lezione": "2", "livello": "A1",
            "testo": "2 Alltag\nÜbungen...",
            "frasi": [], "esercizi": [
                {"consegna": "Fill the gap", "stimolo": "Er ___ jeden Tag.",
                 "soluzione": "arbeitet"},
            ],
        },
    }
    p = tmp_path / "libro_pagine.json"
    p.write_text(json.dumps(dati), encoding="utf-8")
    monkeypatch.setattr(libro, "LIBRO_PAGINE", p)
    return dati


def test_lektioni_aggrega_per_numero(pagine_finte):
    out = libro.lektioni()
    numeri = [l["numero"] for l in out]
    assert numeri == [1, 2]  # ordinate


def test_lektioni_conta_esercizi_risolti(pagine_finte):
    out = libro.lektioni()
    l1 = next(l for l in out if l["numero"] == 1)
    assert l1["esercizi_totali"] == 2
    assert l1["esercizi_risolti"] == 1


def test_lektioni_titolo_dalla_prima_riga(pagine_finte):
    out = libro.lektioni()
    l1 = next(l for l in out if l["numero"] == 1)
    assert l1["titolo"] == "Alles auf einen Blick"


def test_lektion_dettaglio_pagine_in_ordine(pagine_finte):
    d = libro.lektion(1)
    assert d is not None
    assert d["numero"] == 1
    assert len(d["pagine"]) == 1
    assert d["pagine"][0]["chiave"] == "kursbuch:10"


def test_lektion_inesistente_torna_none(pagine_finte):
    assert libro.lektion(99) is None
```

- [ ] **Step 2: Esegui il test, verifica che fallisca**

Run: `venv\Scripts\python.exe -m pytest tests/test_libro_lektioni.py -v`
Expected: FAIL — `AttributeError: module 'do.sapere.libro' has no attribute 'lektioni'`

- [ ] **Step 3: Implementa**

In `do/sapere/libro.py`, aggiungi dopo `esporta_markdown()` (in fondo alla
sezione export, prima di `# --------------------------------------------------------------------- ricerca`):

```python
# --------------------------------------------------------------------- Lektionen
_INTESTAZIONE_LEKTION = re.compile(r"^\s*\d{1,2}\s+(.+)$")


def _titolo_lektion(testo: str) -> str:
    """La prima riga sostanziosa dopo il numero della Lektion, es. "27
    Geschichten und Gesichter Berlins" -> "Geschichten und Gesichter Berlins".
    Euristica, non garanzia: se non trova nulla torna stringa vuota, mai
    un titolo inventato."""
    for riga in (testo or "").splitlines():
        riga = riga.strip()
        if not riga:
            continue
        if m := _INTESTAZIONE_LEKTION.match(riga):
            return m.group(1).strip()
        break  # la prima riga non vuota non era un'intestazione: fermati
    return ""


def lektioni() -> list[dict]:
    """Le Lektionen del Kursbuch aggregate dalle pagine OCR, in ordine.

    Il numero di Lektion e' gia' un campo per pagina (`lezione`, scritto
    dall'OCR — vedi SISTEMA_OCR). Qui si raggruppa, non si inventa nulla:
    una pagina senza `lezione` valorizzato (indice, copertina, appendice)
    non entra in nessuna Lektion.
    """
    per_numero: dict[int, list[dict]] = {}
    for chiave, pag in _carica().items():
        if pag.get("fonte") != "kursbuch":
            continue
        n = str(pag.get("lezione") or "").strip()
        if not n.isdigit():
            continue
        per_numero.setdefault(int(n), []).append(pag)

    fuori = []
    for numero in sorted(per_numero):
        pagine = per_numero[numero]
        livelli = [p.get("livello") for p in pagine if p.get("livello")]
        esercizi = [e for p in pagine for e in p.get("esercizi", [])]
        fuori.append({
            "numero": numero,
            "titolo": next((t for p in pagine if (t := _titolo_lektion(p.get("testo", "")))), ""),
            "livello": max(livelli, key=livelli.count) if livelli else "",
            "pagine": len(pagine),
            "frasi": sum(len(p.get("frasi", [])) for p in pagine),
            "esercizi_totali": len(esercizi),
            "esercizi_risolti": sum(1 for e in esercizi if (e.get("soluzione") or "").strip()),
        })
    return fuori


def lektion(numero: int) -> dict | None:
    """Il dettaglio completo di una Lektion, o None se non esiste."""
    pagine = []
    for chiave, pag in sorted(_carica().items(), key=lambda kv: kv[1].get("indice", 0)):
        if pag.get("fonte") != "kursbuch":
            continue
        n = str(pag.get("lezione") or "").strip()
        if n.isdigit() and int(n) == numero:
            pagine.append({
                "chiave": chiave,
                "tipo": pag.get("tipo", ""),
                "testo": pag.get("testo", ""),
                "frasi": pag.get("frasi", []),
                "esercizi": pag.get("esercizi", []),
            })
    if not pagine:
        return None

    riepilogo = next((l for l in lektioni() if l["numero"] == numero), {})
    return {
        "numero": numero,
        "titolo": riepilogo.get("titolo", ""),
        "livello": riepilogo.get("livello", ""),
        "pagine": pagine,
    }
```

- [ ] **Step 4: Esegui il test, verifica che passi**

Run: `venv\Scripts\python.exe -m pytest tests/test_libro_lektioni.py -v`
Expected: 5 passed

- [ ] **Step 5: Verifica contro il corpus vero (non il test, un controllo a occhio)**

```bash
venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'.'); from do.sapere import libro; l = libro.lektioni(); print(len(l), 'Lektionen'); print(l[0]); print(l[-1])"
```

Atteso: 30 Lektionen (o vicino — dipende da quante hanno almeno una pagina
con `lezione` valorizzato), la prima con titolo plausibile tipo "Alles auf
einen Blick".

- [ ] **Step 6: Commit**

```bash
git add do/sapere/libro.py tests/test_libro_lektioni.py
git commit -m "feat: aggregazione libro per Lektion (lektioni/lektion)"
```

---

### Task 2: `libro.pagina_cachata()` — rendering pagina con cache su disco

**Files:**
- Modify: `do/sapere/libro.py`
- Test: `tests/test_libro_pagina_cachata.py` (nuovo file)

**Interfaces:**
- Consuma: `FONTI` (già esistente, tupla `(nome, path_pdf)`), `_rendi_pagina(pdf, indice, cartella)` (già esistente).
- Produce: `pagina_cachata(fonte: str, indice: int) -> Path | None` — path del PNG, `None` se la fonte non esiste o l'indice è fuori range.

- [ ] **Step 1: Scrivi il test che fallisce**

```python
# tests/test_libro_pagina_cachata.py
from pathlib import Path

import pytest

from do.sapere import libro


def test_fonte_sconosciuta_torna_none():
    assert libro.pagina_cachata("non-esiste", 0) is None


def test_indice_fuori_range_torna_none():
    # kursbuch ha 307 pagine: 99999 non esiste
    assert libro.pagina_cachata("kursbuch", 99999) is None


def test_pagina_valida_produce_un_file_reale(tmp_path, monkeypatch):
    monkeypatch.setattr(libro, "BOOK", libro.BOOK)  # nessun cambio, per chiarezza
    cartella_cache = tmp_path / "pagine_render"
    monkeypatch.setattr(libro, "_CARTELLA_RENDER", cartella_cache)

    path = libro.pagina_cachata("kursbuch", 0)
    assert path is not None
    assert path.exists()
    assert path.suffix == ".png"
    assert path.stat().st_size > 1000  # non un file vuoto/corrotto


def test_seconda_chiamata_riusa_la_cache(tmp_path, monkeypatch):
    cartella_cache = tmp_path / "pagine_render"
    monkeypatch.setattr(libro, "_CARTELLA_RENDER", cartella_cache)

    p1 = libro.pagina_cachata("kursbuch", 0)
    mtime1 = p1.stat().st_mtime
    p2 = libro.pagina_cachata("kursbuch", 0)
    assert p1 == p2
    assert p2.stat().st_mtime == mtime1  # non ri-renderizzata
```

- [ ] **Step 2: Esegui il test, verifica che fallisca**

Run: `venv\Scripts\python.exe -m pytest tests/test_libro_pagina_cachata.py -v`
Expected: FAIL — `AttributeError: module 'do.sapere.libro' has no attribute 'pagina_cachata'`

- [ ] **Step 3: Implementa**

In `do/sapere/libro.py`, subito dopo la definizione di `_rendi_pagina()`
(cerca `def _rendi_pagina` — è nella sezione OCR, vicino a `FONTI`):

```python
# Cache su disco delle pagine renderizzate: l'app le richiede spesso (ogni
# apertura di una Lektion), non ha senso ri-renderizzare la stessa pagina a
# ogni richiesta. Dentro Book/, quindi fuori da git per lo stesso motivo del
# resto del libro (copyright).
_CARTELLA_RENDER = BOOK / "pagine_render"


def pagina_cachata(fonte: str, indice: int) -> Path | None:
    """Il PNG della pagina, renderizzato una volta sola e riusato dopo.

    None se la fonte non esiste o l'indice e' fuori range — mai un'eccezione
    che l'endpoint web dovrebbe intercettare per conto suo.
    """
    fonti = dict(FONTI)
    pdf = fonti.get(fonte)
    if not pdf or not pdf.exists():
        return None

    _CARTELLA_RENDER.mkdir(parents=True, exist_ok=True)
    out = _CARTELLA_RENDER / f"{fonte}_{indice:04d}.png"
    if out.exists():
        return out

    try:
        if indice < 0 or indice >= _pagine_totali(pdf):
            return None
        immagine = _rendi_pagina(pdf, indice, _CARTELLA_RENDER)
    except Exception:                                        # noqa: BLE001
        return None
    # _rendi_pagina scrive gia' col nome atteso da _CARTELLA_RENDER/pagina_NNNN.png
    # (usato per l'OCR temporaneo) — qui serve il nome namespaced per fonte,
    # quindi si rinomina invece di duplicare la logica di rendering.
    immagine.replace(out)
    return out
```

**Nota per l'esecutore:** controlla la firma reale di `_rendi_pagina()` prima
di scrivere questo — se nel frattempo e' cambiata (accetta gia' un nome file
esplicito, per esempio), adatta la chiamata invece di duplicarla. Non
copiare la logica di rendering qui: `pagina_cachata` deve chiamare
`_rendi_pagina`, non reimplementarla.

- [ ] **Step 4: Esegui il test, verifica che passi**

Run: `venv\Scripts\python.exe -m pytest tests/test_libro_pagina_cachata.py -v`
Expected: 4 passed (il primo run di `test_pagina_valida_produce_un_file_reale`
richiede qualche secondo — PyMuPDF apre e renderizza un PDF vero)

- [ ] **Step 5: Commit**

```bash
git add do/sapere/libro.py tests/test_libro_pagina_cachata.py
git commit -m "feat: cache su disco per il rendering pagina (pagina_cachata)"
```

---

### Task 3: `libro.classifica_lezioni_per_lektion()` — collegamento lezione↔Lektion

**Files:**
- Modify: `do/sapere/libro.py`
- Modify: `deutschops.py` (nuovo flag `libro --collega-lezioni`)
- Test: `tests/test_libro_classifica_lezioni.py` (nuovo file)

**Interfaces:**
- Produce: `classifica_lezioni_per_lektion(quante: int = 10) -> dict` — classifica un lotto di lezioni non ancora mappate, salva incrementale in `data/libro_lezioni_mappa.json`, ritorna `{"classificate": int, "rimaste": int, "costo_nozionale_eur": float}`.
- Produce: `lezioni_per_lektion(numero: int) -> list[dict]` — le lezioni collegate a una Lektion, lette dalla mappa già salvata (nessuna chiamata LLM).

- [ ] **Step 1: Scrivi il test che fallisce**

```python
# tests/test_libro_classifica_lezioni.py
import json

import pytest

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
```

- [ ] **Step 2: Esegui il test, verifica che fallisca**

Run: `venv\Scripts\python.exe -m pytest tests/test_libro_classifica_lezioni.py -v`
Expected: FAIL — `AttributeError: module 'do.sapere.libro' has no attribute 'lezioni_per_lektion'`

- [ ] **Step 3: Implementa `lezioni_per_lektion` e il percorso dati**

In `do/base/paths.py`, aggiungi vicino a `LIBRO_PAGINE`:

```python
LIBRO_LEZIONI_MAPPA = DATA / "libro_lezioni_mappa.json"  # collegamento lezione<->Lektion, vedi do/sapere/libro.py
```

In `do/sapere/libro.py`, aggiorna l'import in cima:

```python
from ..base.paths import BOOK, LIBRO_LEZIONI_MAPPA, LIBRO_PAGINE
```

Poi, in fondo al file (dopo `pagina_cachata`), aggiungi:

```python
# --------------------------------------------------------------------- lezioni <-> Lektion
def _carica_mappa_lezioni() -> dict:
    try:
        return json.loads(LIBRO_LEZIONI_MAPPA.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def lezioni_per_lektion(numero: int) -> list[dict]:
    """Le lezioni vere con Stefanie collegate a questa Lektion, dalla mappa
    gia' costruita da `classifica_lezioni_per_lektion()`. Nessuna chiamata
    di rete: legge solo cio' che e' gia' salvato."""
    fuori = []
    for data_lezione, voci in _carica_mappa_lezioni().items():
        for v in voci:
            if isinstance(v, dict) and v.get("lektion") == numero:
                fuori.append({"data_lezione": data_lezione, "motivo": v.get("motivo", "")})
    return fuori
```

- [ ] **Step 4: Esegui il test, verifica che passi**

Run: `venv\Scripts\python.exe -m pytest tests/test_libro_classifica_lezioni.py -v`
Expected: 3 passed

- [ ] **Step 5: Implementa `classifica_lezioni_per_lektion` (il giro LLM)**

Ancora in `do/sapere/libro.py`, subito sotto `lezioni_per_lektion`:

```python
SISTEMA_CLASSIFICA_LEZIONE = """You match one German lesson to the course \
book Lektionen it overlaps with.

You get the lesson's topic and grammar points, and the titles of all 30 \
Lektionen (numbered). Pick 0-3 Lektionen that genuinely overlap in grammar \
or vocabulary theme — not every lesson matches something in an A1-B1 book \
(B2-only topics, free conversation, exam prep have no match, and that is a \
correct answer, not a failure).

Reply with valid JSON only, no backticks:
{"lektionen":[{"numero":<int>,"motivo":"<one short line: what overlaps>"}]}
Empty list if nothing genuinely overlaps."""


def classifica_lezioni_per_lektion(quante: int = 10) -> dict:
    """Classifica un lotto di lezioni non ancora mappate. Incrementale:
    rilanciare aggiunge solo le lezioni nuove.

    BACKEND ABBONAMENTO SEMPRE — lavoro a lotti su materiale storico, non un
    percorso interattivo. Vedi CLAUDE.md "Chi paga".
    """
    from ..base.config import llm_config
    from ..base.llm import chiama, estrai_json
    from ..base.paths import DATA

    mappa = _carica_mappa_lezioni()
    titoli = [f"{l['numero']}. {l['titolo']}" for l in lektioni() if l["titolo"]]
    if not titoli:
        return {"classificate": 0, "rimaste": 0, "costo_nozionale_eur": 0.0}

    da_fare = []
    for f in sorted(DATA.glob("lezione_*.json")):
        etichetta = f.stem.replace("lezione_", "")
        if etichetta in mappa:
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        da_fare.append((etichetta, d))

    if not da_fare:
        return {"classificate": 0, "rimaste": 0, "costo_nozionale_eur": 0.0}

    lotto = da_fare[:quante]
    nozionale = 0.0
    for etichetta, d in lotto:
        regole = "; ".join((g.get("rule") or "") for g in d.get("grammar_points", []))[:500]
        user = (
            f"LESSON TOPIC: {d.get('topic', '')}\n"
            f"GRAMMAR POINTS: {regole}\n\n"
            f"LEKTIONEN:\n" + "\n".join(titoli)
        )
        try:
            testo, uso = chiama(SISTEMA_CLASSIFICA_LEZIONE, user,
                                llm_config(max_tokens=1000, effort="low", backend="claude"))
            voci = [v for v in estrai_json(testo).get("lektionen", [])
                   if isinstance(v, dict) and isinstance(v.get("numero"), int)]
        except Exception as e:                              # noqa: BLE001
            print(f"   {etichetta}: {type(e).__name__}: {str(e)[:150]}")
            continue
        mappa[etichetta] = [{"lektion": v["numero"], "motivo": (v.get("motivo") or "")[:200]}
                            for v in voci]
        nozionale += uso.costo_nozionale_eur
        LIBRO_LEZIONI_MAPPA.parent.mkdir(parents=True, exist_ok=True)
        LIBRO_LEZIONI_MAPPA.write_text(json.dumps(mappa, ensure_ascii=False, indent=2),
                                       encoding="utf-8")

    return {"classificate": len(lotto), "rimaste": len(da_fare) - len(lotto),
            "costo_nozionale_eur": round(nozionale, 4)}
```

- [ ] **Step 6: Wire nella CLI**

In `deutschops.py`, trova il blocco `p = sub.add_parser("libro", ...)` e
aggiungi vicino agli altri flag `libro`:

```python
    p.add_argument("--collega-lezioni", type=int, nargs="?", const=10, default=None, metavar="N",
                   help="collega N lezioni non ancora mappate a una Lektion del libro, poi esce")
```

Poi nel blocco `elif a.cmd == "libro":`, vicino agli altri `if a.qualcosa is not None: ... return 0`:

```python
        if a.collega_lezioni is not None:
            r = libro.classifica_lezioni_per_lektion(a.collega_lezioni)
            print(f"\n  {r['classificate']} classificate | {r['rimaste']} rimaste "
                  f"| ~{r['costo_nozionale_eur']:.2f} EUR nozionali (abbonamento: 0 in fattura)\n")
            return 0
```

- [ ] **Step 7: Verifica manuale contro dati veri (piccolo lotto, costa credito reale)**

```bash
$env:PYTHONIOENCODING="utf-8"
venv\Scripts\python.exe deutschops.py libro --collega-lezioni 3
```

Atteso: "3 classificate | N rimaste | ~0.XX EUR nozionali". Se fallisce con
un errore sul backend claude, controlla che `claude` risponda:
`venv\Scripts\python.exe deutschops.py --motore claude motore` — se anche
questo fallisce, e' un problema di installazione Claude Code sulla macchina,
non di questo codice (successo gia' in passato con lo stesso sintomo: shim
npm sparito durante un update, risolto aspettando che l'update finisse).

- [ ] **Step 8: Commit**

```bash
git add do/sapere/libro.py do/base/paths.py deutschops.py tests/test_libro_classifica_lezioni.py
git commit -m "feat: collegamento lezione<->Lektion (classifica_lezioni_per_lektion)"
```

---

### Task 4: Endpoint `/api/libro/lektioni` e `/api/libro/lektion/<n>`

**Files:**
- Modify: `do/uscite/web.py`
- Test: manuale via HTTP (nessun test automatico — il pattern esistente in `web.py` non ne ha; questi endpoint sono adattatori sottili su funzioni già testate nel Task 1)

**Interfaces:**
- Consuma: `libro.lektioni()`, `libro.lektion(n)`, `libro.lezioni_per_lektion(n)` (Task 1, 3), `sessione.risposte()` (già esistente).
- Produce: risposta JSON per `GET /api/libro/lektioni` — lista di Lektionen, ognuna con `pratica_pct` e `copertura_pct` aggiunti.
- Produce: risposta JSON per `GET /api/libro/lektion/<n>` — dettaglio + `lezioni_collegate`.

- [ ] **Step 1: Implementa le funzioni dati in `web.py`**

Aggiungi dopo la funzione `risposta()` (prima di `# ------------------------------------------------------------------ server`):

```python
# ------------------------------------------------------------------ libro

def _pratica_pct(numero: int, risposte: list[dict]) -> float | None:
    """% di esercizi Listening di questa Lektion risposti giusti, o None
    sotto la soglia minima — coerente con progressi.py: un numero fragile
    non e' meglio di nessun numero."""
    SOGLIA_MINIMA = 5
    rilevanti = [r for r in risposte
                if r.get("zona") == "listening" and r.get("lektion") == numero]
    if len(rilevanti) < SOGLIA_MINIMA:
        return None
    giuste = sum(1 for r in rilevanti if r.get("corretta"))
    return round(100 * giuste / len(rilevanti))


def libro_lektioni() -> dict:
    from ..sapere import libro
    from ..studio import sessione

    risposte = sessione.risposte()
    fuori = []
    for l in libro.lektioni():
        collegate = libro.lezioni_per_lektion(l["numero"])
        fuori.append({
            **l,
            "pratica_pct": _pratica_pct(l["numero"], risposte),
            "copertura_pct": round(100 * min(1, len(collegate) / 1)) if collegate else 0,
        })
    return {"lektioni": fuori}


def libro_lektion(numero: int) -> dict:
    from ..sapere import libro

    d = libro.lektion(numero)
    if d is None:
        return {"errore": f"Lektion {numero} non trovata"}
    d["lezioni_collegate"] = libro.lezioni_per_lektion(numero)
    return d
```

**Nota sulla percentuale "copertura_pct":** e' una prima versione grezza
(0 o 100 a seconda che esista almeno una lezione collegata) — il design
originale parlava di "% di temi coperti", che richiede sapere quanti temi
ha una Lektion in totale, dato che questo piano non estrae. Se in un task
successivo si vuole una percentuale piu' fine, va prima deciso cosa conta
come "tema" di una Lektion — non inventarlo qui. Documenta questa
limitazione nel commit.

- [ ] **Step 2: Aggiungi le rotte nel router GET**

In `do_GET`, dentro il blocco `if percorso.startswith("/api/"):`, PRIMA di
quella riga (le rotte specifiche vanno controllate prima del fallback
generico "endpoint sconosciuto"):

```python
            if percorso == "/api/libro/lektioni":
                return self._json(libro_lektioni())
            if percorso.startswith("/api/libro/lektion/"):
                try:
                    n = int(percorso.rsplit("/", 1)[-1])
                except ValueError:
                    return self._json({"errore": "numero Lektion non valido"}, 400)
                return self._json(libro_lektion(n))
```

- [ ] **Step 3: Verifica manuale (server + chiamata HTTP diretta)**

Avvia il server in background:

```bash
$env:PYTHONIOENCODING="utf-8"
Start-Process -NoNewWindow venv\Scripts\python.exe -ArgumentList "deutschops.py studia --porta 7900 --non-aprire"
```

(oppure, se il tool disponibile supporta `run_in_background`, usalo invece
di `Start-Process` — l'importante e' che il server resti vivo mentre fai le
chiamate sotto)

```bash
venv\Scripts\python.exe -c "
import urllib.request, json
d = json.loads(urllib.request.urlopen('http://localhost:7900/api/libro/lektioni', timeout=15).read())
print(len(d['lektioni']), 'lektioni')
print(d['lektioni'][0])
n = d['lektioni'][0]['numero']
d2 = json.loads(urllib.request.urlopen(f'http://localhost:7900/api/libro/lektion/{n}', timeout=15).read())
print(d2['titolo'], len(d2['pagine']), 'pagine')
"
```

Atteso: 30 (o vicino) lektioni, la prima con `pratica_pct: null` (nessuna
risposta ancora registrata) e `copertura_pct` un numero. Il dettaglio con
pagine popolate.

Ferma il server dopo la verifica (`Stop-Process` sul PID, o Ctrl+C se in
foreground).

- [ ] **Step 4: Commit**

```bash
git add do/uscite/web.py
git commit -m "feat: endpoint /api/libro/lektioni e /api/libro/lektion/<n>"
```

---

### Task 5: Endpoint `/api/libro/pagina/<fonte>/<indice>` — immagine pagina

**Files:**
- Modify: `do/uscite/web.py`

**Interfaces:**
- Consuma: `libro.pagina_cachata(fonte, indice)` (Task 2).
- Produce: risposta binaria `image/png` per `GET /api/libro/pagina/<fonte>/<indice>`.

- [ ] **Step 1: Aggiungi il tipo MIME mancante**

In `do/uscite/web.py`, nel dizionario `TIPI` (vicino a `.svg`):

```python
    ".png": "image/png",
```

- [ ] **Step 2: Implementa la rotta**

Le immagini sono binarie, non JSON: serve chiamare `self._invia()`
direttamente, non `self._json()`. Aggiungi nel blocco delle rotte GET,
insieme alle altre `/api/libro/*`:

```python
            if percorso.startswith("/api/libro/pagina/"):
                resto = percorso[len("/api/libro/pagina/"):]
                if "/" not in resto:
                    return self._json({"errore": "percorso immagine non valido"}, 400)
                fonte, indice_str = resto.rsplit("/", 1)
                try:
                    indice = int(indice_str)
                except ValueError:
                    return self._json({"errore": "indice non valido"}, 400)
                from ..sapere import libro
                path = libro.pagina_cachata(fonte, indice)
                if path is None:
                    return self._json({"errore": "pagina non trovata"}, 404)
                return self._invia(path.read_bytes(), TIPI[".png"])
```

**Attenzione all'ordine:** questa riga deve stare PRIMA del check generico
`if percorso.startswith("/api/"): return self._json({"errore": "endpoint
sconosciuto"}, 404)` nello stesso blocco — altrimenti il fallback intercetta
la richiesta prima che arrivi qui. Guarda l'ordine delle righe già presenti
(`/api/libro/lektioni` va per prima dello stesso motivo) e mantieni lo
stesso pattern.

- [ ] **Step 3: Verifica manuale**

Con il server già avviato (vedi Task 4 Step 3):

```bash
venv\Scripts\python.exe -c "
import urllib.request
d = urllib.request.urlopen('http://localhost:7900/api/libro/lektioni', timeout=15).read()
import json
lek = json.loads(d)['lektioni'][0]
r = urllib.request.urlopen('http://localhost:7900/api/libro/pagina/kursbuch/10', timeout=30)
print(r.status, r.headers.get('Content-Type'), len(r.read()), 'bytes')
"
```

Atteso: `200 image/png` e più di qualche migliaio di byte. Se vuoi
controllare a occhio, salva `r.read()` su un file `.png` e aprilo con lo
strumento Read (accetta immagini).

- [ ] **Step 4: Commit**

```bash
git add do/uscite/web.py
git commit -m "feat: endpoint /api/libro/pagina — serve l'immagine PNG della pagina"
```

---

### Task 6: Endpoint `/api/libro/listening` e `POST /api/libro/risposta`

**Files:**
- Modify: `do/uscite/web.py`

**Interfaces:**
- Consuma: `libro.lektioni()`, `sessione.annota_risposta()` (già esistente — non crearne uno nuovo, vedi Global Constraints/DRY).
- Produce: `GET /api/libro/listening?n=<N>&lektion=<M opzionale>` — fino a N esercizi con `traccia_audio` risolto, campi `consegna, stimolo, soluzione` NASCOSTO fino alla risposta (stesso pattern di `RISERVATI` in `allenamento.py` — controlla quella costante prima di scrivere questo, per restare coerente).
- Produce: `POST /api/libro/risposta` — corpo `{"lektion": int, "chiave_pagina": str, "indice_esercizio": int, "corretta": bool}`, registra via `sessione.annota_risposta`.

- [ ] **Step 1: Implementa le funzioni dati**

Prima, controlla la costante `RISERVATI` in `do/studio/allenamento.py` (cerca
`RISERVATI = `) per vedere esattamente come si nascondono i campi sensibili
prima di servire un esercizio — replica lo stesso principio qui, non un
pattern diverso.

In `do/uscite/web.py`, dopo le funzioni `libro_lektioni`/`libro_lektion`:

```python
def libro_listening(n: int, lektion_filtro: int | None = None) -> dict:
    """Esercizi audio del libro, gia' risolti, soluzione nascosta finche' non
    si risponde — stesso principio di RISERVATI in allenamento.py."""
    from ..sapere import libro

    candidati = []
    for l in libro.lektioni():
        if lektion_filtro is not None and l["numero"] != lektion_filtro:
            continue
        d = libro.lektion(l["numero"])
        if not d:
            continue
        for pag in d["pagine"]:
            for i, e in enumerate(pag.get("esercizi", [])):
                if not e.get("traccia_audio") or not (e.get("soluzione") or "").strip():
                    continue
                candidati.append({
                    "lektion": l["numero"],
                    "chiave_pagina": pag["chiave"],
                    "indice_esercizio": i,
                    "consegna": e.get("consegna", ""),
                    "stimolo": e.get("stimolo", ""),
                })

    return {"esercizi": candidati[:n], "totali": len(candidati)}


def libro_risposta(voce: dict) -> dict:
    """Rivela la soluzione e registra il tentativo. L'unico endpoint Listening
    con effetto collaterale — gli altri sono di sola lettura."""
    from ..sapere import libro
    from ..studio import sessione

    chiave = str(voce.get("chiave_pagina") or "")
    try:
        indice = int(voce.get("indice_esercizio"))
        lektion_n = int(voce.get("lektion"))
    except (TypeError, ValueError):
        return {"errore": "lektion/indice_esercizio non validi"}

    d = libro._carica().get(chiave)                     # noqa: SLF001 — stesso modulo, dato interno
    if not d or indice >= len(d.get("esercizi", [])):
        return {"errore": "esercizio non trovato"}
    e = d["esercizi"][indice]

    corretta = bool(voce.get("corretta"))
    sessione.annota_risposta({
        "zona": "listening", "lektion": lektion_n, "chiave_pagina": chiave,
        "indice_esercizio": indice, "corretta": corretta,
    })
    return {"soluzione": e.get("soluzione", ""), "fonte": e.get("soluzione_fonte", "")}
```

**Nota su `libro._carica()`:** e' una funzione "privata" (prefisso `_`)
dello stesso modulo `libro.py`, usata qui da `web.py` che e' un modulo
diverso — tecnicamente lecito in Python ma rompe la convenzione del
prefisso. Se preferisci restare puliti, aggiungi in `libro.py` una funzione
pubblica minima `esercizio(chiave_pagina: str, indice: int) -> dict | None`
che fa la stessa cosa con un nome che non promette privatezza. Non
obbligatorio per far funzionare il codice, ma piu' corretto — valuta il
tempo a disposizione.

- [ ] **Step 2: Aggiungi le rotte**

Nel blocco GET, insieme alle altre `/api/libro/*`:

```python
            if percorso == "/api/libro/listening":
                q = parse_qs(rotta.query)
                n = max(1, min(30, int(q.get("n", ["10"])[0])))
                lek = q.get("lektion", [""])[0]
                return self._json(libro_listening(n, int(lek) if lek.isdigit() else None))
```

Nel blocco `do_POST`, insieme a `/api/risposta` (che gestisce Practice —
questo e' il suo equivalente per Listening, nome diverso apposta per non
confonderli):

```python
            if percorso == "/api/libro/risposta":
                return self._json(libro_risposta(voce))
```

- [ ] **Step 3: Verifica manuale end-to-end**

Con server avviato:

```bash
venv\Scripts\python.exe -c "
import urllib.request, json

d = json.loads(urllib.request.urlopen('http://localhost:7900/api/libro/listening?n=3', timeout=15).read())
print(len(d['esercizi']), 'di', d['totali'], 'esercizi listening totali')
if d['esercizi']:
    e = d['esercizi'][0]
    print('stimolo:', e['stimolo'])
    assert 'soluzione' not in e, 'la soluzione NON deve essere nella risposta prima di rispondere'

    body = json.dumps({**{k: e[k] for k in ('lektion','chiave_pagina','indice_esercizio')}, 'corretta': True}).encode()
    req = urllib.request.Request('http://localhost:7900/api/libro/risposta', data=body,
                                  headers={'Content-Type': 'application/json'}, method='POST')
    r = json.loads(urllib.request.urlopen(req, timeout=15).read())
    print('soluzione rivelata:', r.get('soluzione'))
"
```

Atteso: la prima chiamata NON contiene `soluzione` (il test lo asserisce
esplicitamente); la seconda la rivela. Se `d['totali']` e' 0, controlla che
`risolvi_esercizi()`/`associa_tracce_esercizi()` dei task precedenti
abbiano davvero prodotto esercizi con `traccia_audio` E `soluzione` insieme
— e' un dato reale del corpus, non un bug di questo endpoint se e' zero.

- [ ] **Step 4: Commit**

```bash
git add do/uscite/web.py
git commit -m "feat: endpoint /api/libro/listening e /api/libro/risposta"
```

---

### Task 7: `web/app.js` — zona Kursbuch (percorso lineare, due barre)

**Files:**
- Modify: `web/app.js`
- Modify: `web/index.html` (nuova icona SVG)

**Interfaces:**
- Consuma: `GET /api/libro/lektioni` (Task 4), pattern `el()`/`icona()`/`api()`/`vai()` già esistenti in cima al file (non ridefinirli).
- Produce: `disegnaKursbuch()`, aggiunta a `ZONE` e al dispatcher `disegna()`.

**Verifica per questo task:** `node --check web/app.js` conferma solo la
sintassi. La resa visiva reale (percorso lineare confermato col companion
visivo durante il brainstorming — vedi lo spec) va controllata in browser
quando disponibile. Se non lo e' in questa sessione, dillo esplicitamente
nel commit invece di dichiarare "verificato".

- [ ] **Step 1: Icona nuova in `index.html`**

In `web/index.html`, dentro il blocco `<svg style="display:none" ...>`,
aggiungi (icona "book-open" stile Lucide, coerente con le altre già
presenti):

```html
  <symbol id="i-book" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
          stroke-linecap="round" stroke-linejoin="round">
    <path d="M12 7v14"/>
    <path d="M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z"/>
  </symbol>
```

- [ ] **Step 2: Zona in `ZONE`, `listening` passa a pronta**

In `web/app.js`, modifica l'array `ZONE`:

```javascript
const ZONE = [
  { id: 'home',      nome: 'Home',      icona: 'i-home',      pronta: true  },
  { id: 'reading',   nome: 'Reading',   icona: 'i-reading',   pronta: true  },
  { id: 'practice',  nome: 'Practice',  icona: 'i-practice',  pronta: true  },
  { id: 'listening', nome: 'Listening', icona: 'i-listening', pronta: true  },
  { id: 'kursbuch',  nome: 'Kursbuch',  icona: 'i-book',      pronta: true  },
  { id: 'reference', nome: 'Reference', icona: 'i-reference', pronta: true  },
  { id: 'exam',      nome: 'Exam',      icona: 'i-exam',      pronta: true  },
  { id: 'progress',  nome: 'Progress',  icona: 'i-progress',  pronta: true  },
];
```

(`fase: 'F6'` sparisce da `listening` insieme a `pronta: false` — non serve
più, il placeholder è finito.)

- [ ] **Step 3: `disegnaKursbuch()` — il percorso lineare**

Aggiungi dopo `disegnaProgressi()` (cerca la fine di quella funzione, prima
della prossima intestazione di sezione):

```javascript
// ------------------------------------------------------------------ kursbuch

async function avviaKursbuch() {
  const d = await api('/api/libro/lektioni');
  stato.kursbuch = { lektioni: d.lektioni, aperta: null };
}

function disegnaKursbuch() {
  const c = $('#contenuto');
  if (!stato.kursbuch) {
    c.replaceChildren(el('p', { class: 'vuoto' }, 'Loading the course book…'));
    avviaKursbuch().then(disegna).catch(mostraErrore);
    return;
  }

  const { lektioni, aperta } = stato.kursbuch;
  // "Sei qui": la prima Lektion senza pratica registrata, o l'ultima se le
  // hai fatte tutte — non e' un dato del server, e' una lettura del client
  // sullo stesso elenco che gia' ha.
  const primaAperta = lektioni.find((l) => l.pratica_pct === null) || lektioni[lektioni.length - 1];
  const correnteNumero = aperta ?? (primaAperta ? primaAperta.numero : null);

  c.replaceChildren(
    el('section', { class: 'kursbuch-percorso' },
      ...lektioni.map((l) => {
        const e_corrente = l.numero === correnteNumero;
        const nodo = el('button', {
          class: 'kursbuch-tappa' + (e_corrente ? ' kursbuch-tappa-corrente' : ''),
          onclick: () => { stato.kursbuch.aperta = l.numero; disegna(); vaiDettaglioLektion(l.numero); },
        },
          el('span', { class: 'kursbuch-numero' }, String(l.numero)),
          el('span', { class: 'kursbuch-titolo' }, l.titolo || `Lektion ${l.numero}`),
        );
        if (!e_corrente) return nodo;

        return el('div', { class: 'kursbuch-tappa-espansa' },
          nodo,
          disegnaBarra('Your practice', l.pratica_pct),
          disegnaBarra('Covered with Stefanie', l.copertura_pct),
        );
      })
    )
  );
}

function disegnaBarra(etichetta, pct) {
  if (pct === null || pct === undefined) {
    return el('p', { class: 'provenienza' }, `${etichetta}: not enough data yet`);
  }
  return el('div', { class: 'kursbuch-barra' },
    el('div', { class: 'kursbuch-barra-etichetta' },
      el('span', {}, etichetta), el('span', {}, `${pct}%`)),
    el('div', { class: 'kursbuch-barra-fondo' },
      el('i', { class: 'kursbuch-barra-riempita', style: `width:${pct}%` })));
}

function vaiDettaglioLektion(numero) {
  // Placeholder per il Task 8: apre il dettaglio della Lektion. Se il Task 8
  // non e' ancora stato eseguito in questa sessione di lavoro, questa
  // funzione esiste ma disegnaLektionDettaglio() no — lascialo cosi', il
  // Task 8 la implementa. Non lasciare pero' un TODO nel codice: la riga
  // sotto e' funzionante finche' disegnaLektionDettaglio esiste.
  stato.zona = 'kursbuch-dettaglio';
  disegna();
}
```

- [ ] **Step 4: Wire nel dispatcher `disegna()`**

In `disegna()` (cerca `if (stato.zona === 'exam')`), aggiungi:

```javascript
  if (stato.zona === 'kursbuch') return disegnaKursbuch();
```

- [ ] **Step 5: Aggiungi lo stato iniziale**

Nell'oggetto `stato` in cima al file, aggiungi il campo:

```javascript
  kursbuch: null,      // { lektioni, aperta } della zona Kursbuch
```

- [ ] **Step 6: Verifica sintattica**

Run: `node --check web/app.js`
Expected: nessun output (sintassi valida)

- [ ] **Step 7: Verifica manuale in browser (se disponibile)**

Avvia `deutschops.py studia`, apri la zona Kursbuch, controlla che il
percorso lineare mostri le Lektionen e che la corrente abbia le due barre.
Se il browser non e' disponibile in questa sessione, scrivilo nel messaggio
di commit invece di affermare che e' stato controllato.

- [ ] **Step 8: Commit**

```bash
git add web/app.js web/index.html
git commit -m "feat: zona Kursbuch — percorso lineare con due barre di completamento"
```

---

### Task 8: `web/app.js` — dettaglio Lektion

**Files:**
- Modify: `web/app.js`

**Interfaces:**
- Consuma: `GET /api/libro/lektion/<n>` (Task 4), `GET /api/libro/pagina/<fonte>/<indice>` (Task 5).
- Produce: `disegnaLektionDettaglio(numero)`, sostituisce il placeholder `vaiDettaglioLektion` del Task 7.

- [ ] **Step 1: Sostituisci `vaiDettaglioLektion` con l'implementazione vera**

In `web/app.js`, sostituisci l'intera funzione `vaiDettaglioLektion`
scritta nel Task 7 con:

```javascript
async function avviaDettaglioLektion(numero) {
  const d = await api(`/api/libro/lektion/${numero}`);
  stato.kursbuchDettaglio = d;
}

function vaiDettaglioLektion(numero) {
  stato.zona = 'kursbuch-dettaglio';
  stato.kursbuchDettaglio = null;
  disegna();
}

function disegnaKursbuchDettaglio() {
  const c = $('#contenuto');
  const numero = stato.kursbuch?.aperta;
  if (!stato.kursbuchDettaglio) {
    c.replaceChildren(el('p', { class: 'vuoto' }, 'Loading Lektion…'));
    avviaDettaglioLektion(numero).then(disegna).catch(mostraErrore);
    return;
  }

  const d = stato.kursbuchDettaglio;
  c.replaceChildren(
    el('button', { class: 'secondario', onclick: () => { stato.zona = 'kursbuch'; disegna(); } },
      '← Back to Kursbuch'),
    el('h1', {}, `Lektion ${d.numero} — ${d.titolo}`),

    d.lezioni_collegate.length
      ? el('section', {},
          el('h2', { style: 'font-size:1rem' }, 'Your lessons on similar topics'),
          ...d.lezioni_collegate.map((lc) =>
            el('div', { class: 'riga' },
              el('div', { class: 'riga-capo' }, lc.data_lezione),
              el('div', { class: 'provenienza' }, lc.motivo))))
      : null,

    ...d.pagine.map((pag) => el('article', { class: 'esercizio' },
      el('img', {
        src: `/api/libro/pagina/${pag.chiave.split(':')[0]}/${pag.chiave.split(':')[1]}`,
        loading: 'lazy', style: 'max-width:100%;border-radius:var(--r2);margin-bottom:var(--s3)',
        alt: `Page ${pag.chiave}`,
      }),
      ...pag.esercizi.filter((e) => e.soluzione).map((e) =>
        el('div', { class: 'riga' },
          el('p', { class: 'stimolo' }, e.stimolo),
          el('p', { class: 'provenienza' }, `→ ${e.soluzione}`)))
    ))
  );
}
```

- [ ] **Step 2: Wire nel dispatcher e nello stato**

In `disegna()`, aggiungi:

```javascript
  if (stato.zona === 'kursbuch-dettaglio') return disegnaKursbuchDettaglio();
```

Nell'oggetto `stato`, aggiungi:

```javascript
  kursbuchDettaglio: null,   // il dettaglio della Lektion aperta
```

- [ ] **Step 3: Verifica sintattica**

Run: `node --check web/app.js`
Expected: nessun output

- [ ] **Step 4: Verifica manuale (browser, se disponibile) — vedi nota Task 7**

- [ ] **Step 5: Commit**

```bash
git add web/app.js
git commit -m "feat: dettaglio Lektion — pagine vere, esercizi risolti, lezioni collegate"
```

---

### Task 9: `web/app.js` — sessione Listening

**Files:**
- Modify: `web/app.js`

**Interfaces:**
- Consuma: `GET /api/libro/listening` (Task 6), `POST /api/libro/risposta` (Task 6).
- Produce: `disegnaAscolto()`, sostituisce il rendering placeholder di `listening` nel dispatcher.

- [ ] **Step 1: Implementa la sessione**

Aggiungi dopo `disegnaKursbuchDettaglio()`:

```javascript
// ------------------------------------------------------------------ listening

async function avviaAscolto() {
  const d = await api('/api/libro/listening?n=10');
  stato.ascolto = { esercizi: d.esercizi, totali: d.totali, i: 0, fase: 'domanda', soluzione: null };
}

function disegnaAscolto() {
  const c = $('#contenuto');
  const a = stato.ascolto;
  if (!a) {
    c.replaceChildren(el('p', { class: 'vuoto' }, 'Loading listening exercises…'));
    avviaAscolto().then(disegna).catch(mostraErrore);
    return;
  }

  const e = a.esercizi[a.i];
  if (!e) {
    c.replaceChildren(el('p', { class: 'vuoto' },
      a.totali === 0
        ? 'No listening exercises ready yet — run libro --risolvi-esercizi first.'
        : "That's all for this session."));
    return;
  }

  if (a.fase === 'rivelato') {
    c.replaceChildren(
      el('article', { class: 'esercizio' },
        el('p', { class: 'consegna' }, e.consegna),
        el('p', { class: 'stimolo' }, e.stimolo),
        el('p', { class: 'traduzione' }, `→ ${a.soluzione}`),
        el('div', { class: 'voti' },
          el('button', { class: 'voto good', onclick: () => avantiAscolto(true) }, 'Got it right'),
          el('button', { class: 'voto again', onclick: () => avantiAscolto(false) }, 'Got it wrong'),
        )
      )
    );
    return;
  }

  c.replaceChildren(
    el('div', { class: 'avanzamento' },
      el('span', {}, `${a.i + 1} of ${a.esercizi.length}`)),
    el('article', { class: 'esercizio' },
      el('p', { class: 'consegna' }, e.consegna),
      el('p', { class: 'stimolo' }, e.stimolo),
      el('button', { class: 'primario', onclick: () => rivelaAscolto() }, 'Show answer'))
  );
}

async function rivelaAscolto() {
  const a = stato.ascolto;
  const e = a.esercizi[a.i];
  const r = await api('/api/libro/risposta', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      lektion: e.lektion, chiave_pagina: e.chiave_pagina,
      indice_esercizio: e.indice_esercizio, corretta: false,  // provvisorio, il voto vero arriva dopo
    }),
  });
  a.soluzione = r.soluzione;
  a.fase = 'rivelato';
  disegna();
}

function avantiAscolto(corretta) {
  // La POST di rivelaAscolto ha gia' registrato "corretta: false" come
  // segnaposto — qui si sovrascrive col voto vero, stessa chiave. Se preferisci
  // non registrare due volte, sposta la POST qui invece che in rivelaAscolto()
  // e passa `corretta` come parametro: valuta quale delle due letture rende
  // il codice piu' chiaro prima di eseguire questo step, non e' un dettaglio
  // che cambia il comportamento visibile.
  const a = stato.ascolto;
  const e = a.esercizi[a.i];
  api('/api/libro/risposta', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      lektion: e.lektion, chiave_pagina: e.chiave_pagina,
      indice_esercizio: e.indice_esercizio, corretta,
    }),
  }).catch(() => {});  // il voto e' gia' mostrato all'utente, un fallimento di rete qui non deve bloccarlo
  a.i += 1;
  a.fase = 'domanda';
  a.soluzione = null;
  disegna();
}
```

**Nota sul doppio POST:** questo step registra due volte per esercizio (una
volta rivelando, con `corretta: false` provvisorio, poi il voto vero) — e'
un difetto onesto, non nascosto: il log finirebbe con un tentativo falso per
ognuno. La via pulita e' NON registrare nulla in `rivelaAscolto()` — quella
chiamata dovrebbe solo restituire la soluzione da un endpoint di sola
lettura — e registrare SOLO in `avantiAscolto()`. Questo pero' significa
avere un endpoint separato per "rivela senza registrare" o passare
`corretta: null` e distinguerlo lato server. Decidi tu quale via prendere
prima di scrivere il codice sopra alla lettera — l'implementazione qui e'
volutamente il caso semplice-ma-imperfetto, documentato perche' tu possa
migliorarlo con cognizione di causa invece di ereditare un difetto silenzioso.

- [ ] **Step 2: Wire nel dispatcher e nello stato**

In `disegna()`, sostituisci la riga generica che gestiva `listening` come
"Not built yet" (o aggiungi, se non c'era una riga dedicata):

```javascript
  if (stato.zona === 'listening') return disegnaAscolto();
```

Nell'oggetto `stato`, aggiungi:

```javascript
  ascolto: null,       // sessione di ascolto in corso
```

- [ ] **Step 3: Verifica sintattica**

Run: `node --check web/app.js`
Expected: nessun output

- [ ] **Step 4: Verifica manuale end-to-end (browser se disponibile, altrimenti solo API — vedi Task 6 Step 3 per il pattern di verifica via HTTP diretto)**

- [ ] **Step 5: Commit**

```bash
git add web/app.js
git commit -m "feat: sessione Listening — esercizi audio del libro, autovalutati"
```

---

### Task 10: Puntatore "vedi Lektion N" nella gap analysis Exam

**Files:**
- Modify: `do/uscite/web.py`
- Test: manuale via HTTP

**Interfaces:**
- Consuma: `esame()` (già esistente, cerca `def esame()`), `libro.esempio_esercizio()` (già esistente).

- [ ] **Step 1: Implementa l'arricchimento**

In `do/uscite/web.py`, nella funzione `esame()` esistente, subito dopo la
riga `temi.sort(...)` e prima del `return`:

```python
    from ..sapere import libro
    for t in temi:
        if t.get("stato") != "mancante":
            continue
        parole = re.findall(r"[a-zA-ZäöüÄÖÜß]{4,}", t.get("tema", ""))
        if trovati := libro.esempio_esercizio(parole, quanti=1):
            e = trovati[0]
            # Serve il numero di Lektion, non l'esercizio in se': si ricava
            # dalla pagina che lo contiene, cercando fra tutte le Lektionen.
            for l in libro.lektioni():
                d = libro.lektion(l["numero"])
                if d and any(e in pag.get("esercizi", []) for pag in d["pagine"]):
                    t["lektion_libro"] = l["numero"]
                    break
```

Questo richiede `import re` in cima a `web.py` — controlla se c'è già
(probabile, il file ha altre regex) prima di aggiungerlo di nuovo.

**Nota sul costo:** questo giro chiama `libro.lektioni()` e `libro.lektion()`
dentro un loop per ogni tema mancante — su ~22 temi B2 e 30 Lektionen è
lavoro ripetuto ma tutto in memoria, zero chiamate di rete o LLM (sia
`esempio_esercizio` che `lektioni`/`lektion` sono deterministici). Se
`/api/esame` diventa percepibilmente lento, la prima ottimizzazione è
costruire l'indice esercizio→Lektion una volta fuori dal loop invece di
ricalcolarlo per ogni tema — non farlo preventivamente se non serve,
YAGNI.

- [ ] **Step 2: Verifica manuale**

```bash
venv\Scripts\python.exe -c "
import urllib.request, json
d = json.loads(urllib.request.urlopen('http://localhost:7900/api/esame', timeout=15).read())
mancanti = [t for t in d['temi'] if t.get('stato') == 'mancante']
con_puntatore = [t for t in mancanti if t.get('lektion_libro')]
print(len(mancanti), 'temi mancanti,', len(con_puntatore), 'con puntatore al libro')
if con_puntatore:
    print(con_puntatore[0])
"
```

Atteso: alcuni temi mancanti (non necessariamente tutti — molti gap B2 sono
oltre il B1 del libro, e' corretto che restino senza puntatore) con
`lektion_libro` valorizzato.

- [ ] **Step 3: Commit**

```bash
git add do/uscite/web.py
git commit -m "feat: puntatore Lektion nella gap analysis Exam"
```

---

## Dopo l'ultimo task

```bash
git push
```

Se il branch remoto e' avanzato nel frattempo (altra sessione, altro
lavoro), fai `git pull --rebase` prima — non forzare mai il push su questo
branch.

Aggiorna `CLAUDE.md` di DeutschOps con una sezione breve su come funziona
la zona Kursbuch/Listening (segui lo stile delle sezioni esistenti — frase
diretta, non un elenco di feature) solo se il tempo/budget lo permette:
non e' un task di questo piano, e' un miglioramento facoltativo.
