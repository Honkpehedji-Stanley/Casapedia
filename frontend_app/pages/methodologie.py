"""Méthodologie — sources, fraîcheur, formules, santé des données (CASAPEDIA_DOC §6.3)."""
import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from lib import queries

st.title("📖 Méthodologie & sources")

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

st.subheader("🩺 Santé des données (lignes par table)")
try:
    health = queries.data_health()
    st.dataframe(health, width="stretch", hide_index=True)
except SQLAlchemyError:
    st.warning("PostgreSQL injoignable — impossible d'afficher le décompte des tables.")
