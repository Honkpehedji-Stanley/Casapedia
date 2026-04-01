from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import requests
import os

# Configuration par défaut du DAG : "Les règles de production"
default_args = {
    'owner': 'casapedia',
    'depends_on_past': False,
    'email_on_failure': False, # Plus tard, on peut brancher des alertes Slack/Email ici
    'email_on_retry': False,
    'retries': 3,               # Tolérance aux pannes : retente 3 fois si l'API de l'Etat crash
    'retry_delay': timedelta(minutes=5), # Attend 5 min entre chaque essai
}

def download_file(url, dest_folder, filename):
    """
    Fonction ELT : Téléchargement 'Dumb'.
    """
    # Dans Docker, le datalake est monté sur /opt/airflow/datalake
    base_path = f"/opt/airflow/datalake/raw/{dest_folder}"
    os.makedirs(base_path, exist_ok=True)
    file_path = os.path.join(base_path, filename)
    
    print(f"Début du téléchargement : {url}")
    
    # stream=True est indispensable en Big Data pour ne pas faire exploser la RAM
    with requests.get(url, stream=True) as r:
        r.raise_for_status() # Lève une exception (et déclenche un Retry Airflow) si erreur 404/500
        with open(file_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192): 
                f.write(chunk)
                
    print(f"Téléchargement terminé avec succès et sauvegardé sous : {file_path}")

# Définition du Workflow (DAG)
with DAG(
    '1_ingestion_raw_data',
    default_args=default_args,
    description='Téléchargement asynchrone des sources publiques vers le Datalake',
    schedule_interval=timedelta(days=30), # Exécution planifiée automatique chaque mois !
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=['casapedia', 'ingestion', 'datalake', 'raw'],
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

    # Le Graphe d'exécution (Flow).
    # Ici, nous disons à Airflow de lancer les 4 téléchargements en PARALLÈLE, pas l'un après l'autre.
    [ingest_communes, ingest_insee, ingest_dvf, ingest_dpe]
    [ingest_communes, ingest_insee, ingest_dvf]