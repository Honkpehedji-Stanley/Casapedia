"""Fiche commune — analyse locale multi-indicateurs (Sprint 3).

Cible : KPI locaux + courbes + prédiction ML (parquet MinIO via lib.connections
.get_minio()) + derniers avis (MongoDB reviews_clean).
"""

import plotly.express as px
import streamlit as st

from lib import formatting as fmt
from lib import queries
from lib import theme

PALETTE = theme.PALETTE
DPE_COLORS = theme.DPE_COLORS

theme.topbar(
    "Fiche territoriale",
    "Indicateurs locaux · marché immobilier, énergie et démographie",
)

# ── Recherche commune ────────────────────────────────────────────────────────
search_query = st.text_input(
    "Rechercher une commune",
    placeholder="Ex : Lyon, Bordeaux, Rennes…",
    max_chars=100,
)

if not search_query or len(search_query) < 2:
    st.info("Saisissez au moins 2 caractères pour rechercher une commune.")
    st.stop()

results = queries.search_communes(search_query)
if results.empty:
    st.warning(f"Aucune commune trouvée pour « {search_query} ».")
    st.stop()

# Sélection parmi les résultats
options = results.apply(
    lambda r: f"{r['nom']} ({r['dept']} — {r['region']})", axis=1
).tolist()
selected_label = st.selectbox("Sélectionner une commune", options)
selected_idx = options.index(selected_label)
code_insee = results.iloc[selected_idx]["code_insee"]

# ── Chargement données ───────────────────────────────────────────────────────
info = queries.commune_detail(code_insee)
kpis = queries.commune_transactions_kpi(code_insee)
yearly = queries.commune_transactions_by_year(code_insee)
types = queries.commune_type_bien(code_insee)
dpe_df = queries.commune_dpe(code_insee)
demo = queries.commune_demographics(code_insee)

if not info:
    st.error("Impossible de charger les données de cette commune.")
    st.stop()

# ── En-tête commune ──────────────────────────────────────────────────────────
st.divider()
st.subheader(f"{info.get('nom', selected_label)}")
st.caption(
    f"Département {info.get('dept', '—')} — {info.get('dept_name', '')} · "
    f"Région {info.get('region', '—')}"
)

# ── KPI immobiliers ──────────────────────────────────────────────────────────
col1, col2, col3, col4 = st.columns(4)
col1.metric("Prix médian de vente", fmt.format_euro(kpis.get("prix_median")))
col2.metric("Prix médian au m²", fmt.format_euro_m2(kpis.get("prix_m2_median")))
col3.metric("Transactions", fmt.format_compact(kpis.get("nb_transactions")))
col4.metric(
    "Surface moyenne",
    f"{kpis['surface_moyenne']:.0f} m²" if kpis.get("surface_moyenne") else "—",
)

# ── Contexte démographique ───────────────────────────────────────────────────
st.divider()
st.subheader("Contexte démographique")

d1, d2, d3 = st.columns(3)
pop = demo.get("population")
chom = demo.get("taux_chomage")
dens = demo.get("densite")

d1.metric(
    f"Population ({demo.get('pop_annee', '—')})",
    fmt.format_compact(pop) if pop else "—",
)
d2.metric(
    f"Taux de chômage ({demo.get('chom_annee', '—')})",
    f"{chom:.1f} %" if chom is not None else "—",
)
d3.metric(
    f"Densité ({demo.get('dens_annee', '—')})",
    f"{dens:.0f} hab/km²" if dens else "—",
)

st.divider()

# ── Dataviz ──────────────────────────────────────────────────────────────────
left, right = st.columns(2)

with left:
    st.subheader("Évolution du prix médian au m²")
    if yearly.empty:
        st.info("Aucune transaction datée disponible pour cette commune.")
    else:
        df = yearly.rename(
            columns={
                "annee": "Année",
                "nb_transactions": "Transactions",
                "prix_m2_median": "Prix médian par m²",
            }
        )
        df["Prix format"] = df["Prix médian par m²"].map(fmt.format_euro_m2)
        df["Tx format"] = df["Transactions"].map(fmt.format_compact)
        fig = px.line(
            df,
            x="Année",
            y="Prix médian par m²",
            markers=True,
            color_discrete_sequence=[PALETTE[0]],
        )
        fig.update_traces(
            customdata=df[["Prix format", "Tx format"]],
            line=dict(color=PALETTE[0], width=3),
            marker=dict(size=9, color=PALETTE[2], line=dict(color="#FFFFFF", width=1.5)),
            hovertemplate=(
                "<b>%{x}</b><br>"
                "Prix médian par m² : %{customdata[0]}<br>"
                "Transactions : %{customdata[1]}"
                "<extra></extra>"
            ),
        )
        fig.update_layout(margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(theme.style_fig(fig), width="stretch")

with right:
    st.subheader("Répartition par type de bien")
    if types.empty:
        st.info("Aucune transaction disponible pour cette commune.")
    else:
        df_t = types.rename(
            columns={"type_bien": "Type de bien", "nb_transactions": "Transactions"}
        )
        df_t["Tx format"] = df_t["Transactions"].map(fmt.format_compact)
        fig = px.bar(
            df_t,
            x="Transactions",
            y="Type de bien",
            orientation="h",
            color="Type de bien",
            color_discrete_sequence=PALETTE,
        )
        fig.update_traces(
            customdata=df_t[["Tx format"]],
            hovertemplate="<b>%{y}</b><br>Transactions : %{customdata[0]}<extra></extra>",
        )
        fig.update_layout(
            margin=dict(l=0, r=0, t=10, b=0),
            showlegend=False,
        )
        st.plotly_chart(theme.style_fig(fig), width="stretch")

# ── Répartition DPE ──────────────────────────────────────────────────────────
st.divider()
st.subheader("Répartition des classes DPE")

if dpe_df.empty:
    st.info("Aucun DPE disponible pour cette commune.")
else:
    dpe_df = dpe_df.sort_values("classe_energetique")
    dpe_df["Couleur"] = dpe_df["classe_energetique"].map(
        lambda x: DPE_COLORS.get(x, "#CCCCCC")
    )
    dpe_df["DPE format"] = dpe_df["nb_dpe"].map(fmt.format_compact)

    fig = px.bar(
        dpe_df,
        x="classe_energetique",
        y="nb_dpe",
        color="classe_energetique",
        color_discrete_map=DPE_COLORS,
        labels={
            "classe_energetique": "Classe DPE",
            "nb_dpe": "Nombre de DPE",
        },
    )
    fig.update_traces(
        customdata=dpe_df[["DPE format"]],
        hovertemplate="<b>Classe %{x}</b><br>DPE : %{customdata[0]}<extra></extra>",
    )
    fig.update_layout(
        margin=dict(l=0, r=0, t=10, b=0),
        showlegend=False,
        xaxis_title="Classe DPE",
        yaxis_title="Nombre de DPE",
    )
    st.plotly_chart(theme.style_fig(fig), width="stretch")

theme.footer("Source : PostgreSQL `casapedia` · DVF · INSEE · ADEME · pipeline Airflow.")