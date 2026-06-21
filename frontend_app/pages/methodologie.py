"""Méthodologie — sources, formules et santé des données.

Transparence sur les sources, les traitements appliqués
et l'état actuel des tables en base.
"""

import streamlit as st

from lib import formatting as fmt
from lib import queries

st.title("Méthodologie")
st.caption("Sources de données · formules · état du pipeline")

st.markdown(
    """
    **Pipeline Big Data** : sources publiques → ingestion Airflow → MinIO (raw) →
    curation Spark (`clean_tabulaires`, `clean_reviews`, `ML_predictions`) →
    MinIO (processed) → PostgreSQL (tabulaire) + MongoDB (textuel).
    
    **Sources principales**
    - **DVF** (transactions immobilières) → `transactions`
    - **INSEE** (population, densité, chômage, revenus) → `demographics_*`, `revenue_disponible`
    - **ADEME** (diagnostics énergétiques) → `dpe`
    - **BPE** (équipements/infrastructures) → `bpe_*`
    - **Avis web** (textuel) → MongoDB `reviews_clean`
    
    **Indicateurs** : prix médian et prix/m² médian calculés via `percentile_cont(0.5)`
    sur PostgreSQL. Les prédictions de prix/m² (Spark MLlib) sont des artefacts parquet
    dans MinIO (`processed/ml_predictions/`).
    """
)

# ── Sources ──────────────────────────────────────────────────────────────────
st.divider()
st.subheader("Sources de données")

sources = [
    {
        "Jeu de données": "DVF — Demandes de valeurs foncières",
        "Fournisseur": "DGFiP / data.gouv.fr",
        "Couverture": "2021 — 2025",
        "Table PostgreSQL": "transactions",
        "Volume indicatif": "~5,1 M lignes",
    },
    {
        "Jeu de données": "Référentiel communal (COG)",
        "Fournisseur": "INSEE",
        "Couverture": "Millésime courant",
        "Table PostgreSQL": "communes",
        "Volume indicatif": "~36 000 lignes",
    },
    {
        "Jeu de données": "Population communale",
        "Fournisseur": "INSEE",
        "Couverture": "Millésime source disponible",
        "Table PostgreSQL": "demographics_population",
        "Volume indicatif": "~34 900 lignes",
    },
    {
        "Jeu de données": "Densité de population",
        "Fournisseur": "INSEE / data.gouv.fr",
        "Couverture": "Millésime source disponible",
        "Table PostgreSQL": "demographics_density",
        "Volume indicatif": "~69 800 lignes",
    },
    {
        "Jeu de données": "Chômage communal (15–64 ans)",
        "Fournisseur": "INSEE",
        "Couverture": "Millésime source disponible",
        "Table PostgreSQL": "demographics_chomage",
        "Volume indicatif": "~104 400 lignes",
    },
    {
        "Jeu de données": "Revenu disponible agrégé",
        "Fournisseur": "INSEE",
        "Couverture": "2023",
        "Table PostgreSQL": "revenue_disponible",
        "Volume indicatif": "~366 lignes",
    },
    {
        "Jeu de données": "DPE — Diagnostics de performance énergétique",
        "Fournisseur": "ADEME",
        "Couverture": "Flux courant (reprise paginée)",
        "Table PostgreSQL": "dpe",
        "Volume indicatif": "~4,7 M lignes",
    },
    {
        "Jeu de données": "BPE — Base permanente des équipements",
        "Fournisseur": "INSEE",
        "Couverture": "2024",
        "Table PostgreSQL": "bpe_equipment, bpe_rollups, bpe_evolution",
        "Volume indicatif": "~4,2 M lignes (3 tables)",
    },
    {
        "Jeu de données": "Avis habitants",
        "Fournisseur": "Scraping web",
        "Couverture": "Date de crawl et date source",
        "Table PostgreSQL": "MongoDB reviews_clean",
        "Volume indicatif": "~114 documents",
    },
]

import pandas as pd  # noqa: E402

st.dataframe(
    pd.DataFrame(sources),
    use_container_width=True,
    hide_index=True,
)

# ── Pipeline ─────────────────────────────────────────────────────────────────
st.divider()
st.subheader("Pipeline de traitement")

st.markdown(
    """
La chaîne de traitement comporte trois étapes orchestrées par Apache Airflow :

**1. Ingestion** (`1_ingestion_raw_data`)  
Téléchargement des fichiers sources publics et des avis web vers MinIO `raw`.
Les données brutes ne sont jamais modifiées à cette étape.

**2. Curation Spark** (`2_transform_spark_data`)  
Nettoyage, normalisation des identifiants communes, cast des types numériques
et suppression des lignes invalides. Les fichiers JSONL propres sont écrits
dans MinIO `processed`.

**3. Chargement base** (`3_load_databases`)  
Publication des données curatées dans PostgreSQL (tables relationnelles avec
clés étrangères vers `communes`) et dans MongoDB (`reviews_clean`).
Un système de checkpoints garantit la reprise idempotente des lots volumineux.
"""
)

# ── Formules ─────────────────────────────────────────────────────────────────
st.divider()
st.subheader("Formules et conventions de calcul")

st.markdown(
    """
**Prix médian de vente**  
`PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY prix) FILTER (WHERE prix > 0)`  
Calculé côté PostgreSQL pour éviter le transfert de millions de lignes.
Robuste aux valeurs extrêmes DVF (successions atypiques, ventes groupées).

**Prix médian au m²**  
`PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY prix_m2) FILTER (WHERE prix_m2 > 0)`  
Filtre `prix_m2 > 0` pour exclure les biens sans surface déclarée.

**Taux de chômage**  
Ratio `chomeurs_15_64 / actifs_15_64` issu de la source INSEE.
Exprimé en pourcentage dans l'interface.

**Classes DPE**  
Étiquettes A à G issues de la source ADEME. Les valeurs hors plage (vides,
codes inconnus) sont exclues des agrégats grâce à la contrainte CHECK de la table.

**Sentiment des avis**  
Dérivé de la note source : positif ≥ 4 / 5, neutre entre 3 et 4, négatif < 3.
Aucun modèle NLP externe n'est appliqué à ce stade ; la classification repose
uniquement sur la note déclarée par l'auteur de l'avis.

**Revenu disponible**  
La médiane brute de `revenue_disponible.valeur` n'est pas exposée dans l'interface.
Le jeu INSEE mélange plusieurs mesures et tranches (`mesure`, `nb_pers`, `pcs`)
sans filtrage, ce qui produirait une valeur non interprétable.
Ce KPI sera réintroduit après fiabilisation (dette technique Sprint 1).
"""
)

# ── Santé des données ────────────────────────────────────────────────────────
st.divider()
st.subheader("État actuel des tables")

health_df = queries.data_health()

if health_df.empty:
    st.warning(
        "Impossible de joindre PostgreSQL. "
        "Vérifiez que `docker compose up` est actif et que le DAG `3_load_databases` "
        "a publié les données."
    )
else:
    def _style_statut(val):
        if val == "OK":
            return "color: #54A24B; font-weight: 600"
        return "color: #E45756; font-weight: 600"

    def _format_lignes(val):
        if val is None:
            return "—"
        return fmt.format_compact(int(val))

    health_display = health_df.copy()
    health_display["Lignes"] = health_display["Lignes"].map(_format_lignes)

    st.dataframe(
        health_display.style.applymap(_style_statut, subset=["Statut"]),
        use_container_width=True,
        hide_index=True,
    )

st.caption(
    "Source : PostgreSQL `casapedia_db` · MongoDB `casapedia.reviews_clean` · pipeline Airflow."
)