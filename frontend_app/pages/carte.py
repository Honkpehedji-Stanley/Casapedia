"""Carte — exploration spatiale multi-échelles (Sprint 1).

Vue interactive à partir des coordonnées communales et des agrégats nationaux.
Bulles communales et heatmap de concentration des transactions.
"""

import pandas as pd
import pydeck as pdk
import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from lib import formatting as fmt
from lib import queries

PALETTE = ["#2B59C3", "#4C78A8", "#72B7B2", "#54A24B", "#EECA3B", "#F58518", "#E45756"]

st.title("Carte")
st.caption("Exploration spatiale multi-échelles")

st.markdown(
    "Visualisation des communes françaises selon leur activité immobilière, "
    "leur prix au m² ou leur parc DPE. Affinez la sélection via les filtres "
    "pour zoomer sur une région ou un département."
)

# ── Sidebar filtres ──────────────────────────────────────────────────────────
with st.sidebar:
    st.subheader("Filtres")

    regions = ["France entière"] + queries.map_regions()
    region_choice = st.selectbox("Région", regions, index=0)

    dept_options = queries.map_depts(
        None if region_choice == "France entière" else region_choice
    )
    dept_choice = st.selectbox("Département", ["Tous"] + dept_options, index=0)

    display_mode = st.radio(
        "Mode d'affichage",
        ["Points communaux", "Heatmap"],
        horizontal=False,
    )

    map_metric = st.selectbox(
        "Indicateur des points",
        ["Nombre de transactions", "Prix médian par m²", "Nombre de DPE"],
        index=0,
    )

# ── Chargement données ───────────────────────────────────────────────────────
region_param = None if region_choice == "France entière" else region_choice
dept_param = None if dept_choice == "Tous" else dept_choice

map_df = queries.commune_map_data(region=region_param, dept=dept_param, limit=8000)

if map_df.empty:
    st.info(
        "Aucune donnée géographique disponible pour ce périmètre. "
        "Vérifiez que le pipeline Airflow a bien chargé les données."
    )
    st.stop()

map_df = map_df.dropna(subset=["latitude", "longitude"]).copy()
map_df["latitude"] = pd.to_numeric(map_df["latitude"], errors="coerce")
map_df["longitude"] = pd.to_numeric(map_df["longitude"], errors="coerce")
map_df = map_df.dropna(subset=["latitude", "longitude"])

if map_df.empty:
    st.info("Les données de ce périmètre ne contiennent pas de coordonnées valides.")
    st.stop()

# ── Calcul métrique ──────────────────────────────────────────────────────────
if map_metric == "Nombre de transactions":
    map_df["metric_value"] = map_df["nb_transactions"].fillna(0)
    map_df["metric_label"] = "Transactions"
    map_df["metric_display"] = map_df["metric_value"].map(fmt.format_compact)
    fill_color = "[44, 89, 195, 170]"
elif map_metric == "Prix médian par m²":
    map_df["metric_value"] = map_df["prix_m2_median"].fillna(0)
    map_df["metric_label"] = "Prix médian par m²"
    map_df["metric_display"] = map_df["metric_value"].map(fmt.format_euro_m2)
    fill_color = "[228, 87, 86, 170]"
else:
    map_df["metric_value"] = map_df["nb_dpe"].fillna(0)
    map_df["metric_label"] = "DPE"
    map_df["metric_display"] = map_df["metric_value"].map(fmt.format_compact)
    fill_color = "[84, 162, 75, 170]"

if map_metric == "Prix médian par m²":
    map_df["radius"] = map_df["metric_value"].clip(lower=0) / 50
else:
    map_df["radius"] = map_df["metric_value"].clip(lower=0)

# ── KPI summary ──────────────────────────────────────────────────────────────
top_communes = map_df.sort_values("metric_value", ascending=False).head(5)
top_regions = ", ".join(sorted(map_df["region"].dropna().unique().tolist())[:3])

col1, col2, col3 = st.columns(3)
col1.metric("Communes cartographiées", fmt.format_compact(len(map_df)))
col2.metric(
    "Communes actives",
    fmt.format_compact(int((map_df["nb_transactions"] > 0).sum())),
)
col3.metric(
    "Périmètre",
    region_choice if region_choice != "France entière" else "France entière",
)

if top_regions:
    st.caption(f"Régions visibles : {top_regions}")

# ── Couches pydeck ───────────────────────────────────────────────────────────
center_lat = float(map_df["latitude"].mean())
center_lon = float(map_df["longitude"].mean())

scatter_layer = pdk.Layer(
    "ScatterplotLayer",
    data=map_df,
    get_position="[longitude, latitude]",
    get_radius="radius",
    get_fill_color=fill_color,
    get_line_color="[255, 255, 255, 100]",
    line_width_min_pixels=1,
    radius_units="meters",
    pickable=True,
    auto_highlight=True,
)

heatmap_layer = pdk.Layer(
    "HeatmapLayer",
    data=map_df,
    get_position="[longitude, latitude]",
    get_weight="metric_value",
    radiusPixels=65,
)

layers = [heatmap_layer] if display_mode == "Heatmap" else [scatter_layer]

tooltip = {
    "html": (
        "<b>{nom}</b><br/>"
        "Département : {dept} — {dept_name}<br/>"
        "Région : {region}<br/>"
        "Transactions : {nb_transactions}<br/>"
        "Prix médian au m² : {prix_m2_median}<br/>"
        "DPE : {nb_dpe}<br/>"
        "Population : {population}<br/>"
        "<b>{metric_label} : {metric_display}</b>"
    ),
    "style": {
        "backgroundColor": "#0F172A",
        "color": "#F8FAFC",
        "fontSize": "12px",
        "padding": "8px",
        "borderRadius": "4px",
    },
}

view_state = pdk.ViewState(
    latitude=center_lat,
    longitude=center_lon,
    zoom=5.0 if region_choice == "France entière" else 7.0,
    pitch=0,
)

deck = pdk.Deck(
    layers=layers,
    initial_view_state=view_state,
    map_style="light",  # style natif pydeck, évite les erreurs CORS/WebGL
    tooltip=tooltip,
)

st.pydeck_chart(deck, use_container_width=True)

# ── Table top communes ───────────────────────────────────────────────────────
st.divider()
st.subheader("Communes les plus actives")

top_display = top_communes[
    ["nom", "dept", "region", "nb_transactions", "prix_m2_median", "nb_dpe"]
].copy()
top_display.columns = [
    "Commune",
    "Département",
    "Région",
    "Transactions",
    "Prix médian par m²",
    "DPE",
]
top_display["Transactions"] = top_display["Transactions"].map(fmt.format_compact)
top_display["Prix médian par m²"] = top_display["Prix médian par m²"].map(
    fmt.format_euro_m2
)
top_display["DPE"] = top_display["DPE"].map(fmt.format_compact)

st.dataframe(top_display, use_container_width=True, hide_index=True)
st.caption("Source : PostgreSQL `casapedia` · curation Spark · pipeline Airflow.")