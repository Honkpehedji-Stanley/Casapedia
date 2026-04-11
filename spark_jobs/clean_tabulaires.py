import os
import zipfile
import shutil
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, concat, lit

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
        col("code_commune_INSEE").alias("code_insee"),
        col("nom_commune"),
        col("code_postal"),
        col("latitude").cast("float"),
        col("longitude").cast("float"),
        col("code_departement"),
        col("nom_region")
    ).dropDuplicates(["code_insee"])
    
    prepare_output_path(f"{PROCESSED_DIR}/communes")
    df_communes_clean.write.mode("overwrite").parquet(f"{PROCESSED_DIR}/communes")
    
    # 2. Traitement DVF (Valeurs Foncières)
    print("Traitement de transactions_dvf_brut.csv.gz...")
    df_dvf = spark.read.csv(f"{RAW_DIR}/dvf/transactions_dvf_brut.csv.gz", header=True, sep=",")
    df_dvf_clean = df_dvf.select(
        col("id_mutation").alias("id"),
        col("code_commune").alias("commune_id"),
        col("date_mutation").alias("date_transaction"),
        col("valeur_fonciere").cast("float").alias("prix"),
        col("surface_reelle_bati").cast("float").alias("surface"),
        col("type_local").alias("type_bien"),
        col("nombre_pieces_principales").cast("int").alias("nombre_pieces"),
        col("adresse_nom_voie").alias("adresse"),
        col("code_postal")
    ).dropna(subset=["commune_id", "prix", "surface"]) \
     .filter(col("surface") > 0) \
     .withColumn("prix_m2", col("prix") / col("surface"))
    
    prepare_output_path(f"{PROCESSED_DIR}/transactions")
    df_dvf_clean.write.mode("overwrite").parquet(f"{PROCESSED_DIR}/transactions")
    
    # 3. Traitement DPE (Diagnostics Energétiques)
    print("Traitement de dpe_logements_brut.csv...")
    # MultiLine=True et escape='"' sont importants car le fichier DPE contient beaucoup de textes complexes
    df_dpe = spark.read.csv(f"{RAW_DIR}/dpe/dpe_logements_brut.csv", header=True, sep=",", multiLine=True, escape='"')
    df_dpe_clean = df_dpe.select(
        col("numero_dpe").alias("id"),
        col("code_insee_ban").alias("commune_id"),
        col("etiquette_dpe").alias("classe_energetique"),
        col("etiquette_ges").alias("classe_ges"),
        col("emission_ges_5_usages").cast("float").alias("emissions_co2"),
        col("conso_5_usages_ep").cast("float").alias("consommation_energie"),
        col("type_batiment"),
        col("annee_construction").cast("int"),
        col("surface_habitable_logement").cast("float").alias("surface"),
        col("date_etablissement_dpe").alias("date_etablissement")
    ).dropna(subset=["commune_id"])
    
    prepare_output_path(f"{PROCESSED_DIR}/dpe")
    df_dpe_clean.write.mode("overwrite").parquet(f"{PROCESSED_DIR}/dpe")
    
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
            concat(col("CODDEP"), col("CODCOM")).alias("commune_id"),
            col("PMUN").cast("int").alias("population")
        ).withColumn("annee", lit(2023))
        
        prepare_output_path(f"{PROCESSED_DIR}/demographics")
        df_insee_clean.write.mode("overwrite").parquet(f"{PROCESSED_DIR}/demographics")
        if os.path.exists(tmp_csv_path):
            os.remove(tmp_csv_path)
    else:
        print("Fichier INSEE introuvable, ingestion passée.")
        
    print("Traitement Big Data PySpark terminé avec succès !")
    spark.stop()

if __name__ == "__main__":
    main()
