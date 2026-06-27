"""Analyse NLP — sentiment & word cloud sur les avis (Sprint 5).

Dépend de spark_jobs/sentiment_reviews.py (collections nlp_sentiments / nlp_themes
/ nlp_theme_sentiments). En attendant : distribution des notes sur reviews_clean.
"""

import re
from collections import Counter

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from lib import formatting as fmt
from lib import queries
from lib import theme

PALETTE = theme.PALETTE

# Mots vides français minimalistes (sans dépendance NLTK)
STOPWORDS_FR = {
    "le", "la", "les", "un", "une", "des", "de", "du", "en", "et", "est",
    "il", "elle", "nous", "vous", "ils", "elles", "je", "tu", "on",
    "ce", "qui", "que", "ou", "si", "mais", "donc", "car", "ni", "or",
    "au", "aux", "par", "pour", "sur", "sous", "avec", "sans", "dans",
    "à", "y", "se", "me", "te", "lui", "leur", "plus", "très", "bien",
    "pas", "ne", "tout", "cette", "son", "sa", "ses", "mon", "ma", "mes",
    "ton", "ta", "tes", "cet", "ces", "cela", "ça", "même", "aussi",
    "après", "avant", "comme", "quand", "dont", "où", "être", "avoir",
    "faire", "ville", "quartier",
}


def _word_freq(texts: list[str], top_n: int = 40) -> dict[str, int]:
    words: list[str] = []
    for t in texts:
        if not isinstance(t, str):
            continue
        tokens = re.findall(r"\b[a-zA-ZÀ-ÿ]{4,}\b", t.lower())
        words.extend(w for w in tokens if w not in STOPWORDS_FR)
    return dict(Counter(words).most_common(top_n))


def _rating_label(r) -> str:
    try:
        v = float(r)
        if v >= 4:
            return "Positif"
        if v >= 3:
            return "Neutre"
        return "Négatif"
    except (TypeError, ValueError):
        return "Inconnu"


# ── Interface ────────────────────────────────────────────────────────────────
theme.topbar(
    "Analyse des avis habitants",
    "Sentiment (lexique FEEL) · mots-clés · thèmes",
)

st.markdown(
    "Analyse des avis collectés sur les communes françaises. "
    "Filtrez par ville pour explorer les opinions, les points forts "
    "et les points faibles exprimés par les habitants."
)

# ── Sidebar filtres ──────────────────────────────────────────────────────────
with st.sidebar:
    st.subheader("Filtres")
    cities = queries.nlp_cities()
    city_choice = st.selectbox(
        "Ville",
        ["Toutes"] + cities,
        index=0,
    )
    min_rating = st.slider("Note minimale", 0.0, 5.0, 0.0, 0.5)

# ── Chargement ───────────────────────────────────────────────────────────────
city_param = None if city_choice == "Toutes" else city_choice
df = queries.nlp_reviews(city=city_param, limit=500)

if df.empty:
    st.info(
        "Aucun avis disponible. Vérifiez que MongoDB est accessible "
        "et que le DAG `3_load_databases` a chargé la collection `reviews_clean`."
    )
    st.stop()

# Filtre note
if "rating" in df.columns and min_rating > 0:
    df = df[pd.to_numeric(df["rating"], errors="coerce").fillna(0) >= min_rating]

if df.empty:
    st.info("Aucun avis ne correspond aux filtres sélectionnés.")
    st.stop()

df["rating_num"] = pd.to_numeric(df["rating"], errors="coerce")
df["sentiment"] = df["rating_num"].map(_rating_label)

# ── KPI ──────────────────────────────────────────────────────────────────────
total = len(df)
note_moy = df["rating_num"].mean()
nb_cities = df["city_name"].nunique() if "city_name" in df.columns else 0
nb_positifs = (df["sentiment"] == "Positif").sum()

col1, col2, col3, col4 = st.columns(4)
col1.metric("Avis chargés", fmt.format_compact(total))
col2.metric("Note moyenne", f"{note_moy:.1f} / 5" if not pd.isna(note_moy) else "—")
col3.metric("Villes couvertes", fmt.format_compact(nb_cities))
col4.metric(
    "Avis positifs",
    f"{nb_positifs / total * 100:.0f} %" if total else "—",
)

st.divider()

# ── Répartition sentiment ────────────────────────────────────────────────────
left, right = st.columns(2)

with left:
    st.subheader("Répartition des sentiments")
    sent_counts = df["sentiment"].value_counts().reset_index()
    sent_counts.columns = ["Sentiment", "Nombre"]
    color_map = theme.SENTIMENT_COLORS
    fig_sent = px.pie(
        sent_counts,
        names="Sentiment",
        values="Nombre",
        color="Sentiment",
        color_discrete_map=color_map,
        hole=0.4,
    )
    fig_sent.update_traces(
        textposition="inside",
        textinfo="percent+label",
        hovertemplate="<b>%{label}</b><br>%{value} avis<extra></extra>",
    )
    fig_sent.update_layout(margin=dict(l=0, r=0, t=10, b=0), showlegend=False)
    st.plotly_chart(theme.style_fig(fig_sent), width="stretch")

with right:
    st.subheader("Distribution des notes")
    notes = df["rating_num"].dropna()
    if notes.empty:
        st.info("Aucune note disponible.")
    else:
        fig_hist = px.histogram(
            notes,
            nbins=10,
            color_discrete_sequence=[PALETTE[0]],
            labels={"value": "Note", "count": "Nombre d'avis"},
        )
        fig_hist.update_layout(
            margin=dict(l=0, r=0, t=10, b=0),
            xaxis_title="Note",
            yaxis_title="Nombre d'avis",
            bargap=0.05,
        )
        st.plotly_chart(theme.style_fig(fig_hist), width="stretch")

# ── Nuage de mots (fréquences) ───────────────────────────────────────────────
st.divider()
st.subheader("Mots les plus fréquents")

tab_all, tab_pos, tab_neg = st.tabs(["Tous les avis", "Avis positifs", "Avis négatifs"])

text_col = "clean_text" if "clean_text" in df.columns else "review_text"

with tab_all:
    freq = _word_freq(df[text_col].tolist())
    if freq:
        wf = pd.DataFrame(freq.items(), columns=["Mot", "Fréquence"]).sort_values(
            "Fréquence", ascending=True
        )
        fig_wf = px.bar(
            wf.tail(20),
            x="Fréquence",
            y="Mot",
            orientation="h",
            color="Fréquence",
            color_continuous_scale=["#72B7B2", "#2B59C3"],
        )
        fig_wf.update_layout(
            margin=dict(l=0, r=0, t=10, b=0),
            coloraxis_showscale=False,
            yaxis_title=None,
        )
        st.plotly_chart(theme.style_fig(fig_wf), width="stretch")
    else:
        st.info("Aucun texte disponible pour l'analyse.")

with tab_pos:
    pos_texts = df.loc[df["sentiment"] == "Positif", text_col].tolist()
    freq_p = _word_freq(pos_texts)
    if freq_p:
        wfp = pd.DataFrame(freq_p.items(), columns=["Mot", "Fréquence"]).sort_values(
            "Fréquence", ascending=True
        )
        fig_p = px.bar(
            wfp.tail(20),
            x="Fréquence",
            y="Mot",
            orientation="h",
            color="Fréquence",
            color_continuous_scale=["#B6D234", "#00A84F"],
        )
        fig_p.update_layout(
            margin=dict(l=0, r=0, t=10, b=0),
            coloraxis_showscale=False,
            yaxis_title=None,
        )
        st.plotly_chart(theme.style_fig(fig_p), width="stretch")
    else:
        st.info("Aucun avis positif disponible.")

with tab_neg:
    neg_texts = df.loc[df["sentiment"] == "Négatif", text_col].tolist()
    freq_n = _word_freq(neg_texts)
    if freq_n:
        wfn = pd.DataFrame(freq_n.items(), columns=["Mot", "Fréquence"]).sort_values(
            "Fréquence", ascending=True
        )
        fig_n = px.bar(
            wfn.tail(20),
            x="Fréquence",
            y="Mot",
            orientation="h",
            color="Fréquence",
            color_continuous_scale=["#F5A10E", "#E52322"],
        )
        fig_n.update_layout(
            margin=dict(l=0, r=0, t=10, b=0),
            coloraxis_showscale=False,
            yaxis_title=None,
        )
        st.plotly_chart(theme.style_fig(fig_n), width="stretch")
    else:
        st.info("Aucun avis négatif disponible.")

# ── Table des avis ───────────────────────────────────────────────────────────
st.divider()
st.subheader("Avis détaillés")

display_cols = [c for c in ["city_name", "rating", "sentiment", "review_text", "source"] if c in df.columns]
display_labels = {
    "city_name": "Ville",
    "rating": "Note",
    "sentiment": "Sentiment",
    "review_text": "Avis",
    "source": "Source",
}
df_display = df[display_cols].rename(columns=display_labels).head(50)
st.dataframe(df_display, width="stretch", hide_index=True)

theme.footer("Source : MongoDB `casapedia.reviews_clean` · scraping web · pipeline Airflow.")