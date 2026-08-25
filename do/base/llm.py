"""Client LLM unico — Anthropic o Ollama, con il costo REALE.

Tre problemi della v1 che questo modulo chiude:

1. La logica di dispatch backend era duplicata in extractor.py:11-52 e
   error_extractor.py:22-63, e ignorata da altri 7 moduli con il modello
   cablato (grammar_book, b1_gap, pharma_glossary, weak_cards, book_*,
   bulk_import). doc_reader e retroactive_doc_images chiamavano Ollama in
   hardcoded, senza nemmeno leggere OLLAMA_HOST.

2. Il prezzo per token era copiato in due punti.

3. Il costo reale veniva CALCOLATO e poi buttato: extractor.py:50-52 lo
   ricavava da response.usage, extract() lo stampava a riga 240, e poi
   ritornava solo `data`. main.py:230 scriveva al suo posto una costante
   `claude_cost = 0.10`. Risultato: 2,95 dei 4,82 euro nel registry sono una
   costante moltiplicata per 30 lezioni.

Qui ogni chiamata restituisce (testo, Uso) e Uso ha il costo misurato.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass

import requests

from .config import (
    CLAUDE_CLI,
    CLAUDE_CLI_TIMEOUT_S,
    RICERCA_MAX_USI,
    LLMConfig,
    api_key,
    llm_config,
)


# --------------------------------------------------------------------- prezzi
# USD per milione di token, listino Anthropic. Una sola fonte in tutto il
# progetto. Aggiornato al 2026-07-26.
PREZZI: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    # Sonnet 5: listino 3.00/15.00, con prezzo introduttivo 2.00/10.00 fino al
    # 2026-08-31. Teniamo il listino pieno: meglio sovrastimare il costo che
    # sottostimarlo e scoprirlo a settembre.
    "claude-sonnet-5": (3.00, 15.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
}

# Cambio indicativo USD -> EUR. Il registry storico e' in euro.
USD_EUR = 0.92


@dataclass(frozen=True)
class Uso:
    """Consumo reale di una chiamata. Sostituisce la costante hardcoded."""

    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    costo_eur: float
    model: str
    stimato: bool = False
    """True quando il costo NON e' misurato (backend locale, o modello
    sconosciuto al listino). Il registry deve marcarlo come tale invece di
    spacciarlo per misurato — vedi il debito storico descritto in cima."""

    costo_nozionale_eur: float = 0.0
    """Quanto sarebbe costata la stessa chiamata a consumo, quando NON si paga
    a consumo. Sul backend "claude" il conto va sull'abbonamento e `costo_eur`
    e' zero davvero — ma buttare via il numero ripeterebbe l'errore della v1 al
    contrario: senza questo campo non si puo' piu' rispondere a "quanto mi sta
    facendo risparmiare l'abbonamento?" ne' accorgersi che un lotto e' cresciuto
    fino a mangiarsi la finestra di quota."""


def _costo_eur(model: str, inp: int, out: int, cache_read: int = 0) -> tuple[float, bool]:
    prezzi = PREZZI.get(model)
    if prezzi is None:
        return 0.0, True
    p_in, p_out = prezzi
    # Le letture da cache costano circa 0,1x l'input.
    usd = ((inp + cache_read * 0.1) * p_in + out * p_out) / 1_000_000
    return round(usd * USD_EUR, 6), False


# --------------------------------------------------------------------- client
_client = None


# Quanto si insiste prima di arrendersi. Il default dell'SDK e' 2.
# Qui conta piu' del solito: l'estrazione arriva DOPO 45 minuti di
# trascrizione locale, e perderla per un secondo di rete assente sarebbe un
# costo sproporzionato all'errore. Il task tracker copre comunque il caso
# peggiore — al rilancio si riparte dall'estrazione — ma non doverci arrivare
# e' meglio.
TENTATIVI = 5
TIMEOUT_S = 900.0


def _anthropic_client():
    """Client creato pigramente: importarlo non deve richiedere una chiave."""
    global _client
    if _client is None:
        import anthropic

        _client = anthropic.Anthropic(
            api_key=api_key("ANTHROPIC_API_KEY"),
            max_retries=TENTATIVI,
            timeout=TIMEOUT_S,
        )
    return _client


def chiama(
    system: str,
    user: str,
    cfg: LLMConfig | None = None,
    *,
    ricerca_web: bool = False,
    formato_json: bool | dict = False,
) -> tuple[str, Uso]:
    """Una chiamata LLM. Ritorna sempre (testo, Uso) — il costo non si perde.

    Solleva l'eccezione del backend in caso di errore: chi chiama decide se
    degradare. Non inghiottiamo errori qui — nella v1 il sync NotebookLM e'
    fallito 12 volte di fila dentro un try/except che stampava e proseguiva.

    `ricerca_web` monta il tool di ricerca lato server. Non e' disponibile su
    Ollama: chi lo chiede su backend locale riceve un errore esplicito invece
    di una risposta silenziosamente senza fonti.
    """
    cfg = cfg or llm_config()

    if cfg.backend == "ollama":
        if ricerca_web:
            raise RuntimeError(
                "ricerca_web non disponibile con LLM_BACKEND=ollama: "
                "il backend locale non ha accesso a internet."
            )
        return _chiama_ollama(system, user, cfg, formato_json=formato_json)
    if cfg.backend == "claude":
        return _chiama_claude_cli(system, user, cfg, ricerca_web=ricerca_web)
    return _chiama_anthropic(system, user, cfg, ricerca_web=ricerca_web)


def _chiama_ollama(system: str, user: str, cfg: LLMConfig,
                   *, formato_json: bool | dict = False) -> tuple[str, Uso]:
    corpo = {
        "model": cfg.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {
            "num_predict": cfg.max_tokens,
            # Ollama tronca al num_ctx di default (~4096 token): un transcript
            # da ~8K token verrebbe tagliato a meta' -> estrazione monca (pochi
            # vocaboli, campi vuoti). Dimensioniamo la finestra su prompt+output
            # (stima grezza char/3) cosi' il modello vede tutto il transcript.
            "num_ctx": min(int(os.getenv("DO_OLLAMA_NUM_CTX", "16384")),
                           (len(system) + len(user)) // 3 + 3072),
        },
    }
    if formato_json:
        # Vincola l'output: uno schema JSON (structured outputs) forza la FORMA
        # esatta; la stringa "json" solo la validita' sintattica. Senza, il 7B
        # free-forma in prosa/Markdown o inventa la struttura (visto su 08-11).
        corpo["format"] = formato_json if isinstance(formato_json, dict) else "json"
    r = requests.post(
        f"{cfg.ollama_host}/api/chat",
        json=corpo,
        timeout=18000,  # CPU + contesto ampio: puo' volerci un'ora o piu'.
                        # Torna appena finito; la lentezza non e' un errore.
    )
    r.raise_for_status()
    dati = r.json()
    testo = dati.get("message", {}).get("content", "")
    return testo, Uso(
        input_tokens=dati.get("prompt_eval_count", 0),
        output_tokens=dati.get("eval_count", 0),
        cache_read_tokens=0,
        costo_eur=0.0,          # locale: gratis davvero, non stimato a zero
        model=cfg.model,
        stimato=False,
    )


# ------------------------------------------------------- backend abbonamento
# Le chiavi che, se presenti nell'ambiente del sottoprocesso, fanno usare a
# Claude Code il consumo a token INVECE dell'abbonamento — in silenzio, con un
# risultato identico a vedersi. Verificato il 2026-07-31: con una chiave finta
# in ambiente la CLI esce 401 senza mai ripiegare su OAuth, quindi la chiave
# vince sempre sull'abbonamento.
#
# Non e' un caso di scuola: config._carica_env() mette ANTHROPIC_API_KEY dentro
# os.environ all'import, e subprocess eredita l'ambiente del padre. Senza questa
# ripulitura ogni chiamata "sull'abbonamento" partita da DeutschOps finirebbe
# sulla fattura a consumo, e il costo misurato direbbe zero.
_CHIAVI_DA_TOGLIERE = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
)


def _ambiente_abbonamento() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in _CHIAVI_DA_TOGLIERE}


# Stati che meritano un altro tentativo. L'SDK Anthropic riprova da solo
# (TENTATIVI=5, riga 85); la CLI no — il primo 529 esce dal processo e arriva
# qui. Senza questa lista un lotto di 20 blocchi muore al primo sovraccarico
# passeggero, a meta' libreria. Incontrato davvero il 2026-07-31.
#
# 401 e 429 restano fuori di proposito: il primo e' autenticazione mancante e
# non migliora aspettando, il secondo e' la quota dell'abbonamento finita e
# insistere la brucia soltanto piu' in fretta.
_RIPROVABILI = (500, 502, 503, 504, 529)
_ATTESE_S = (2, 8, 20, 45)


def _chiama_claude_cli(system: str, user: str, cfg: LLMConfig,
                       *, ricerca_web: bool = False) -> tuple[str, Uso]:
    """Stessa chiamata, ma attraverso Claude Code in modalita' non interattiva.

    Il conto va sull'abbonamento invece che sui token API. Quello che cambia
    davvero rispetto a `_chiama_anthropic`, misurato il 2026-07-31:

    - **Sovrapprezzo fisso di contesto.** Claude Code monta comunque il proprio
      impianto: 5.974 token a chiamata con la configurazione normale, 1.063 con
      `--safe-mode` piu' `--system-prompt` (che rimpiazza il prompt di sistema
      invece di aggiungersi). Usiamo la seconda. Su un lotto da 25 esercizi si
      diluisce; su una singola frase da giudicare e' quasi tutto il costo.
    - **~0,7 s di avvio processo** piu' il giro di autenticazione. Sono ~6 s
      end-to-end anche per una risposta di quattro token.
    - **`max_tokens` non e' esponibile.** Il guardrail sul troncamento della via
      API qui non esiste: si controlla `stop_reason`.
    - **Il prompt viaggia su stdin, non su argv.** La riga di comando di Windows
      si ferma a ~32.000 caratteri e qui passano interi transcript da 700 KB.

    Le due strade restano intercambiabili per chi chiama: (testo, Uso).
    """
    return _esegui_claude_cli(system, user, cfg, strumenti="WebSearch" if ricerca_web else "")


def chiama_visione(system: str, user: str, immagine, cfg: LLMConfig | None = None
                   ) -> tuple[str, Uso]:
    """Come `chiama()`, ma con un'immagine locale allegata. Solo backend claude.

    PERCHE' SOLO CLAUDE, E PERCHE' IL TOOL Read
    Vision via API costerebbe token a consumo per pagina — su un libro di
    centinaia di pagine e' il caso d'uso per cui l'abbonamento esiste.
    L'API `-p` senza strumenti NON vede le immagini referenziate nel prompt
    (`@percorso`, provato il 2026-08-13: risponde "non vedo nessuna
    immagine" pur trovando il file). Con `--tools Read` invece il modello
    apre davvero il file — il Read tool di Claude Code legge le immagini
    nativamente — e la vede. Verificato: OCR accurato su una pagina di
    Kursbuch scansionata, encoding UTF-8 corretto end-to-end (il replacement
    character visto in un primo giro era un artefatto del terminale di
    verifica, non del dato — controllato sui codepoint, non sulla stampa).
    """
    cfg = cfg or llm_config(backend="claude")
    if cfg.backend != "claude":
        raise RuntimeError(
            "chiama_visione richiede backend claude (Read tool locale, "
            "niente costo API per pagina)."
        )
    prompt = f"Read the image at {immagine} using the Read tool.\n\n{user}"
    return _esegui_claude_cli(system, prompt, cfg, strumenti="Read")


def _esegui_claude_cli(system: str, user: str, cfg: LLMConfig, *, strumenti: str
                       ) -> tuple[str, Uso]:
    """Il nucleo comune a `_chiama_claude_cli` e `chiama_visione`: processo,
    retry, parsing. Cambia solo quali strumenti la CLI puo' usare."""
    # Il percorso RISOLTO, non il nome nudo: su Windows l'installazione npm
    # lascia un `claude` senza estensione accanto a `claude.cmd`, e subprocess
    # senza shell sa lanciare solo il secondo. shutil.which() applica PATHEXT e
    # restituisce quello giusto.
    eseguibile = shutil.which(CLAUDE_CLI)
    if eseguibile is None:
        raise RuntimeError(
            f"LLM_BACKEND=claude ma l'eseguibile {CLAUDE_CLI!r} non e' nel PATH. "
            f"Installa Claude Code (npm i -g @anthropic-ai/claude-code) oppure "
            f"indica il percorso con CLAUDE_CLI in .env."
        )

    # NIENTE TESTO SU argv.
    # Su Windows `claude` e' uno shim .CMD, quindi subprocess lo lancia
    # attraverso cmd.exe, che RIANALIZZA la riga di comando. SYSTEM di
    # allenamento.py sono 5.863 caratteri con dentro `< > | "`: passato come
    # argomento veniva riscritto da cmd.exe e tutto cio' che seguiva —
    # `--output-format json` compreso — spariva. Il sintomo era la CLI che
    # rispondeva in prosa invece che in JSON, exit 0, nessun errore.
    #
    # Quindi: prompt di sistema su FILE, prompt utente su STDIN. Su argv
    # restano solo flag fisse e il nome del modello. Chiude anche la variante
    # cattiva dello stesso problema — un transcript con `& del ...` dentro non
    # deve mai poter finire su una riga di comando reinterpretata da una shell.
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False,
                                     encoding="utf-8") as f:
        f.write(system)
        prompt_sistema = f.name

    cmd = [
        eseguibile, "-p",
        "--model", cfg.model,
        # Rimpiazza il prompt di sistema di Claude Code invece di accodarsi:
        # e' la differenza fra 1.063 e 5.974 token di impianto a chiamata.
        "--system-prompt-file", prompt_sistema,
        # Niente CLAUDE.md, skill, hook, plugin: qui serve un modello, non un
        # agente che eredita il contesto del workspace Antigravity.
        "--safe-mode",
        # Strumenti minimi per il compito: vuoto per una chiamata di testo
        # pura, "Read" per leggere un'immagine locale (chiama_visione),
        # "WebSearch" per l'approfondimento grammaticale. Mai di piu': senza
        # un tetto stretto un prompt sfortunato potrebbe leggere altri file o
        # girare comandi dentro DeutschOps.
        "--tools", strumenti,
        # 20 blocchi di libreria non devono lasciare 20 sessioni su disco.
        "--no-session-persistence",
        "--output-format", "json",
    ]

    # `thinking: disabled` non esiste come flag della CLI. La via API lo manda
    # su ogni estrazione JSON (riga ~190) perche' il ragionamento adattivo
    # gonfia output e attesa senza migliorare un JSON deterministico. Qui il
    # comando piu' vicino e' `--effort low`, che non spegne il pensiero ma lo
    # accorcia — la differenza residua e' il prezzo di questo backend.
    if sforzo := (cfg.effort or (None if cfg.thinking else "low")):
        cmd += ["--effort", sforzo]

    ambiente = _ambiente_abbonamento()
    esito: dict = {}
    try:
        for giro in range(len(_ATTESE_S) + 1):
            try:
                p = subprocess.run(
                    cmd,
                    input=user,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=CLAUDE_CLI_TIMEOUT_S,
                    env=ambiente,
                )
            except subprocess.TimeoutExpired as e:
                raise RuntimeError(
                    f"Claude Code non ha risposto entro {CLAUDE_CLI_TIMEOUT_S}s. "
                    f"Alza CLAUDE_CLI_TIMEOUT_S, oppure spezza la richiesta."
                ) from e

            if not (p.stdout or "").strip():
                raise RuntimeError(
                    f"Claude Code non ha prodotto output (exit {p.returncode}). "
                    f"stderr: {(p.stderr or '').strip()[:400] or '(vuoto)'}"
                )

            try:
                esito = json.loads(p.stdout)
            except json.JSONDecodeError as e:
                raise RuntimeError(
                    f"Output di Claude Code non in JSON (exit {p.returncode}): "
                    f"{p.stdout[:300]!r}"
                ) from e

            if not esito.get("is_error"):
                break

            stato = esito.get("api_error_status")
            if stato in _RIPROVABILI and giro < len(_ATTESE_S):
                attesa = _ATTESE_S[giro]
                print(f"   {stato} dal server, riprovo fra {attesa}s "
                      f"({giro + 1}/{len(_ATTESE_S)})", flush=True)
                time.sleep(attesa)
                continue

            # Il 401 qui ha una causa sola e vale la pena dirla per nome: la
            # ripulitura sopra ha lasciato passare una credenziale, oppure
            # l'abbonamento non e' autenticato su questa macchina.
            aiuto = ""
            if stato == 401:
                aiuto = (" — l'abbonamento non risulta autenticato: lancia `claude` "
                         "una volta in interattivo e accedi.")
            elif stato == 429:
                aiuto = (" — quota dell'abbonamento esaurita per questa finestra. "
                         "Aspetta la riapertura o usa LLM_BACKEND=anthropic per questo lotto.")
            elif stato in _RIPROVABILI:
                aiuto = f" — dopo {len(_ATTESE_S)} tentativi. Il servizio e' giu', non e' colpa tua."
            raise RuntimeError(
                f"Claude Code ha fallito (stato {stato}): "
                f"{str(esito.get('result'))[:300]}{aiuto}"
            )
    finally:
        with contextlib.suppress(OSError):
            os.unlink(prompt_sistema)

    fermata = esito.get("stop_reason")
    if fermata not in (None, "end_turn", "stop_sequence", "tool_use"):
        raise RuntimeError(
            f"Risposta interrotta da Claude Code (stop_reason={fermata!r}). "
            f"Con questo backend max_tokens non e' regolabile: spezza la richiesta "
            f"in blocchi piu' piccoli."
        )

    testo = esito.get("result") or ""

    # Il conteggio token e' reale; il costo no. `total_cost_usd` e' quanto la
    # stessa chiamata sarebbe costata a consumo — utile per sapere cosa
    # l'abbonamento sta assorbendo, sbagliato da sommare come spesa.
    entrati, usciti, letti = _token_usati(esito)
    nozionale = round(float(esito.get("total_cost_usd") or 0.0) * USD_EUR, 6)
    return testo, Uso(
        input_tokens=entrati,
        output_tokens=usciti,
        cache_read_tokens=letti,
        costo_eur=0.0,          # abbonamento: zero davvero, non stimato a zero
        model=cfg.model,
        stimato=False,
        costo_nozionale_eur=nozionale,
    )


def _token_usati(esito: dict) -> tuple[int, int, int]:
    """(input, output, letti da cache) da una risposta della CLI.

    `usage` NON e' affidabile: su una risposta a piu' iterazioni torna a zero
    (misurato il 2026-07-31 sull'estrazione di un transcript da 44 KB — costo
    nozionale 0,166 EUR e usage tutto a zero). `modelUsage` invece somma per
    modello sull'intera esecuzione, e include anche il modello di servizio che
    Claude Code usa per conto suo: e' consumo vero e va contato.

    `usage` resta come ripiego, per non tornare a zero se un domani cambia la
    forma di `modelUsage`.
    """
    per_modello = esito.get("modelUsage") or {}
    if per_modello:
        entrati = sum(int(v.get("inputTokens") or 0)
                      + int(v.get("cacheCreationInputTokens") or 0)
                      for v in per_modello.values())
        usciti = sum(int(v.get("outputTokens") or 0) for v in per_modello.values())
        letti = sum(int(v.get("cacheReadInputTokens") or 0) for v in per_modello.values())
        if entrati or usciti:
            return entrati, usciti, letti

    u = esito.get("usage") or {}
    return (
        int(u.get("input_tokens") or 0) + int(u.get("cache_creation_input_tokens") or 0),
        int(u.get("output_tokens") or 0),
        int(u.get("cache_read_input_tokens") or 0),
    )


def _chiama_anthropic(system: str, user: str, cfg: LLMConfig,
                      *, ricerca_web: bool = False) -> tuple[str, Uso]:
    kwargs: dict = {
        "model": cfg.model,
        "max_tokens": cfg.max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }

    if ricerca_web:
        # extractor.py:172 montava `web_search_20250305`. Su Sonnet 5 la
        # versione corrente e' quella del 2026-02-09, con filtro dinamico.
        #
        # `max_uses` non e' un dettaglio: senza tetto il modello incatena
        # ricerche e ogni giro rimanda in input tutto il contesto accumulato.
        # E' li' che nasce lo 0,58 EUR a regola misurato il 2026-07-27, contro
        # gli 0,02 della stessa richiesta senza ricerca.
        kwargs["tools"] = [{
            "type": "web_search_20260209",
            "name": "web_search",
            "max_uses": RICERCA_MAX_USI,
        }]

    # Su Sonnet 5 e Opus 5 il pensiero adattivo e' ATTIVO quando il campo viene
    # omesso, e max_tokens limita pensiero + risposta insieme. Per un'estrazione
    # JSON deterministica lo spegniamo esplicitamente: e' il comportamento che
    # la v1 aveva di fatto, e evita che il JSON venga troncato a meta'.
    # NB: con thinking disabilitato l'effort resta valido solo fino a "high".
    if cfg.thinking:
        kwargs["thinking"] = {"type": "adaptive"}
    else:
        kwargs["thinking"] = {"type": "disabled"}
    if cfg.effort:
        kwargs["output_config"] = {"effort": cfg.effort}

    # IN STREAMING, SEMPRE.
    # Il 2026-07-27 l'estrazione e' morta con APITimeoutError dopo 45 minuti di
    # trascrizione. Con `messages.create()` la connessione resta muta per tutta
    # la generazione: con max_tokens a 16.000 sono minuti in cui nessuno manda
    # un byte, e qualsiasi cosa in mezzo — proxy, wifi, NAT — puo' chiudere.
    # In streaming i token arrivano man mano e la connessione non e' mai ferma.
    # Non cambia nulla per chi chiama: `get_final_message()` ritorna lo stesso
    # oggetto Message, con usage e stop_reason.
    with _anthropic_client().messages.stream(**kwargs) as flusso:
        resp = flusso.get_final_message()

    # I classificatori possono rifiutare: HTTP 200 con stop_reason "refusal" e
    # content vuoto. Leggere content[0] senza controllare esplode.
    if resp.stop_reason == "refusal":
        motivo = getattr(getattr(resp, "stop_details", None), "explanation", "") or "nessun dettaglio"
        raise RuntimeError(f"Richiesta rifiutata dal modello ({motivo}).")

    blocchi = [b.text for b in resp.content if b.type == "text" and b.text.strip()]
    # Con la ricerca web la risposta e' a piu' blocchi: commento del modello,
    # server_tool_use, risultati, e infine la risposta vera. Concatenarli
    # metterebbe il ragionamento davanti al JSON e il parser prenderebbe la
    # prima graffa che trova nel commento. L'ultimo blocco e' la risposta.
    testo = (blocchi[-1] if ricerca_web and blocchi else "".join(blocchi))

    # Troncamento a max_tokens: senza questo controllo il chiamante riceve un
    # JSON tagliato a meta' e vede un JSONDecodeError incomprensibile a riga
    # ignota, invece della causa vera.
    if resp.stop_reason == "max_tokens":
        raise RuntimeError(
            f"Risposta troncata a max_tokens={cfg.max_tokens} "
            f"({resp.usage.output_tokens} token generati). Alza max_tokens: "
            f"su Sonnet 5 il tokenizer produce circa il 30% di token in piu' "
            f"rispetto a Sonnet 4.5, quindi i limiti tarati sulla v1 stanno stretti."
        )

    u = resp.usage
    cache_read = getattr(u, "cache_read_input_tokens", 0) or 0
    costo, stimato = _costo_eur(cfg.model, u.input_tokens, u.output_tokens, cache_read)
    return testo, Uso(
        input_tokens=u.input_tokens,
        output_tokens=u.output_tokens,
        cache_read_tokens=cache_read,
        costo_eur=costo,
        model=cfg.model,
        stimato=stimato,
    )


def estrai_json(testo: str) -> dict:
    """Estrae l'oggetto JSON da una risposta, tollerando i fence markdown.

    Non usa regex creative: cerca il primo '{' e l'ultimo '}'. Se il parsing
    fallisce solleva — un JSON malformato non deve diventare un dict vuoto che
    si propaga in silenzio fino ad Anki.
    """
    t = testo.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    inizio, fine = t.find("{"), t.rfind("}")
    if inizio == -1 or fine <= inizio:
        raise ValueError(f"Nessun oggetto JSON nella risposta: {testo[:200]!r}")
    return json.loads(t[inizio : fine + 1])
