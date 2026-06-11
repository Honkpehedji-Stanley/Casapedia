"""Requêtes analytiques cachées.

Chaque fonction est décorée par st.cache_data : le résultat (DataFrame ou dict,
sérialisable) est mémorisé et indexé par les arguments. Les connexions vivantes
viennent de connections.py (cache_resource) et ne sont jamais passées en argument
d'une fonction cache_data.

Périmètre Sprint 0 : agrégats NATIONAUX. Les filtres multi-échelles (region/dept/
commune) seront ajoutés au Sprint 2 en paramétrant ces mêmes fonctions.
"""
import pandas as pd
import streamlit as st
from sqlalchemy import text

from lib.connections import get_engine

# TTL : les données sont rechargées par le pipeline Airflow, pas en continu.
_TTL = 3600


def _read_sql(query, params=None):
    engine = get_engine()
    with engine.connect() as conn:
        return pd.read_sql(text(query), conn, params=params or {})


@st.cache_data(ttl=_TTL, show_spinner="Chargement des indicateurs nationaux…")
def national_kpis() -> dict:
    """KPI prioritaires au niveau national (CASAPEDIA_DOC §5.1)."""
    tx = _read_sql(
        """
        SELECT
            COUNT(*)                                              AS nb_transactions,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY prix)     AS prix_median,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY prix_m2)  AS prix_m2_median
        FROM transactions
        WHERE prix_m2 IS NOT NULL AND prix_m2 > 0
        """
    )
    pop = _read_sql("SELECT SUM(population_actuelle) AS population FROM communes")

    # TODO Sprint 1+ : revenu médian à fiabiliser après exploration de
    # revenue_disponible (variables unite_mesure / unite_mult / filtres niveau géo).
    # La médiane brute de `valeur` mélange plusieurs mesures/dimensions INSEE et ne
    # constitue PAS un vrai revenu médian. Ne pas réintroduire avant validation de la
    # modalité. Requête de départ conservée pour mémoire :
    #   SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY valeur) AS revenu_median
    #   FROM revenue_disponible WHERE valeur IS NOT NULL

    row = tx.iloc[0]
    return {
        "nb_transactions": _scalar(row["nb_transactions"]),
        "prix_median": _scalar(row["prix_median"]),
        "prix_m2_median": _scalar(row["prix_m2_median"]),
        "population": _scalar(pop.iloc[0]["population"]),
    }


@st.cache_data(ttl=_TTL, show_spinner=False)
def transactions_by_year() -> pd.DataFrame:
    """Volume et prix/m² médian par année (courbe de tendance temporelle)."""
    return _read_sql(
        """
        SELECT
            EXTRACT(YEAR FROM date_transaction)::int            AS annee,
            COUNT(*)                                            AS nb_transactions,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY prix_m2) AS prix_m2_median
        FROM transactions
        WHERE date_transaction IS NOT NULL
          AND prix_m2 IS NOT NULL AND prix_m2 > 0
        GROUP BY 1
        ORDER BY 1
        """
    )


@st.cache_data(ttl=_TTL, show_spinner=False)
def type_bien_distribution() -> pd.DataFrame:
    """Répartition des transactions par type de bien (barres)."""
    return _read_sql(
        """
        SELECT COALESCE(NULLIF(TRIM(type_bien), ''), 'Inconnu') AS type_bien,
               COUNT(*) AS nb_transactions
        FROM transactions
        GROUP BY 1
        ORDER BY nb_transactions DESC
        """
    )


@st.cache_data(ttl=_TTL, show_spinner=False)
def dpe_distribution() -> pd.DataFrame:
    """Répartition des classes énergétiques DPE (A..G)."""
    return _read_sql(
        """
        SELECT classe_energetique, COUNT(*) AS nb_dpe
        FROM dpe
        WHERE classe_energetique IS NOT NULL
        GROUP BY classe_energetique
        ORDER BY classe_energetique
        """
    )


@st.cache_data(ttl=_TTL, show_spinner=False)
def data_health() -> pd.DataFrame:
    """Nombre de lignes par table de publication (santé du chargement BDD)."""
    tables = [
        "communes", "transactions", "dpe",
        "demographics_population", "demographics_density", "demographics_chomage",
        "revenue_disponible", "bpe_equipment", "bpe_rollups", "bpe_evolution",
    ]
    union = "\nUNION ALL\n".join(
        f"SELECT '{t}' AS table_name, COUNT(*) AS lignes FROM {t}" for t in tables
    )
    return _read_sql(union + "\nORDER BY table_name")


def _scalar(value):
    """Normalise une valeur SQL (NaN/None -> None, sinon float/int natif)."""
    if value is None or pd.isna(value):
        return None
    return value.item() if hasattr(value, "item") else value
