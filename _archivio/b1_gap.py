# b1_gap.py
# Gap analysis toward Goethe-Zertifikat B1. Turns the lessons from REACTIVE
# (whatever Stefanie happens to cover) into PLANNED: it maps what's already been
# studied against the canonical B1 grammar curriculum and the recurring error
# categories, and proposes concrete topics to ask Stefanie next.
#
# Cost: 1 Claude call (~€0.02).

import os
import json
from pathlib import Path
from datetime import datetime
from collections import Counter

from dotenv import load_dotenv
import anthropic

load_dotenv()
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

OUT = Path("data/b1_gap.json")
MODEL = "claude-sonnet-4-5"

# Canonical Goethe B1 grammar curriculum — stable checklist to map coverage onto.
B1_GRAMMAR = [
    "Konjunktiv II (würde + Höflichkeit, irreale Bedingung)",
    "Passiv (Präsens, Präteritum, mit Modalverben)",
    "Genitiv (Possessiv + Präpositionen wegen/trotz/während)",
    "Relativsätze (Nominativ/Akkusativ/Dativ, mit Präposition)",
    "Futur I (werden + Infinitiv)",
    "Präteritum der schwachen und starken Verben",
    "Plusquamperfekt + nachdem",
    "Adjektivdeklination (alle Fälle, mit/ohne Artikel)",
    "n-Deklination (der Junge, der Name)",
    "Infinitiv mit zu / um...zu / ohne...zu / statt...zu",
    "Konnektoren: deshalb, trotzdem, sondern, entweder...oder, je...desto",
    "Subjunktionen: obwohl, damit, falls, seitdem, während, bevor",
    "Wechselpräpositionen (Wo/Wohin, Dativ/Akkusativ)",
    "Verben mit festen Präpositionen + Präpositionaladverbien (darüber, worauf)",
    "Reflexive Verben (Akkusativ und Dativ)",
    "Komparativ und Superlativ (attributiv)",
    "indirekte Fragen / Nebensätze mit ob und W-Wörtern",
    "Temporale Angaben: TeKaMoLo / Wortstellung im Mittelfeld",
    "Nomen-Verb-Verbindungen (Redemittel)",
    "Partizip I und II als Adjektiv",
]


def _covered_rules() -> list:
    try:
        g = json.loads(Path("data/grammar_db.json").read_text(encoding="utf-8"))
        return sorted({r.get("rule", "").strip()
                       for r in g.get("rules", {}).values() if r.get("rule")})
    except Exception:
        return []


def _vocab_by_level() -> dict:
    try:
        v = json.loads(Path("data/vocab_db.json").read_text(encoding="utf-8"))
        return dict(Counter(w.get("level", "?") for w in v.get("words", {}).values()))
    except Exception:
        return {}


def _error_categories() -> list:
    try:
        e = json.loads(Path("data/error_db.json").read_text(encoding="utf-8"))
        return Counter(x.get("category", "?") for x in e.get("errors", [])).most_common()
    except Exception:
        return []


SYSTEM = """You are a Goethe B1 examiner and German tutor for Kevin (Italian, A2→B1,
preparing for the Swiss-German pharma job market in Basel).

You receive: (1) the official B1 grammar checklist, (2) the grammar rules already
covered in his lessons, (3) his vocabulary count by CEFR level, (4) his recurring
error categories. Produce an honest gap analysis.

Return ONLY valid JSON (no backticks):
{"b1_grammar":[{"topic":"<from the checklist>","status":"covered|partial|missing","note":"<short>"}],
 "vocab_assessment":"<2-3 sentences on B1 vocab readiness given the level distribution>",
 "priority_next":[{"topic":"<what to ask Stefanie next>","why":"<ties to a gap or a recurring error>"}],
 "stefanie_message":"<a short friendly German message Kevin can send Stefanie proposing the next 3 topics>"}

priority_next: exactly 5, ordered by importance. Tie them to his recurring errors where relevant."""


def analyze() -> dict:
    covered = _covered_rules()
    levels = _vocab_by_level()
    errs = _error_categories()

    user = (
        "B1 GRAMMAR CHECKLIST:\n" + "\n".join(f"- {t}" for t in B1_GRAMMAR) +
        f"\n\nALREADY COVERED RULES ({len(covered)}):\n" +
        "\n".join(f"- {r}" for r in covered) +
        f"\n\nVOCAB BY LEVEL: {json.dumps(levels)}" +
        f"\n\nRECURRING ERROR CATEGORIES (count): {json.dumps(errs, ensure_ascii=False)}"
    )
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
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"   Gap analysis salvata: {OUT} | {cost:.3f} EUR")
    return data


def print_report(data: dict):
    print(f"\n{'='*58}\n  GAP ANALYSIS B1 — rotta verso il Zertifikat\n{'='*58}")
    cov = Counter(t["status"] for t in data.get("b1_grammar", []))
    print(f"  Grammatica B1: {cov.get('covered',0)} coperti · "
          f"{cov.get('partial',0)} parziali · {cov.get('missing',0)} mancanti\n")
    print("  ── Da proporre a Stefanie (priorità) ──")
    for i, p in enumerate(data.get("priority_next", []), 1):
        print(f"   {i}. {p['topic']}")
        print(f"      → {p['why']}")
    print(f"\n  ── Messaggio pronto per Stefanie ──\n  {data.get('stefanie_message','')}")
    print(f"{'='*58}\n")


if __name__ == "__main__":
    print_report(analyze())
