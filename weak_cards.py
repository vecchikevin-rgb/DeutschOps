# weak_cards.py
# Closes the feedback loop with Anki: queries the review stats that AnkiConnect
# already exposes and surfaces YOUR weakest cards (high lapses / low ease / short
# interval). Optionally generates fresh targeted practice sentences (Claude) that
# reuse exactly those weak words, so review effort goes where it's actually needed.
#
# Requires Anki open with AnkiConnect (uses the same helpers as anki_feeder).

import os
import re
import sys
import json
from datetime import datetime
from pathlib import Path

from anki_feeder import ankiconnect, ensure_anki_running, DECK_NAME

WEAK_REPORT = Path("data/weak_cards.json")


def _strip_html(s: str) -> str:
    s = re.sub(r"<br\s*/?>", " ", s or "", flags=re.I)   # <br> -> spazio
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", s).replace("&nbsp;", " ").strip()


def _weakness_score(c: dict) -> float:
    """Higher = weaker. Combines lapses, low ease, and short interval."""
    lapses = c.get("lapses", 0)
    factor = c.get("factor", 2500) or 2500     # ease ×1000 (2500 = 250%)
    interval = c.get("interval", 0)            # days
    score = lapses * 1000
    score += max(0, 2500 - factor)             # penalise low ease
    if 0 < interval < 4:
        score += 800                           # still not "learned"
    return score


def find_weak(limit: int = 20) -> list:
    if not ensure_anki_running():
        print("❌ Anki non raggiungibile.")
        return []
    card_ids = ankiconnect("findCards", query=f'deck:"{DECK_NAME}"')
    if not card_ids:
        print("   Nessuna carta nel deck.")
        return []
    info = ankiconnect("cardsInfo", cards=card_ids)

    reviewed = [c for c in info if c.get("reps", 0) > 0]
    scored = sorted(reviewed, key=_weakness_score, reverse=True)
    weak = []
    for c in scored[:limit]:
        if _weakness_score(c) <= 0:
            continue
        weak.append({
            "front": _strip_html(c.get("fields", {}).get("Fronte", {}).get("value", "")),
            "back": _strip_html(c.get("fields", {}).get("Retro", {}).get("value", "")),
            "lapses": c.get("lapses", 0),
            "ease": round((c.get("factor", 0) or 0) / 10),   # %
            "interval_days": c.get("interval", 0),
            "reps": c.get("reps", 0),
        })
    return weak


def save_and_report(weak: list):
    WEAK_REPORT.parent.mkdir(exist_ok=True)
    WEAK_REPORT.write_text(json.dumps(
        {"generated": datetime.now().isoformat(timespec="seconds"), "cards": weak},
        ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'='*56}\n  CARTE PIÙ DEBOLI ({len(weak)})\n{'='*56}")
    print(f"  {'parola':28s} {'lapses':>6s} {'ease':>5s} {'int':>4s}")
    print(f"  {'-'*28} {'-'*6} {'-'*5} {'-'*4}")
    for c in weak:
        print(f"  {c['front'][:28]:28s} {c['lapses']:6d} {c['ease']:4d}% "
              f"{c['interval_days']:3d}d")
    print(f"{'='*56}")
    print(f"  Salvato in {WEAK_REPORT}")


def generate_practice(weak: list) -> str:
    """Claude generates targeted A2→B1 practice using the weak words."""
    if not weak:
        return ""
    from dotenv import load_dotenv
    import anthropic
    load_dotenv()
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    words = "\n".join(f"- {c['front']} ({c['back']})" for c in weak)
    prompt = (
        "These are the German words/phrases Kevin (Italian, A2→B1) keeps "
        "forgetting in spaced repetition. Create a SHORT targeted practice sheet "
        "to drill exactly these. For each: one fill-in-the-blank sentence (A2→B1, "
        "Basel/pharma context welcome) plus the answer. Group naturally. "
        "Output clean readable text (no JSON).\n\n" + words
    )
    resp = client.messages.create(
        model="claude-sonnet-4-5", max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text


if __name__ == "__main__":
    args = sys.argv[1:]
    limit = 20
    weak = find_weak(limit=limit)
    if not weak:
        print("   Nessuna carta debole trovata (o deck non ancora ripassato).")
        sys.exit(0)
    save_and_report(weak)
    if "--practice" in args:
        print("\nGenerazione foglio di pratica mirato...\n")
        sheet = generate_practice(weak)
        out = Path("pdfs") / f"pratica_mirata_{datetime.now():%Y-%m-%d}.txt"
        out.parent.mkdir(exist_ok=True)
        out.write_text(sheet, encoding="utf-8")
        print(sheet)
        print(f"\nSalvato: {out}")
