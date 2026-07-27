# extractor.py
import os
import json
import requests
from pathlib import Path
from dotenv import load_dotenv
import anthropic

load_dotenv()

LLM_BACKEND  = os.getenv("LLM_BACKEND", "anthropic")   # "anthropic" | "ollama"
OLLAMA_HOST  = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct")

_client = None


def _anthropic_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _client


def call_llm(system: str, user_content: str, max_tokens: int = 8000) -> tuple[str, float]:
    """Dispatch to Anthropic Claude (default) o Ollama locale (LLM_BACKEND=ollama)."""
    if LLM_BACKEND == "ollama":
        resp = requests.post(
            f"{OLLAMA_HOST}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ],
                "stream": False,
                "options": {"num_predict": max_tokens},
            },
            timeout=900,
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"], 0.0

    response = _anthropic_client().messages.create(
        model="claude-sonnet-4-5",
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_content}],
    )
    cost = (response.usage.input_tokens * 0.000003 +
            response.usage.output_tokens * 0.000015)
    return response.content[0].text.strip(), cost

SYSTEM_PROMPT = """You are a German language tutor. Student: Kevin (Italian, A2→B1), lessons in English with native speaker Stefanie. Transcript: English + German examples + occasional Italian.

Return ONLY valid JSON — no backticks, no extra text.

{"lesson_number":"<int or ''>","topic":"<5 words>","summary_en":"<≤120 words>","summary_it":"<Italian>","vocabulary":[{"german":"<base word>","article":"<der|die|das|''>","plural":"<or ''>","category":"<see below>","italian":"<str>","english":"<str>","example_de":"<str>","example_it":"<str>","level":"<A1|A2|B1|B2>"}],"grammar_points":[{"rule":"<str>","explanation_en":"<str>","examples":["<str>"],"full_rule":"","common_mistakes":"","exceptions":"","source_verified":false}],"phrases":[{"german":"<str>","english":"<str>","context":"<str>"}],"homework":"<str or ''>","comprehension_questions":[{"question_de":"<str>","answer_de":"<str>"}],"doc_sections_covered":["<str>"]}

Rules:
- vocabulary.german: base word ONLY, NEVER include article (✓ "Sorge", ✗ "die Sorge")
- category: verb_regular|verb_irregular|verb_separable|verb_modal|noun|adjective|adverb|phrase|expression
- article: der/die/das for nouns, "" otherwise; plural for nouns when deducible, "" otherwise
- grammar_points: max 5, explicitly covered rules only
- vocabulary: ALL new A2→B1 words, no cap
- comprehension_questions: exactly 3
- phrases.english: English only, no Italian

Stefanie's corrections (apply strictly):
- sollen Präsens = "shall I?" (asking opinion), NEVER "should" (= Konjunktiv II sollte)
- verreisen = go on a trip (no destination); reisen nach [place] = travel to a specific place
- German AI = "die KI" not "AI"
- "keine Ahnung" → phrases only: {"german":"Ich habe keine Ahnung","english":"I have no idea","context":"fixed phrase"}
- die Sorge = "concern" not "worry"
- egal → phrases only: {"german":"Es ist mir egal","english":"It does not matter to me"}; NOT in grammar_points
- mindestens example: "Du brauchst mindestens 14 GB" """


def parse_json_safe(raw: str, fallback: dict = None) -> dict | None:
    """Try to parse JSON from a potentially dirty string."""
    if not raw or not raw.strip():
        return fallback

    clean = raw.strip()

    if clean.startswith("```"):
        lines = clean.split("\n")
        clean = "\n".join(lines[1:-1]).strip()

    start = clean.find("{")
    end   = clean.rfind("}") + 1
    if start >= 0 and end > start:
        clean = clean[start:end]

    try:
        return json.loads(clean)
    except json.JSONDecodeError as e:
        print(f"   Warning: JSON parse error: {e}")
        return fallback


def extract_text_from_response(response) -> str:
    """Extract text from API response, handling web search multi-block responses."""
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

    return text_blocks[-1]


def needs_web_search(grammar_points: list) -> list:
    """Check which grammar points need web search. Skip already researched ones."""
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
            print(f"   New rule: {gp.get('rule')}")
        elif not seen_rules[rule_key].get("common_mistakes"):
            to_research.append(gp)
            print(f"   Incomplete: {gp.get('rule')} -- will enrich")
        else:
            print(f"   Already complete: {gp.get('rule')} -- skip")

    return to_research


_GRAMMAR_WEB_SYSTEM = (
    "You are a German grammar expert with web search access. All output in English.\n"
    "Search: dartmouth.edu/~deutsch, germanveryeasy.com, duden.de\n"
    "For each rule provide: complete forms/conjugation tables, Italian-speaker mistakes, 4 example sentences, exceptions.\n"
    'Return ONLY valid JSON, no backticks: {"grammar_points":[{"rule":"<exact input name>","explanation_en":"<str>","full_rule":"<complete with tables>","common_mistakes":"<Italian-speaker errors>","examples":["<str>","<str>","<str>","<str>"],"exceptions":"<str>","source_verified":true}]}'
)


def enrich_grammar_with_web(grammar_points: list) -> list:
    """Use web search to enrich grammar points."""
    if not grammar_points:
        return grammar_points

    user_msg = (
        "Research these grammar rules:\n"
        + json.dumps(grammar_points, ensure_ascii=False, indent=2)
    )

    response = _anthropic_client().messages.create(
        model="claude-sonnet-4-5",
        max_tokens=8000,
        system=_GRAMMAR_WEB_SYSTEM,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": user_msg}]
    )

    cost = (response.usage.input_tokens * 0.000003 +
            response.usage.output_tokens * 0.000015)
    print(f"   Web search cost: {cost:.3f} EUR")

    raw = extract_text_from_response(response)
    print(f"   Raw preview: {repr(raw[:150])}")

    result = parse_json_safe(raw)
    if result:
        enriched = result.get("grammar_points", [])
        if enriched:
            print(f"   {len(enriched)} rules enriched with web search")
            return enriched

    print("   Could not parse web search result -- using base grammar")
    return grammar_points


def extract(transcript_path: str, output_filename: str = None,
            doc_new_content: str = "", visual_context: dict | None = None) -> dict:
    """
    Extract didactic structure from transcript + Google Doc new content + visual context.
    Call 1: base vocabulary and structure (no web search)
    Call 2: web search only for new or incomplete grammar rules
    """
    transcript_path = Path(transcript_path)
    if not transcript_path.exists():
        raise FileNotFoundError(f"Transcript not found: {transcript_path}")

    if output_filename is None:
        output_filename = transcript_path.stem

    output_path     = Path("data") / f"{output_filename}.json"
    transcript_text = transcript_path.read_text(encoding="utf-8")

    print(f"Transcript: {transcript_path.name} ({len(transcript_text)} char)")

    user_content = f"=== TRANSCRIPT ===\n{transcript_text}\n\n"

    if doc_new_content.strip():
        trimmed = (doc_new_content[-8000:]
                   if len(doc_new_content) > 8000
                   else doc_new_content)
        user_content += f"=== DOC NEW CONTENT ===\n{trimmed}\n\n"
        print(f"Doc content: {len(trimmed)} chars included")
    else:
        print("Doc content: none")

    if visual_context and visual_context.get("visual_items"):
        from frame_extractor import format_for_extraction
        visual_text = format_for_extraction(visual_context)
        if visual_text:
            user_content += visual_text
            print(f"Visual content: {visual_context['frames_with_content']}/"
                  f"{visual_context['frames_analyzed']} frame con testo")

    # Call 1: base extraction (Anthropic Claude oppure Ollama locale, LLM_BACKEND=ollama)
    print(f"Call 1/2 -- Base extraction ({LLM_BACKEND})...")
    raw1, cost1 = call_llm(SYSTEM_PROMPT, user_content)
    data = parse_json_safe(raw1)
    if not data:
        raise ValueError("Could not parse base extraction response")

    print(f"   {len(data.get('vocabulary',[]))} words, "
          f"{len(data.get('grammar_points',[]))} grammar points | {cost1:.3f} EUR")

    # Call 2: web search for grammar (solo backend Anthropic -- Ollama non ha web search)
    grammar_points = data.get("grammar_points", [])
    if grammar_points and LLM_BACKEND == "anthropic":
        print("Call 2/2 -- Checking grammar for web search...")
        to_research = needs_web_search(grammar_points)

        if to_research:
            print(f"   Researching {len(to_research)}/{len(grammar_points)} rules...")
            enriched     = enrich_grammar_with_web(to_research)
            enriched_map = {gp.get("rule","").lower(): gp for gp in enriched}
            final_grammar = []
            for gp in grammar_points:
                key = gp.get("rule","").lower()
                final_grammar.append(enriched_map.get(key, gp))
            data["grammar_points"] = final_grammar
        else:
            print("   All rules already complete -- web search skipped")
    elif grammar_points:
        print("   Ollama backend: web search grammar enrichment non disponibile, skip")
    else:
        print("No grammar points -- skipping web search")

    output_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"\nSaved: {output_path}")
    print(f"Topic: {data.get('topic','N/A')}")
    print(f"Words: {len(data.get('vocabulary',[]))} | "
          f"Grammar: {len(data.get('grammar_points',[]))} | "
          f"Phrases: {len(data.get('phrases',[]))}")

    if data.get("homework"):
        print(f"Homework: {data['homework']}")
    if data.get("doc_sections_covered"):
        print(f"Sections: {', '.join(data['doc_sections_covered'])}")

    print(f"\nSummary EN: {data.get('summary_en','')}")

    return data


if __name__ == "__main__":
    extract(
        transcript_path="transcripts/lezione_2026-05-15-stefanie.txt",
        output_filename="lezione_2026-05-15-stefanie",
        doc_new_content="",
    )