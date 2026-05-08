import os
import tempfile
import zipfile
import sys
from pathlib import Path

from pyspark.sql import SparkSession
from pyspark.sql.functions import col, concat, lit, lpad, trim

AIRFLOW_HOME = Path(__file__).resolve().parents[1]
if str(AIRFLOW_HOME) not in sys.path:
    sys.path.insert(0, str(AIRFLOW_HOME))

from io import BytesIO

from storage.minio_utils import download_to_path, ensure_bucket, get_minio_client, get_minio_settings, upload_fileobj

S3_BUCKET = os.getenv("CASAPEDIA_S3_BUCKET", "casapedia-datalake")
RAW_DIR = f"s3a://{S3_BUCKET}/raw"
PROCESSED_DIR = f"s3a://{S3_BUCKET}/processed"
SHARED_WORK_DIR = AIRFLOW_HOME / "spark_jobs" / "_work" / "clean_tabulaires"


def download_raw_object(object_key, destination_path):
    client = get_minio_client()
    settings = get_minio_settings()
    bucket = ensure_bucket(client, settings["bucket"])
    download_to_path(client, bucket, object_key, destination_path)
    os.chmod(destination_path, 0o644)


def write_jsonl_to_minio(df, output_prefix, filename):
    client = get_minio_client()
    settings = get_minio_settings()
    bucket = ensure_bucket(client, settings["bucket"])

    buffer = BytesIO()
    for row_json in df.toJSON().toLocalIterator():
        buffer.write((row_json + "\n").encode("utf-8"))
    buffer.seek(0)

    object_key = f"{output_prefix}/{filename}"
    upload_fileobj(client, bucket, object_key, buffer, content_type="application/x-ndjson")
    print(f"Jeu de données écrit dans : s3a://{bucket}/{object_key}")

def main():
    print("Initialisation de SparkSession...")
    spark = SparkSession.builder \
        .appName("Casapedia_Clean_Tabulaires") \
        .config("spark.sql.legacy.timeParserPolicy", "LEGACY") \
        .getOrCreate()

    os.makedirs(SHARED_WORK_DIR, exist_ok=True)

    with tempfile.TemporaryDirectory(dir=SHARED_WORK_DIR) as temp_dir:
        os.chmod(temp_dir, 0o777)

        # 1. Traitement COMMUNES
        print("Traitement de communes.csv...")
        local_communes_path = os.path.join(temp_dir, "communes.csv")
        download_raw_object("raw/communes/communes.csv", local_communes_path)
        df_communes = spark.read.csv(local_communes_path, header=True, sep=",")
        df_communes_clean = df_communes.select(
            trim(col("code_commune_INSEE")).alias("code_insee"),
            trim(col("nom_commune")).alias("nom"),
            trim(col("code_postal")).alias("code_postal"),
            col("latitude").cast("double").alias("latitude"),
            col("longitude").cast("double").alias("longitude"),
            trim(col("code_departement")).alias("dept"),
            trim(col("nom_region")).alias("region")
        ).dropDuplicates(["code_insee"])

        write_jsonl_to_minio(df_communes_clean, "processed/communes", "communes.jsonl")

        # 2. Traitement DVF (Valeurs Foncières)
        print("Traitement de transactions_dvf_brut.csv.gz...")
        local_dvf_path = os.path.join(temp_dir, "transactions_dvf_brut.csv.gz")
        download_raw_object("raw/dvf/transactions_dvf_brut.csv.gz", local_dvf_path)
        df_dvf = spark.read.csv(local_dvf_path, header=True, sep=",")
        df_dvf_clean = df_dvf.select(
            trim(col("id_mutation")).alias("id"),
            trim(col("code_commune")).alias("commune_id"),
            trim(col("date_mutation")).alias("date_transaction"),
            col("valeur_fonciere").cast("double").alias("prix"),
            col("surface_reelle_bati").cast("double").alias("surface"),
            trim(col("type_local")).alias("type_bien"),
            col("nombre_pieces_principales").cast("int").alias("nombre_pieces"),
            trim(col("adresse_nom_voie")).alias("adresse"),
            trim(col("code_postal")).alias("code_postal")
        ).dropna(subset=["commune_id", "prix", "surface"]) \
         .filter(col("surface") > 0) \
         .withColumn("prix_m2", col("prix") / col("surface")) \
         .dropDuplicates(["id"])

        write_jsonl_to_minio(df_dvf_clean, "processed/transactions", "transactions.jsonl")

        # 3. Traitement DPE (Diagnostics Énergétiques)
        print("Traitement de dpe_logements_brut.csv...")
        local_dpe_path = os.path.join(temp_dir, "dpe_logements_brut.csv")
        download_raw_object("raw/dpe/dpe_logements_brut.csv", local_dpe_path)
        df_dpe = spark.read.csv(local_dpe_path, header=True, sep=",", multiLine=True, escape='"')
        df_dpe_clean = df_dpe.select(
            trim(col("numero_dpe")).alias("id"),
            trim(col("code_insee_ban")).alias("commune_id"),
            trim(col("etiquette_dpe")).alias("classe_energetique"),
            trim(col("etiquette_ges")).alias("classe_ges"),
            col("emission_ges_5_usages").cast("float").alias("emissions_co2"),
            col("conso_5_usages_ep").cast("float").alias("consommation_energie"),
            trim(col("type_batiment")).alias("type_batiment"),
            col("annee_construction").cast("int").alias("annee_construction"),
            col("surface_habitable_logement").cast("float").alias("surface"),
            trim(col("date_etablissement_dpe")).alias("date_etablissement")
        ).dropna(subset=["commune_id"]).dropDuplicates(["id"])

        write_jsonl_to_minio(df_dpe_clean, "processed/dpe", "dpe.jsonl")

        # 4. Traitement Démographie (INSEE)
        print("Traitement de demographie_insee.zip (extraction préalable)...")
        local_zip_path = os.path.join(temp_dir, "demographie_insee.zip")
        local_extract_dir = os.path.join(temp_dir, "extract")
        os.makedirs(local_extract_dir, exist_ok=True)

        try:
            download_raw_object("raw/insee/demographie_insee.zip", local_zip_path)
            os.chmod(local_zip_path, 0o644)

            with zipfile.ZipFile(local_zip_path, "r") as archive:
                archive.extract("donnees_communes.csv", local_extract_dir)

            extracted_csv_path = os.path.join(local_extract_dir, "donnees_communes.csv")
            os.chmod(extracted_csv_path, 0o644)

            df_insee = spark.read.csv(extracted_csv_path, header=True, sep=";")
            df_insee_clean = df_insee.select(
                concat(trim(col("CODDEP")), lpad(trim(col("CODCOM")), 3, "0")).alias("commune_id"),
                col("PMUN").cast("int").alias("population")
            ).withColumn("annee", lit(2023))

            write_jsonl_to_minio(df_insee_clean.dropna(subset=["commune_id", "population"]), "processed/demographics", "demographics.jsonl")
        except Exception:
            print("Fichier INSEE introuvable, ingestion passée.")
        
    print("Traitement Big Data PySpark terminé avec succès !")
    spark.stop()

if __name__ == "__main__":
    main()
