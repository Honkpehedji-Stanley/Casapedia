"""Configuration centralisée du frontend.

Lit les variables d'environnement (mêmes clés que le reste du projet : Postgres,
MongoDB, MinIO) et expose des constantes de domaine partagées par toutes les pages.
"""
import os

from dotenv import load_dotenv

load_dotenv()


# --- Niveaux de lecture multi-échelles (project.pdf : national -> communal) ---
SCALE_NATIONAL = "national"
SCALE_REGION = "region"
SCALE_DEPARTEMENT = "departement"
SCALE_COMMUNE = "commune"

SCALE_LEVELS = [SCALE_NATIONAL, SCALE_REGION, SCALE_DEPARTEMENT, SCALE_COMMUNE]

# Colonne de regroupement Postgres associée à chaque échelle (table communes).
SCALE_GROUP_COLUMN = {
    SCALE_REGION: "region_code",
    SCALE_DEPARTEMENT: "dept",
    SCALE_COMMUNE: "code_insee",
}

# Classes énergétiques DPE, dans l'ordre d'affichage (project.pdf : A..G).
DPE_CLASSES = ["A", "B", "C", "D", "E", "F", "G"]


def postgres_settings():
    """Paramètres de connexion PostgreSQL (mêmes défauts que database/db_manager.py)."""
    return {
        "host": os.getenv("DB_HOST", "localhost"),
        "port": os.getenv("DB_PORT", "5432"),
        "database": os.getenv("DB_NAME", "casapedia_db"),
        "user": os.getenv("DB_USER", "postgres"),
        "password": os.getenv("DB_PASSWORD", "postgres"),
    }


def mongo_settings():
    """Paramètres de connexion MongoDB (mêmes défauts que database/mongo_manager.py)."""
    return {
        "host": os.getenv("MONGO_HOST", "localhost"),
        "port": os.getenv("MONGO_PORT", "27017"),
        "database": os.getenv("MONGO_DB", "casapedia"),
        "user": os.getenv("MONGO_USER", "root"),
        "password": os.getenv("MONGO_PASSWORD", "examplepassword"),
    }


def minio_settings():
    """Paramètres MinIO/S3 (mêmes clés que storage/minio_utils.py)."""
    return {
        "endpoint_url": os.getenv("MINIO_ENDPOINT", "http://localhost:9000"),
        "access_key": os.getenv("MINIO_ROOT_USER", "minioadmin"),
        "secret_key": os.getenv("MINIO_ROOT_PASSWORD", "minioadmin123"),
        "bucket": os.getenv("CASAPEDIA_S3_BUCKET", "casapedia-datalake"),
    }


def mapbox_token():
    """Token Mapbox optionnel.

    Si présent, les cartes Plotly/Pydeck basculent sur un style Mapbox premium ;
    sinon on reste sur les fonds libres (open-street-map / Carto), sans token.
    """
    return os.getenv("MAPBOX_TOKEN") or None
