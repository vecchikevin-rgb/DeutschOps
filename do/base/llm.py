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

import json
from dataclasses import dataclass

import requests

from .config import LLMConfig, api_key, llm_config


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


def _anthropic_client():
    """Client creato pigramente: importarlo non deve richiedere una chiave."""
    global _client
    if _client is None:
        import anthropic

        _client = anthropic.Anthropic(api_key=api_key("ANTHROPIC_API_KEY"))
    return _client


def chiama(
    system: str,
    user: str,
    cfg: LLMConfig | None = None,
    *,
    ricerca_web: bool = False,
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
        return _chiama_ollama(system, user, cfg)
    return _chiama_anthropic(system, user, cfg, ricerca_web=ricerca_web)


def _chiama_ollama(system: str, user: str, cfg: LLMConfig) -> tuple[str, Uso]:
    r = requests.post(
        f"{cfg.ollama_host}/api/chat",
        json={
            "model": cfg.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {"num_predict": cfg.max_tokens},
        },
        timeout=1800,   # 7B quantizzato su GTX 980: lento ma accettabile
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
        kwargs["tools"] = [{"type": "web_search_20260209", "name": "web_search"}]

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

    resp = _anthropic_client().messages.create(**kwargs)

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
