---
name: weekly-maintenance
description: Run the weekly DeutschOps feedback-loop maintenance pass (weak_cards.py + b1_gap.py) that CLAUDE.md recommends running on a weekly cadence.
disable-model-invocation: true
---

# Weekly Maintenance

Runs the weekly feedback-loop tools CLAUDE.md recommends: `weak_cards.py` and `b1_gap.py`. (`error_extractor.py` already runs automatically as part of `main.py`'s post-pipeline steps, so it's not repeated here.)

## Usage

`/weekly-maintenance`

## Steps

1. Activate the venv and set `PYTHONIOENCODING=utf-8` as usual for this project.
2. Run `python weak_cards.py` to identify the weakest Anki cards (highest lapses/ease). If the user wants targeted practice exercises, also run `python weak_cards.py --practice`.
3. Run `python b1_gap.py` to get a gap analysis against the B1 curriculum — concrete topics worth proposing to Stefanie for upcoming lessons.
4. Summarize both outputs concisely for the user: the top weak cards and the top curriculum gaps. Don't dump raw output — extract the actionable parts.

If either script errors, report the error rather than retrying blindly — both depend on `data/` files (`vocab_db.json`, lesson JSON) being present and on Anki being reachable via AnkiConnect for `weak_cards.py`.

Mention to the user this can be scheduled to run automatically via the `schedule` skill instead of manual weekly invocation.
