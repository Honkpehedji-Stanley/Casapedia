import os
import zipfile
import shutil
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, concat, lit, lpad, trim

# Chemins unifiés pour Docker
RAW_DIR = "/opt/airflow/datalake/raw"
PROCESSED_DIR = "/opt/airflow/datalake/processed"


def prepare_output_path(path):
    if os.path.exists(path):
        shutil.rmtree(path)
    previous_umask = os.umask(0)
    try:
        os.makedirs(path, mode=0o777, exist_ok=True)
        os.chmod(path, 0o777)
    finally:
        os.umask(previous_umask)


def write_clean_parquet(df, path):
    prepare_output_path(path)
    df.write.mode("overwrite").parquet(path)

def main():
    print("Initialisation de SparkSession...")
    spark = SparkSession.builder \
        .appName("Casapedia_Clean_Tabulaires") \
        .config("spark.sql.legacy.timeParserPolicy", "LEGACY") \
        .config("spark.driver.memory", "4g") \
        .getOrCreate()

    previous_umask = os.umask(0)
    try:
        os.makedirs(PROCESSED_DIR, mode=0o777, exist_ok=True)
    finally:
        os.umask(previous_umask)
    
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
    zip_path = f"{RAW_DIR}/insee/demographie_insee.zip"
    tmp_csv_path = f"{PROCESSED_DIR}/donnees_communes.csv"
    
    # Extraction propre du fichier cible
    if os.path.exists(zip_path):
        with zipfile.ZipFile(zip_path, 'r') as z:
            z.extract("donnees_communes.csv", PROCESSED_DIR)
            
        df_insee = spark.read.csv(tmp_csv_path, header=True, sep=";")
        df_insee_clean = df_insee.select(
            concat(trim(col("CODDEP")), lpad(trim(col("CODCOM")), 3, "0")).alias("commune_id"),
            col("PMUN").cast("int").alias("population")
        ).withColumn("annee", lit(2023))

        write_clean_parquet(df_insee_clean.dropna(subset=["commune_id", "population"]), f"{PROCESSED_DIR}/demographics")
        if os.path.exists(tmp_csv_path):
            os.remove(tmp_csv_path)
    else:
        print("Fichier INSEE introuvable, ingestion passée.")
        
    print("Traitement Big Data PySpark terminé avec succès !")
    spark.stop()

if __name__ == "__main__":
    main()
