from airflow import DAG
from airflow.providers.apache.spark.operators.spark_submit import SparkSubmitOperator
from datetime import datetime, timedelta


default_args = {
    'owner': 'casapedia',
    'depends_on_past': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}


with DAG(
    '3_sentiment_analysis_spark_data',
    default_args=default_args,
    description='Déclenche le job Spark NLP de sentiment et wordclouds sur les textes bruts',
    schedule_interval=None,
    start_date=datetime(2026, 4, 19),
    catchup=False,
    tags=['casapedia', 'nlp', 'spark', 'sentiment', 'minio'],
) as dag:

    sentiment_analysis_spark = SparkSubmitOperator(
        task_id='sentiment_analysis_job',
        application='/opt/airflow/spark_jobs/sentiment_analysis.py',
        conn_id='spark_default',
        name='Airflow_Spark_NLP_Job',
        executor_cores=1,
        executor_memory='1g',
        driver_memory='1g',
        verbose=True,
        conf={
            'spark.driver.host': 'airflow-scheduler',
            'spark.driver.bindAddress': '0.0.0.0',
            'spark.hadoop.fs.permissions.umask-mode': '000',
        }
    )

    sentiment_analysis_spark