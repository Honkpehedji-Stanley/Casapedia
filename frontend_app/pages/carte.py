"""Carte — exploration spatiale multi-échelles (interactive).

Carte pydeck (deck.gl, fond Carto sans token) : bulles communales dimensionnées
et colorées selon l'indicateur choisi, avec tooltip au survol (commune, prix au m²,
transactions, DPE, population). Filtres région / département (libellés) cascadés.
"""

import pandas as pd
import pydeck as pdk
import streamlit as st

from lib import formatting as fmt
from lib import queries
from lib import theme

theme.topbar(
    "Carte interactive du marché",
    "Exploration spatiale multi-échelles · France métropolitaine",
    chip="Marché résidentiel · DVF",
)


def _rgb_scale(t: float, stops: list[str]) -> list[int]:
    """Couleur [r,g,b] interpolée le long des stops hex, pour t dans [0,1]."""
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    pos = t * (len(stops) - 1)
    i = int(pos)
    f = pos - i
    c1, c2 = stops[i], stops[min(i + 1, len(stops) - 1)]
    r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
    r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
    return [round(r1 + (r2 - r1) * f), round(g1 + (g2 - g1) * f), round(b1 + (b2 - b1) * f)]


# ── Sidebar filtres ──────────────────────────────────────────────────────────
with st.sidebar:
    st.subheader("Filtres")

    regions = ["France entière"] + queries.map_regions()
    region_choice = st.selectbox(
        "Région", regions, index=0,
        help="Restreint la carte à une région. « France entière » = tout le pays.",
    )
    region_param = None if region_choice == "France entière" else region_choice

    # Département : libellé « code — nom », cascadé sur la région choisie.
    dept_opts = queries.map_dept_options(region_param)
    dept_labels = ["Tous les départements"] + [
        f"{r.dept} — {r.dept_name}" for r in dept_opts.itertuples()
    ]
    dept_label = st.selectbox(
        "Département", dept_labels, index=0,
        help="Affiné selon la région. Choisissez un département pour zoomer dessus.",
    )
    dept_param = None if dept_label == "Tous les départements" else dept_label.split(" — ")[0]

    map_metric = st.selectbox(
        "Indicateur (couleur & taille des bulles)",
        ["Nombre de transactions", "Prix médian par m²", "Nombre de DPE"],
        index=0,
        help="Détermine la couleur et la taille de chaque bulle communale.",
    )

# ── Chargement données ───────────────────────────────────────────────────────
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

# ── Métrique sélectionnée ─────────────────────────────────────────────────────
if map_metric == "Nombre de transactions":
    map_df["metric_value"] = map_df["nb_transactions"].fillna(0)
    map_df["metric_display"] = map_df["metric_value"].map(fmt.format_compact)
    stops = ["#BCD2F5", "#3D6FD6", "#1E3A8A"]
elif map_metric == "Prix médian par m²":
    map_df["metric_value"] = map_df["prix_m2_median"].fillna(0)
    map_df["metric_display"] = map_df["metric_value"].map(fmt.format_euro_m2)
    stops = theme.SCALE_PRICE
else:
    map_df["metric_value"] = map_df["nb_dpe"].fillna(0)
    map_df["metric_display"] = map_df["metric_value"].map(fmt.format_compact)
    stops = ["#BCD2F5", "#52B043", "#1F8F4E"]

vals = map_df["metric_value"].astype(float)
vmin, vmax = float(vals.min()), float(vals.max())
_span = (vmax - vmin) or 1.0

# Champs pour pydeck : couleur RGBA, rayon (m), libellés formatés pour le tooltip.
map_df["fill"] = vals.map(lambda v: _rgb_scale((v - vmin) / _span, stops) + [200])
map_df["radius_m"] = vals.map(lambda v: 700 + (max(v, 0) / (vmax or 1.0)) * 9000)
map_df["tx_fmt"] = map_df["nb_transactions"].map(fmt.format_compact)
map_df["prix_fmt"] = map_df["prix_m2_median"].map(fmt.format_euro_m2)
map_df["dpe_fmt"] = map_df["nb_dpe"].map(fmt.format_compact)
map_df["pop_fmt"] = map_df["population"].map(fmt.format_compact)

# ── KPI ───────────────────────────────────────────────────────────────────────
top_communes = map_df.sort_values("metric_value", ascending=False).head(8)
col1, col2, col3 = st.columns(3)
col1.metric("Communes cartographiées", fmt.format_compact(len(map_df)))
col2.metric("Communes actives", fmt.format_compact(int((map_df["nb_transactions"] > 0).sum())))
col3.metric("Périmètre", region_choice if region_param else "France entière")

# ── Carte pydeck interactive (fond Carto, sans token) ────────────────────────
zoom = 4.6 if (region_param is None and dept_param is None) else (6.2 if dept_param is None else 8.0)
view_state = pdk.ViewState(
    latitude=float(map_df["latitude"].mean()),
    longitude=float(map_df["longitude"].mean()),
    zoom=zoom,
    pitch=0,
)
layer = pdk.Layer(
    "ScatterplotLayer",
    data=map_df,
    get_position="[longitude, latitude]",
    get_radius="radius_m",
    get_fill_color="fill",
    get_line_color=[255, 255, 255, 140],
    line_width_min_pixels=0.5,
    radius_min_pixels=2,
    radius_max_pixels=45,
    pickable=True,
    auto_highlight=True,
)
tooltip = {
    "html": (
        "<b>{nom}</b><br/>"
        "{dept} — {dept_name} · {region}<br/>"
        "Transactions : {tx_fmt}<br/>"
        "Prix médian/m² : {prix_fmt}<br/>"
        "DPE : {dpe_fmt} · Population : {pop_fmt}"
    ),
    "style": {"backgroundColor": "#1E293B", "color": "#F8FAFC",
              "fontSize": "12px", "padding": "8px", "borderRadius": "8px"},
}

with st.container(border=True):
    theme.card_title(
        f"{map_metric} par commune",
        "Survolez une bulle pour le détail · molette = zoom · glisser = déplacer",
    )
    st.pydeck_chart(
        pdk.Deck(
            layers=[layer],
            initial_view_state=view_state,
            map_provider="carto",
            map_style="light",
            tooltip=tooltip,
        ),
        width="stretch",
    )

# ── Table top communes ───────────────────────────────────────────────────────
st.divider()
st.subheader("Communes les plus actives")
top_display = top_communes[["nom", "dept", "region", "nb_transactions", "prix_m2_median", "nb_dpe"]].copy()
top_display.columns = ["Commune", "Département", "Région", "Transactions", "Prix médian par m²", "DPE"]
top_display["Transactions"] = top_display["Transactions"].map(fmt.format_compact)
top_display["Prix médian par m²"] = top_display["Prix médian par m²"].map(fmt.format_euro_m2)
top_display["DPE"] = top_display["DPE"].map(fmt.format_compact)
st.dataframe(top_display, width="stretch", hide_index=True)
theme.footer("Source : PostgreSQL `casapedia` · curation Spark · pipeline Airflow.")
