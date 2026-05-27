import os
import json
import tempfile
import zipfile
import sys
import struct
import zlib
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

from storage.minio_utils import download_to_path, ensure_bucket, get_minio_client, get_minio_settings, list_objects_with_prefix, upload_fileobj

S3_BUCKET = os.getenv("CASAPEDIA_S3_BUCKET", "casapedia-datalake")
SHARED_WORK_DIR = AIRFLOW_HOME / "spark_jobs" / "_work" / "clean_tabulaires"
COG_COMMUNE_URL = os.getenv(
    "CASAPEDIA_COG_COMMUNES_URL",
    "https://www.insee.fr/fr/statistiques/fichier/8740222/v_commune_2026.csv",
)
COG_COMMUNE_MILLESIME = os.getenv("CASAPEDIA_COG_COMMUNE_MILLESIME", "2026")
DVF_YEARS = [
    int(year.strip())
    for year in os.getenv("CASAPEDIA_DVF_YEARS", "2021,2022,2023,2024,2025").split(",")
    if year.strip()
]


def download_raw_object(object_key, destination_path):
    client = get_minio_client()
    settings = get_minio_settings()
    bucket = ensure_bucket(client, settings["bucket"])
    download_to_path(client, bucket, object_key, destination_path)
    os.chmod(destination_path, 0o644)


def write_jsonl_to_minio(df, output_prefix, filename):
    settings = get_minio_settings()
    object_key = f"{output_prefix}/{filename}"
    local_output_dir = SHARED_WORK_DIR / output_prefix.replace("/", "_")
    local_output_dir.mkdir(parents=True, exist_ok=True)
    local_output_path = local_output_dir / filename

    def write_partition(rows_iter):
        row_count = 0
        with open(local_output_path, "w", encoding="utf-8") as temp_file:
            for row in rows_iter:
                temp_file.write(json.dumps(row.asDict(recursive=True), ensure_ascii=False, default=str))
                temp_file.write("\n")
                row_count += 1

        if row_count == 0:
            raise RuntimeError(f"Aucune ligne à exporter pour {object_key}")

    df.coalesce(1).rdd.foreachPartition(write_partition)

    if not local_output_path.exists():
        raise RuntimeError(f"Le fichier local attendu est introuvable pour {object_key}")

    client = get_minio_client()
    bucket = ensure_bucket(client, settings["bucket"])

    try:
        with open(local_output_path, "rb") as buffer:
            upload_fileobj(client, bucket, object_key, buffer, content_type="application/x-ndjson")
    finally:
        if local_output_path.exists():
            local_output_path.unlink()

    print(f"Jeu de données écrit dans : s3a://{settings['bucket']}/{object_key}")


def write_json_to_minio(payload, output_prefix, filename):
    client = get_minio_client()
    settings = get_minio_settings()
    bucket = ensure_bucket(client, settings["bucket"])

    buffer = BytesIO(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))
    object_key = f"{output_prefix}/{filename}"
    upload_fileobj(client, bucket, object_key, buffer, content_type="application/json")
    print(f"Rapport QA écrit dans : s3a://{bucket}/{object_key}")


def extract_archive_members(source_path, destination_dir):
    extracted_paths = []

    try:
        with zipfile.ZipFile(source_path, "r") as archive:
            archive.extractall(destination_dir)
            for member_name in archive.namelist():
                extracted_paths.append(os.path.join(destination_dir, member_name))
        return extracted_paths
    except zipfile.BadZipFile:
        pass

    with open(source_path, "rb") as handle:
        content = handle.read()

    offset = 0
    while True:
        header_offset = content.find(b"PK\x03\x04", offset)
        if header_offset < 0:
            break

        header = struct.unpack("<IHHHHHIIIHH", content[header_offset:header_offset + 30])
        _, _, _, compression, _, _, _, _, _, filename_len, extra_len = header
        filename = content[header_offset + 30:header_offset + 30 + filename_len].decode("utf-8", "replace")
        data_start = header_offset + 30 + filename_len + extra_len
        next_header_offset = content.find(b"PK\x03\x04", data_start)
        if next_header_offset < 0:
            next_header_offset = len(content)

        segment = content[data_start:next_header_offset]
        data_descriptor_offset = segment.rfind(b"PK\x07\x08")
        if data_descriptor_offset >= 0 and len(segment) - data_descriptor_offset <= 20:
            segment = segment[:data_descriptor_offset]

        if compression == 8:
            try:
                raw_content = zlib.decompress(segment, -15)
            except zlib.error:
                raw_content = zlib.decompressobj(-15).decompress(segment)
        else:
            raw_content = segment

        local_path = os.path.join(destination_dir, filename)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, "wb") as output_file:
            output_file.write(raw_content)
        extracted_paths.append(local_path)
        offset = next_header_offset

    return extracted_paths


def first_csv_path(directory_path):
    csv_candidates = sorted(Path(directory_path).rglob("*.csv"))
    if not csv_candidates:
        raise FileNotFoundError(f"Aucun CSV trouvé dans {directory_path}")
    return str(csv_candidates[0])


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
    years = [
        row[0]
        for row in df.selectExpr(f"substring(cast({date_column} as string), 1, 4) as annee")
        .where("annee is not null and annee <> ''")
        .distinct()
        .orderBy("annee")
        .collect()
    ]
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
    df_communes_status = df_communes_status.na.fill({
        "dept": "inconnu",
        "dept_name": "Inconnu",
        "region_code": "inconnu",
        "region": "Inconnu",
    })

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
        print("Traitement des millésimes DVF...")
        local_dvf_paths = []
        loaded_dvf_years = []

        for year in DVF_YEARS:
            object_key = f"raw/dvf/transactions_dvf_{year}.csv.gz"
            local_dvf_path = os.path.join(temp_dir, f"transactions_dvf_{year}.csv.gz")
            try:
                download_raw_object(object_key, local_dvf_path)
                local_dvf_paths.append(local_dvf_path)
                loaded_dvf_years.append(str(year))
            except Exception as error:
                print(f"DVF {year} ignoré: {error}")

        if not local_dvf_paths:
            raise RuntimeError("Aucun millésime DVF disponible dans MinIO.")

        print(f"DVF - millésimes chargés: {', '.join(loaded_dvf_years)}")
        df_dvf = spark.read.csv(sorted(local_dvf_paths), header=True, sep=",")
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
        print("Traitement de dpe_logements_brut...")
        minio_client = get_minio_client()
        minio_bucket = ensure_bucket(minio_client, get_minio_settings()["bucket"])
        dpe_object_keys = list_objects_with_prefix(minio_client, minio_bucket, "raw/dpe/")
        dpe_object_keys = [key for key in dpe_object_keys if key.endswith(".csv") or key.endswith(".csv.gz")]
        if not dpe_object_keys:
            dpe_object_keys = ["raw/dpe/dpe_logements_brut.csv"]

        local_dpe_paths = []
        for object_key in dpe_object_keys:
            local_dpe_path = os.path.join(temp_dir, os.path.basename(object_key))
            download_raw_object(object_key, local_dpe_path)
            local_dpe_paths.append(local_dpe_path)

        df_dpe = spark.read.csv(sorted(local_dpe_paths), header=True, sep=",", multiLine=True, escape='"')
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

        # 4. Traitement Démographie et contexte territorial (INSEE + data.gouv)
        print("Traitement des données INSEE complémentaires...")
        local_extract_dir = os.path.join(temp_dir, "extract")
        os.makedirs(local_extract_dir, exist_ok=True)

        source_qa = {
            "sources": []
        }

        try:
            # 4.1 Population communale
            print("Traitement de demographie_insee.zip (population communale)...")
            local_zip_path = os.path.join(temp_dir, "demographie_insee.zip")
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

            print(f"INSEE population - lignes sources: {df_insee.count()}")
            print("INSEE population - année de traitement fixée par le job: 2023")

            write_jsonl_to_minio(df_insee_clean.dropna(subset=["commune_id", "population"]), "processed/demographics", "demographics.jsonl")
            source_qa["sources"].append({
                "file": "raw/insee/demographie_insee.zip",
                "processed_year": 2023,
                "note": "Population communale du fichier INSEE de référence; le millésime est fixé explicitement au traitement.",
            })

            # 4.2 Densité communale
            print("Traitement de densite_population_communes.csv (densité communale)...")
            local_density_path = os.path.join(temp_dir, "densite_population_communes.csv")
            download_raw_object("raw/insee/densite_population_communes.csv", local_density_path)
            os.chmod(local_density_path, 0o644)

            df_density = spark.read.csv(local_density_path, header=True, sep=",")
            df_density_clean = df_density.select(
                col("annee").cast("int").alias("annee"),
                lpad(trim(col("code_com")), 5, "0").alias("commune_id"),
                trim(col("nom_territoire")).alias("nom_territoire"),
                col("valeur").cast("double").alias("densite_population"),
                col("numerateur").cast("double").alias("numerateur"),
                col("denominateur").cast("double").alias("denominateur"),
            )
            print(f"Densité - lignes sources: {df_density.count()}")
            print_year_coverage(df_density, "annee", "Densité")
            write_jsonl_to_minio(df_density_clean.dropna(subset=["commune_id"]), "processed/demographics", "density.jsonl")
            source_qa["sources"].append({
                "file": "raw/insee/densite_population_communes.csv",
                "processed_year": "2021",
                "note": "Densité de population par commune issue de data.gouv / INSEE; la source porte son année dans la colonne annee.",
            })

            # 4.3 Chômage / population active
            print("Traitement de population_active_chomage_2022.zip (population active et chômage)...")
            local_unemployment_path = os.path.join(temp_dir, "population_active_chomage_2022.zip")
            local_unemployment_extract_dir = os.path.join(temp_dir, "unemployment_extract")
            os.makedirs(local_unemployment_extract_dir, exist_ok=True)
            download_raw_object("raw/insee/population_active_chomage_2022.zip", local_unemployment_path)
            os.chmod(local_unemployment_path, 0o644)

            extract_archive_members(local_unemployment_path, local_unemployment_extract_dir)
            unemployment_csv_path = first_csv_path(local_unemployment_extract_dir)
            df_unemployment = spark.read.csv(unemployment_csv_path, header=True, sep=";")
            df_unemployment_clean = df_unemployment.select(
                trim(col("GEO")).alias("commune_id"),
                trim(col("GEO_OBJECT")).alias("geo_object"),
                trim(col("EMPSTA_ENQ")).alias("statut_emploi"),
                trim(col("AGE")).alias("age"),
                trim(col("PCS")).alias("pcs"),
                trim(col("RP_MEASURE")).alias("mesure"),
                trim(col("FREQ")).alias("frequence"),
                col("TIME_PERIOD").cast("int").alias("annee"),
                col("OBS_VALUE").cast("double").alias("valeur")
            )
            df_unemployment_communes = df_unemployment_clean.where(
                (col("geo_object") == "COM") &
                (col("age") == "Y15T64") &
                (col("pcs") == "_T") &
                (col("frequence") == "A") &
                (col("mesure") == "POP") &
                (col("statut_emploi").isin("1T2", "2"))
            )

            taux_chomage = df_unemployment_communes.groupBy("commune_id", "annee").pivot("statut_emploi", ["1T2", "2"]).agg(spark_sum("valeur")).na.fill(0)
            taux_chomage = taux_chomage.select(
                col("commune_id"),
                col("annee"),
                col("1T2").alias("actifs_15_64"),
                col("2").alias("chomeurs_15_64"),
            ).withColumn(
                "taux_chomage",
                when(col("actifs_15_64") > 0, col("chomeurs_15_64") / col("actifs_15_64")).otherwise(None)
            )
            print(f"Chômage - lignes sources: {df_unemployment.count()}")
            print_year_coverage(df_unemployment, "TIME_PERIOD", "Chômage")
            write_jsonl_to_minio(taux_chomage.dropna(subset=["commune_id"]), "processed/demographics", "chomage_commune.jsonl")
            source_qa["sources"].append({
                "file": "raw/insee/population_active_chomage_2022.zip",
                "processed_year": 2022,
                "note": "Taux de chômage calculé comme chômeurs / actifs 15-64 ans à partir des indicateurs POP du fichier INSEE.",
            })

            # 4.4 Revenu disponible des ménages
            print("Traitement de revenu_disponible_menages_2023.zip (revenu disponible)...")
            local_revenue_path = os.path.join(temp_dir, "revenu_disponible_menages_2023.zip")
            local_revenue_extract_dir = os.path.join(temp_dir, "revenue_extract")
            os.makedirs(local_revenue_extract_dir, exist_ok=True)
            download_raw_object("raw/insee/revenu_disponible_menages_2023.zip", local_revenue_path)
            os.chmod(local_revenue_path, 0o644)

            extract_archive_members(local_revenue_path, local_revenue_extract_dir)
            revenue_csv_path = first_csv_path(local_revenue_extract_dir)
            df_revenue = spark.read.csv(revenue_csv_path, header=True, sep=";")
            df_revenue_clean = df_revenue.select(
                trim(col("AGE")).alias("age"),
                trim(col("ERFS_MEASURE")).alias("mesure"),
                trim(col("NB_PERS")).alias("nb_pers"),
                trim(col("NCH")).alias("nch"),
                trim(col("PCS")).alias("pcs"),
                trim(col("TPH")).alias("tph"),
                trim(col("OBS_STATUS")).alias("statut_obs"),
                trim(col("UNIT_MEASURE")).alias("unite_mesure"),
                trim(col("UNIT_MULT")).alias("unite_mult"),
                col("TIME_PERIOD").cast("int").alias("annee"),
                col("OBS_VALUE").cast("double").alias("valeur")
            )
            revenu_median = df_revenue_clean.where(col("mesure") == "MED_DI")
            print(f"Revenu disponible - lignes sources: {df_revenue.count()}")
            print_year_coverage(df_revenue, "TIME_PERIOD", "Revenu disponible")
            write_jsonl_to_minio(df_revenue_clean, "processed/demographics", "revenu_disponible.jsonl")
            source_qa["sources"].append({
                "file": "raw/insee/revenu_disponible_menages_2023.zip",
                "processed_year": 2023,
                "note": "Revenu disponible des ménages à un niveau agrégé ménages/territoires; la source ne porte pas un code commune comme les autres fichiers communaux.",
            })

            # 4.5 Base permanente des équipements (BPE)
            print("Traitement de bpe_2024.zip (équipements et services)...")
            local_bpe_path = os.path.join(temp_dir, "bpe_2024.zip")
            local_bpe_extract_dir = os.path.join(temp_dir, "bpe_extract")
            os.makedirs(local_bpe_extract_dir, exist_ok=True)
            download_raw_object("raw/infrastructure/bpe_2024.zip", local_bpe_path)
            os.chmod(local_bpe_path, 0o644)

            extract_archive_members(local_bpe_path, local_bpe_extract_dir)
            bpe_data_path = os.path.join(local_bpe_extract_dir, "DS_BPE_2024_data.csv")
            bpe_metadata_path = os.path.join(local_bpe_extract_dir, "DS_BPE_2024_metadata.csv")
            df_bpe = spark.read.csv(bpe_data_path, header=True, sep=";")
            df_bpe_metadata = spark.read.csv(bpe_metadata_path, header=True, sep=";")

            bpe_meta_dom = df_bpe_metadata.where(col("COD_VAR") == "FACILITY_DOM").select(
                trim(col("COD_MOD")).alias("FACILITY_DOM"),
                trim(col("LIB_MOD")).alias("facility_dom_label"),
            )
            bpe_meta_sdom = df_bpe_metadata.where(col("COD_VAR") == "FACILITY_SDOM").select(
                trim(col("COD_MOD")).alias("FACILITY_SDOM"),
                trim(col("LIB_MOD")).alias("facility_sdom_label"),
            )
            bpe_meta_type = df_bpe_metadata.where(col("COD_VAR") == "FACILITY_TYPE").select(
                trim(col("COD_MOD")).alias("FACILITY_TYPE"),
                trim(col("LIB_MOD")).alias("facility_type_label"),
            )

            df_bpe_clean = df_bpe.select(
                trim(col("GEO")).alias("geo"),
                trim(col("GEO_OBJECT")).alias("geo_object"),
                trim(col("FACILITY_DOM")).alias("facility_dom"),
                trim(col("FACILITY_SDOM")).alias("facility_sdom"),
                trim(col("FACILITY_TYPE")).alias("facility_type"),
                trim(col("BPE_MEASURE")).alias("bpe_measure"),
                col("TIME_PERIOD").cast("int").alias("annee"),
                col("OBS_VALUE").cast("double").alias("valeur")
            )

            df_bpe_labeled = df_bpe_clean \
                .join(bpe_meta_dom, on="facility_dom", how="left") \
                .join(bpe_meta_sdom, on="facility_sdom", how="left") \
                .join(bpe_meta_type, on="facility_type", how="left")

            df_bpe_rollup = df_bpe_labeled.groupBy(
                "annee",
                "geo",
                "geo_object",
                "facility_dom",
                "facility_dom_label",
                "facility_sdom",
                "facility_sdom_label",
            ).agg(
                spark_sum("valeur").alias("equipements_total")
            )

            print(f"BPE - lignes sources: {df_bpe.count()}")
            print_year_coverage(df_bpe, "TIME_PERIOD", "BPE")
            write_jsonl_to_minio(df_bpe_labeled, "processed/infrastructure", "bpe_equipment.jsonl")
            write_jsonl_to_minio(df_bpe_rollup, "processed/infrastructure", "bpe_rollups.jsonl")
            source_qa["sources"].append({
                "file": "raw/infrastructure/bpe_2024.zip",
                "processed_year": 2024,
                "note": "Dénombrement BPE communal et géolocalisé couvrant services, commerces, enseignement, santé, transports, sports et culture.",
            })

            # 4.6 Évolution BPE
            print("Traitement de bpe_evolution_2019_2024.zip (évolution des équipements)...")
            local_bpe_evolution_path = os.path.join(temp_dir, "bpe_evolution_2019_2024.zip")
            local_bpe_evolution_extract_dir = os.path.join(temp_dir, "bpe_evolution_extract")
            os.makedirs(local_bpe_evolution_extract_dir, exist_ok=True)
            download_raw_object("raw/infrastructure/bpe_evolution_2019_2024.zip", local_bpe_evolution_path)
            os.chmod(local_bpe_evolution_path, 0o644)

            extract_archive_members(local_bpe_evolution_path, local_bpe_evolution_extract_dir)
            bpe_evolution_data_path = first_csv_path(local_bpe_evolution_extract_dir)
            if os.path.exists(bpe_evolution_data_path):
                df_bpe_evolution = spark.read.csv(bpe_evolution_data_path, header=True, sep=";")
                df_bpe_evolution_clean = df_bpe_evolution.select(
                    trim(col("GEO")).alias("geo"),
                    trim(col("GEO_OBJECT")).alias("geo_object"),
                    trim(col("FACILITY_TYPE")).alias("facility_type"),
                    trim(col("BPE_MEASURE")).alias("bpe_measure"),
                    col("TIME_PERIOD").cast("int").alias("annee"),
                    col("OBS_VALUE").cast("double").alias("valeur")
                )
                print(f"BPE évolution - lignes sources: {df_bpe_evolution.count()}")
                print_year_coverage(df_bpe_evolution, "TIME_PERIOD", "BPE évolution")
                write_jsonl_to_minio(df_bpe_evolution_clean, "processed/infrastructure", "bpe_evolution.jsonl")
                source_qa["sources"].append({
                    "file": "raw/infrastructure/bpe_evolution_2019_2024.zip",
                    "processed_year": 2024,
                    "note": "Présence ou absence d'équipement par commune sur la période 2019-2024.",
                })
            else:
                print("BPE évolution introuvable après extraction, ingestion passée.")

            write_json_to_minio(
                source_qa,
                "processed/qa",
                "insee_source_qa.json",
            )
        except Exception as error:
            print(f"Données INSEE complémentaires introuvables ou incomplètes: {error}")
        
    print("Traitement Big Data PySpark terminé avec succès !")
    spark.stop()

if __name__ == "__main__":
    main()
