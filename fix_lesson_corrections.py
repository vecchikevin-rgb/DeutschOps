# fix_lesson_corrections.py
# Applica le correzioni di Stefanie ai JSON delle lezioni esistenti

import json
from pathlib import Path

def fix_lesson(json_path: str):
    path = Path(json_path)
    if not path.exists():
        print(f"❌ Non trovato: {json_path}")
        return

    data = json.loads(path.read_text(encoding="utf-8"))
    changes = []

    # Fix vocabolario
    new_vocab = []
    for w in data.get("vocabulary", []):
        german = w.get("german", "")
        
        # Fix 1: sollen — correzione traduzione
        if german == "sollen":
            w["english"] = "shall (asking for opinion/suggestion)"
            w["example_de"] = "Soll ich ihm schreiben?"
            w["example_it"] = "Glielo scrivo? (chiedo opinione)"
            changes.append("sollen: fixed translation and example")

        # Fix 2: verreisen — esempio sbagliato
        if german == "verreisen":
            w["english"] = "to go on a trip (no specific destination)"
            w["example_de"] = "Ich verreise nächste Woche."
            w["example_it"] = "La settimana prossima parto per un viaggio."
            changes.append("verreisen: fixed example sentence")

        # Fix 4: keine Ahnung — sposta in phrases, rimuovi da vocab
        if german == "Ahnung":
            changes.append("Ahnung: moved to phrases as fixed expression")
            continue  # rimuovi dal vocab

        # Fix 5: die Sorge — traduzione più precisa
        if german == "Sorge":
            w["english"] = "concern"
            changes.append("Sorge: corrected to 'concern'")

        # Fix 6: egal — sposta in phrases, rimuovi da vocab
        if german == "egal":
            changes.append("egal: moved to phrases as fixed expression")
            continue  # rimuovi dal vocab

        # Fix 7: mindestens — esempio corretto
        if german == "mindestens":
            w["example_de"] = "Du brauchst mindestens 14 GB."
            w["example_it"] = "Hai bisogno di almeno 14 GB."
            changes.append("mindestens: fixed example sentence")

        # Fix 3: AI → KI
        for field in ["example_de", "example_it", "english", "italian"]:
            if field in w and " AI " in w[field]:
                w[field] = w[field].replace(" AI ", " KI ")
                changes.append(f"{german}: AI→KI in {field}")

        new_vocab.append(w)

    data["vocabulary"] = new_vocab

    # Fix 4+6: aggiungi keine Ahnung e es ist mir egal alle phrases se non ci sono
    phrases = data.get("phrases", [])
    existing_phrases = [p.get("german","") for p in phrases]

    if "Ich habe keine Ahnung" not in existing_phrases and \
       "Ich habe keine Ahnung, ob..." not in existing_phrases:
        phrases.append({
            "german": "Ich habe keine Ahnung",
            "english": "I have no idea",
            "context": "fixed phrase — expresses complete lack of knowledge"
        })
        changes.append("Added 'keine Ahnung' to phrases")

    if "Es ist mir egal" not in existing_phrases:
        phrases.append({
            "german": "Es ist mir egal",
            "english": "It doesn't matter to me / I don't care",
            "context": "fixed structure — egal only used in this form"
        })
        changes.append("Added 'es ist mir egal' to phrases")

    data["phrases"] = phrases

    # Fix grammar: rimuovi "es ist mir egal" dai grammar_points
    new_grammar = []
    for gp in data.get("grammar_points", []):
        rule = gp.get("rule","").lower()
        if "egal" in rule:
            changes.append(f"Removed from grammar_points: {gp.get('rule')}")
            continue
        new_grammar.append(gp)
    data["grammar_points"] = new_grammar

    # Salva
    if changes:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"✅ {path.name}:")
        for c in changes:
            print(f"   • {c}")
    else:
        print(f"ℹ️  {path.name}: nessuna modifica necessaria")

    return changes


if __name__ == "__main__":
    print("🔧 Applicazione correzioni di Stefanie...\n")
    for f in sorted(Path("data").glob("lezione_*.json")):
        fix_lesson(str(f))
    print("\n✅ Correzioni applicate. Rilancia pdf_gen.py per rigenerare i PDF.")