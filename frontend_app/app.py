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
    page_icon=":material/home:",
    layout="wide",
    initial_sidebar_state="expanded",
)

PAGES = {
    "Exploration": [
        st.Page("pages/dashboard.py", title="Tableau de bord", icon=":material/home:", default=True),
        st.Page("pages/carte.py", title="Carte", icon=":material/map:"),
        st.Page("pages/comparateur.py", title="Comparateur", icon=":material/balance:"),
        st.Page("pages/fiche.py", title="Fiche territoriale", icon=":material/location_on:"),
    ],
    "Analyses": [
        st.Page("pages/nlp.py", title="Analyse NLP", icon=":material/chat:"),
    ],
    "À propos": [
        st.Page("pages/methodologie.py", title="Méthodologie", icon=":material/menu_book:"),
    ],
}

st.navigation(PAGES).run()
