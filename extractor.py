# extractor.py
import os
import json
from pathlib import Path
from dotenv import load_dotenv
import anthropic

load_dotenv()
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

EXTRACTION_PROMPT = """You are an expert German language tutor.
The student is Kevin, Italian, level A2→B1, studying via English with a native German speaker.
The lesson transcript is in English with German examples and occasional Italian.

Extract ONLY valid JSON, zero backtick, zero extra text.

Format:
{
  "lesson_number": "progressive number if deducible, else empty string",
  "topic": "main topic in 5 words",
  "summary_en": "lesson summary in English (max 120 words)",
  "summary_it": "same summary in Italian",
  "vocabulary": [
    {
      "german": "Sorge",
      "article": "die",
      "plural": "die Sorgen",
      "category": "noun",
      "italian": "la preoccupazione",
      "english": "worry, concern",
      "example_de": "Mach dir keine Sorgen.",
      "example_it": "Non preoccuparti.",
      "level": "A2"
    }
  ],
  "grammar_points": [
    {
      "rule": "rule name",
      "explanation_en": "clear explanation in English",
      "examples": ["example 1", "example 2", "example 3"],
      "full_rule": "",
      "common_mistakes": "",
      "exceptions": "",
      "source_verified": false
    }
  ],
  "phrases": [
    {
      "german": "Ich frage mich, ob...",
      "english": "I wonder if...",
      "context": "introducing indirect question"
    }
  ],
  "homework": "homework if mentioned, else empty string",
  "comprehension_questions": [
    {"question_de": "...", "answer_de": "..."}
  ],
  "doc_sections_covered": ["list of doc sections covered"]
}

CRITICAL RULES:
- vocabulary "german" field: NEVER include the article. Base word only.
  CORRECT: {"german": "Sorge", "article": "die"}
  WRONG:   {"german": "die Sorge", "article": "die"}
- category must be one of: verb_regular, verb_irregular, verb_separable,
  verb_modal, noun, adjective, adverb, phrase, expression
- article: der/die/das for nouns, empty string for everything else
- plural: include for nouns when deducible, else empty string
- level: A1, A2, B1, or B2
- All explanations in English only
- grammar_points: max 5, only those explicitly covered in the lesson
- vocabulary: extract ALL new words for A2→B1, no artificial cap
- comprehension_questions: exactly 3
- phrases: English field only, no Italian"""


def parse_json_safe(raw: str, fallback: dict = None) -> dict | None:
    """
    Prova a parsare JSON da una stringa potenzialmente sporca.
    Cerca il primo { e l'ultimo } e prova a parsare quel blocco.
    """
    if not raw or not raw.strip():
        return fallback

    clean = raw.strip()

    # Rimuovi backtick
    if clean.startswith("```"):
        lines = clean.split("\n")
        clean = "\n".join(lines[1:-1]).strip()

    # Trova il blocco JSON principale
    start = clean.find("{")
    end   = clean.rfind("}") + 1
    if start >= 0 and end > start:
        clean = clean[start:end]

    try:
        return json.loads(clean)
    except json.JSONDecodeError as e:
        print(f"   ⚠️  JSON parse error: {e}")
        return fallback


def extract_text_from_response(response) -> str:
    """
    Estrae il testo dalla risposta API, gestendo sia risposte normali
    che risposte con tool use (web search) che hanno blocchi multipli.
    """
    print(f"   Response blocks: {len(response.content)}")

    text_blocks = []
    for i, block in enumerate(response.content):
        btype = getattr(block, "type", "?")
        btext = getattr(block, "text", "")
        print(f"   Block {i}: type={btype} len={len(btext)}")
        if btype == "text" and btext.strip():
            text_blocks.append(btext)

    if not text_blocks:
        return ""

    # Prendi l'ultimo blocco text — è la risposta finale dopo le ricerche
    return text_blocks[-1]


def needs_web_search(grammar_points: list) -> list:
    """
    Controlla quali grammar points necessitano web search.
    Salta quelli già approfonditi in lezioni precedenti.
    """
    seen_rules = {}
    for f in sorted(Path("data").glob("lezione_*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            for gp in d.get("grammar_points", []):
                rule_key = gp.get("rule", "").lower().strip()
                if rule_key and gp.get("full_rule"):
                    seen_rules[rule_key] = gp
        except Exception:
            pass

    to_research = []
    for gp in grammar_points:
        rule_key = gp.get("rule", "").lower().strip()
        if not rule_key:
            continue
        if rule_key not in seen_rules:
            to_research.append(gp)
            print(f"   🆕 New rule: {gp.get('rule')}")
        elif not seen_rules[rule_key].get("common_mistakes"):
            to_research.append(gp)
            print(f"   📝 Incomplete: {gp.get('rule')} — will enrich")
        else:
            print(f"   ✅ Already complete: {gp.get('rule')} — skip")

    return to_research


def enrich_grammar_with_web(grammar_points: list) -> list:
    """
    Usa web search per approfondire i grammar points indicati.
    """
    if not grammar_points:
        return grammar_points

    grammar_prompt = f"""You are an expert German grammar tutor with web search access.
Research each grammar rule below using web search.
Search on: dartmouth.edu/~deutsch, germanveryeasy.com, duden.de

For each rule find and include:
1. Complete rule with ALL forms, cases, conjugation tables
2. Common mistakes Italian speakers make
3. 4 varied example sentences showing different contexts
4. Exceptions and special cases

Grammar points to research:
{json.dumps(grammar_points, ensure_ascii=False, indent=2)}

After your research, return ONLY valid JSON with NO backtick, NO extra text:
{{
  "grammar_points": [
    {{
      "rule": "exact same rule name as input",
      "explanation_en": "complete explanation in English",
      "full_rule": "complete grammar rule with all forms and tables",
      "common_mistakes": "typical mistakes Italian speakers make",
      "examples": ["example 1", "example 2", "example 3", "example 4"],
      "exceptions": "exceptions and special cases",
      "source_verified": true
    }}
  ]
}}"""

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=8000,
        tools=[{
            "type": "web_search_20250305",
            "name": "web_search"
        }],
        messages=[{"role": "user", "content": grammar_prompt}]
    )

    cost = (response.usage.input_tokens * 0.000003 +
            response.usage.output_tokens * 0.000015)
    print(f"   💶 Web search cost: €{cost:.3f}")

    raw = extract_text_from_response(response)
    print(f"   Raw text preview: {repr(raw[:150])}")

    result = parse_json_safe(raw)
    if result:
        enriched = result.get("grammar_points", [])
        if enriched:
            print(f"   ✅ {len(enriched)} rules enriched with web search")
            return enriched

    print("   ⚠️  Could not parse web search result — using base grammar")
    return grammar_points


def extract(transcript_path: str, output_filename: str = None,
            doc_new_content: str = "", doc_full_content: str = "") -> dict:
    """
    Estrae struttura didattica da transcript + novità Google Doc.
    Call 1: vocabolario e struttura base (no web search)
    Call 2: web search solo per regole grammaticali nuove o incomplete
    """
    transcript_path = Path(transcript_path)
    if not transcript_path.exists():
        raise FileNotFoundError(f"Transcript not found: {transcript_path}")

    if output_filename is None:
        output_filename = transcript_path.stem

    output_path  = Path("data") / f"{output_filename}.json"
    transcript_text = transcript_path.read_text(encoding="utf-8")

    print(f"📄 Transcript: {transcript_path.name} ({len(transcript_text)} char)")

    user_content  = f"{EXTRACTION_PROMPT}\n\n"
    user_content += f"=== TRANSCRIPT AUDIO ===\n{transcript_text}\n\n"

    if doc_new_content.strip():
        trimmed = (doc_new_content[-8000:]
                   if len(doc_new_content) > 8000
                   else doc_new_content)
        user_content += f"=== DOC NEW CONTENT ===\n{trimmed}\n\n"
        print(f"📝 Doc content: {len(trimmed)} chars included")
    else:
        print("📝 Doc content: none")

    # ── CALL 1: estrazione base ──────────────────────────────────────────────
    print("🧠 Call 1/2 — Base extraction...")
    response1 = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=8000,
        messages=[{"role": "user", "content": user_content}]
    )

    raw1  = response1.content[0].text.strip()
    data  = parse_json_safe(raw1)
    if not data:
        raise ValueError("Could not parse base extraction response")

    cost1 = (response1.usage.input_tokens * 0.000003 +
             response1.usage.output_tokens * 0.000015)
    print(f"   ✅ {len(data.get('vocabulary',[]))} words, "
          f"{len(data.get('grammar_points',[]))} grammar points | €{cost1:.3f}")

    # ── CALL 2: web search grammatica ────────────────────────────────────────
    grammar_points = data.get("grammar_points", [])
    if grammar_points:
        print("🌐 Call 2/2 — Checking grammar for web search...")
        to_research = needs_web_search(grammar_points)

        if to_research:
            print(f"   Researching {len(to_research)}/{len(grammar_points)} rules...")
            enriched = enrich_grammar_with_web(to_research)

            # Merge: sostituisci solo i punti ricercati
            enriched_map = {gp.get("rule","").lower(): gp for gp in enriched}
            final_grammar = []
            for gp in grammar_points:
                key = gp.get("rule","").lower()
                final_grammar.append(enriched_map.get(key, gp))
            data["grammar_points"] = final_grammar
        else:
            print("   ✅ All rules already complete — web search skipped")
    else:
        print("🌐 No grammar points — skipping web search")

    # Salva
    output_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"\n✅ Saved: {output_path}")
    print(f"📚 Topic: {data.get('topic','N/A')}")
    print(f"📝 Words: {len(data.get('vocabulary',[]))} | "
          f"Grammar: {len(data.get('grammar_points',[]))} | "
          f"Phrases: {len(data.get('phrases',[]))}")

    if data.get("homework"):
        print(f"📌 Homework: {data['homework']}")
    if data.get("doc_sections_covered"):
        print(f"📖 Sections: {', '.join(data['doc_sections_covered'])}")

    print(f"\n--- SUMMARY ---")
    print(f"EN: {data.get('summary_en','')}")

    return data


if __name__ == "__main__":
    extract(
        transcript_path="transcripts/lezione_2026-05-15-stefanie.txt",
        output_filename="lezione_2026-05-15-stefanie",
        doc_new_content="",
        doc_full_content=""
    )