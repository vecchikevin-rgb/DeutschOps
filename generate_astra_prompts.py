# generate_astra_prompts.py
# Genera un file prompt per ogni argomento trattato nelle lezioni
# I file vanno nella cartella astra_prompts/ pronti da incollare in Astra

import json
from pathlib import Path

PROMPTS_DIR = Path("astra_prompts")
PROMPTS_DIR.mkdir(exist_ok=True)


def build_prompt(lesson_data: dict, lesson_date: str) -> str:
    topic    = lesson_data.get("topic", "")
    summary  = lesson_data.get("summary_en", "")
    vocab    = lesson_data.get("vocabulary", [])
    grammar  = lesson_data.get("grammar_points", [])
    phrases  = lesson_data.get("phrases", [])
    homework = lesson_data.get("homework", "")
    sections = lesson_data.get("doc_sections_covered", [])

    # Vocabolario formattato
    vocab_lines = []
    for w in vocab:
        art = f"{w.get('article','')} " if w.get("article") else ""
        german = w.get("german", "")
        if art and german.lower().startswith(art.strip().lower() + " "):
            german = german[len(art.strip())+1:]
        eng = w.get("english", "")
        lvl = w.get("level", "")
        vocab_lines.append(f"  • {art}{german} — {eng} [{lvl}]")

    # Grammatica formattata
    grammar_lines = []
    for g in grammar:
        rule = g.get("rule", "")
        exp  = g.get("explanation_en", "")
        exs  = g.get("examples", [])
        grammar_lines.append(f"  • {rule}")
        if exp:
            grammar_lines.append(f"    → {exp}")
        for ex in exs[:2]:
            grammar_lines.append(f"    e.g. {ex}")

    # Frasi
    phrase_lines = []
    for p in phrases:
        g = p.get("german", "")
        e = p.get("english", "") or p.get("italian", "")
        phrase_lines.append(f"  • {g} — {e}")

    prompt = f"""=== ASTRA STUDY PROMPT ===
Date: {lesson_date}
Topic: {topic}
Sections: {', '.join(sections) if sections else 'N/A'}

--- CONTEXT FOR ASTRA ---
You are my German tutor. I am Kevin, Italian, level A2-B1.
My lessons are taught in English by a native German speaker (Stefanie).
Today we are reviewing: {topic}

--- LESSON SUMMARY ---
{summary}

--- KEY VOCABULARY ---
{chr(10).join(vocab_lines) if vocab_lines else 'N/A'}

--- GRAMMAR POINTS ---
{chr(10).join(grammar_lines) if grammar_lines else 'N/A'}

--- USEFUL PHRASES ---
{chr(10).join(phrase_lines) if phrase_lines else 'N/A'}

{"--- HOMEWORK ---" + chr(10) + homework if homework else ""}

--- EXERCISES TO GENERATE ---
Based on the above material, please generate:

1. FILL IN THE BLANK (5 sentences)
   Use the key vocabulary above. Leave one word blank per sentence.
   Include the answer below each sentence in a spoiler or after a separator.

2. TRANSLATION DE → EN (5 sentences)
   Use vocabulary and grammar from this lesson.

3. TRANSLATION EN → DE (5 sentences)
   Use vocabulary and grammar from this lesson.

4. DIALOGUE COMPLETION (2 short dialogues, 3-4 lines each)
   Leave one or two lines blank for me to complete.
   Context: everyday situations using today's grammar ({grammar[0].get('rule','') if grammar else ''}).

5. FREE WRITING PROMPT (1 task)
   Ask me to write 3-5 sentences in German using at least 5 words
   from today's vocabulary.

6. GRAMMAR DRILL (5 sentences)
   Focus specifically on: {grammar[0].get('rule','') if grammar else 'today grammar'}
   Show me sentences with errors for me to correct.

--- INSTRUCTIONS ---
- Correct all my answers immediately with explanation in English
- Note recurring mistakes
- Use only A2-B1 vocabulary unless I ask for more
- If I write something correct but unnatural, suggest a more native alternative
=== END PROMPT ===
"""
    return prompt


def generate_all_prompts():
    data_files = sorted(Path("data").glob("lezione_*.json"))

    if not data_files:
        print("❌ No lesson files found in data/")
        return

    generated = 0
    for f in data_files:
        try:
            lesson_data = json.loads(f.read_text(encoding="utf-8"))
            lesson_id   = f.stem.replace("lezione_", "")

            # Nome file pulito basato su topic
            topic = lesson_data.get("topic", "lesson")
            safe_topic = (
                topic.lower()
                    .replace(" ", "_")
                    .replace("/", "-")
                    .replace(",", "")
                    .replace(":", "")
                    [:50]
            )
            filename = f"{lesson_id}_{safe_topic}.txt"
            out_path = PROMPTS_DIR / filename

            prompt = build_prompt(lesson_data, lesson_id)
            out_path.write_text(prompt, encoding="utf-8")
            print(f"✅ {filename}")
            generated += 1

        except Exception as e:
            print(f"❌ {f.name}: {e}")

    print(f"\n📁 {generated} prompt files in: {PROMPTS_DIR.absolute()}")
    print("   Copy any file content and paste into Astra to start studying.")


if __name__ == "__main__":
    generate_all_prompts()