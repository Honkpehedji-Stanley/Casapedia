"""Analyse NLP — sentiment & word cloud sur les avis (Sprint 5).

Dépend de spark_jobs/sentiment_reviews.py (collections nlp_sentiments / nlp_themes
/ nlp_theme_sentiments). En attendant : distribution des notes sur reviews_clean.
"""
import streamlit as st

st.title("💬 Analyse NLP")
st.info(
    "🚧 **Sprint 5** — sentiment + word cloud. "
    "Dépend du job `sentiment_reviews.py` (collections `nlp_*`)."
)
