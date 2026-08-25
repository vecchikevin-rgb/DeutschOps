# pharma_glossary.py
# Kevin's goal is the Swiss-German pharma job market (Basel). This builds a growing
# professional glossary from the cumulative vocabulary and, on demand, a short
# workplace dialogue (interview / Produktion / Qualitätssicherung) using vocabulary
# he already knows — so professional German grows alongside the general lessons.
#
# Standalone by design: it does NOT change the extractor's JSON contract; it derives
# the professional subset from data/vocab_db.json, so it works on past and future
# lessons uniformly. Cost: 1 Claude call (~€0.02) per run.

import os
import json
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
import anthropic

load_dotenv()
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

GLOSSARY = Path("data/pharma_glossary.json")
DIALOGUE = Path("pdfs")
MODEL = "claude-sonnet-4-5"

SYSTEM = """You help Kevin (Italian, A2→B1) build PROFESSIONAL German for the Swiss
pharmaceutical job market in Basel (manufacturing/production manager background).

From his known vocabulary you (1) select the terms already useful in a professional
/ manufacturing / pharma / business context, (2) add the 15 most important MISSING
B1-level professional terms he should learn next (production, quality, safety,
meetings, job interview), and (3) write a SHORT realistic workplace dialogue
(8-12 turns, A2→B1) he can read aloud — a Vorstellungsgespräch or a Produktions-/
Qualitätssicherung situation — reusing his known words plus a few of the new ones.

Return ONLY valid JSON (no backticks):
{"known_professional":[{"de":"<word with article if noun>","en":"<gloss>"}],
 "to_learn":[{"de":"<word>","en":"<gloss>","context":"<Produktion|Qualität|Sicherheit|Meeting|Interview>"}],
 "dialogue_title":"<short>","dialogue":[{"speaker":"<name/role>","de":"<line>","it":"<traduzione>"}]}"""


def _known_vocab() -> list:
    try:
        v = json.loads(Path("data/vocab_db.json").read_text(encoding="utf-8"))
        out = []
        for w in v.get("words", {}).values():
            art = (w.get("article") or "").strip()
            de = w.get("german", "").strip()
            out.append(f"{art + ' ' if art else ''}{de}".strip())
        return [x for x in out if x]
    except Exception:
        return []


def build() -> dict:
    vocab = _known_vocab()
    user = ("KNOWN VOCABULARY (" + str(len(vocab)) + " words):\n" +
            ", ".join(sorted(vocab)))
    resp = client.messages.create(
        model=MODEL, max_tokens=4000, system=SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    cost = (resp.usage.input_tokens * 0.000003 + resp.usage.output_tokens * 0.000015)
    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:-1])
    s, e = raw.find("{"), raw.rfind("}") + 1
    data = json.loads(raw[s:e])
    data["generated"] = datetime.now().isoformat(timespec="seconds")
    GLOSSARY.parent.mkdir(exist_ok=True)
    GLOSSARY.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"   Glossario pharma salvato: {GLOSSARY} | {cost:.3f} EUR")
    return data


def write_dialogue_txt(data: dict) -> Path:
    DIALOGUE.mkdir(exist_ok=True)
    out = DIALOGUE / f"pharma_dialog_{datetime.now():%Y-%m-%d}.txt"
    lines = [f"# {data.get('dialogue_title','Workplace-Dialog')}",
             f"# Basel · Pharma · {datetime.now():%d %b %Y}", ""]
    for t in data.get("dialogue", []):
        lines.append(f"{t.get('speaker','')}: {t.get('de','')}")
        if t.get("it"):
            lines.append(f"   ({t['it']})")
    lines += ["", "── Da imparare ──"]
    for w in data.get("to_learn", []):
        lines.append(f"• {w.get('de','')} — {w.get('en','')} [{w.get('context','')}]")
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def print_report(data: dict):
    print(f"\n{'='*56}\n  GLOSSARIO PHARMA / BASILEA\n{'='*56}")
    print(f"  Già utili: {len(data.get('known_professional',[]))} termini · "
          f"Da imparare: {len(data.get('to_learn',[]))}")
    print("\n  ── Prossimi 15 termini professionali ──")
    for w in data.get("to_learn", [])[:15]:
        print(f"    {w.get('de',''):28s} {w.get('en','')[:24]:24s} [{w.get('context','')}]")
    print(f"\n  Dialogo: „{data.get('dialogue_title','')}“ "
          f"({len(data.get('dialogue',[]))} battute)")
    print(f"{'='*56}\n")


if __name__ == "__main__":
    d = build()
    print_report(d)
    out = write_dialogue_txt(d)
    print(f"  Dialogo salvato: {out}")
