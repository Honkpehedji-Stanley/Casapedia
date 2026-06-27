"""Dashboard — vue nationale (reproduit l'écran "Accueil" de la maquette).

Hero header dégradé + cartes KPI + cartes-graphiques (tendance, type de bien, DPE).
Les requêtes dégradent gracieusement tant que les tables ne sont pas chargées.
"""
import plotly.express as px
import streamlit as st

from lib import formatting as fmt
from lib import queries
from lib import theme

PALETTE = theme.PALETTE

theme.hero_header(
    "Tableau de bord national",
    "Vue d'ensemble du marché résidentiel français — prix, volumes, "
    "démographie et performance énergétique.",
    badge="France entière",
    note="Données 2024 · sources publiques croisées",
)

# ── Cartes KPI ────────────────────────────────────────────────────────────────
kpis = queries.national_kpis()
theme.kpi_cards([
    {"label": "Prix médian de vente", "value": fmt.format_euro(kpis["prix_median"]),
     "sub": "médiane DVF des transactions"},
    {"label": "Prix médian au m²", "value": fmt.format_euro_m2(kpis["prix_m2_median"]),
     "sub": "robuste aux valeurs extrêmes"},
    {"label": "Transactions", "value": fmt.format_compact(kpis["nb_transactions"]),
     "sub": "ventes indexées (DVF)"},
    {"label": "Population", "value": fmt.format_compact(kpis["population"]),
     "sub": "dernier millésime INSEE"},
])

# ── Rangée graphiques : tendance + type de bien ───────────────────────────────
left, right = st.columns([1.65, 1], gap="medium")

with left:
    with st.container(border=True):
        theme.card_title("Évolution du prix médian au m²", "France métropolitaine · par année")
        yearly = queries.transactions_by_year()
        if yearly.empty:
            st.info("Données de transactions pas encore chargées (pipeline en cours).")
        else:
            yearly = yearly.rename(columns={
                "annee": "Année", "nb_transactions": "Transactions",
                "prix_m2_median": "Prix médian par m²",
            })
            yearly["Prix"] = yearly["Prix médian par m²"].map(fmt.format_euro_m2)
            yearly["Tx"] = yearly["Transactions"].map(fmt.format_compact)
            fig = px.area(yearly, x="Année", y="Prix médian par m²", markers=True)
            fig.update_traces(
                line=dict(color=PALETTE[0], width=3),
                marker=dict(size=8, color="#FFFFFF", line=dict(color=PALETTE[0], width=2)),
                fillcolor="rgba(43,89,195,0.12)",
                customdata=yearly[["Prix", "Tx"]],
                hovertemplate="<b>%{x}</b><br>Prix médian/m² : %{customdata[0]}<br>Transactions : %{customdata[1]}<extra></extra>",
            )
            st.plotly_chart(theme.style_fig(fig, height=280), width="stretch")

with right:
    with st.container(border=True):
        theme.card_title("Répartition par type de bien", "Part des transactions")
        types = queries.type_bien_distribution()
        if types.empty:
            st.info("Pas encore de données.")
        else:
            types = types.rename(columns={"type_bien": "Type de bien", "nb_transactions": "Transactions"})
            types["Tx"] = types["Transactions"].map(fmt.format_compact)
            fig = px.bar(types, x="Transactions", y="Type de bien", orientation="h",
                         color="Type de bien", color_discrete_sequence=PALETTE)
            fig.update_traces(
                customdata=types[["Tx"]],
                hovertemplate="<b>%{y}</b><br>Transactions : %{customdata[0]}<extra></extra>",
            )
            fig.update_layout(showlegend=False, yaxis_title=None, xaxis_title=None)
            st.plotly_chart(theme.style_fig(fig, height=280), width="stretch")

# ── Rangée DPE ────────────────────────────────────────────────────────────────
with st.container(border=True):
    theme.card_title(
        "Performance énergétique du parc · classes DPE",
        "Répartition des logements par étiquette énergie (ADEME) · A = sobre, G = passoire",
    )
    dpe = queries.dpe_distribution()
    if dpe.empty:
        st.info("Données DPE pas encore chargées (pipeline en cours).")
    else:
        dpe = dpe.rename(columns={"classe_energetique": "Classe DPE", "nb_dpe": "Nombre de DPE"})
        dpe["DPE"] = dpe["Nombre de DPE"].map(fmt.format_compact)
        fig = px.bar(dpe, x="Classe DPE", y="Nombre de DPE", color="Classe DPE",
                     color_discrete_map=theme.DPE_COLORS)
        fig.update_traces(
            customdata=dpe[["DPE"]],
            hovertemplate="<b>Classe %{x}</b><br>DPE : %{customdata[0]}<extra></extra>",
        )
        fig.update_layout(showlegend=False, xaxis_title=None, yaxis_title="Nombre de DPE")
        st.plotly_chart(theme.style_fig(fig, height=300), width="stretch")

theme.footer("Source : PostgreSQL `casapedia` · curation Spark · pipeline Airflow.")
