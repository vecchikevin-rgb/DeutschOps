# notebooklm_export.py
# Automates synchronization of DeutschOps materials to Google NotebookLM.
# Extracts lessons, grammar master, vocabulary database, and student context,
# and pushes them directly to NotebookLM using the notebooklm-py library.

import os
import sys
import json
import subprocess
import re
from pathlib import Path
from datetime import datetime

STATE_FILE = Path("data/notebooklm_state.json")
CATEGORY_ORDER = [
    "Verbs — Basics",
    "Verbs — Separable & Modal",
    "Verbs — Irregular & Tenses",
    "Sentence Structure — Word Order",
    "Subordinate Clauses",
    "Cases — Kasus",
    "Pronouns",
    "Adjectives & Adverbs",
    "Prepositions",
    "Other Structures",
]

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "notebook_id": None,
        "notebook_title": "DeutschOps — German Learning",
        "last_synced": None,
        "sync_count": 0
    }

def save_state(state: dict):
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

def run_cli(args: list) -> str:
    """Helper to execute the notebooklm CLI from the local virtual environment."""
    # Look for notebooklm executable in standard Windows venv paths
    venv_path = Path("venv/Scripts/notebooklm.exe")
    if not venv_path.exists():
        venv_path = Path(".venv/Scripts/notebooklm.exe")
    
    cmd = [str(venv_path)] if venv_path.exists() else ["notebooklm"]
    cmd.extend(args)
    
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if res.returncode != 0:
        raise Exception(
            f"NotebookLM CLI command {' '.join(cmd)} failed (code {res.returncode}):\n"
            f"Stdout: {res.stdout}\n"
            f"Stderr: {res.stderr}"
        )
    return res.stdout

def ensure_notebook() -> str:
    """Checks if the DeutschOps notebook exists or creates it, setting active context."""
    state = load_state()
    notebook_id = state.get("notebook_id")
    
    # 1. Verify existing ID in the state file
    if notebook_id:
        try:
            res = run_cli(["list", "--json"])
            data = json.loads(res)
            notebooks = data.get("notebooks", [])
            # notebooklm list --json returns a dict with 'notebooks' key
            exists = any(nb.get("id") == notebook_id or nb.get("notebook_id") == notebook_id for nb in notebooks)
            if exists:
                run_cli(["use", notebook_id])
                return notebook_id
        except Exception as e:
            print(f"[WARN] Could not verify existing notebook ID: {e}")

    # 2. Search for notebook by title in the list
    try:
        res = run_cli(["list", "--json"])
        data = json.loads(res)
        notebooks = data.get("notebooks", [])
        for nb in notebooks:
            title = nb.get("title", "")
            if "DeutschOps" in title:
                nb_id = nb.get("id") or nb.get("notebook_id")
                if nb_id:
                    print(f"[FOUND] Found existing notebook: '{title}' (ID: {nb_id})")
                    state["notebook_id"] = nb_id
                    state["notebook_title"] = title
                    save_state(state)
                    run_cli(["use", nb_id])
                    return nb_id
    except Exception as e:
        print(f"[WARN] Could not search notebook list: {e}")

    # 3. Create a new notebook
    title = "DeutschOps — German Learning"
    print(f"[CREATE] Creating new NotebookLM notebook: '{title}'...")
    try:
        run_cli(["create", title])
        # Find the newly created notebook ID
        res = run_cli(["list", "--json"])
        data = json.loads(res)
        notebooks = data.get("notebooks", [])
        for nb in notebooks:
            if "DeutschOps" in nb.get("title", ""):
                nb_id = nb.get("id") or nb.get("notebook_id")
                if nb_id:
                    print(f"[SUCCESS] Created notebook '{title}' (ID: {nb_id})")
                    state["notebook_id"] = nb_id
                    state["notebook_title"] = title
                    save_state(state)
                    run_cli(["use", nb_id])
                    return nb_id
    except Exception as e:
        print(f"[ERROR] Error creating notebook: {e}")
        raise e
    
    raise Exception("Notebook creation succeeded but could not retrieve its ID.")

def build_context_source() -> str:
    """Generates the student context and interaction instructions document."""
    try:
        registry = json.loads(Path("lesson_registry.json").read_text(encoding="utf-8"))
        stats = registry.get("stats", {})
        total_lessons = stats.get("total", 0)
        total_minutes = stats.get("total_minutes", 0)
    except Exception:
        total_lessons = 0
        total_minutes = 0
        
    context = f"""DEUTSCHOPS — STUDY CONTEXT & INSTRUCTIONS
Kevin Vecchi · A2→B1 · Basel Pharma Track
Last Updated: {datetime.now().strftime("%d %b %Y")}
════════════════════════════════════════════════════

STUDENT PROFILE:
- Name: Kevin Vecchi
- Native Language: Italian
- Current Target: Transitioning from A2 to B1 (intermediate German)
- Career context: Industrial manufacturing manager preparing for roles in the Swiss pharmaceutical sector (Basel area)
- Lesson Format: Weekly conversational lessons with Stefanie. Explanations and instruction are in English, with occasional Italian references.

TEACHER PROFILE:
- Name: Stefanie
- Status: Native German speaker, professional German language tutor

STUDY INTERACTION INSTRUCTIONS (For NotebookLM Chat/Notebook generation):
1. Level Constraint: Keep vocabulary and grammatical difficulty strictly in the A2 to B1 range, unless specifically asked to push boundaries.
2. Error Analysis: Note any grammar errors or unnatural phrasing, and explain the correction clearly in English.
3. Contrastive Learning (Italian): Highlight common pitfalls that native Italian speakers face, specifically:
   - Placement of verbs in main vs subordinate clauses
   - Choice of prepositions (e.g., using 'in' vs 'zu' or 'nach')
   - Mixing up 'als' vs 'wie' in comparisons
   - Confusing gender (German grammatical gender often differs from Italian grammatical gender)
4. Phrasing suggestions: If I write a sentence that is grammatically correct but sounds unnatural, propose a standard, more native-sounding alternative (e.g. standard spoken German vs formal written).
5. Vocabulary focus: Highlight vocabulary that is useful for business, pharmaceutical, or professional environments in Switzerland.
6. Preferred term: Use 'die KI' (feminine) instead of 'AI' when referring to artificial intelligence in German.

PROGRESS STATS:
- Total lessons processed: {total_lessons}
- Total audio hours of study: {total_minutes / 60:.1f} hours ({total_minutes} minutes)

GLOSSARY OF KEY TERMS:
- DeutschOps: The automated pipeline that records, transcribes, and extracts lesson materials.
- Redemittel: Set phrases and idioms used to express specific ideas or functions in conversations.
- Dativ/Akkusativ: The two major grammatical cases studied for prepositional and verb-object relationships.
════════════════════════════════════════════════════
"""
    return context

def build_vocab_source() -> str:
    """Consolidates vocabulary from data/vocab_db.json into a clean Markdown table format."""
    try:
        vocab_db = json.loads(Path("data/vocab_db.json").read_text(encoding="utf-8"))
        words = vocab_db.get("words", {})
    except Exception:
        words = {}
    
    # Group by category
    by_category = {}
    for w in words.values():
        cat = w.get("category") or "Other"
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(w)
    
    lines = []
    lines.append("DEUTSCHOPS — VOCABULARY MASTER DATABASE")
    lines.append("Kevin Vecchi · A2→B1 · Stefanie · Basel")
    lines.append(f"Total Words: {len(words)} · Categories: {len(by_category)}")
    lines.append(f"Last updated: {datetime.now().strftime('%d %b %Y')}")
    lines.append("════════════════════════════════════════════════════\n")
    
    # Sort categories alphabetically
    for cat in sorted(by_category.keys()):
        cat_words = by_category[cat]
        cat_words.sort(key=lambda x: x.get("german", "").lower())
        
        lines.append(f"CATEGORY: {cat.upper()} ({len(cat_words)} words)")
        lines.append("────────────────────────────────────────────────────")
        
        for w in cat_words:
            german = w.get("german", "").strip()
            article = w.get("article", "").strip()
            plural = w.get("plural", "").strip()
            english = w.get("english", "").strip()
            italian = w.get("italian", "").strip()
            level = w.get("level", "").strip() or "?"
            example = w.get("example_de", "").strip()
            occurrences = w.get("occurrences", 1)
            
            gender_repr = f" ({article})" if article else ""
            plural_repr = f" (pl. {plural})" if plural else ""
            
            word_line = f"• {german}{gender_repr}{plural_repr} — English: {english} | Italian: {italian} | Level: {level} (Seen {occurrences}x)"
            lines.append(word_line)
            if example:
                lines.append(f"  Example: \"{example}\"")
        lines.append("────────────────────────────────────────────────────\n")
        
    return "\n".join(lines)

def assign_category(rule: str, explanation: str) -> str:
    text = (rule + " " + explanation).lower()
    cat_map = [
        (["separable", "trennbar", "prefix", "trennbare"], "Verbs — Separable & Modal"),
        (["modal", "können", "müssen", "dürfen", "wollen", "sollen", "mögen", "shall", "should", "konjunktiv ii"], "Verbs — Separable & Modal"),
        (["irregular", "unregelmäßig", "vowel change", "umlaut", "strong verb", "ablaut"], "Verbs — Irregular & Tenses"),
        (["perfekt", "präteritum", "futur", "passive", "partizip", "perfect tense", "past tense", "tense", "haben/sein"], "Verbs — Irregular & Tenses"),
        (["verb", "conjugat", "konjugat", "infinitiv", "infinitive", "conjugation"], "Verbs — Basics"),
        (["nebensatz", "subordinate", "conjunction", "weil", "dass", "wenn", "ob", "als", "obwohl", "damit", "indirect question", "word order in"], "Subordinate Clauses"),
        (["word order", "wortstellung", "position", "v2", "verb second", "satzstellung", "sentence structure", "tekamolo", "main clause"], "Sentence Structure — Word Order"),
        (["akkusativ", "dativ", "genitiv", "nominativ", "case", "kasus", "declension", "deklination", "außer", "preposition with dativ"], "Cases — Kasus"),
        (["pronoun", "pronomen", "reflexive", "personal", "possessiv", "relative", "demonstrativ"], "Pronouns"),
        (["adjektiv", "adjective", "adverb", "komparativ", "superlativ", "comparative", "superlative", "gefallen", "dative object"], "Adjectives & Adverbs"),
        (["präposition", "preposition", "mit dativ", "mit akkusativ", "two-way"], "Prepositions"),
    ]
    for keywords, category in cat_map:
        if any(kw in text for kw in keywords):
            return category
    return "Other Structures"

def build_grammar_source() -> str:
    """Consolidates all grammar rules from data/grammar_db.json into a highly detailed plain text reference."""
    try:
        grammar_db = json.loads(Path("data/grammar_db.json").read_text(encoding="utf-8"))
        rules = grammar_db.get("rules", {})
    except Exception:
        rules = {}
    
    categories = {cat: [] for cat in CATEGORY_ORDER}
    for rule in rules.values():
        cat = assign_category(rule.get("rule", ""), rule.get("explanation_en", ""))
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(rule)
        
    lines = []
    lines.append("DEUTSCHOPS — PROGRESSIVE GRAMMAR REFERENCE BOOK")
    lines.append("Kevin Vecchi · A2→B1 · Stefanie · Basel")
    lines.append(f"Total Rules: {len(rules)}")
    lines.append(f"Last updated: {datetime.now().strftime('%d %b %Y')}")
    lines.append("════════════════════════════════════════════════════\n")
    
    for cat in CATEGORY_ORDER:
        cat_rules = categories[cat]
        if not cat_rules:
            continue
            
        lines.append(f"CHAPTER: {cat.upper()} ({len(cat_rules)} rules)")
        lines.append("────────────────────────────────────────────────────\n")
        
        for r in sorted(cat_rules, key=lambda x: x.get("rule", "").lower()):
            rule_name = r.get("rule", "").strip()
            explanation = r.get("explanation_en", "").strip()
            full_rule = r.get("full_rule", "").strip()
            examples = r.get("examples", [])
            mistakes = r.get("common_mistakes", "").strip()
            exceptions = r.get("exceptions", "").strip()
            level = r.get("level", "").strip() or "A2"
            status = "Web verified" if r.get("source_verified") else "From lesson only"
            
            lines.append(f"RULE: {rule_name}")
            lines.append(f"Status: {status} | Level: {level}")
            lines.append("")
            
            if explanation:
                lines.append("EXPLANATION:")
                lines.append(explanation)
                lines.append("")
                
            if full_rule:
                lines.append("COMPLETE RULE DEFINITION & TABLES:")
                lines.append(full_rule)
                lines.append("")
                
            if examples:
                lines.append("EXAMPLES:")
                for ex in examples:
                    lines.append(f"→ {ex}")
                lines.append("")
                
            if mistakes:
                lines.append("COMMON MISTAKES (Italian Speakers):")
                lines.append(mistakes)
                lines.append("")
                
            if exceptions:
                lines.append("EXCEPTIONS & SPECIAL CASES:")
                lines.append(exceptions)
                lines.append("")
                
            lines.append("· · · · · · · · · · · · · · · · · · · · · · · · · · ·\n")
        lines.append("────────────────────────────────────────────────────\n")
        
    return "\n".join(lines)

def build_lessons_source() -> str:
    """Consolidates all lesson files in reverse chronological order (newest first)."""
    data_files = sorted(Path("data").glob("lezione_*.json"))
    data_files.reverse()
    
    lines = []
    lines.append("DEUTSCHOPS — LESSON ARCHIVE")
    lines.append("Kevin Vecchi · A2→B1 · Stefanie · Basel")
    lines.append(f"Total Lessons: {len(data_files)}")
    lines.append(f"Last updated: {datetime.now().strftime('%d %b %Y')}")
    lines.append("════════════════════════════════════════════════════\n")
    
    for f in data_files:
        try:
            lesson_data = json.loads(f.read_text(encoding="utf-8"))
            lesson_date = f.stem.replace("lezione_", "").split("-stefanie")[0].split("-v")[0]
            
            topic = lesson_data.get("topic", "N/A")
            summary_en = lesson_data.get("summary_en", "") or lesson_data.get("summary", {}).get("en", "")
            summary_it = lesson_data.get("summary_it", "") or lesson_data.get("summary", {}).get("it", "")
            vocab = lesson_data.get("vocabulary", [])
            grammar = lesson_data.get("grammar_points", [])
            phrases = lesson_data.get("phrases", [])
            homework = lesson_data.get("homework", "")
            
            lines.append(f"LESSON: {topic}")
            lines.append(f"Date: {lesson_date}")
            lines.append("────────────────────────────────────────────────────")
            
            if summary_en:
                lines.append("SUMMARY (English):")
                lines.append(summary_en)
                lines.append("")
                
            if summary_it:
                lines.append("SUMMARY (Italian):")
                lines.append(summary_it)
                lines.append("")
                
            if vocab:
                lines.append("VOCABULARY LEARNED:")
                for w in vocab:
                    art = f"{w.get('article', '')} " if w.get("article") else ""
                    base = w.get("german", "")
                    if art and base.lower().startswith(art.strip().lower() + " "):
                        base = base[len(art.strip()) + 1:]
                    eng = w.get("english", "")
                    it = w.get("italian", "")
                    lvl = w.get("level", "")
                    lvl_str = f" [{lvl}]" if lvl else ""
                    lines.append(f"• {art}{base} — {eng} / {it}{lvl_str}")
                lines.append("")
                
            if grammar:
                lines.append("GRAMMAR POINTS DISCUSSED:")
                for gp in grammar:
                    lines.append(f"📐 {gp.get('rule', '')}")
                    exp = gp.get("explanation_en", "")
                    if exp:
                        lines.append(f"   {exp}")
                    for ex in gp.get("examples", [])[:2]:
                        lines.append(f"   Example: {ex}")
                lines.append("")
                
            if phrases:
                lines.append("USEFUL PHRASES / REDEMITTEL:")
                for p in phrases:
                    german = p.get("german", "")
                    translation = p.get("english", "") or p.get("italian", "")
                    ctx = p.get("context", "")
                    ctx_str = f" ({ctx})" if ctx else ""
                    lines.append(f"• \"{german}\" — {translation}{ctx_str}")
                lines.append("")
                
            if homework:
                lines.append("HOMEWORK ASSIGNED:")
                lines.append(homework)
                lines.append("")
                
            lines.append("════════════════════════════════════════════════════\n")
        except Exception as e:
            print(f"[WARN] Error building lesson archive for {f.name}: {e}")
            
    return "\n".join(lines)

def push_source(title: str, content: str):
    """Pushes a source to NotebookLM. Deletes existing source with same title, writes new file, and uploads."""
    print(f"\n[PUSH] Pushing source: '{title}'...")
    
    temp_dir = Path("data")
    temp_dir.mkdir(exist_ok=True)
    
    # Google NotebookLM gives the source the name of the file uploaded.
    # Therefore, we name the file exactly like our target title to ensure perfect names.
    safe_title = re.sub(r'[<>:"/\\|?*]', '-', title).strip()
    temp_file = temp_dir / f"{safe_title}.md"
    
    try:
        temp_file.write_text(content, encoding="utf-8")
        
        # 1. Try to delete the old source by title
        print(f" - Deleting old source (if exists) via delete-by-title...")
        try:
            run_cli(["source", "delete-by-title", title])
        except Exception as e:
            # delete-by-title fails if source does not exist, which is fine!
            pass
            
        # 2. Upload the new source file
        print(f" - Uploading new source file: {temp_file.name}...")
        run_cli(["source", "add", str(temp_file)])
        print(f" [SUCCESS] Source '{title}' successfully synchronized!")
    except Exception as e:
        print(f" [ERROR] Failed to push source '{title}': {e}")
        raise e
    finally:
        # Clean up temp file
        if temp_file.exists():
            try:
                temp_file.unlink()
            except Exception:
                pass

def _sync_all_sources():
    push_source("DeutschOps Context & Instructions", build_context_source())
    push_source("DeutschOps Lesson Archive", build_lessons_source())
    push_source("DeutschOps Vocabulary Master", build_vocab_source())
    push_source("DeutschOps Grammar Book", build_grammar_source())
    state = load_state()
    state["last_synced"] = datetime.now().isoformat()
    state["sync_count"] = state.get("sync_count", 0) + 1
    save_state(state)

def update_from_lesson(lesson_json_path: str):
    """Updates NotebookLM with all cumulative information. Called after processing a new lesson."""
    print("\n" + "="*60)
    print("DeutschOps — NotebookLM Incremental Sync")
    print("="*60)
    ensure_notebook()
    _sync_all_sources()
    print("\n" + "="*60)
    print("NotebookLM Sync completed successfully!")
    print("="*60)

def full_sync():
    """Full synchronization of all files to NotebookLM from scratch."""
    print("\n" + "="*60)
    print("DeutschOps — NotebookLM Full Rebuild")
    print("="*60)
    ensure_notebook()
    _sync_all_sources()
    print("\n" + "="*60)
    print("Full NotebookLM Sync completed successfully!")
    print("="*60)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Synchronize DeutschOps data with Google NotebookLM.")
    parser.add_argument("--full", action="store_true", help="Perform a full rebuild and sync of all 4 sources.")
    parser.add_argument("--lesson", type=str, help="Incremental sync triggered by a specific lesson JSON path.")
    parser.add_argument("--check", action="store_true", help="Check NotebookLM auth and notebook existence.")
    
    args = parser.parse_args()
    
    try:
        if args.check:
            print("[CHECK] Checking NotebookLM status...")
            run_cli(["auth", "check"])
            nb_id = ensure_notebook()
            print(f"[OK] Auth and context OK. Active Notebook ID: {nb_id}")
        elif args.lesson:
            update_from_lesson(args.lesson)
        elif args.full or (not args.check and not args.lesson):
            full_sync()
    except Exception as e:
        print(f"\n[ERROR] Execution failed: {e}")
        sys.exit(1)
