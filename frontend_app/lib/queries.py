"""Requêtes analytiques cachées.

Chaque fonction est décorée par st.cache_data : le résultat (DataFrame ou dict,
sérialisable) est mémorisé et indexé par les arguments. Les connexions vivantes
viennent de connections.py (cache_resource) et ne sont jamais passées en argument
d'une fonction cache_data.

Périmètre :
  Sprint 0 — agrégats nationaux (dashboard)
  Sprint 1 — données cartographiques (carte)
  Sprint 3 — fiche commune
  Sprint 4 — comparateur régional / départemental
  Sprint 5 — avis MongoDB (NLP)
  Méthodologie — santé des données (data_health étendu)
"""

import pandas as pd
import streamlit as st
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from lib.connections import get_engine

# TTL : les données sont rechargées par le pipeline Airflow, pas en continu.
_TTL = 3600


def _read_sql(query, params=None):
    engine = get_engine()
    with engine.connect() as conn:
        return pd.read_sql(text(query), conn, params=params or {})


def _scalar(value):
    """Normalise une valeur SQL (NaN/None -> None, sinon float/int natif)."""
    if value is None or pd.isna(value):
        return None
    return value.item() if hasattr(value, "item") else value


# ─────────────────────────────────────────────────────────────────────────────
# Sprint 0 — Dashboard national
# ─────────────────────────────────────────────────────────────────────────────

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
    pop = _read_sql(
        """
        WITH latest_year AS (
            SELECT MAX(annee) AS annee
            FROM demographics_population
            WHERE population IS NOT NULL
        )
        SELECT SUM(dp.population) AS population
        FROM demographics_population dp
        JOIN latest_year ly ON ly.annee = dp.annee
        WHERE dp.population IS NOT NULL
        """
    )

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
            EXTRACT(YEAR FROM date_transaction)::int              AS annee,
            COUNT(*)                                              AS nb_transactions,
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
    """Répartition des classes énergétiques DPE (A..G) — national."""
    return _read_sql(
        """
        SELECT classe_energetique, COUNT(*) AS nb_dpe
        FROM dpe
        WHERE classe_energetique IS NOT NULL
        GROUP BY classe_energetique
        ORDER BY classe_energetique
        """
    )


# ─────────────────────────────────────────────────────────────────────────────
# Sprint 1 — Carte
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=_TTL, show_spinner=False)
def map_regions() -> list[str]:
    """Liste des régions disponibles pour la carte."""
    df = _read_sql(
        """
        SELECT DISTINCT region
        FROM communes
        WHERE latitude IS NOT NULL
          AND longitude IS NOT NULL
          AND region IS NOT NULL
          AND TRIM(region) <> ''
        ORDER BY region
        """
    )
    return df["region"].dropna().tolist()


@st.cache_data(ttl=_TTL, show_spinner=False)
def map_depts(region: str | None = None) -> list[str]:
    """Liste des départements disponibles pour une région donnée."""
    params = {}
    where_clause = ""
    if region:
        where_clause = "AND region = :region"
        params["region"] = region
    df = _read_sql(
        f"""
        SELECT DISTINCT dept
        FROM communes
        WHERE latitude IS NOT NULL
          AND longitude IS NOT NULL
          AND dept IS NOT NULL
          AND TRIM(dept) <> ''
          {where_clause}
        ORDER BY dept
        """,
        params,
    )
    return df["dept"].dropna().astype(str).tolist()


@st.cache_data(ttl=_TTL, show_spinner=False)
def commune_map_data(
    region: str | None = None,
    dept: str | None = None,
    limit: int = 8000,
) -> pd.DataFrame:
    """Données communales prêtes pour la carte (points + agrégats)."""
    params: dict = {"limit": limit}
    filters = ["c.latitude IS NOT NULL", "c.longitude IS NOT NULL"]
    if region:
        filters.append("c.region = :region")
        params["region"] = region
    if dept:
        filters.append("c.dept = :dept")
        params["dept"] = str(dept)

    where_clause = " AND ".join(filters)
    return _read_sql(
        f"""
        WITH tx AS (
            SELECT commune_id,
                   COUNT(*) AS nb_transactions,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY prix_m2) AS prix_m2_median,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY prix)    AS prix_median
            FROM transactions
            WHERE prix_m2 IS NOT NULL AND prix_m2 > 0
            GROUP BY commune_id
        ),
        dpe_agg AS (
            SELECT commune_id,
                   COUNT(*) AS nb_dpe,
                   ROUND(
                       100.0 * COUNT(*) FILTER (WHERE classe_energetique IN ('A', 'B'))
                       / NULLIF(COUNT(*), 0), 1
                   ) AS part_a_b
            FROM dpe
            WHERE classe_energetique IS NOT NULL
            GROUP BY commune_id
        ),
        pop AS (
            SELECT commune_id, population
            FROM demographics_population
            WHERE annee = (
                SELECT MAX(annee)
                FROM demographics_population
                WHERE population IS NOT NULL
            )
            AND population IS NOT NULL
        )
        SELECT
            c.code_insee,
            c.nom,
            c.dept,
            c.dept_name,
            c.region,
            c.latitude,
            c.longitude,
            COALESCE(tx.nb_transactions, 0)  AS nb_transactions,
            tx.prix_m2_median,
            tx.prix_median,
            COALESCE(dpe_agg.nb_dpe, 0)      AS nb_dpe,
            dpe_agg.part_a_b,
            pop.population
        FROM communes c
        LEFT JOIN tx       ON tx.commune_id       = c.code_insee
        LEFT JOIN dpe_agg  ON dpe_agg.commune_id  = c.code_insee
        LEFT JOIN pop      ON pop.commune_id       = c.code_insee
        WHERE {where_clause}
        ORDER BY nb_transactions DESC, c.nom
        LIMIT :limit
        """,
        params,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Sprint 3 — Fiche commune
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=_TTL, show_spinner=False)
def search_communes(query: str, limit: int = 20) -> pd.DataFrame:
    """Recherche plein-texte sur le nom de commune."""
    return _read_sql(
        """
        SELECT code_insee, nom, dept, dept_name, region
        FROM communes
        WHERE LOWER(nom) LIKE LOWER(:q)
        ORDER BY nom
        LIMIT :lim
        """,
        {"q": f"%{query}%", "lim": limit},
    )


@st.cache_data(ttl=_TTL, show_spinner=False)
def commune_detail(code_insee: str) -> dict:
    """Informations de base d'une commune."""
    try:
        engine = get_engine()
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT nom, dept, dept_name, region,
                           latitude, longitude, population_actuelle
                    FROM communes
                    WHERE code_insee = :c
                    """
                ),
                {"c": code_insee},
            ).fetchone()
        return dict(row._mapping) if row else {}
    except SQLAlchemyError:
        return {}


@st.cache_data(ttl=_TTL, show_spinner=False)
def commune_transactions_kpi(code_insee: str) -> dict:
    """KPI immobiliers pour une commune."""
    try:
        df = _read_sql(
            """
            SELECT
                COUNT(*)                                                       AS nb_transactions,
                percentile_cont(0.5) WITHIN GROUP (ORDER BY prix)
                    FILTER (WHERE prix > 0)                                    AS prix_median,
                percentile_cont(0.5) WITHIN GROUP (ORDER BY prix_m2)
                    FILTER (WHERE prix_m2 > 0)                                 AS prix_m2_median,
                AVG(surface) FILTER (WHERE surface > 0)                        AS surface_moyenne
            FROM transactions
            WHERE commune_id = :c
            """,
            {"c": code_insee},
        )
        row = df.iloc[0]
        return {k: _scalar(row[k]) for k in row.index}
    except (SQLAlchemyError, IndexError):
        return {}


@st.cache_data(ttl=_TTL, show_spinner=False)
def commune_transactions_by_year(code_insee: str) -> pd.DataFrame:
    """Évolution annuelle des transactions pour une commune."""
    return _read_sql(
        """
        SELECT
            EXTRACT(YEAR FROM date_transaction)::INTEGER          AS annee,
            COUNT(*)                                              AS nb_transactions,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY prix_m2)
                FILTER (WHERE prix_m2 > 0)                        AS prix_m2_median
        FROM transactions
        WHERE commune_id = :c
          AND date_transaction IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        {"c": code_insee},
    )


@st.cache_data(ttl=_TTL, show_spinner=False)
def commune_type_bien(code_insee: str) -> pd.DataFrame:
    """Répartition des types de bien pour une commune."""
    return _read_sql(
        """
        SELECT COALESCE(NULLIF(TRIM(type_bien), ''), 'Inconnu') AS type_bien,
               COUNT(*) AS nb_transactions
        FROM transactions
        WHERE commune_id = :c
        GROUP BY 1
        ORDER BY 2 DESC
        """,
        {"c": code_insee},
    )


@st.cache_data(ttl=_TTL, show_spinner=False)
def commune_dpe(code_insee: str) -> pd.DataFrame:
    """Répartition DPE pour une commune."""
    return _read_sql(
        """
        SELECT classe_energetique, COUNT(*) AS nb_dpe
        FROM dpe
        WHERE commune_id = :c
          AND classe_energetique IS NOT NULL
        GROUP BY classe_energetique
        ORDER BY classe_energetique
        """,
        {"c": code_insee},
    )


@st.cache_data(ttl=_TTL, show_spinner=False)
def commune_demographics(code_insee: str) -> dict:
    """Contexte démographique (population, chômage, densité) pour une commune."""
    result: dict = {}
    try:
        engine = get_engine()
        with engine.connect() as conn:
            pop = conn.execute(
                text(
                    """
                    SELECT annee, population
                    FROM demographics_population
                    WHERE commune_id = :c
                    ORDER BY annee DESC LIMIT 1
                    """
                ),
                {"c": code_insee},
            ).fetchone()
            chom = conn.execute(
                text(
                    """
                    SELECT annee, taux_chomage
                    FROM demographics_chomage
                    WHERE commune_id = :c
                    ORDER BY annee DESC LIMIT 1
                    """
                ),
                {"c": code_insee},
            ).fetchone()
            dens = conn.execute(
                text(
                    """
                    SELECT annee, densite_population
                    FROM demographics_density
                    WHERE commune_id = :c
                    ORDER BY annee DESC LIMIT 1
                    """
                ),
                {"c": code_insee},
            ).fetchone()
        if pop:
            result["population"] = pop[1]
            result["pop_annee"] = pop[0]
        if chom:
            result["taux_chomage"] = float(chom[1]) * 100
            result["chom_annee"] = chom[0]
        if dens:
            result["densite"] = float(dens[1])
            result["dens_annee"] = dens[0]
    except SQLAlchemyError:
        pass
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Sprint 4 — Comparateur
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=_TTL, show_spinner=False)
def comparateur_region_data() -> pd.DataFrame:
    """Agrégats transactions par région."""
    return _read_sql(
        """
        SELECT
            c.region,
            COUNT(t.id)                                                        AS nb_transactions,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY t.prix_m2)
                FILTER (WHERE t.prix_m2 > 0)                                   AS prix_m2_median,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY t.prix)
                FILTER (WHERE t.prix > 0)                                      AS prix_median,
            AVG(t.surface) FILTER (WHERE t.surface > 0)                        AS surface_moyenne
        FROM transactions t
        JOIN communes c ON c.code_insee = t.commune_id
        WHERE c.region IS NOT NULL
        GROUP BY c.region
        ORDER BY prix_m2_median DESC NULLS LAST
        """
    )


@st.cache_data(ttl=_TTL, show_spinner=False)
def comparateur_dept_data(regions: list[str] | None = None) -> pd.DataFrame:
    """Agrégats transactions par département, filtrable par liste de régions."""
    params: dict = {}
    where = ""
    if regions:
        where = "WHERE c.region = ANY(:regions)"
        params["regions"] = regions
    return _read_sql(
        f"""
        SELECT
            c.dept,
            c.dept_name,
            c.region,
            COUNT(t.id)                                                        AS nb_transactions,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY t.prix_m2)
                FILTER (WHERE t.prix_m2 > 0)                                   AS prix_m2_median,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY t.prix)
                FILTER (WHERE t.prix > 0)                                      AS prix_median
        FROM transactions t
        JOIN communes c ON c.code_insee = t.commune_id
        {where}
        GROUP BY c.dept, c.dept_name, c.region
        ORDER BY prix_m2_median DESC NULLS LAST
        """,
        params,
    )


@st.cache_data(ttl=_TTL, show_spinner=False)
def comparateur_dpe_region() -> pd.DataFrame:
    """Répartition DPE par région (pour graphique empilé)."""
    return _read_sql(
        """
        SELECT
            c.region,
            d.classe_energetique,
            COUNT(*) AS nb_dpe
        FROM dpe d
        JOIN communes c ON c.code_insee = d.commune_id
        WHERE c.region IS NOT NULL
          AND d.classe_energetique IS NOT NULL
        GROUP BY c.region, d.classe_energetique
        ORDER BY c.region, d.classe_energetique
        """
    )


# ─────────────────────────────────────────────────────────────────────────────
# Sprint 5 — NLP / Avis MongoDB
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=_TTL, show_spinner=False)
def nlp_cities() -> list[str]:
    """Liste des villes disponibles dans reviews_clean."""
    try:
        from lib.connections import get_mongo_db
        db = get_mongo_db()
        cities = db["reviews_clean"].distinct("city_name")
        return sorted([c for c in cities if c])
    except Exception:
        return []


@st.cache_data(ttl=_TTL, show_spinner=False)
def nlp_reviews(city: str | None = None, limit: int = 500) -> pd.DataFrame:
    """
    Lit les avis depuis MongoDB reviews_clean.
    Colonnes : city_name, commune_id, rating, review_text,
               positive_text, negative_text, clean_text, review_date, source.
    """
    try:
        from lib.connections import get_mongo_db
        db = get_mongo_db()
        query: dict = {}
        if city:
            query["city_name"] = {"$regex": city, "$options": "i"}
        docs = list(
            db["reviews_clean"].find(
                query,
                {
                    "_id": 0,
                    "city_name": 1,
                    "commune_id": 1,
                    "rating": 1,
                    "review_text": 1,
                    "positive_text": 1,
                    "negative_text": 1,
                    "clean_text": 1,
                    "review_date": 1,
                    "source": 1,
                },
                limit=limit,
            )
        )
        return pd.DataFrame(docs) if docs else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


# ─────────────────────────────────────────────────────────────────────────────
# Méthodologie — santé des données
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=_TTL, show_spinner=False)
def data_health() -> pd.DataFrame:
    """Nombre de lignes par table de publication (santé du chargement BDD)."""
    tables = [
        ("communes",                "Référentiel communal"),
        ("transactions",            "Transactions DVF"),
        ("dpe",                     "DPE"),
        ("demographics_population", "Population"),
        ("demographics_density",    "Densité"),
        ("demographics_chomage",    "Chômage"),
        ("revenue_disponible",      "Revenu disponible"),
        ("bpe_equipment",           "Équipements BPE"),
        ("bpe_rollups",             "Agrégats BPE"),
        ("bpe_evolution",           "Évolution BPE"),
    ]
    rows = []
    try:
        engine = get_engine()
        with engine.connect() as conn:
            for table, label in tables:
                try:
                    count = conn.execute(
                        text(f"SELECT COUNT(*) FROM {table}")
                    ).scalar()
                    rows.append({"Table": label, "Lignes": count, "Statut": "OK"})
                except Exception:
                    rows.append({"Table": label, "Lignes": None, "Statut": "Indisponible"})
    except SQLAlchemyError:
        return pd.DataFrame()
    return pd.DataFrame(rows)
