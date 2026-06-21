"""Comparateur — analyse comparative multi-territoires (Sprint 4).

Comparaison des indicateurs immobiliers et énergétiques entre régions
et départements, avec sélection interactive.
"""

import plotly.express as px
import streamlit as st

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

DPE_COLORS = {
    "A": "#00A84F",
    "B": "#51B848",
    "C": "#B6D234",
    "D": "#F9E11E",
    "E": "#F5A10E",
    "F": "#EF7622",
    "G": "#E52322",
}

st.title("Comparateur")
st.caption("Analyse comparative par région et département")

st.markdown(
    "Comparez les marchés immobiliers de plusieurs territoires sur les mêmes "
    "indicateurs : prix au m², volume de transactions et répartition DPE."
)

# ── Chargement données régionales ────────────────────────────────────────────
region_df = queries.comparateur_region_data()

if region_df.empty:
    st.info(
        "Aucune donnée régionale disponible. "
        "Vérifiez que le pipeline Airflow a chargé les transactions et les communes."
    )
    st.stop()

# ── Sélection régions ────────────────────────────────────────────────────────
all_regions = sorted(region_df["region"].dropna().unique().tolist())

with st.sidebar:
    st.subheader("Sélection")
    selected_regions = st.multiselect(
        "Régions à comparer",
        all_regions,
        default=all_regions[:6],
        help="Laissez vide pour voir toutes les régions.",
    )
    echelle = st.radio("Échelle", ["Région", "Département"], horizontal=True)

if selected_regions:
    region_df = region_df[region_df["region"].isin(selected_regions)]

# ── Vue régionale ────────────────────────────────────────────────────────────
if echelle == "Région":
    st.subheader("Prix médian au m² par région")

    if region_df.empty:
        st.info("Aucune région sélectionnée.")
    else:
        df_sorted = region_df.sort_values("prix_m2_median", ascending=True)
        df_sorted["Prix format"] = df_sorted["prix_m2_median"].map(fmt.format_euro_m2)
        df_sorted["Tx format"] = df_sorted["nb_transactions"].map(fmt.format_compact)

        fig = px.bar(
            df_sorted,
            x="prix_m2_median",
            y="region",
            orientation="h",
            color="prix_m2_median",
            color_continuous_scale=["#72B7B2", "#2B59C3"],
            labels={"prix_m2_median": "Prix médian par m²", "region": "Région"},
        )
        fig.update_traces(
            customdata=df_sorted[["Prix format", "Tx format"]],
            hovertemplate=(
                "<b>%{y}</b><br>"
                "Prix médian par m² : %{customdata[0]}<br>"
                "Transactions : %{customdata[1]}"
                "<extra></extra>"
            ),
        )
        fig.update_layout(
            margin=dict(l=0, r=0, t=10, b=0),
            coloraxis_showscale=False,
            yaxis_title=None,
            xaxis_title="Prix médian par m²",
        )
        st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # ── Scatter : prix vs volume ──────────────────────────────────────────
    st.subheader("Prix au m² et volume de transactions")

    if not region_df.empty:
        df_sc = region_df.dropna(subset=["prix_m2_median", "nb_transactions"])
        df_sc["Prix format"] = df_sc["prix_m2_median"].map(fmt.format_euro_m2)
        df_sc["Tx format"] = df_sc["nb_transactions"].map(fmt.format_compact)

        fig2 = px.scatter(
            df_sc,
            x="nb_transactions",
            y="prix_m2_median",
            text="region",
            color="region",
            color_discrete_sequence=PALETTE,
            labels={
                "nb_transactions": "Nombre de transactions",
                "prix_m2_median": "Prix médian par m²",
                "region": "Région",
            },
        )
        fig2.update_traces(
            textposition="top center",
            marker=dict(size=12),
            customdata=df_sc[["Prix format", "Tx format"]],
            hovertemplate=(
                "<b>%{text}</b><br>"
                "Prix médian par m² : %{customdata[0]}<br>"
                "Transactions : %{customdata[1]}"
                "<extra></extra>"
            ),
        )
        fig2.update_layout(
            margin=dict(l=0, r=0, t=10, b=0),
            showlegend=False,
        )
        st.plotly_chart(fig2, use_container_width=True)

# ── Vue départementale ───────────────────────────────────────────────────────
else:
    dept_df = queries.comparateur_dept_data(
        regions=selected_regions if selected_regions else None
    )

    if dept_df.empty:
        st.info("Aucune donnée départementale disponible pour la sélection.")
    else:
        st.subheader("Prix médian au m² par département")

        df_sorted = dept_df.sort_values("prix_m2_median", ascending=False).head(30)
        df_sorted["label"] = df_sorted["dept"] + " — " + df_sorted["dept_name"]
        df_sorted["Prix format"] = df_sorted["prix_m2_median"].map(fmt.format_euro_m2)
        df_sorted["Tx format"] = df_sorted["nb_transactions"].map(fmt.format_compact)

        fig = px.bar(
            df_sorted.sort_values("prix_m2_median", ascending=True),
            x="prix_m2_median",
            y="label",
            orientation="h",
            color="region",
            color_discrete_sequence=PALETTE,
            labels={
                "prix_m2_median": "Prix médian par m²",
                "label": "Département",
                "region": "Région",
            },
        )
        fig.update_traces(
            customdata=df_sorted.sort_values("prix_m2_median", ascending=True)[
                ["Prix format", "Tx format", "region"]
            ].values,
            hovertemplate=(
                "<b>%{y}</b><br>"
                "Région : %{customdata[2]}<br>"
                "Prix médian par m² : %{customdata[0]}<br>"
                "Transactions : %{customdata[1]}"
                "<extra></extra>"
            ),
        )
        fig.update_layout(
            margin=dict(l=0, r=0, t=10, b=0),
            yaxis_title=None,
            xaxis_title="Prix médian par m²",
            height=max(400, len(df_sorted) * 22),
        )
        st.plotly_chart(fig, use_container_width=True)

# ── DPE régional ─────────────────────────────────────────────────────────────
st.divider()
st.subheader("Répartition DPE par région")

dpe_region = queries.comparateur_dpe_region()

if dpe_region.empty:
    st.info("Aucune donnée DPE régionale disponible.")
else:
    if selected_regions:
        dpe_region = dpe_region[dpe_region["region"].isin(selected_regions)]

    dpe_pivot = (
        dpe_region.groupby(["region", "classe_energetique"])["nb_dpe"]
        .sum()
        .reset_index()
    )
    dpe_pivot["nb_dpe"] = dpe_pivot["nb_dpe"].map(fmt.format_compact)

    fig3 = px.bar(
        dpe_region,
        x="region",
        y="nb_dpe",
        color="classe_energetique",
        color_discrete_map=DPE_COLORS,
        barmode="stack",
        labels={
            "region": "Région",
            "nb_dpe": "Nombre de DPE",
            "classe_energetique": "Classe DPE",
        },
    )
    fig3.update_layout(
        margin=dict(l=0, r=0, t=10, b=0),
        xaxis_title=None,
        yaxis_title="Nombre de DPE",
        legend_title="Classe DPE",
        xaxis_tickangle=-35,
    )
    st.plotly_chart(fig3, use_container_width=True)

st.caption("Source : PostgreSQL `casapedia` · DVF · ADEME · pipeline Airflow.")