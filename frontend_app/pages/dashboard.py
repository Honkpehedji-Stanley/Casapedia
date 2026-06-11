"""Dashboard — vue d'ensemble nationale (Sprint 0).

KPI prioritaires + premières dataviz descriptives au niveau national.
Le sélecteur d'échelle (national -> commune) et les filtres globaux arrivent
au Sprint 2 ; cette page établit le socle data/affichage.
"""
import plotly.express as px
import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from lib import formatting as fmt
from lib import queries

st.title("🏠 Casapedia — Vue nationale")
st.caption("Marché immobilier français · indicateurs agrégés au niveau national")

try:
    kpis = queries.national_kpis()
except SQLAlchemyError as exc:
    st.error(
        "Impossible de joindre PostgreSQL ou les tables ne sont pas encore chargées.\n\n"
        "Vérifiez que `docker compose up` tourne et que le DAG `3_load_databases` "
        "a publié les données."
    )
    st.exception(exc)
    st.stop()

# --- KPI cards (CASAPEDIA_DOC §5.1) ---
# Revenu médian volontairement absent : médiane brute de revenue_disponible non
# fiable (dette technique identifiée, à traiter Sprint 1). 4 KPI solides > 5 dont 1 faux.
col1, col2, col3, col4 = st.columns(4)
col1.metric("💶 Prix médian de vente", fmt.format_euro(kpis["prix_median"]))
col2.metric("📐 Prix médian au m²", fmt.format_euro_m2(kpis["prix_m2_median"]))
col3.metric("🔢 Transactions", fmt.format_compact(kpis["nb_transactions"]))
col4.metric("👥 Population", fmt.format_compact(kpis["population"]))

st.divider()

# --- Tendance temporelle + répartition type de bien ---
left, right = st.columns(2)

with left:
    st.subheader("📈 Évolution du prix médian au m²")
    yearly = queries.transactions_by_year()
    if yearly.empty:
        st.info("Aucune transaction datée disponible.")
    else:
        fig = px.line(yearly, x="annee", y="prix_m2_median", markers=True)
        fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), yaxis_title="€/m²", xaxis_title="")
        st.plotly_chart(fig, width="stretch")

with right:
    st.subheader("🏠 Répartition par type de bien")
    types = queries.type_bien_distribution()
    if types.empty:
        st.info("Aucune transaction disponible.")
    else:
        fig = px.bar(types, x="nb_transactions", y="type_bien", orientation="h")
        fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), yaxis_title="", xaxis_title="Transactions")
        st.plotly_chart(fig, width="stretch")

st.divider()

# --- Répartition DPE ---
st.subheader("🌱 Répartition des classes DPE (A → G)")
dpe = queries.dpe_distribution()
if dpe.empty:
    st.info("Aucun DPE disponible.")
else:
    fig = px.bar(dpe, x="classe_energetique", y="nb_dpe")
    fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), xaxis_title="Classe", yaxis_title="Nombre de DPE")
    st.plotly_chart(fig, width="stretch")

st.caption("Source : PostgreSQL `casapedia` · curation Spark · pipeline Airflow.")
