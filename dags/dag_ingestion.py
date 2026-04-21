import sys
from pathlib import Path

from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import tempfile

import requests

AIRFLOW_HOME = Path(__file__).resolve().parents[1]
if str(AIRFLOW_HOME) not in sys.path:
    sys.path.insert(0, str(AIRFLOW_HOME))

from storage.minio_utils import ensure_bucket, get_minio_client, get_minio_settings, upload_fileobj

# Configuration par défaut du DAG : "Les règles de production"
default_args = {
    'owner': 'casapedia',
    'depends_on_past': False,
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 3,              
    'retry_delay': timedelta(minutes=5),
}

def download_file(url, dest_folder, filename):
    """
    Fonction ELT : Téléchargement 'Dumb'.
    """
    settings = get_minio_settings()
    client = get_minio_client()
    bucket = ensure_bucket(client, settings["bucket"])
    object_key = f"raw/{dest_folder}/{filename}"

    print(f"Début du téléchargement : {url}")

    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with tempfile.NamedTemporaryFile(suffix=f"-{filename}") as temp_file:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    temp_file.write(chunk)
            temp_file.flush()
            temp_file.seek(0)
            upload_fileobj(client, bucket, object_key, temp_file, content_type=r.headers.get("Content-Type"))

    print(f"Téléchargement terminé avec succès et sauvegardé sous : s3a://{bucket}/{object_key}")

# Définition du Workflow (DAG)
with DAG(
    '1_ingestion_raw_data',
    default_args=default_args,
    description='Téléchargement asynchrone des sources publiques vers MinIO',
    schedule_interval=timedelta(days=30), 
    start_date=datetime(2026, 4, 3),
    catchup=False,
    tags=['casapedia', 'ingestion', 'minio', 'raw'],
) as dag:

    # Tâche 1 : Ingestion des Communes (Référentiel de base)
    ingest_communes = PythonOperator(
        task_id='download_communes',
        python_callable=download_file,
        op_kwargs={
            'url': 'https://www.data.gouv.fr/fr/datasets/r/dbe8a621-a9c4-4bc3-9cae-be1699c5ff25',
            'dest_folder': 'communes',
            'filename': 'communes.csv'
        }
    )

    # Tâche 2 : Ingestion INSEE (Base zippée très lourde)
    ingest_insee = PythonOperator(
        task_id='download_insee',
        python_callable=download_file,
        op_kwargs={
            'url': 'https://www.insee.fr/fr/statistiques/fichier/6683035/ensemble.zip',
            'dest_folder': 'insee',
            'filename': 'demographie_insee.zip'
        }
    )

    # Tâche 3 : Ingestion DVF (Base consolidée Data.gouv pour toute la France)
    ingest_dvf = PythonOperator(
        task_id='download_dvf',
        python_callable=download_file,
        op_kwargs={
            'url': 'https://files.data.gouv.fr/geo-dvf/latest/csv/2023/full.csv.gz', 
            'dest_folder': 'dvf',
            'filename': 'transactions_dvf_brut.csv.gz'
        }
    )

    # Tâche 4 : Ingestion DPE (Diagnostics de performance énergétique - Échantillon ADEME)
    ingest_dpe = PythonOperator(
        task_id='download_dpe',
        python_callable=download_file,
        op_kwargs={
            'url': 'https://data.ademe.fr/data-fair/api/v1/datasets/dpe03existant/lines?size=10000&format=csv',
            'dest_folder': 'dpe',
            'filename': 'dpe_logements_brut.csv'
        }
    )

    # Les 4 téléchargements en PARALLÈLE, pas l'un après l'autre.
    [ingest_communes, ingest_insee, ingest_dvf, ingest_dpe]