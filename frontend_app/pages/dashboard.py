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

PALETTE = [
    "#2B59C3",
    "#4C78A8",
    "#72B7B2",
    "#54A24B",
    "#EECA3B",
    "#F58518",
    "#E45756",
    "#B279A2",
]

st.title("Casapedia — Vue nationale")
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
col1.metric("Prix médian de vente", fmt.format_euro(kpis["prix_median"]))
col2.metric("Prix médian au m²", fmt.format_euro_m2(kpis["prix_m2_median"]))
col3.metric("Nombre de transactions", fmt.format_compact(kpis["nb_transactions"]))
col4.metric("Population", fmt.format_compact(kpis["population"]))

st.divider()

# --- Tendance temporelle + répartition type de bien ---
left, right = st.columns(2)

with left:
    st.subheader("Évolution du prix médian au m²")
    yearly = queries.transactions_by_year()
    if yearly.empty:
        st.info("Aucune transaction datée disponible.")
    else:
        yearly_display = yearly.rename(
            columns={
                "annee": "Année",
                "nb_transactions": "Nombre de transactions",
                "prix_m2_median": "Prix médian par m²",
            }
        )
        yearly_display["Prix format"] = yearly_display["Prix médian par m²"].map(fmt.format_euro_m2)
        yearly_display["Transactions format"] = yearly_display["Nombre de transactions"].map(fmt.format_compact)
        fig = px.line(
            yearly_display,
            x="Année",
            y="Prix médian par m²",
            markers=True,
            color_discrete_sequence=[PALETTE[0]],
        )
        fig.update_traces(
            customdata=yearly_display[["Prix format", "Transactions format"]],
            line=dict(color=PALETTE[0], width=3),
            marker=dict(size=9, color=PALETTE[2], line=dict(color="#FFFFFF", width=1.5)),
            hovertemplate=(
                "<b>Année %{x}</b><br>"
                "Prix médian par m² : %{customdata[0]}<br>"
                "Nombre de transactions : %{customdata[1]}"
                "<extra></extra>"
            ),
        )
        fig.update_layout(
            margin=dict(l=0, r=0, t=10, b=0),
            yaxis_title="Prix médian par m²",
            xaxis_title="Année",
        )
        st.plotly_chart(fig, use_container_width=True)

with right:
    st.subheader("Répartition par type de bien")
    types = queries.type_bien_distribution()
    if types.empty:
        st.info("Aucune transaction disponible.")
    else:
        types_display = types.rename(
            columns={
                "type_bien": "Type de bien",
                "nb_transactions": "Nombre de transactions",
            }
        )
        types_display["Transactions format"] = types_display["Nombre de transactions"].map(fmt.format_compact)
        fig = px.bar(
            types_display,
            x="Nombre de transactions",
            y="Type de bien",
            orientation="h",
            color="Type de bien",
            color_discrete_sequence=PALETTE,
        )
        fig.update_traces(
            customdata=types_display[["Transactions format"]],
            hovertemplate=(
                "<b>Type de bien</b> : %{y}<br>"
                "<b>Nombre de transactions</b> : %{customdata[0]}"
                "<extra></extra>"
            ),
        )
        fig.update_layout(
            margin=dict(l=0, r=0, t=10, b=0),
            yaxis_title="Type de bien",
            xaxis_title="Nombre de transactions",
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True)

st.divider()

# --- Répartition DPE ---
st.subheader("Répartition des classes DPE (A à G)")
dpe = queries.dpe_distribution()
if dpe.empty:
    st.info("Aucun DPE disponible.")
else:
    dpe_display = dpe.rename(
        columns={
            "classe_energetique": "Classe DPE",
            "nb_dpe": "Nombre de DPE",
        }
    )
    dpe_display["DPE format"] = dpe_display["Nombre de DPE"].map(fmt.format_compact)
    fig = px.bar(
        dpe_display,
        x="Classe DPE",
        y="Nombre de DPE",
        color="Classe DPE",
        color_discrete_sequence=PALETTE,
    )
    fig.update_traces(
        customdata=dpe_display[["DPE format"]],
        hovertemplate=(
            "<b>Classe DPE</b> : %{x}<br>"
            "<b>Nombre de DPE</b> : %{customdata[0]}"
            "<extra></extra>"
        ),
    )
    fig.update_layout(
        margin=dict(l=0, r=0, t=10, b=0),
        xaxis_title="Classe DPE",
        yaxis_title="Nombre de DPE",
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)

st.caption("Source : PostgreSQL `casapedia` · curation Spark · pipeline Airflow.")
