from airflow import DAG
from airflow.providers.apache.spark.operators.spark_submit import SparkSubmitOperator
from datetime import datetime, timedelta

from spark_minio_conf import get_minio_spark_conf

default_args = {
    'owner': 'casapedia',
    'depends_on_past': False,
    'retries': 1,              
    'retry_delay': timedelta(minutes=5),
}

with DAG(
    '2_transform_spark_data',
    default_args=default_args,
    description='Déclenche le nettoyage PySpark sur MinIO via le cluster Spark Bitnami',
    schedule_interval=None, # Déclenchement manuel ou par TriggerDagRunOperator
    start_date=datetime(2026, 4, 3),
    catchup=False,
    tags=['casapedia', 'transform', 'spark', 'minio'],
) as dag:

    # Soumission du job PySpark au cluster Spark Master (Bitnami)
    clean_data_spark = SparkSubmitOperator(
        task_id='clean_tabulaires_job',
        # Emplacement du script dans les 2 conteneurs (Airflow & Spark)
        application='/opt/airflow/spark_jobs/clean_tabulaires.py',
        # ID automatique/manuelle
        conn_id='spark_default',
        name='Airflow_PySpark_Job',
        executor_cores=1,
        executor_memory='1g',
        driver_memory='1g',
        verbose=True,
        conf={
            **get_minio_spark_conf(),
            'spark.driver.host': 'airflow-scheduler',
            'spark.driver.bindAddress': '0.0.0.0',
            'spark.hadoop.fs.permissions.umask-mode': '000',
        }
    )

    clean_data_spark