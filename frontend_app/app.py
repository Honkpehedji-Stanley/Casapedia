"""Point d'entrée du frontend Casapedia.

Lancer depuis la racine du projet :
    streamlit run frontend_app/app.py

Navigation programmable via st.navigation / st.Page (Streamlit >= 1.36).
Streamlit ajoute le dossier du script principal au sys.path : les pages peuvent
donc importer `lib.*` directement.
"""
import streamlit as st

st.set_page_config(
    page_title="Casapedia",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
)

PAGES = {
    "Exploration": [
        st.Page("pages/dashboard.py", title="Dashboard", icon="🏠", default=True),
        st.Page("pages/carte.py", title="Carte", icon="🗺️"),
        st.Page("pages/comparateur.py", title="Comparateur", icon="⚖️"),
        st.Page("pages/fiche.py", title="Fiche territoriale", icon="📍"),
    ],
    "Analyses": [
        st.Page("pages/nlp.py", title="Analyse NLP", icon="💬"),
    ],
    "À propos": [
        st.Page("pages/methodologie.py", title="Méthodologie", icon="📖"),
    ],
}

st.navigation(PAGES).run()
