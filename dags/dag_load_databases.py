from __future__ import annotations

import json
import os
import sys
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import psycopg2
from airflow import DAG
from airflow.operators.python import PythonOperator
from botocore.exceptions import ClientError

AIRFLOW_HOME = Path(__file__).resolve().parents[1]
if str(AIRFLOW_HOME) not in sys.path:
    sys.path.insert(0, str(AIRFLOW_HOME))

from storage.minio_utils import ensure_bucket, get_minio_client, get_minio_settings

DEFAULT_ARGS = {
    "owner": "casapedia",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

POSTGRES_TABLES = [
    "communes",
    "transactions",
    "demographics_population",
    "demographics_density",
    "demographics_chomage",
    "revenue_disponible",
    "dpe",
    "bpe_equipment",
    "bpe_rollups",
    "bpe_evolution",
]

LOAD_PLAN = [
    ("communes", "processed/communes/communes.jsonl", ["code_insee", "nom", "code_postal", "latitude", "longitude", "dept", "dept_name", "region_code", "region"]),
    ("transactions", "processed/transactions/transactions.jsonl", ["id", "commune_id", "date_transaction", "prix", "surface", "prix_m2", "type_bien", "nombre_pieces", "adresse", "code_postal"]),
    ("demographics_population", "processed/demographics/demographics.jsonl", ["commune_id", "annee", "population"]),
    ("demographics_density", "processed/demographics/density.jsonl", ["commune_id", "annee", "nom_territoire", "densite_population", "numerateur", "denominateur"]),
    ("demographics_chomage", "processed/demographics/chomage_commune.jsonl", ["commune_id", "annee", "actifs_15_64", "chomeurs_15_64", "taux_chomage"]),
    ("revenue_disponible", "processed/demographics/revenu_disponible.jsonl", ["age", "mesure", "nb_pers", "nch", "pcs", "tph", "statut_obs", "unite_mesure", "unite_mult", "annee", "valeur"]),
    ("dpe", "processed/dpe/dpe.jsonl", ["id", "commune_id", "classe_energetique", "classe_ges", "emissions_co2", "consommation_energie", "type_batiment", "annee_construction", "surface", "date_etablissement"]),
    ("bpe_equipment", "processed/infrastructure/bpe_equipment.jsonl", ["geo", "geo_object", "facility_dom", "facility_dom_label", "facility_sdom", "facility_sdom_label", "facility_type", "facility_type_label", "bpe_measure", "annee", "valeur"]),
    ("bpe_rollups", "processed/infrastructure/bpe_rollups.jsonl", ["annee", "geo", "geo_object", "facility_dom", "facility_dom_label", "facility_sdom", "facility_sdom_label", "equipements_total"]),
    ("bpe_evolution", "processed/infrastructure/bpe_evolution.jsonl", ["geo", "geo_object", "facility_type", "bpe_measure", "annee", "valeur"]),
]


def get_postgres_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "postgres-app"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "casapedia_db"),
        user=os.getenv("DB_USER", "casapedia_user"),
        password=os.getenv("DB_PASSWORD", "casapedia_password"),
    )


def read_jsonl_from_minio(object_key):
    settings = get_minio_settings()
    client = get_minio_client()
    bucket = ensure_bucket(client, settings["bucket"])

    try:
        response = client.get_object(Bucket=bucket, Key=object_key)
    except ClientError as error:
        error_code = error.response.get("Error", {}).get("Code", "")
        if error_code in {"NoSuchKey", "404", "NotFound"}:
            print(f"Objet MinIO absent, chargement ignoré: s3a://{bucket}/{object_key}")
            return []
        raise

    body = response["Body"].read().decode("utf-8")

    records = []
    for line in body.splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


def get_commune_id_set(cursor):
    cursor.execute("SELECT code_insee FROM communes")
    return {row[0] for row in cursor.fetchall()}


def normalize_commune_id(commune_id):
    if commune_id is None:
        return None

    commune_id = str(commune_id).strip()
    if not commune_id:
        return None

    if commune_id.isdigit() and len(commune_id) < 5:
        return commune_id.zfill(5)

    return commune_id


def filter_rows_by_communes(rows, columns, valid_commune_ids):
    if "commune_id" not in columns:
        return rows

    commune_index = columns.index("commune_id")
    filtered_rows = []
    skipped = 0
    for row in rows:
        commune_id = normalize_commune_id(row[commune_index])
        if commune_id in valid_commune_ids:
            filtered_row = list(row)
            filtered_row[commune_index] = commune_id
            filtered_rows.append(tuple(filtered_row))
        else:
            skipped += 1

    return filtered_rows, skipped


def execute_schema(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS communes (
            code_insee VARCHAR(5) PRIMARY KEY,
            nom VARCHAR(255) NOT NULL,
            code_postal VARCHAR(10),
            dept VARCHAR(5),
            dept_name VARCHAR(255),
            region_code VARCHAR(10),
            region VARCHAR(100),
            latitude DECIMAL(10, 8),
            longitude DECIMAL(11, 8),
            population_actuelle INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS transactions (
            id VARCHAR(100) PRIMARY KEY,
            commune_id VARCHAR(5) REFERENCES communes(code_insee),
            date_transaction DATE,
            prix DECIMAL(15, 2),
            surface DECIMAL(10, 2),
            prix_m2 DECIMAL(10, 2),
            type_bien VARCHAR(100),
            nombre_pieces INTEGER,
            adresse VARCHAR(255),
            code_postal VARCHAR(10),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS dpe (
            id VARCHAR(100) PRIMARY KEY,
            commune_id VARCHAR(5) REFERENCES communes(code_insee),
            classe_energetique CHAR(1),
            classe_ges CHAR(1),
            emissions_co2 DECIMAL(10, 2),
            consommation_energie DECIMAL(10, 2),
            type_batiment VARCHAR(100),
            annee_construction INTEGER,
            surface DECIMAL(10, 2),
            date_etablissement DATE
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS demographics_population (
            id SERIAL PRIMARY KEY,
            commune_id VARCHAR(5) REFERENCES communes(code_insee),
            annee INTEGER,
            population INTEGER,
            UNIQUE (commune_id, annee)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS demographics_density (
            id SERIAL PRIMARY KEY,
            commune_id VARCHAR(5) REFERENCES communes(code_insee),
            annee INTEGER,
            nom_territoire VARCHAR(255),
            densite_population DECIMAL(15, 4),
            numerateur DECIMAL(15, 4),
            denominateur DECIMAL(15, 4),
            UNIQUE (commune_id, annee)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS demographics_chomage (
            id SERIAL PRIMARY KEY,
            commune_id VARCHAR(5) REFERENCES communes(code_insee),
            annee INTEGER,
            actifs_15_64 DECIMAL(15, 4),
            chomeurs_15_64 DECIMAL(15, 4),
            taux_chomage DECIMAL(8, 6),
            UNIQUE (commune_id, annee)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS revenue_disponible (
            id SERIAL PRIMARY KEY,
            age VARCHAR(50),
            mesure VARCHAR(50),
            nb_pers VARCHAR(50),
            nch VARCHAR(50),
            pcs VARCHAR(50),
            tph VARCHAR(50),
            statut_obs VARCHAR(50),
            unite_mesure VARCHAR(50),
            unite_mult VARCHAR(50),
            annee INTEGER,
            valeur DECIMAL(15, 4)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS bpe_equipment (
            id SERIAL PRIMARY KEY,
            geo VARCHAR(50),
            geo_object VARCHAR(20),
            facility_dom VARCHAR(50),
            facility_dom_label VARCHAR(255),
            facility_sdom VARCHAR(50),
            facility_sdom_label VARCHAR(255),
            facility_type VARCHAR(50),
            facility_type_label VARCHAR(255),
            bpe_measure VARCHAR(50),
            annee INTEGER,
            valeur DECIMAL(15, 4)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS bpe_rollups (
            id SERIAL PRIMARY KEY,
            annee INTEGER,
            geo VARCHAR(50),
            geo_object VARCHAR(20),
            facility_dom VARCHAR(50),
            facility_dom_label VARCHAR(255),
            facility_sdom VARCHAR(50),
            facility_sdom_label VARCHAR(255),
            equipements_total DECIMAL(15, 4)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS bpe_evolution (
            id SERIAL PRIMARY KEY,
            geo VARCHAR(50),
            geo_object VARCHAR(20),
            facility_type VARCHAR(50),
            bpe_measure VARCHAR(50),
            annee INTEGER,
            valeur DECIMAL(15, 4)
        )
        """
    )

    # Garantit les FK commune_id même si les tables existaient déjà sans contrainte.
    cursor.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                WHERE n.nspname = 'public'
                  AND t.relname = 'transactions'
                  AND c.contype = 'f'
                  AND pg_get_constraintdef(c.oid) LIKE 'FOREIGN KEY (commune_id) REFERENCES communes(code_insee)%'
            ) THEN
                ALTER TABLE transactions
                ADD CONSTRAINT fk_transactions_commune_id
                FOREIGN KEY (commune_id) REFERENCES communes(code_insee) NOT VALID;
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                WHERE n.nspname = 'public'
                  AND t.relname = 'dpe'
                  AND c.contype = 'f'
                  AND pg_get_constraintdef(c.oid) LIKE 'FOREIGN KEY (commune_id) REFERENCES communes(code_insee)%'
            ) THEN
                ALTER TABLE dpe
                ADD CONSTRAINT fk_dpe_commune_id
                FOREIGN KEY (commune_id) REFERENCES communes(code_insee) NOT VALID;
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                WHERE n.nspname = 'public'
                  AND t.relname = 'demographics_population'
                  AND c.contype = 'f'
                  AND pg_get_constraintdef(c.oid) LIKE 'FOREIGN KEY (commune_id) REFERENCES communes(code_insee)%'
            ) THEN
                ALTER TABLE demographics_population
                ADD CONSTRAINT fk_demographics_population_commune_id
                FOREIGN KEY (commune_id) REFERENCES communes(code_insee) NOT VALID;
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                WHERE n.nspname = 'public'
                  AND t.relname = 'demographics_density'
                  AND c.contype = 'f'
                  AND pg_get_constraintdef(c.oid) LIKE 'FOREIGN KEY (commune_id) REFERENCES communes(code_insee)%'
            ) THEN
                ALTER TABLE demographics_density
                ADD CONSTRAINT fk_demographics_density_commune_id
                FOREIGN KEY (commune_id) REFERENCES communes(code_insee) NOT VALID;
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                WHERE n.nspname = 'public'
                  AND t.relname = 'demographics_chomage'
                  AND c.contype = 'f'
                  AND pg_get_constraintdef(c.oid) LIKE 'FOREIGN KEY (commune_id) REFERENCES communes(code_insee)%'
            ) THEN
                ALTER TABLE demographics_chomage
                ADD CONSTRAINT fk_demographics_chomage_commune_id
                FOREIGN KEY (commune_id) REFERENCES communes(code_insee) NOT VALID;
            END IF;
        END $$;
        """
    )


def prepare_postgres_schema(**_context):
    connection = get_postgres_connection()
    try:
        with connection:
            with connection.cursor() as cursor:
                execute_schema(cursor)
        print("Schéma PostgreSQL vérifié et prêt")
    finally:
        connection.close()


def load_postgres_data(**_context):
    connection = get_postgres_connection()
    try:
        with connection:
            with connection.cursor() as cursor:
                for table_name in POSTGRES_TABLES:
                    cursor.execute(f"TRUNCATE TABLE {table_name} RESTART IDENTITY CASCADE")

                for table_name, object_key, columns in LOAD_PLAN:
                    records = read_jsonl_from_minio(object_key)
                    if not records:
                        print(f"Aucune donnée à charger pour {table_name}")
                        continue

                    rows = [
                        tuple(
                            normalize_commune_id(record.get(column)) if column == "commune_id" else record.get(column)
                            for column in columns
                        )
                        for record in records
                    ]
                    if table_name != "communes" and "commune_id" in columns:
                        valid_commune_ids = get_commune_id_set(cursor)
                        rows, skipped = filter_rows_by_communes(rows, columns, valid_commune_ids)
                        if skipped:
                            print(f"{skipped} lignes ignorées dans {table_name} car commune_id absent de communes")

                    if not rows:
                        print(f"Aucune ligne exploitable à charger pour {table_name}")
                        continue

                    placeholders = ", ".join(["%s"] * len(columns))
                    column_list = ", ".join(columns)
                    insert_sql = f"INSERT INTO {table_name} ({column_list}) VALUES ({placeholders})"
                    cursor.executemany(insert_sql, rows)
                    print(f"{len(rows)} lignes chargées dans {table_name}")

                # Valide les FK ajoutées en NOT VALID après chargement.
                cursor.execute("ALTER TABLE transactions VALIDATE CONSTRAINT fk_transactions_commune_id")
                cursor.execute("ALTER TABLE dpe VALIDATE CONSTRAINT fk_dpe_commune_id")
                cursor.execute("ALTER TABLE demographics_population VALIDATE CONSTRAINT fk_demographics_population_commune_id")
                cursor.execute("ALTER TABLE demographics_density VALIDATE CONSTRAINT fk_demographics_density_commune_id")
                cursor.execute("ALTER TABLE demographics_chomage VALIDATE CONSTRAINT fk_demographics_chomage_commune_id")
    finally:
        connection.close()


def load_reviews_to_mongo(**_context):
    records = read_jsonl_from_minio("processed/reviews/clean_reviews.jsonl")
    if not records:
        print("Aucun avis nettoyé à charger dans MongoDB")
        return 0

    try:
        from pymongo import MongoClient
    except ImportError as error:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--user", "pymongo"])
            from pymongo import MongoClient
        except Exception as install_error:
            raise RuntimeError(
                "pymongo n'est pas installé dans l'image Airflow et l'installation locale a échoué"
            ) from install_error

    mongo_host = os.getenv("MONGO_HOST", "mongodb")
    mongo_port = os.getenv("MONGO_PORT", "27017")
    mongo_db = os.getenv("MONGO_DB", "casapedia")
    mongo_user = os.getenv("MONGO_USER", "root")
    mongo_password = os.getenv("MONGO_PASSWORD", "examplepassword")

    client = MongoClient(
        f"mongodb://{mongo_user}:{mongo_password}@{mongo_host}:{mongo_port}/?authSource=admin"
    )
    try:
        collection = client[mongo_db]["reviews_clean"]
        collection.delete_many({})
        inserted = collection.insert_many(records)
        print(f"{len(inserted.inserted_ids)} documents chargés dans MongoDB/reviews_clean")
    finally:
        client.close()


with DAG(
    "3_load_databases",
    default_args=DEFAULT_ARGS,
    description="Charge les données curées depuis MinIO vers PostgreSQL et MongoDB",
    schedule_interval=None,
    start_date=datetime(2026, 4, 19),
    catchup=False,
    tags=["casapedia", "load", "postgresql", "mongodb", "minio"],
) as dag:
    prepare_schema = PythonOperator(
        task_id="prepare_postgres_schema",
        python_callable=prepare_postgres_schema,
    )

    load_postgres = PythonOperator(
        task_id="load_postgres_data",
        python_callable=load_postgres_data,
    )

    load_mongo = PythonOperator(
        task_id="load_reviews_to_mongo",
        python_callable=load_reviews_to_mongo,
    )

    prepare_schema >> [load_postgres, load_mongo]