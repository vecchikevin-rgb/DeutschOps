# pages/1_Exercises.py
import json
import random
import streamlit as st
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from save_results import save_session_result

st.set_page_config(
    page_title="DeutschOps — Exercises",
    page_icon="✏️",
    layout="wide"
)

st.markdown("""
<style>
    .correct {
        background: #1b5e2020;
        border-left: 4px solid #2e7d32;
        padding: 10px 16px;
        border-radius: 6px;
        color: #81c784;
        margin: 4px 0;
    }
    .wrong {
        background: #b71c1c20;
        border-left: 4px solid #c62828;
        padding: 10px 16px;
        border-radius: 6px;
        color: #ef9a9a;
        margin: 4px 0;
    }
    .partial {
        background: #f57f1720;
        border-left: 4px solid #f57f17;
        padding: 10px 16px;
        border-radius: 6px;
        color: #ffcc02;
        margin: 4px 0;
    }
    .hint-box {
        background: #0d2137;
        border: 1px dashed #1565c0;
        border-radius: 6px;
        padding: 8px 14px;
        margin: 6px 0;
        color: #90caf9;
        font-size: 0.9em;
    }
    .question-card {
        background: #161b22;
        border-radius: 10px;
        padding: 20px 24px;
        margin: 12px 0;
        border: 1px solid #1e3a5f;
    }
    .ex-tag {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 10px;
        font-size: 0.75em;
        background: #1565c020;
        color: #90caf9;
        margin-bottom: 8px;
    }
    .context-box {
        background: #0d2137;
        border-radius: 6px;
        padding: 8px 14px;
        color: #64b5f6;
        font-style: italic;
        font-size: 0.9em;
        margin: 6px 0;
    }
</style>
""", unsafe_allow_html=True)

st.markdown("# ✏️ Practice Exercises")
st.markdown("*Generated from your personal vocabulary and grammar*")
st.divider()


@st.cache_data(ttl=60)
def load_vocab():
    path = Path("data/vocab_db.json")
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("words", {})


@st.cache_data(ttl=60)
def load_lessons():
    lessons = []
    for f in sorted(Path("data").glob("lezione_*.json")):
        try:
            lessons.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    return lessons


words     = load_vocab()
lessons   = load_lessons()
word_list = list(words.values())

if not words:
    st.warning("No vocabulary found. Process a lesson first.")
    st.stop()


# ─── SIDEBAR ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### ⚙️ Session settings")
    n_questions    = st.slider("Questions", 5, 25, 10)
    level_filter   = st.multiselect(
        "Levels", ["A1", "A2", "B1", "B2"],
        default=["A1", "A2", "B1"]
    )
    show_hints     = st.toggle("💡 Show hints", value=True)
    show_context   = st.toggle("📝 Show context sentences", value=True)

    exercise_types = st.multiselect(
        "Exercise types",
        ["DE → EN", "EN → DE", "IT → DE", "Fill in the blank",
         "Article quiz", "Plural quiz", "Grammar fill",
         "Phrase completion", "Word to sentence", "Error correction",
         "Category guess"],
        default=["DE → EN", "EN → DE", "Fill in the blank",
                 "Article quiz", "Grammar fill"]
    )
    st.divider()
    if st.button("🔀 New session", type="primary", use_container_width=True):
        for k in ["exercises","answers","submitted","result_saved"]:
            st.session_state.pop(k, None)
        st.cache_data.clear()
        st.rerun()


# ─── HINT BUILDER ─────────────────────────────────────────────────────────────
def build_hint(word: dict, ex_type: str) -> str:
    """Genera un hint intelligente senza dare la risposta."""
    cat     = word.get("category", "")
    article = word.get("article", "")
    level   = word.get("level", "")
    plural  = word.get("plural", "")
    german  = word.get("german", "")
    english = word.get("english", "")
    example = word.get("example_de", "")

    hints = []

    # Genere per sostantivi
    if cat == "noun" and article:
        gender_map = {"der": "masculine (m)", "die": "feminine (f)", "das": "neuter (n)"}
        hints.append(f"Gender: {gender_map.get(article, article)}")
        if plural:
            hints.append(f"Plural: {plural}")

    # Tipo verbo
    if cat == "verb_separable":
        hints.append("⚡ Separable verb — prefix goes to the end of the sentence")
    elif cat == "verb_irregular":
        hints.append("⚠️ Irregular verb — check the vowel change")
    elif cat == "verb_modal":
        hints.append("🔧 Modal verb — usually followed by infinitive at end")

    # Livello
    hints.append(f"Level: {level}")

    # Parole insolite nella frase (parole > 6 lettere non target)
    if example and ex_type in ["Fill in the blank", "DE → EN"]:
        ex_words = example.split()
        unusual  = [w for w in ex_words
                    if len(w) > 6
                    and w.lower() not in german.lower()
                    and w.lower() not in (english or "").lower()
                    and not w[0].isupper()]  # esclude nomi propri
        if unusual:
            # Prendi al massimo 2 parole insolite
            sample = unusual[:2]
            hints.append(f"Vocab note: '{sample[0]}' = to help you understand the context")

    return " · ".join(hints) if hints else f"Level: {level}"


def build_context(word: dict, ex_type: str) -> str:
    """
    Genera una frase contestuale SENZA la parola target.
    Sostituisce la parola con '___' nella frase esempio.
    """
    example = word.get("example_de", "")
    german  = word.get("german", "")
    article = word.get("article", "")
    if not example or not german:
        return ""

    # Rimuovi articolo duplicato
    base = german
    if article and base.lower().startswith(article.lower() + " "):
        base = base[len(article)+1:].strip()

    # Sostituisci la parola target con ___
    context = example
    for variant in [german, base, base.lower(), base.capitalize(),
                    f"{article} {base}", f"{article} {base.capitalize()}"]:
        if variant in context:
            context = context.replace(variant, "___", 1)
            break

    if context == example:
        return ""  # non siamo riusciti a sostituire
    return context


# ─── EXERCISE GENERATOR ───────────────────────────────────────────────────────
def clean_german(word: dict) -> tuple[str, str]:
    german  = word.get("german", "")
    article = word.get("article", "")
    if article and german.lower().startswith(article.lower() + " "):
        german = german[len(article)+1:].strip()
    return article, german


def fg(word: dict) -> str:
    art, base = clean_german(word)
    return f"{art} {base}".strip() if art else base


def generate_exercises(word_list, lessons, n, types, levels):
    filtered = [w for w in word_list if w.get("level") in levels]
    if len(filtered) < 4:
        filtered = word_list

    grammar_pool = []
    phrase_pool  = []
    for lesson in lessons:
        for gp in lesson.get("grammar_points", []):
            for ex in gp.get("examples", []):
                grammar_pool.append({
                    "example": ex,
                    "rule": gp.get("rule", ""),
                    "explanation": gp.get("explanation_en", "")
                })
        for ph in lesson.get("phrases", []):
            if ph.get("german") and (ph.get("english") or ph.get("italian")):
                phrase_pool.append(ph)

    exercises = []
    attempts  = 0

    while len(exercises) < n and attempts < n * 5:
        attempts += 1
        ex_type = random.choice(types)
        word    = random.choice(filtered)

        art, base = clean_german(word)
        full      = fg(word)
        english   = word.get("english", "")
        italian   = word.get("italian", "")
        example   = word.get("example_de", "")
        ex_it     = word.get("example_it", "")
        cat       = word.get("category", "")
        level     = word.get("level", "")
        plural    = word.get("plural", "")

        hint    = build_hint(word, ex_type)
        context = build_context(word, ex_type)

        if ex_type == "DE → EN" and english:
            exercises.append({
                "type": "text", "tag": "DE → EN",
                "question": f"Translate to English:\n\n**{full}**",
                "answer": english,
                "hint": hint,
                "context": context,
                "example": ex_it if ex_it else ""
            })

        elif ex_type == "EN → DE" and english:
            exercises.append({
                "type": "text", "tag": "EN → DE",
                "question": f"Translate to German:\n\n**{english}**",
                "answer": full,
                "hint": hint,
                "context": context if context else example,
                "example": ""
            })

        elif ex_type == "IT → DE" and italian:
            exercises.append({
                "type": "text", "tag": "IT → DE",
                "question": f"Traduci in tedesco:\n\n**{italian}**",
                "answer": full,
                "hint": hint,
                "context": "",
                "example": ""
            })

        elif ex_type == "Fill in the blank" and example and base:
            blanked  = example
            replaced = False
            for variant in [base, base.lower(), base.capitalize(),
                            full, f"{art} {base}"]:
                if variant in blanked:
                    blanked  = blanked.replace(variant, "_______", 1)
                    replaced = True
                    break
            if replaced:
                exercises.append({
                    "type": "text", "tag": "Fill in the blank",
                    "question": f"Fill in the blank:\n\n*{blanked}*",
                    "answer": base,
                    "answer_alt": full,
                    "hint": hint,
                    "context": f"= {english}" if english else "",
                    "example": ex_it if ex_it else ""
                })

        elif ex_type == "Article quiz" and art and cat == "noun":
            all_arts = ["der", "die", "das"]
            options  = [art] + random.sample([a for a in all_arts if a != art], 2)
            random.shuffle(options)
            exercises.append({
                "type": "mc", "tag": "Article quiz",
                "question": f"What is the article for:\n\n**{base}** *(= {english})*",
                "answer": art,
                "options": options,
                "hint": hint,
                "context": context,
                "example": example
            })

        elif ex_type == "Plural quiz" and plural and cat == "noun":
            exercises.append({
                "type": "text", "tag": "Plural quiz",
                "question": f"What is the plural of:\n\n**{full}** *(= {english})*",
                "answer": plural,
                "hint": hint,
                "context": "",
                "example": example
            })

        elif ex_type == "Grammar fill" and grammar_pool:
            gp      = random.choice(grammar_pool)
            ex_text = gp["example"]
            ws      = ex_text.split()
            if len(ws) >= 3:
                j       = random.randint(1, len(ws)-1)
                target  = ws[j]
                blanked = " ".join(ws[:j] + ["_______"] + ws[j+1:])
                exercises.append({
                    "type": "text", "tag": "Grammar",
                    "question": (
                        f"**Rule:** {gp['rule']}\n\n"
                        f"Complete:\n\n*{blanked}*"
                    ),
                    "answer": target,
                    "answer_alt": ex_text,
                    "hint": gp["explanation"],
                    "context": "",
                    "example": ""
                })

        elif ex_type == "Phrase completion" and phrase_pool:
            ph   = random.choice(phrase_pool)
            g    = ph.get("german", "")
            e    = ph.get("english", "") or ph.get("italian", "")
            ws   = g.split()
            if len(ws) >= 2:
                half    = max(1, len(ws) // 2)
                partial = " ".join(ws[:half]) + " ___"
                exercises.append({
                    "type": "text", "tag": "Phrase completion",
                    "question": (
                        f"Complete the phrase:\n\n**{partial}**\n\n"
                        f"*(meaning: {e})*"
                    ),
                    "answer": g,
                    "hint": ph.get("context", ""),
                    "context": "",
                    "example": ""
                })

        elif ex_type == "Word to sentence" and example:
            exercises.append({
                "type": "text", "tag": "Write a sentence",
                "question": (
                    f"Use **{full}** in a complete German sentence.\n\n"
                    f"*(= {english})*"
                ),
                "answer": example,
                "hint": "Any correct sentence is valid — hint shows one possible answer",
                "context": "",
                "example": ex_it if ex_it else ""
            })

        elif ex_type == "Error correction" and grammar_pool:
            gp      = random.choice(grammar_pool)
            ex_text = gp["example"]
            ws      = ex_text.split()
            if len(ws) >= 3:
                j        = random.randint(1, len(ws)-1)
                ws_error = ws[:]
                ws_error[j], ws_error[-1] = ws_error[-1], ws_error[j]
                exercises.append({
                    "type": "text", "tag": "Error correction",
                    "question": (
                        f"**Rule:** {gp['rule']}\n\n"
                        f"Correct this sentence:\n\n❌ *{' '.join(ws_error)}*"
                    ),
                    "answer": ex_text,
                    "hint": gp["explanation"],
                    "context": "",
                    "example": ""
                })

        elif ex_type == "Category guess" and english:
            cat_labels = {
                "noun": "Noun", "verb_regular": "Regular verb",
                "verb_irregular": "Irregular verb",
                "verb_separable": "Separable verb",
                "verb_modal": "Modal verb", "adjective": "Adjective",
                "adverb": "Adverb", "phrase": "Phrase",
                "expression": "Expression"
            }
            correct_label = cat_labels.get(cat, cat)
            all_cats      = list(set(cat_labels.values()))
            if correct_label in all_cats:
                wrong   = [c for c in all_cats if c != correct_label]
                options = [correct_label] + random.sample(wrong, min(2, len(wrong)))
                random.shuffle(options)
                exercises.append({
                    "type": "mc", "tag": "Word type",
                    "question": f"What type of word is **{full}**?\n\n*(= {english})*",
                    "answer": correct_label,
                    "options": options,
                    "hint": f"Level: {level}",
                    "context": context,
                    "example": example
                })

    return exercises[:n]


# ─── SESSION STATE ────────────────────────────────────────────────────────────
if "exercises" not in st.session_state:
    st.session_state.exercises    = generate_exercises(
        word_list, lessons, n_questions, exercise_types, level_filter
    )
    st.session_state.answers      = [""] * len(st.session_state.exercises)
    st.session_state.submitted    = False
    st.session_state.result_saved = False

exercises = st.session_state.exercises
n_ex      = len(exercises)


# ─── SCORE + SAVE ─────────────────────────────────────────────────────────────
def calc_score():
    correct = 0
    for i, ex in enumerate(exercises):
        user = st.session_state.answers[i].strip().lower()
        ans  = ex["answer"].strip().lower()
        alt  = ex.get("answer_alt", "").strip().lower()
        if user and (user in ans or ans in user or (alt and user in alt)):
            correct += 1
    return correct


if st.session_state.submitted:
    correct = calc_score()
    pct     = int(correct / n_ex * 100) if n_ex else 0
    color   = "#2e7d32" if pct >= 70 else "#f57f17" if pct >= 50 else "#c62828"
    emoji   = "🏆" if pct >= 90 else "✅" if pct >= 70 else "📈" if pct >= 50 else "💪"
    msg     = ("Excellent!" if pct >= 90 else "Good work!" if pct >= 70
               else "Keep practicing!" if pct >= 50 else "Review and retry.")

    st.markdown(
        f'<div style="background:{color}15;border-left:5px solid {color};'
        f'padding:16px;border-radius:8px;margin-bottom:20px">'
        f'<span style="font-size:1.6em;color:{color}">'
        f'{emoji} Score: {correct}/{n_ex} ({pct}%)</span>'
        f'<br><span style="color:#90a4ae">{msg}</span></div>',
        unsafe_allow_html=True
    )

    # Salva risultato una sola volta
    if not st.session_state.result_saved:
        save_session_result(correct, n_ex, exercise_types, level_filter)
        st.session_state.result_saved = True


# ─── RENDER EXERCISES ─────────────────────────────────────────────────────────
for i, ex in enumerate(exercises):
    submitted = st.session_state.submitted
    user_ans  = st.session_state.answers[i]
    ans       = ex["answer"].strip().lower()
    alt       = ex.get("answer_alt", "").strip().lower()
    is_ok     = (
        user_ans.strip().lower() in ans
        or ans in user_ans.strip().lower()
        or (alt and user_ans.strip().lower() in alt)
    ) and len(user_ans.strip()) > 0

    st.markdown('<div class="question-card">', unsafe_allow_html=True)
    st.markdown(
        f'<span class="ex-tag">{ex.get("tag","")}</span>',
        unsafe_allow_html=True
    )
    st.markdown(f"**Q{i+1}.** {ex['question']}")

    # Context sentence (senza la parola)
    if show_context and ex.get("context") and not submitted:
        st.markdown(
            f'<div class="context-box">📝 Context: {ex["context"]}</div>',
            unsafe_allow_html=True
        )

    # Hint prima della risposta
    if show_hints and ex.get("hint") and not submitted:
        st.markdown(
            f'<div class="hint-box">💡 {ex["hint"]}</div>',
            unsafe_allow_html=True
        )

    # Input
    if ex["type"] == "mc":
        if not submitted:
            choice = st.radio(
                f"opt_{i}", ex["options"],
                key=f"ans_{i}",
                label_visibility="collapsed"
            )
            st.session_state.answers[i] = choice
        else:
            user = st.session_state.answers[i]
            if user.lower() == ex["answer"].lower():
                st.markdown(
                    f'<div class="correct">✅ Correct: <b>{ex["answer"]}</b></div>',
                    unsafe_allow_html=True
                )
            else:
                st.markdown(
                    f'<div class="wrong">❌ You answered: {user} &nbsp;|&nbsp; '
                    f'Correct: <b>{ex["answer"]}</b></div>',
                    unsafe_allow_html=True
                )
    else:
        if not submitted:
            val = st.text_input(
                f"ans_{i}", key=f"ans_{i}",
                placeholder="Type your answer...",
                label_visibility="collapsed"
            )
            st.session_state.answers[i] = val
        else:
            user = st.session_state.answers[i]
            if not user.strip():
                st.markdown(
                    f'<div class="partial">⏭️ Skipped &nbsp;|&nbsp; '
                    f'Answer: <b>{ex["answer"]}</b></div>',
                    unsafe_allow_html=True
                )
            elif is_ok:
                st.markdown(
                    f'<div class="correct">✅ Correct! &nbsp; <b>{ex["answer"]}</b></div>',
                    unsafe_allow_html=True
                )
            else:
                extra = (f'<br><i>Full sentence: {ex["answer_alt"]}</i>'
                         if ex.get("answer_alt") else "")
                st.markdown(
                    f'<div class="wrong">❌ You wrote: "{user}" &nbsp;|&nbsp; '
                    f'Correct: <b>{ex["answer"]}</b>{extra}</div>',
                    unsafe_allow_html=True
                )

    # Post-submit: hint + esempio
    if submitted:
        if ex.get("hint"):
            st.caption(f"💡 {ex['hint']}")
        if ex.get("example"):
            st.caption(f"📝 {ex['example']}")

    st.markdown('</div>', unsafe_allow_html=True)

st.divider()

col1, col2, col3 = st.columns(3)
with col1:
    if not st.session_state.submitted:
        if st.button("✅ Check answers", type="primary", use_container_width=True):
            st.session_state.submitted = True
            st.rerun()
with col2:
    if st.button("🔀 New exercises", use_container_width=True):
        for k in ["exercises","answers","submitted","result_saved"]:
            st.session_state.pop(k, None)
        st.rerun()
with col3:
    if st.session_state.submitted:
        if st.button("📊 Dashboard", use_container_width=True):
            st.switch_page("dashboard.py")