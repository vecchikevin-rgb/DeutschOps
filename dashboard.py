# dashboard.py
# Dashboard KPI interattiva per DeutschOps
# Lancia con: streamlit run dashboard.py

import json
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path
from datetime import datetime

# ─── CONFIG ───────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="DeutschOps Dashboard",
    page_icon="🇩🇪",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ─── LOAD DATA ────────────────────────────────────────────────────────────────
@st.cache_data(ttl=30)  # refresh ogni 30 secondi
def load_registry():
    path = Path("lesson_registry.json")
    if not path.exists():
        return {"lessons": [], "stats": {}}
    return json.loads(path.read_text(encoding="utf-8"))

@st.cache_data(ttl=30)
def load_vocab_db():
    path = Path("data/vocab_db.json")
    if not path.exists():
        return {"words": {}, "stats": {}}
    return json.loads(path.read_text(encoding="utf-8"))

@st.cache_data(ttl=30)
def load_lesson_data(lesson_id: str):
    path = Path(f"data/lezione_{lesson_id}.json")
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))

# ─── STYLES ───────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .main { background-color: #0d1117; }
    .metric-card {
        background: linear-gradient(135deg, #1a3a5c, #0d2137);
        border-radius: 12px;
        padding: 20px;
        border-left: 4px solid #0288d1;
        margin: 8px 0;
    }
    .metric-value {
        font-size: 2.5em;
        font-weight: bold;
        color: #0288d1;
    }
    .metric-label {
        color: #90caf9;
        font-size: 0.9em;
        margin-top: 4px;
    }
    .section-header {
        color: #0288d1;
        font-size: 1.3em;
        font-weight: bold;
        border-bottom: 2px solid #1565c0;
        padding-bottom: 8px;
        margin: 20px 0 12px 0;
    }
    .lesson-card {
        background: #161b22;
        border-radius: 8px;
        padding: 12px 16px;
        margin: 6px 0;
        border-left: 3px solid #1565c0;
    }
    .word-pill {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 12px;
        font-size: 0.85em;
        margin: 2px;
    }
</style>
""", unsafe_allow_html=True)

# ─── HEADER ───────────────────────────────────────────────────────────────────
col_title, col_refresh = st.columns([5, 1])
with col_title:
    st.markdown("# 🇩🇪 DeutschOps — Kevin's Learning Dashboard")
    st.markdown(f"*Last updated: {datetime.now().strftime('%d %b %Y %H:%M')}*")
with col_refresh:
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()

st.divider()

# ─── LOAD ─────────────────────────────────────────────────────────────────────
registry   = load_registry()
vocab_db   = load_vocab_db()
lessons    = registry.get("lessons", [])
stats      = registry.get("stats", {})
vocab_stats = vocab_db.get("stats", {})
words      = vocab_db.get("words", {})

if not lessons:
    st.warning("No lessons found. Process your first lesson with `python main.py`")
    st.stop()

# ─── KPI ROW ──────────────────────────────────────────────────────────────────
st.markdown('<div class="section-header">📊 Overall Progress</div>',
            unsafe_allow_html=True)

k1, k2, k3, k4, k5 = st.columns(5)

with k1:
    st.metric("🎓 Lessons", stats.get("total", 0))
with k2:
    mins = stats.get("total_minutes", 0)
    st.metric("⏱️ Audio studied", f"{mins:.0f} min", f"{mins/60:.1f}h")
with k3:
    st.metric("📚 Vocabulary", vocab_stats.get("total_words", 0), "words learned")
with k4:
    by_level = vocab_stats.get("by_level", {})
    b1_count = by_level.get("B1", 0) + by_level.get("B2", 0)
    st.metric("🎯 B1+ words", b1_count)
with k5:
    st.metric("💶 API cost", f"€{stats.get('total_cost_eur', 0):.2f}")

st.divider()

# ─── CHARTS ROW ───────────────────────────────────────────────────────────────
col_left, col_right = st.columns(2)

with col_left:
    st.markdown('<div class="section-header">📈 Vocabulary by Level</div>',
                unsafe_allow_html=True)

    by_level = vocab_stats.get("by_level", {})
    level_data = pd.DataFrame([
        {"Level": lvl, "Words": by_level.get(lvl, 0)}
        for lvl in ["A1", "A2", "B1", "B2"]
    ])
    fig = px.bar(
        level_data, x="Level", y="Words",
        color="Level",
        color_discrete_map={
            "A1": "#42a5f5", "A2": "#1565c0",
            "B1": "#00838f", "B2": "#2e7d32"
        },
        template="plotly_dark"
    )
    fig.update_layout(
        plot_bgcolor="#0d1117",
        paper_bgcolor="#0d1117",
        showlegend=False,
        height=280,
        margin=dict(t=10, b=10, l=10, r=10)
    )
    st.plotly_chart(fig, use_container_width=True)

with col_right:
    st.markdown('<div class="section-header">🗂️ Vocabulary by Category</div>',
                unsafe_allow_html=True)

    by_cat = vocab_stats.get("by_category", {})
    cat_labels = {
        "noun": "Nouns", "verb_regular": "V.Regular",
        "verb_irregular": "V.Irregular", "verb_separable": "V.Separable",
        "verb_modal": "V.Modal", "adjective": "Adjectives",
        "adverb": "Adverbs", "phrase": "Phrases", "expression": "Expressions"
    }
    cat_data = pd.DataFrame([
        {"Category": cat_labels.get(k, k), "Count": v}
        for k, v in sorted(by_cat.items(), key=lambda x: x[1], reverse=True)
        if v > 0
    ])
    fig2 = px.pie(
        cat_data, values="Count", names="Category",
        template="plotly_dark",
        color_discrete_sequence=px.colors.qualitative.Set3
    )
    fig2.update_layout(
        plot_bgcolor="#0d1117",
        paper_bgcolor="#0d1117",
        height=280,
        margin=dict(t=10, b=10, l=10, r=10)
    )
    st.plotly_chart(fig2, use_container_width=True)

st.divider()

# ─── LESSONS TIMELINE ─────────────────────────────────────────────────────────
st.markdown('<div class="section-header">📋 Lesson History</div>',
            unsafe_allow_html=True)

lessons_sorted = sorted(lessons, key=lambda x: x.get("date", ""))

# Grafico parole per lezione
lesson_df = pd.DataFrame([{
    "Date": l.get("date", ""),
    "Topic": l.get("topic", "")[:30],
    "Words": l.get("vocabulary_count", 0),
    "Grammar": l.get("grammar_count", 0),
    "Duration": l.get("duration_minutes", 0),
    "Cost": l.get("cost_total_eur", 0)
} for l in lessons_sorted])

fig3 = go.Figure()
fig3.add_trace(go.Bar(
    x=lesson_df["Date"],
    y=lesson_df["Words"],
    name="New words",
    marker_color="#0288d1"
))
fig3.add_trace(go.Scatter(
    x=lesson_df["Date"],
    y=lesson_df["Duration"],
    name="Duration (min)",
    yaxis="y2",
    line=dict(color="#f9a825", width=2),
    mode="lines+markers"
))
fig3.update_layout(
    template="plotly_dark",
    plot_bgcolor="#0d1117",
    paper_bgcolor="#0d1117",
    height=280,
    margin=dict(t=10, b=10, l=10, r=10),
    yaxis=dict(title="New words"),
    yaxis2=dict(title="Duration (min)", overlaying="y", side="right"),
    legend=dict(orientation="h", y=1.1)
)
st.plotly_chart(fig3, use_container_width=True)

# Cards lezioni
for lesson in reversed(lessons_sorted):
    with st.expander(
        f"📖 [{lesson.get('date','')}] {lesson.get('topic','')} "
        f"— {lesson.get('vocabulary_count',0)} words · "
        f"{lesson.get('duration_minutes',0):.0f} min"
    ):
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            st.metric("Words", lesson.get("vocabulary_count", 0))
        with col_b:
            st.metric("Grammar rules", lesson.get("grammar_count", 0))
        with col_c:
            st.metric("Cost", f"€{lesson.get('cost_total_eur', 0):.3f}")

        hw = lesson.get("homework", "")
        if hw:
            st.info(f"📌 **Homework:** {hw}")

        sections = lesson.get("doc_sections", [])
        if sections:
            st.markdown(f"**Sections covered:** {', '.join(sections)}")

        # Carica vocabolario dettagliato
        lesson_id = lesson.get("id", "")
        lesson_detail = load_lesson_data(lesson_id)
        vocab = lesson_detail.get("vocabulary", [])
        if vocab:
            st.markdown("**Vocabulary:**")
            cat_colors = {
                "noun": "#6a1b9a", "verb_regular": "#2e7d32",
                "verb_irregular": "#2e7d32", "verb_separable": "#00838f",
                "verb_modal": "#2e7d32", "adjective": "#bf360c",
                "adverb": "#1565c0", "phrase": "#00695c",
                "expression": "#00695c"
            }
            pills_html = ""
            for w in vocab:
                cat = w.get("category", "other")
                color = cat_colors.get(cat, "#546e7a")
                art = f"{w.get('article','')} " if w.get("article") else ""
                pills_html += (
                    f'<span class="word-pill" '
                    f'style="background:{color}20;color:{color};'
                    f'border:1px solid {color}">'
                    f'{art}{w["german"]}</span>'
                )
            st.markdown(pills_html, unsafe_allow_html=True)

st.divider()

# ─── VOCAB EXPLORER ───────────────────────────────────────────────────────────
st.markdown('<div class="section-header">🔍 Vocabulary Explorer</div>',
            unsafe_allow_html=True)

col_filter1, col_filter2, col_filter3 = st.columns(3)
with col_filter1:
    cat_filter = st.selectbox(
        "Category",
        ["All"] + list(cat_labels.values())
    )
with col_filter2:
    level_filter = st.selectbox("Level", ["All", "A1", "A2", "B1", "B2"])
with col_filter3:
    search = st.text_input("Search", placeholder="Type to filter...")

# Filtra parole
cat_reverse = {v: k for k, v in cat_labels.items()}
filtered_words = []
for key, word in words.items():
    if cat_filter != "All" and word.get("category") != cat_reverse.get(cat_filter):
        continue
    if level_filter != "All" and word.get("level") != level_filter:
        continue
    if search and search.lower() not in (
        word.get("german","").lower() + word.get("english","").lower()
        + word.get("italian","").lower()
    ):
        continue
    filtered_words.append(word)

st.markdown(f"*Showing {len(filtered_words)} of {len(words)} words*")

if filtered_words:
    vocab_table = pd.DataFrame([{
        "German":  (f"{w.get('article','')} " if w.get('article') else "")
                   + w.get("german",""),
        "English": w.get("english",""),
        "Italian": w.get("italian",""),
        "Category": cat_labels.get(w.get("category",""), w.get("category","")),
        "Level":   w.get("level",""),
        "First seen": w.get("first_seen",""),
        "Lessons": w.get("occurrences", 1)
    } for w in filtered_words[:200]])

    st.dataframe(
        vocab_table,
        use_container_width=True,
        hide_index=True,
        column_config={
            "German": st.column_config.TextColumn("🇩🇪 German", width=150),
            "English": st.column_config.TextColumn("🇬🇧 English", width=150),
            "Italian": st.column_config.TextColumn("🇮🇹 Italian", width=150),
            "Level": st.column_config.TextColumn("Level", width=70),
            "Lessons": st.column_config.NumberColumn("Times seen", width=100),
        }
    )

# ─── BOOK EXPLORER ────────────────────────────────────────────────────────────
book_db_path = Path("data/book_db.json")
if book_db_path.exists():
    st.divider()
    st.markdown('<div class="section-header">📗 Book Explorer — DaF Kompakt Neu A1-B1</div>',
                unsafe_allow_html=True)

    @st.cache_data(ttl=60)
    def load_book_db():
        return json.loads(book_db_path.read_text(encoding="utf-8"))

    book_db   = load_book_db()
    lektionen = book_db.get("lektionen", {})

    # Filtri
    col_lvl, col_lekt = st.columns(2)
    with col_lvl:
        lvl_filter = st.selectbox(
            "Level", ["All", "A1", "A2", "B1"], key="book_level"
        )
    with col_lekt:
        lekt_nums = sorted([int(k) for k in lektionen.keys()])
        lekt_options = ["All"] + [f"Lektion {n}" for n in lekt_nums]
        lekt_sel = st.selectbox("Lektion", lekt_options, key="book_lekt")

    # Filtra
    filtered_lektionen = {}
    for k, v in lektionen.items():
        if lvl_filter != "All" and v.get("level") != lvl_filter:
            continue
        if lekt_sel != "All" and f"Lektion {k}" != lekt_sel:
            continue
        filtered_lektionen[k] = v

    # Totali
    total_v = sum(len(v.get("vocabulary",[])) for v in filtered_lektionen.values())
    total_g = sum(len(v.get("grammar_rules",[])) for v in filtered_lektionen.values())
    total_r = sum(len(v.get("redemittel",[])) for v in filtered_lektionen.values())
    b1, b2, b3 = st.columns(3)
    with b1: st.metric("Vocabulary", total_v)
    with b2: st.metric("Grammar rules", total_g)
    with b3: st.metric("Redemittel", total_r)

    st.divider()

    # Mostra Lektionen
    for k in sorted(filtered_lektionen.keys(), key=int):
        ldata = filtered_lektionen[k]
        lnum  = int(k)
        level = ldata.get("level","")
        vocab = ldata.get("vocabulary", [])
        grammar = ldata.get("grammar_rules", [])
        redemittel = ldata.get("redemittel", [])

        with st.expander(
            f"📗 Lektion {lnum} ({level}) — "
            f"{len(vocab)} words · {len(grammar)} grammar · {len(redemittel)} Redemittel"
        ):
            # Vocab per campo semantico
            if vocab:
                st.markdown("**Vocabulary by semantic field:**")
                fields = {}
                for w in vocab:
                    sf = w.get("semantic_field", "Other")
                    fields.setdefault(sf, []).append(w)

                for field, words in fields.items():
                    st.markdown(f"*{field}*")
                    pills = ""
                    for w in words:
                        art  = f"{w.get('article','')} " if w.get("article") else ""
                        base = w.get("german","")
                        eng  = w.get("english","")
                        lvl  = w.get("level","")
                        cat  = w.get("category","")
                        color_map = {
                            "noun": "#1565c0", "verb": "#2e7d32",
                            "adjective": "#bf360c", "adverb": "#00838f",
                            "phrase": "#6a1b9a", "expression": "#6a1b9a"
                        }
                        color = color_map.get(cat, "#546e7a")
                        pills += (
                            f'<span style="background:{color}20;color:{color};'
                            f'border:1px solid {color};border-radius:10px;'
                            f'padding:2px 8px;margin:2px;display:inline-block;'
                            f'font-size:0.85em">'
                            f'{art}{base} <i style="color:#90a4ae">({eng})</i>'
                            f'</span>'
                        )
                    st.markdown(pills, unsafe_allow_html=True)
                    st.markdown("")

            # Grammar rules
            if grammar:
                st.divider()
                st.markdown("**Grammar rules:**")
                for r in grammar:
                    st.markdown(f"📐 **{r.get('rule','')}**")
                    if r.get("explanation_en"):
                        st.markdown(f"  {r['explanation_en']}")
                    if r.get("examples"):
                        for ex in r["examples"][:2]:
                            st.markdown(f"  → *{ex}*")

            # Redemittel
            if redemittel:
                st.divider()
                st.markdown("**Redemittel:**")
                for rm in redemittel:
                    ctx = f" _{rm.get('context','')}_" if rm.get("context") else ""
                    st.markdown(
                        f"• **{rm.get('german','')}** — "
                        f"{rm.get('english','')}{ctx}"
                    )
    st.markdown(
    "*DeutschOps — AI-powered German learning pipeline | "
    "[GitHub](https://github.com/vecchikevin-rgb/DeutschOps)*"
)