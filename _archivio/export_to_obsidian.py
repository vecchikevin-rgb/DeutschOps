# export_to_obsidian.py
# Esporta grammar_db e book_db in formato Obsidian (.md)
# Genera note collegate con il grafo delle connessioni
# Uso: python export_to_obsidian.py --vault "C:\Users\vecch\ObsidianVault\DeutschOps"

import json
import sys
import re
from pathlib import Path
from datetime import datetime

GRAMMAR_DB = Path("data/grammar_db.json")
BOOK_DB    = Path("data/book_db.json")

CATEGORY_EMOJI = {
    "Verbs — Basics":                    "🟢",
    "Verbs — Separable & Modal":         "🔵",
    "Verbs — Irregular & Tenses":        "🟣",
    "Sentence Structure — Word Order":   "🟡",
    "Subordinate Clauses":               "🟠",
    "Cases — Kasus":                     "🔴",
    "Pronouns":                          "⚪",
    "Adjectives & Adverbs":              "🟤",
    "Prepositions":                      "⚫",
    "Other Structures":                  "⬜",
}

LEVEL_TAG = {"A1": "#A1", "A2": "#A2", "B1": "#B1", "B2": "#B2"}


def safe_filename(name: str) -> str:
    """Converte un nome in filename sicuro per Obsidian."""
    return re.sub(r'[<>:"/\\|?*]', '-', name).strip()


def assign_category(rule: str, explanation: str) -> str:
    text = (rule + " " + explanation).lower()
    cat_map = [
        (["separable","trennbar","prefix"],              "Verbs — Separable & Modal"),
        (["modal","sollen","können","müssen","dürfen"],  "Verbs — Separable & Modal"),
        (["irregular","vowel change","umlaut"],          "Verbs — Irregular & Tenses"),
        (["perfekt","prateritum","futur","tense"],       "Verbs — Irregular & Tenses"),
        (["verb","conjugat"],                            "Verbs — Basics"),
        (["nebensatz","subordinate","weil","dass","ob"], "Subordinate Clauses"),
        (["word order","wortstellung","position"],       "Sentence Structure — Word Order"),
        (["akkusativ","dativ","nominativ","case"],       "Cases — Kasus"),
        (["pronoun","reflexive","possessiv"],            "Pronouns"),
        (["adjective","adverb","comparative"],           "Adjectives & Adverbs"),
        (["preposition","praposition"],                  "Prepositions"),
    ]
    for keywords, cat in cat_map:
        if any(k in text for k in keywords):
            return cat
    return "Other Structures"


def make_grammar_note(rule: dict, knowledge_map: dict) -> str:
    """Genera una nota Obsidian per una regola grammaticale."""
    name        = rule.get("rule", "")
    explanation = rule.get("explanation_en", "")
    full_rule   = rule.get("full_rule", "")
    examples    = rule.get("examples", [])
    mistakes    = rule.get("common_mistakes", "")
    exceptions  = rule.get("exceptions", "")
    level       = rule.get("level", "")
    book_ch     = rule.get("book_chapter", "")
    book_pg     = rule.get("book_page", "")
    book_order  = rule.get("book_order", 9999)
    verified    = rule.get("source_verified", False)
    category    = assign_category(name, explanation)
    emoji       = CATEGORY_EMOJI.get(category, "⬜")

    # Prerequisiti e derivati dalla knowledge map
    km_entry  = knowledge_map.get(name, {})
    prereqs   = km_entry.get("prerequisites", [])
    # Trova regole che hanno questa come prerequisito
    derived   = [
        r for r, data in knowledge_map.items()
        if name in data.get("prerequisites", [])
    ]

    lines = []

    # Frontmatter YAML
    lines.append("---")
    lines.append(f"rule: \"{name}\"")
    lines.append(f"category: \"{category}\"")
    lines.append(f"level: {level}")
    lines.append(f"book_chapter: \"{book_ch}\"")
    lines.append(f"book_page: {book_pg or 'null'}")
    lines.append(f"book_order: {book_order}")
    lines.append(f"source_verified: {str(verified).lower()}")
    lines.append(f"tags: [german, grammar, {level.lower()}, "
                 f"{category.lower().replace(' ','_').replace('—','').replace('/','').strip()}]")
    lines.append("---")
    lines.append("")

    # Titolo
    lines.append(f"# {emoji} {name}")
    lines.append("")

    # Badge
    badges = []
    if level:
        badges.append(f"`{level}`")
    if book_ch:
        badges.append(f"`{book_ch}`")
    if book_pg:
        badges.append(f"`p.{book_pg}`")
    if verified:
        badges.append("`✅ Web verified`")
    else:
        badges.append("`📝 From lesson`")
    if badges:
        lines.append("  ".join(badges))
        lines.append("")

    # Categoria con link
    lines.append(f"**Category:** [[{category}]]")
    lines.append("")

    # Spiegazione
    if explanation:
        lines.append("## Explanation")
        lines.append("")
        lines.append(explanation)
        lines.append("")

    # Regola completa
    if full_rule:
        lines.append("## Complete Rule")
        lines.append("")
        lines.append("```")
        lines.append(full_rule)
        lines.append("```")
        lines.append("")

    # Esempi
    if examples:
        lines.append("## Examples")
        lines.append("")
        for ex in examples:
            lines.append(f"- {ex}")
        lines.append("")

    # Errori comuni
    if mistakes:
        lines.append("## ⚠️ Common Mistakes (Italian Speakers)")
        lines.append("")
        for line in mistakes.split("\n"):
            if line.strip():
                lines.append(f"> {line.strip()}")
        lines.append("")

    # Eccezioni
    if exceptions:
        lines.append("## 🔸 Exceptions")
        lines.append("")
        for line in exceptions.split("\n"):
            if line.strip():
                lines.append(f"- {line.strip()}")
        lines.append("")

    # Prerequisiti (con wikilink)
    if prereqs:
        lines.append("## Prerequisites")
        lines.append("")
        for p in prereqs:
            lines.append(f"- [[{p}]]")
        lines.append("")

    # Regole collegate (derivate)
    if derived:
        lines.append("## Leads To")
        lines.append("")
        for d in derived[:5]:
            lines.append(f"- [[{d}]]")
        lines.append("")

    # Link al libro
    if book_ch or book_pg:
        lines.append("## 📗 Book Reference")
        lines.append("")
        lines.append(f"**DaF Kompakt Neu A1-B1** — "
                     f"{book_ch}, page {book_pg}")
        lines.append("")

    lines.append("---")
    lines.append(f"*Generated by DeutschOps on "
                 f"{datetime.now().strftime('%Y-%m-%d')}*")

    return "\n".join(lines)


def make_category_note(category: str, rules: list) -> str:
    """Genera una nota indice per una categoria."""
    emoji = CATEGORY_EMOJI.get(category, "⬜")
    lines = []

    lines.append("---")
    lines.append(f"type: category_index")
    lines.append(f"category: \"{category}\"")
    lines.append(f"tags: [german, grammar, index]")
    lines.append("---")
    lines.append("")
    lines.append(f"# {emoji} {category}")
    lines.append("")
    lines.append(f"**{len(rules)} rules** in this category, "
                 f"ordered by book progression")
    lines.append("")

    # Raggruppa per livello
    for level in ["A1", "A2", "B1", "B2"]:
        level_rules = [r for r in rules if r.get("level") == level]
        if level_rules:
            lines.append(f"## {level}")
            lines.append("")
            for r in sorted(level_rules,
                             key=lambda x: x.get("book_order", 9999)):
                verified = "✅" if r.get("source_verified") else "📝"
                book_ch  = r.get("book_chapter", "")
                lines.append(
                    f"- {verified} [[{r['rule']}]]"
                    + (f" — *{book_ch}*" if book_ch else "")
                )
            lines.append("")

    lines.append("---")
    lines.append(f"*{len(rules)} grammar rules | "
                 f"DeutschOps — Kevin Vecchi*")
    return "\n".join(lines)


def make_lektion_note(lnum: int, ldata: dict) -> str:
    """Genera una nota per una Lektion del libro."""
    level   = ldata.get("level", "")
    title   = ldata.get("lektion_title", f"Lektion {lnum}")
    vocab   = ldata.get("vocabulary", [])
    grammar = ldata.get("grammar_rules", [])
    redemit = ldata.get("redemittel", [])
    pages   = ldata.get("recap_pages", {})

    lines = []
    lines.append("---")
    lines.append(f"lektion: {lnum}")
    lines.append(f"title: \"{title}\"")
    lines.append(f"level: {level}")
    lines.append(f"vocab_count: {len(vocab)}")
    lines.append(f"grammar_count: {len(grammar)}")
    lines.append(f"tags: [german, daf_kompakt, {level.lower()}, lektion]")
    lines.append("---")
    lines.append("")
    lines.append(f"# 📗 Lektion {lnum} — {title}")
    lines.append("")
    lines.append(f"`{level}` | `{len(vocab)} words` | "
                 f"`{len(grammar)} grammar rules` | "
                 f"`{len(redemit)} Redemittel`")
    lines.append("")

    # Grammar rules con wikilink
    if grammar:
        lines.append("## Grammar Rules")
        lines.append("")
        for g in grammar:
            lines.append(f"- [[{g.get('rule','')}]]")
        lines.append("")

    # Redemittel
    if redemit:
        lines.append("## Redemittel")
        lines.append("")
        for r in redemit[:10]:
            lines.append(
                f"- **{r.get('german','')}** — "
                f"{r.get('english','')}"
            )
        if len(redemit) > 10:
            lines.append(f"- *...and {len(redemit)-10} more*")
        lines.append("")

    # Vocabolario per campo semantico
    if vocab:
        lines.append("## Vocabulary")
        lines.append("")
        fields = {}
        for w in vocab:
            sf = w.get("semantic_field", "Other")
            fields.setdefault(sf, []).append(w)

        for field, words in list(fields.items())[:6]:
            lines.append(f"### {field}")
            for w in words[:8]:
                art  = f"{w.get('article','')} " if w.get("article") else ""
                base = w.get("german", "")
                eng  = w.get("english", "")
                lines.append(f"- **{art}{base}** — {eng}")
            if len(words) > 8:
                lines.append(f"- *...+{len(words)-8} more*")
            lines.append("")

    lines.append("---")
    lines.append(f"*DaF Kompakt Neu A1-B1 — "
                 f"DeutschOps*")
    return "\n".join(lines)

def make_vocab_note(word: dict) -> str:
    """Genera una nota Obsidian per una parola del vocabolario."""
    german   = word.get("german", "")
    article  = word.get("article", "")
    plural   = word.get("plural", "")
    english  = word.get("english", "")
    italian  = word.get("italian", "")
    category = word.get("category", "")
    level    = word.get("level", "")
    field    = word.get("semantic_field", "")
    lektion  = word.get("lektion_num", "")
    book_pg  = word.get("book_page", "")
    audio    = word.get("audio_ref", "")

    full_german = f"{article} {german}".strip() if article else german

    lines = []
    lines.append("---")
    lines.append(f"german: \"{full_german}\"")
    lines.append(f"english: \"{english}\"")
    lines.append(f"italian: \"{italian}\"")
    lines.append(f"article: \"{article}\"")
    lines.append(f"plural: \"{plural}\"")
    lines.append(f"category: \"{category}\"")
    lines.append(f"level: {level}")
    lines.append(f"semantic_field: \"{field}\"")
    lines.append(f"lektion: {lektion or 'null'}")
    lines.append(f"book_page: {book_pg or 'null'}")
    lines.append(f"tags: [german, vocab, {level.lower()}, "
                 f"{category.lower().replace('_','-')}, "
                 f"daf-kompakt]")
    lines.append("---")
    lines.append("")

    # Titolo con colore per categoria
    cat_emoji = {
        "noun": "🔵", "verb": "🟢", "verb_regular": "🟢",
        "verb_irregular": "🟣", "verb_separable": "🔷",
        "verb_modal": "🟢", "adjective": "🔴",
        "adverb": "🟡", "phrase": "⬜", "expression": "⬜"
    }
    emoji = cat_emoji.get(category, "⬜")
    lines.append(f"# {emoji} {full_german}")
    lines.append("")

    # Badge
    badges = [f"`{level}`", f"`{category}`"]
    if field:
        badges.append(f"`{field}`")
    lines.append("  ".join(badges))
    lines.append("")

    # Traduzioni
    lines.append("## Translations")
    lines.append("")
    lines.append(f"| 🇩🇪 German | 🇬🇧 English | 🇮🇹 Italian |")
    lines.append(f"|-----------|-----------|-----------|")
    lines.append(f"| **{full_german}** | {english} | {italian} |")
    if plural:
        lines.append(f"| Plural: {plural} | | |")
    lines.append("")

    # Link al libro
    if lektion:
        lines.append("## 📗 Book Reference")
        lines.append("")
        lines.append(f"**DaF Kompakt Neu A1-B1** — "
                     f"Lektion {lektion}, p.{book_pg}")
        if audio:
            lines.append(f"🔊 Audio track: {audio}")
        lines.append("")

    # Link semantici
    lines.append("## Related")
    lines.append("")
    if field:
        lines.append(f"- Field: [[vocab_field_{safe_filename(field)}]]")
    if lektion:
        lines.append(f"- Source: Lektion {lektion}")
    lines.append("")

    lines.append("---")
    lines.append(f"*DeutschOps — DaF Kompakt Neu A1-B1*")
    return "\n".join(lines)


def make_vocab_field_note(field: str, words: list) -> str:
    """Genera una nota indice per un campo semantico."""
    lines = []
    lines.append("---")
    lines.append(f"type: vocab_field")
    lines.append(f"field: \"{field}\"")
    lines.append(f"word_count: {len(words)}")
    lines.append(f"tags: [german, vocab, semantic-field]")
    lines.append("---")
    lines.append("")
    lines.append(f"# 📚 {field}")
    lines.append("")
    lines.append(f"**{len(words)} words** in this semantic field")
    lines.append("")

    # Raggruppa per livello
    for level in ["A1", "A2", "B1"]:
        lw = [w for w in words if w.get("level") == level]
        if lw:
            lines.append(f"## {level} ({len(lw)} words)")
            lines.append("")
            for w in sorted(lw, key=lambda x: x.get("german","")):
                art  = f"{w.get('article','')} " if w.get("article") else ""
                base = w.get("german","")
                eng  = w.get("english","")
                lines.append(f"- [[{art}{base}]] — {eng}")
            lines.append("")

    lines.append("---")
    lines.append("*DeutschOps — DaF Kompakt Neu A1-B1*")
    return "\n".join(lines)

def make_index_note(all_rules: list,
                     lektionen: dict) -> str:
    """Genera la nota indice principale."""
    lines = []
    lines.append("---")
    lines.append("type: index")
    lines.append("tags: [german, index, deutschops]")
    lines.append("---")
    lines.append("")
    lines.append("# 🇩🇪 DeutschOps — German Grammar")
    lines.append("")
    lines.append(f"**{len(all_rules)} grammar rules** | "
                 f"**{len(lektionen)} Lektionen** | "
                 f"Kevin Vecchi | A2→B2")
    lines.append("")
    lines.append(f"*Last updated: "
                 f"{datetime.now().strftime('%d %b %Y')}*")
    lines.append("")

    lines.append("## Grammar Categories")
    lines.append("")
    from collections import Counter
    cats = Counter(
        assign_category(r.get("rule",""), r.get("explanation_en",""))
        for r in all_rules
    )
    for cat, count in sorted(cats.items(),
                              key=lambda x: x[1], reverse=True):
        emoji = CATEGORY_EMOJI.get(cat, "⬜")
        lines.append(f"- {emoji} [[{cat}]] ({count} rules)")
    lines.append("")

    lines.append("## By Level")
    lines.append("")
    for level in ["A1", "A2", "B1", "B2"]:
        level_rules = [r for r in all_rules
                       if r.get("level") == level]
        if level_rules:
            lines.append(f"### {level} ({len(level_rules)} rules)")
            for r in sorted(level_rules,
                             key=lambda x: x.get("book_order",9999))[:8]:
                lines.append(f"- [[{r['rule']}]]")
            if len(level_rules) > 8:
                lines.append(f"- *...+{len(level_rules)-8} more*")
            lines.append("")

    lines.append("## Book — DaF Kompakt Neu A1-B1")
    lines.append("")
    for level_name, lnums in [("A1", range(1,9)),
                                ("A2", range(9,19)),
                                ("B1", range(19,31))]:
        lines.append(f"### {level_name}")
        for n in lnums:
            ldata = lektionen.get(str(n), {})
            title = ldata.get("lektion_title", f"Lektion {n}")
            nv    = len(ldata.get("vocabulary", []))
            lines.append(
                f"- [[Lektion {n:02d} — {safe_filename(title)}]] "
                f"({nv} words)"
            )
        lines.append("")

    lines.append("---")
    lines.append("*Generated by [DeutschOps]"
                 "(https://github.com/vecchikevin-rgb/DeutschOps)*")
    return "\n".join(lines)


def export_to_obsidian(vault_path: str):
    """Esporta tutto il grammar_db e book_db in formato Obsidian."""
    vault = Path(vault_path)

    # Struttura cartelle
    grammar_dir  = vault / "Grammar"
    category_dir = vault / "Grammar" / "_Categories"
    lektion_dir  = vault / "Book"

    for d in [grammar_dir, category_dir, lektion_dir]:
        d.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*50}")
    print(f"  DeutschOps → Obsidian Export")
    print(f"  Vault: {vault}")
    print(f"{'='*50}\n")

    # Carica dati
    grammar_db = json.loads(GRAMMAR_DB.read_text(encoding="utf-8"))
    rules_db   = grammar_db.get("rules", {})

    book_db    = {}
    lektionen  = {}
    km         = {}
    if BOOK_DB.exists():
        book_db   = json.loads(BOOK_DB.read_text(encoding="utf-8"))
        lektionen = book_db.get("lektionen", {})
        km        = book_db.get("knowledge_map", {})

    # Fallback knowledge map dal grammar_db
    if not km:
        km = grammar_db.get("knowledge_map", {})

    all_rules = list(rules_db.values())
    print(f"Rules: {len(all_rules)}")
    print(f"Lektionen: {len(lektionen)}")

    # Organizza per categoria
    categories = {}
    for rule in all_rules:
        cat = assign_category(
            rule.get("rule",""), rule.get("explanation_en","")
        )
        categories.setdefault(cat, []).append(rule)

    # 1. Note grammaticali
    print("\nExporting grammar rules...")
    grammar_count = 0
    for rule in sorted(all_rules,
                        key=lambda r: r.get("book_order", 9999)):
        name     = rule.get("rule", "").strip()
        if not name:
            continue
        content  = make_grammar_note(rule, km)
        filename = safe_filename(name) + ".md"
        filepath = grammar_dir / filename
        filepath.write_text(content, encoding="utf-8")
        grammar_count += 1

    print(f"   {grammar_count} grammar notes")

    # 2. Note categorie
    print("Exporting categories...")
    for cat, rules in categories.items():
        if not rules:
            continue
        content  = make_category_note(
            cat, sorted(rules, key=lambda r: r.get("book_order",9999))
        )
        filename = safe_filename(cat) + ".md"
        filepath = category_dir / filename
        filepath.write_text(content, encoding="utf-8")

    print(f"   {len(categories)} category notes")

    # 3. Note Lektionen
    print("Exporting Lektionen...")
    lektion_count = 0
    for lnum_str, ldata in sorted(lektionen.items(),
                                    key=lambda x: int(x[0])):
        lnum    = int(lnum_str)
        title   = ldata.get("lektion_title", f"Lektion {lnum}")
        content = make_lektion_note(lnum, ldata)
        filename = f"Lektion {lnum:02d} — {safe_filename(title)}.md"
        filepath  = lektion_dir / filename
        filepath.write_text(content, encoding="utf-8")
        lektion_count += 1

    print(f"   {lektion_count} Lektion notes")

# 3b. Note vocabolario
    print("Exporting vocabulary...")
    vocab_dir      = vault / "Vocabulary"
    vocab_field_dir = vault / "Vocabulary" / "_Fields"
    vocab_dir.mkdir(exist_ok=True)
    vocab_field_dir.mkdir(exist_ok=True)

    # Raccogli tutto il vocab dal book_db con metadati
    all_vocab = []
    for lnum_str, ldata in lektionen.items():
        lnum  = int(lnum_str)
        pages = ldata.get("recap_pages", {})
        vp    = pages.get("vocab") if isinstance(pages, dict) else None
        for w in ldata.get("vocabulary", []):
            w2 = dict(w)
            w2.setdefault("lektion_num", lnum)
            w2.setdefault("book_page",   vp)
            all_vocab.append(w2)

    # Dedup per parola tedesca
    seen_words = set()
    unique_vocab = []
    for w in all_vocab:
        art  = w.get("article","")
        base = w.get("german","")
        key  = f"{art} {base}".strip().lower()
        if key not in seen_words:
            seen_words.add(key)
            unique_vocab.append(w)

    # Genera note per ogni parola
    vocab_count = 0
    for word in unique_vocab:
        art      = word.get("article","")
        base     = word.get("german","")
        full     = f"{art} {base}".strip() if art else base
        filename = safe_filename(full) + ".md"
        filepath = vocab_dir / filename
        content  = make_vocab_note(word)
        filepath.write_text(content, encoding="utf-8")
        vocab_count += 1

    # Genera note per campi semantici
    fields = {}
    for w in unique_vocab:
        sf = w.get("semantic_field","Other")
        fields.setdefault(sf, []).append(w)

    for field, words in fields.items():
        filename = f"vocab_field_{safe_filename(field)}.md"
        filepath = vocab_field_dir / filename
        content  = make_vocab_field_note(field, words)
        filepath.write_text(content, encoding="utf-8")

    print(f"   {vocab_count} vocabulary notes")
    print(f"   {len(fields)} semantic field notes")

    # 4. Index
    print("Exporting index...")
    index_content = make_index_note(all_rules, lektionen)
    (vault / "DeutschOps Index.md").write_text(
        index_content, encoding="utf-8"
    )

    print(f"\n{'='*50}")
    print(f"  Export complete!")
    print(f"  {grammar_count} grammar notes → {grammar_dir}")
    print(f"  {len(categories)} category notes → {category_dir}")
    print(f"  {lektion_count} Lektion notes → {lektion_dir}")
    print(f"  Index → {vault / 'DeutschOps Index.md'}")
    print(f"\n  Open Obsidian → Open Folder → {vault}")
    print(f"  Then: Settings → Graph View → open graph")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        # Default vault path
        default = Path.home() / "ObsidianVault" / "DeutschOps"
        print(f"Usage: python export_to_obsidian.py PATH_TO_VAULT")
        print(f"Example: python export_to_obsidian.py "
              f"\"C:\\Users\\vecch\\ObsidianVault\\DeutschOps\"")
        print(f"\nUsing default: {default}")
        vault = str(default)
    else:
        vault = sys.argv[1]

    export_to_obsidian(vault)