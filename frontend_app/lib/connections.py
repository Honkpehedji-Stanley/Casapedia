"""Connexions aux sources de données, mises en cache pour la durée de vie de l'app.

Règle de cache Streamlit :
  - st.cache_resource pour les objets vivants non-sérialisables (engine SQLAlchemy,
    MongoClient, client boto3) -> un seul exemplaire réutilisé entre les reruns.
  - st.cache_data (voir queries.py) pour les résultats sérialisables (DataFrames).
"""
import boto3
import streamlit as st
from botocore.client import Config
from pymongo import MongoClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from lib import config


@st.cache_resource(show_spinner=False)
def get_engine() -> Engine:
    """Engine SQLAlchemy vers PostgreSQL (pool géré par SQLAlchemy).

    Utilisé avec pandas.read_sql dans queries.py. pre_ping évite les connexions
    mortes après une longue inactivité de l'app.
    """
    cfg = config.postgres_settings()
    url = (
        f"postgresql+psycopg2://{cfg['user']}:{cfg['password']}"
        f"@{cfg['host']}:{cfg['port']}/{cfg['database']}"
    )
    return create_engine(url, pool_pre_ping=True, pool_recycle=1800)


@st.cache_resource(show_spinner=False)
def get_mongo():
    """Base MongoDB (le MongoClient gère son propre pool ; un seul par session)."""
    cfg = config.mongo_settings()
    uri = (
        f"mongodb://{cfg['user']}:{cfg['password']}"
        f"@{cfg['host']}:{cfg['port']}/?authSource=admin"
    )
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    return client[cfg["database"]]


@st.cache_resource(show_spinner=False)
def get_minio():
    """Client boto3 vers MinIO (lecture des artefacts ML en parquet)."""
    cfg = config.minio_settings()
    return boto3.client(
        "s3",
        endpoint_url=cfg["endpoint_url"],
        aws_access_key_id=cfg["access_key"],
        aws_secret_access_key=cfg["secret_key"],
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
