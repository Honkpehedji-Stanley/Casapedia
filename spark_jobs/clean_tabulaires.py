import os
import tempfile
import zipfile
from io import BytesIO
import sys
from pathlib import Path

from pyspark.sql import SparkSession
from pyspark.sql.functions import col, concat, lit, lpad, trim

AIRFLOW_HOME = Path(__file__).resolve().parents[1]
if str(AIRFLOW_HOME) not in sys.path:
    sys.path.insert(0, str(AIRFLOW_HOME))

S3_BUCKET = os.getenv("CASAPEDIA_S3_BUCKET", "casapedia-datalake")
RAW_DIR = f"s3a://{S3_BUCKET}/raw"
PROCESSED_DIR = f"s3a://{S3_BUCKET}/processed"


def write_clean_parquet(df, path):
    df.write.mode("overwrite").parquet(path)

def main():
    print("Initialisation de SparkSession...")
    spark = SparkSession.builder \
        .appName("Casapedia_Clean_Tabulaires") \
        .config("spark.sql.legacy.timeParserPolicy", "LEGACY") \
        .config("spark.driver.memory", "4g") \
        .getOrCreate()

    # 1. Traitement COMMUNES
    print("Traitement de communes.csv...")
    df_communes = spark.read.csv(f"{RAW_DIR}/communes/communes.csv", header=True, sep=",")
    df_communes_clean = df_communes.select(
        trim(col("code_commune_INSEE")).alias("code_insee"),
        trim(col("nom_commune")).alias("nom"),
        trim(col("code_postal")).alias("code_postal"),
        col("latitude").cast("double").alias("latitude"),
        col("longitude").cast("double").alias("longitude"),
        trim(col("code_departement")).alias("dept"),
        trim(col("nom_region")).alias("region")
    ).dropDuplicates(["code_insee"])

    write_clean_parquet(df_communes_clean, f"{PROCESSED_DIR}/communes")
    
    # 2. Traitement DVF (Valeurs Foncières)
    print("Traitement de transactions_dvf_brut.csv.gz...")
    df_dvf = spark.read.csv(f"{RAW_DIR}/dvf/transactions_dvf_brut.csv.gz", header=True, sep=",")
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

    write_clean_parquet(df_dvf_clean, f"{PROCESSED_DIR}/transactions")
    
    # 3. Traitement DPE (Diagnostics Energétiques)
    print("Traitement de dpe_logements_brut.csv...")
    # MultiLine=True et escape='"' sont importants car le fichier DPE contient beaucoup de textes complexes
    df_dpe = spark.read.csv(f"{RAW_DIR}/dpe/dpe_logements_brut.csv", header=True, sep=",", multiLine=True, escape='"')
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

    write_clean_parquet(df_dpe_clean, f"{PROCESSED_DIR}/dpe")
    
    # 4. Traitement Démographie (INSEE)
    print("Traitement de demographie_insee.zip (extraction préalable)...")
    with tempfile.TemporaryDirectory() as temp_dir:
        local_zip_path = os.path.join(temp_dir, "demographie_insee.zip")
        local_extract_dir = os.path.join(temp_dir, "extract")
        os.makedirs(local_extract_dir, exist_ok=True)

        try:
            zip_row = spark.read.format("binaryFile").load(f"{RAW_DIR}/insee/demographie_insee.zip").select("content").first()
            if zip_row is None:
                raise FileNotFoundError("Archive INSEE introuvable dans MinIO")

            with open(local_zip_path, "wb") as local_zip_file:
                local_zip_file.write(zip_row["content"])

            with zipfile.ZipFile(BytesIO(zip_row["content"]), "r") as archive:
                archive.extract("donnees_communes.csv", local_extract_dir)

            df_insee = spark.read.csv(os.path.join(local_extract_dir, "donnees_communes.csv"), header=True, sep=";")
            df_insee_clean = df_insee.select(
                concat(trim(col("CODDEP")), lpad(trim(col("CODCOM")), 3, "0")).alias("commune_id"),
                col("PMUN").cast("int").alias("population")
            ).withColumn("annee", lit(2023))

            write_clean_parquet(df_insee_clean.dropna(subset=["commune_id", "population"]), f"{PROCESSED_DIR}/demographics")
        except Exception:
            print("Fichier INSEE introuvable, ingestion passée.")
        
    print("Traitement Big Data PySpark terminé avec succès !")
    spark.stop()

if __name__ == "__main__":
    main()
