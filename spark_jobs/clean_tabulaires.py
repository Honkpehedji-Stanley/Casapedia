import os
import json
import tempfile
import zipfile
import sys
from collections import Counter
from csv import DictReader
from pathlib import Path
from urllib.request import urlopen

from pyspark.sql import SparkSession
from pyspark.sql.functions import col, concat, countDistinct, lit, lpad, sum as spark_sum, trim, when

AIRFLOW_HOME = Path(__file__).resolve().parents[1]
if str(AIRFLOW_HOME) not in sys.path:
    sys.path.insert(0, str(AIRFLOW_HOME))

from io import BytesIO

from storage.minio_utils import download_to_path, ensure_bucket, get_minio_client, get_minio_settings, upload_fileobj

S3_BUCKET = os.getenv("CASAPEDIA_S3_BUCKET", "casapedia-datalake")
SHARED_WORK_DIR = AIRFLOW_HOME / "spark_jobs" / "_work" / "clean_tabulaires"
COG_COMMUNE_URL = os.getenv(
    "CASAPEDIA_COG_COMMUNES_URL",
    "https://www.insee.fr/fr/statistiques/fichier/8740222/v_commune_2026.csv",
)
COG_COMMUNE_MILLESIME = os.getenv("CASAPEDIA_COG_COMMUNE_MILLESIME", "2026")


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


def write_json_to_minio(payload, output_prefix, filename):
    client = get_minio_client()
    settings = get_minio_settings()
    bucket = ensure_bucket(client, settings["bucket"])

    buffer = BytesIO(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))
    object_key = f"{output_prefix}/{filename}"
    upload_fileobj(client, bucket, object_key, buffer, content_type="application/json")
    print(f"Rapport QA écrit dans : s3a://{bucket}/{object_key}")


def load_current_cog_commune_codes():
    current_codes = set()
    type_counts = Counter()

    with urlopen(COG_COMMUNE_URL, timeout=60) as response:
        decoded = (line.decode("utf-8", "replace") for line in response)
        reader = DictReader(decoded)
        for row in reader:
            type_code = (row.get("TYPECOM") or "").strip()
            commune_code = (row.get("COM") or "").strip()
            if not commune_code:
                continue
            type_counts[type_code] += 1
            if type_code == "COM":
                current_codes.add(commune_code)

    return current_codes, dict(type_counts)


def print_year_coverage(df, date_column, label):
    years = [row[0] for row in df.selectExpr(f"substring({date_column}, 1, 4) as annee").where("annee is not null and annee <> ''").distinct().orderBy("annee").collect()]
    if years:
        print(f"{label} - années présentes: {', '.join(years)}")
    else:
        print(f"{label} - aucune année explicite trouvée dans la colonne {date_column}")


def build_commune_qa_report(df_communes_source, df_communes_clean, active_commune_codes, cog_type_counts):
    source_distinct_codes = df_communes_clean.select("code_insee").where(col("code_insee").isNotNull()).distinct()
    active_codes_df = df_communes_clean.sparkSession.createDataFrame(
        [(code,) for code in active_commune_codes],
        ["code_insee"],
    )

    active_communes = source_distinct_codes.join(active_codes_df, on="code_insee", how="inner")
    historical_communes = source_distinct_codes.join(active_codes_df, on="code_insee", how="left_anti")
    duplicated_codes = df_communes_source.groupBy("code_commune_INSEE").count().where(col("count") > 1)

    active_count = active_communes.count()
    historical_count = historical_communes.count()
    distinct_count = source_distinct_codes.count()
    raw_count = df_communes_source.count()

    historical_examples = [row[0] for row in historical_communes.orderBy("code_insee").limit(20).collect()]
    duplicate_examples = [
        {"code_commune_INSEE": row[0], "occurrences": row[1]}
        for row in duplicated_codes.orderBy(col("count").desc(), col("code_commune_INSEE")).limit(20).collect()
    ]

    return {
        "source": {
            "file": "raw/communes/communes.csv",
            "raw_rows": raw_count,
            "distinct_code_insee": distinct_count,
            "duplicate_code_rows": raw_count - distinct_count,
            "active_codes_in_current_cog": active_count,
            "historical_or_non_current_codes": historical_count,
            "active_vs_historical_gap": distinct_count - active_count,
            "current_cog_millesime": COG_COMMUNE_MILLESIME,
            "current_cog_url": COG_COMMUNE_URL,
            "current_cog_type_distribution": cog_type_counts,
            "historical_code_examples": historical_examples,
            "duplicate_code_examples": duplicate_examples,
            "note": (
                "Les codes non présents dans le COG courant incluent des codes historiques, des communes associées ou déléguées, "
                "et des lignes sources répliquées par code postal ou zonage local."
            ),
        }
    }


def build_commune_rollups(df_communes_clean, active_codes_df):
    df_communes_status = df_communes_clean.join(active_codes_df, on="code_insee", how="left")
    df_communes_status = df_communes_status.withColumn("is_active_cog", col("active_flag").isNotNull())

    def aggregate_rollup(level_name, grouping_columns):
        grouped = df_communes_status.groupBy(*grouping_columns).agg(
            countDistinct("code_insee").alias("commune_count"),
            spark_sum(when(col("is_active_cog"), 1).otherwise(0)).cast("int").alias("active_commune_count"),
            spark_sum(when(~col("is_active_cog"), 1).otherwise(0)).cast("int").alias("historical_commune_count"),
        )

        return grouped.select(
            lit(level_name).alias("niveau"),
            *grouping_columns,
            "commune_count",
            "active_commune_count",
            "historical_commune_count",
        )

    departements = aggregate_rollup(
        "departement",
        [
            "dept",
            "dept_name",
        ],
    )

    regions = aggregate_rollup(
        "region",
        [
            "region_code",
            "region",
        ],
    )

    national = df_communes_status.groupBy().agg(
        countDistinct("code_insee").alias("commune_count"),
        spark_sum(when(col("is_active_cog"), 1).otherwise(0)).cast("int").alias("active_commune_count"),
        spark_sum(when(~col("is_active_cog"), 1).otherwise(0)).cast("int").alias("historical_commune_count"),
    ).select(
        lit("national").alias("niveau"),
        lit("FR").alias("code_niveau"),
        lit("France").alias("libelle_niveau"),
        "commune_count",
        "active_commune_count",
        "historical_commune_count",
    )

    return departements, regions, national


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
            lpad(trim(col("code_commune_INSEE")), 5, "0").alias("code_insee"),
            trim(col("nom_commune")).alias("nom"),
            trim(col("code_postal")).alias("code_postal"),
            col("latitude").cast("double").alias("latitude"),
            col("longitude").cast("double").alias("longitude"),
            trim(col("code_departement")).alias("dept"),
            trim(col("nom_departement")).alias("dept_name"),
            trim(col("code_region")).alias("region_code"),
            trim(col("nom_region")).alias("region")
        ).dropDuplicates(["code_insee"])

        active_commune_codes, cog_type_counts = load_current_cog_commune_codes()
        active_codes_df = df_communes_clean.sparkSession.createDataFrame(
            [(code, 1) for code in active_commune_codes],
            ["code_insee", "active_flag"],
        )
        communes_count = df_communes_clean.count()
        commune_qa_report = build_commune_qa_report(df_communes, df_communes_clean, active_commune_codes, cog_type_counts)
        departement_rollups, region_rollups, national_rollup = build_commune_rollups(df_communes_clean, active_codes_df)

        print(f"Nombre d'entrées communes distinctes dans la source: {communes_count}")
        print(f"Nombre de lignes communes brutes dans le fichier source: {df_communes.count()}")
        print(
            f"Communes actives selon le COG {COG_COMMUNE_MILLESIME}: {commune_qa_report['source']['active_codes_in_current_cog']}"
        )
        print(
            f"Communes historiques ou non courantes dans la source: {commune_qa_report['source']['historical_or_non_current_codes']}"
        )
        print(
            "Attention: les lignes restantes regroupent des codes historiques, des communes associées ou déléguées, "
            "et des doublons de zonage local."
        )

        write_jsonl_to_minio(df_communes_clean, "processed/communes", "communes.jsonl")
        write_jsonl_to_minio(departement_rollups, "processed/communes_rollups", "departements.jsonl")
        write_jsonl_to_minio(region_rollups, "processed/communes_rollups", "regions.jsonl")
        write_jsonl_to_minio(national_rollup, "processed/communes_rollups", "national.jsonl")
        write_json_to_minio(commune_qa_report, "processed/qa", "source_qa.json")

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

        print(f"DVF - lignes sources: {df_dvf.count()}")
        print_year_coverage(df_dvf, "date_mutation", "DVF")

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

        print(f"DPE - lignes sources: {df_dpe.count()}")
        print_year_coverage(df_dpe, "date_etablissement_dpe", "DPE")

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

            print(f"INSEE - lignes sources: {df_insee.count()}")
            print("INSEE - année de traitement fixée par le job: 2023")

            write_jsonl_to_minio(df_insee_clean.dropna(subset=["commune_id", "population"]), "processed/demographics", "demographics.jsonl")
            write_json_to_minio(
                {
                    "source": {
                        "file": "raw/insee/demographie_insee.zip",
                        "processed_year": 2023,
                        "note": "Le millésime n'est pas porté explicitement par le fichier brut; le job l'attache au moment du traitement.",
                    }
                },
                "processed/qa",
                "insee_source_qa.json",
            )
        except Exception:
            print("Fichier INSEE introuvable, ingestion passée.")
        
    print("Traitement Big Data PySpark terminé avec succès !")
    spark.stop()

if __name__ == "__main__":
    main()
