import os
import json
import sys
import tempfile
from pathlib import Path
from io import BytesIO

from pyspark.sql import SparkSession
from pyspark.sql.functions import (
    col,
    avg,
    count,
    explode,
    lit,
    lower,
    regexp_replace,
    split,
    sum as spark_sum,
    trim,
    when,
)

AIRFLOW_HOME = Path(__file__).resolve().parents[1]
if str(AIRFLOW_HOME) not in sys.path:
    sys.path.insert(0, str(AIRFLOW_HOME))

from storage.minio_utils import download_to_path, ensure_bucket, get_minio_client, get_minio_settings, upload_fileobj

S3_BUCKET = os.getenv("CASAPEDIA_S3_BUCKET", "casapedia-datalake")
RAW_DIR = f"s3a://{S3_BUCKET}/raw"
PROCESSED_DIR = f"s3a://{S3_BUCKET}/processed"
SHARED_WORK_DIR = AIRFLOW_HOME / "spark_jobs" / "_work" / "sentiment_analysis"

POSITIVE_WORDS = [
    "agreable",
    "beau",
    "calme",
    "charmant",
    "clair",
    "convivial",
    "sain",
    "satisfaisant",
    "satisfait",
    "seren",
    "serene",
    "stable",
    "sympa",
    "tranquille",
    "vivable",
]

NEGATIVE_WORDS = [
    "agressif",
    "bruyant",
    "cher",
    "dangereux",
    "dégradé",
    "difficile",
    "sale",
    "stressant",
    "triste",
    "violent",
]

THEME_RULES = [
    (
        "sécurité",
        "sécurité",
        r"(dangereux|violen|agressif|stressant|insécur|insecur|bruyant)",
    ),
    (
        "transports",
        "transports",
        r"(transport|bus|tram|metro|métro|train|gare|trafic|circul|parking|voitur)",
    ),
    (
        "écoles",
        "écoles",
        r"(ecole|école|college|collège|lycee|lycée|creche|crèche|université)",
    ),
    (
        "propreté",
        "propreté",
        r"(propre|sale|propreté|proprete|dechet|déchet|entretien)",
    ),
    (
        "cadre_de_vie",
        "cadre_de_vie",
        r"(calme|agreable|agréable|sympa|vivable|verdure|parc|ambiance)",
    ),
    (
        "commerces_services",
        "commerces_et_services",
        r"(commerce|magasin|restaurant|supermarch|boulanger|service|amenag|aménag)",
    ),
]


def write_jsonl_to_minio(df, output_prefix, filename):
    settings = get_minio_settings()
    client = get_minio_client()

    bucket = settings["bucket"]
    prefix = output_prefix
    if output_prefix.startswith("s3a://"):
        without_scheme = output_prefix[len("s3a://"):]
        bucket_name, _, object_prefix = without_scheme.partition("/")
        bucket = bucket_name or bucket
        prefix = object_prefix

    bucket = ensure_bucket(client, bucket)
    object_key = f"{prefix.rstrip('/')}/{filename}" if prefix else filename

    buffer = BytesIO()
    for row_json in df.toJSON().toLocalIterator():
        buffer.write((row_json + "\n").encode("utf-8"))
    buffer.seek(0)

    upload_fileobj(client, bucket, object_key, buffer, content_type="application/x-ndjson")
    print(f"Jeu de données écrit dans : s3a://{bucket}/{object_key}")


def normalize_columns(df):
    for column_name in df.columns:
        df = df.withColumnRenamed(column_name, column_name.strip().lower())
    return df


def first_existing_column(columns, candidates):
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def build_theme_mentions(prepared_df):
    theme_frames = []

    for theme_key, theme_label, pattern in THEME_RULES:
        theme_frames.append(
            prepared_df.where(lower(col("clean_text")).rlike(pattern)).select(
                "commune_id",
                "source",
                "review_text",
                "clean_text",
                "rating",
            ).withColumn("theme", lit(theme_key)).withColumn("theme_label", lit(theme_label))
        )

    if not theme_frames:
        return prepared_df.limit(0).select(
            "commune_id",
            "source",
            "review_text",
            "clean_text",
            "rating",
            lit(None).cast("string").alias("theme"),
            lit(None).cast("string").alias("theme_label"),
        )

    theme_mentions = theme_frames[0]
    for frame in theme_frames[1:]:
        theme_mentions = theme_mentions.unionByName(frame)

    return theme_mentions


def read_reviews_dataset(spark, input_path):
    local_path = Path(input_path)
    if local_path.exists():
        if local_path.is_file():
            if input_path.lower().endswith(".csv"):
                return spark.read.csv(input_path, header=True, inferSchema=True)
            if input_path.lower().endswith(".json") or input_path.lower().endswith(".jsonl"):
                return spark.read.json(input_path)
            if input_path.lower().endswith(".txt"):
                return spark.read.text(input_path).withColumnRenamed("value", "text")

        if local_path.is_dir():
            for extension, reader in (
                ("*.jsonl", lambda file_path: spark.read.json(file_path)),
                ("*.json", lambda file_path: spark.read.json(file_path)),
                ("*.csv", lambda file_path: spark.read.csv(file_path, header=True, inferSchema=True)),
                ("*.txt", lambda file_path: spark.read.text(file_path).withColumnRenamed("value", "text")),
            ):
                matching_files = sorted(local_path.glob(extension))
                if matching_files:
                    return reader(str(matching_files[0]))

    lower_path = input_path.lower()
    readers = []

    if lower_path.endswith(".csv"):
        readers.append(lambda: spark.read.csv(input_path, header=True, inferSchema=True))
    elif lower_path.endswith(".json"):
        readers.append(lambda: spark.read.json(input_path))
    elif lower_path.endswith(".jsonl"):
        readers.append(lambda: spark.read.json(input_path))
    elif lower_path.endswith(".txt"):
        readers.append(lambda: spark.read.text(input_path).withColumnRenamed("value", "text"))
    else:
        readers.extend([
            lambda: spark.read.csv(f"{input_path}/*.csv", header=True, inferSchema=True),
            lambda: spark.read.json(f"{input_path}/*.json"),
            lambda: spark.read.json(f"{input_path}/*.jsonl"),
            lambda: spark.read.text(f"{input_path}/*.txt").withColumnRenamed("value", "text"),
        ])

    last_error = None
    for reader in readers:
        try:
            return reader()
        except Exception as error:
            last_error = error

    raise FileNotFoundError(
        f"Aucune source texte exploitable trouvée dans {input_path}."
    ) from last_error


def stage_reviews_input(input_path, destination_dir):
    if not input_path.startswith("s3a://"):
        return input_path

    without_scheme = input_path[len("s3a://"):]
    bucket_name, _, object_path = without_scheme.partition("/")
    object_path = object_path.lstrip("/")

    client = get_minio_client()
    settings = get_minio_settings()
    bucket = ensure_bucket(client, bucket_name or settings["bucket"])

    os.makedirs(destination_dir, exist_ok=True)

    if object_path and any(object_path.lower().endswith(ext) for ext in (".jsonl", ".json", ".csv", ".txt")):
        local_file = os.path.join(destination_dir, os.path.basename(object_path))
        download_to_path(client, bucket, object_path, local_file)
        os.chmod(local_file, 0o644)
        return local_file

    prefix = object_path.rstrip("/")
    prefix = f"{prefix}/" if prefix else ""

    response = client.list_objects(Bucket=bucket, Prefix=prefix)
    for item in response.get("Contents", []):
        object_key = item["Key"]
        if object_key.endswith("/"):
            continue

        relative_key = object_key[len(prefix):].lstrip("/") if prefix else os.path.basename(object_key)
        if not relative_key:
            continue

        local_path = os.path.join(destination_dir, relative_key)
        download_to_path(client, bucket, object_key, local_path)
        os.chmod(local_path, 0o644)

    return destination_dir


def main():
    input_path = os.environ.get("CASAPEDIA_SENTIMENT_INPUT", f"{PROCESSED_DIR}/reviews")
    output_root = os.environ.get("CASAPEDIA_SENTIMENT_OUTPUT", f"{PROCESSED_DIR}/nlp")

    print("Initialisation de SparkSession pour le job NLP...")
    spark = SparkSession.builder.appName("Casapedia_Sentiment_Analysis").getOrCreate()

    os.makedirs(SHARED_WORK_DIR, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=SHARED_WORK_DIR) as temp_dir:
        os.chmod(temp_dir, 0o777)
        staged_input = stage_reviews_input(input_path, os.path.join(temp_dir, "input"))

        df_reviews = normalize_columns(read_reviews_dataset(spark, staged_input))

        text_column = first_existing_column(df_reviews.columns, ["review_text", "text", "review", "comment", "contenu", "avis", "message", "clean_text"])
        if text_column is None:
            raise ValueError("Aucune colonne texte exploitable trouvée dans la source reviews.")

        commune_column = first_existing_column(
            df_reviews.columns,
            ["commune_id", "code_insee", "code_commune", "code_insee_ban", "city_code"],
        )
        score_column = first_existing_column(df_reviews.columns, ["rating", "note", "score"])
        source_column = first_existing_column(df_reviews.columns, ["source", "site", "origine"])

        base_columns = [trim(col(text_column)).alias("review_text")]
        if commune_column is not None:
            base_columns.insert(0, trim(col(commune_column)).alias("commune_id"))
        else:
            base_columns.insert(0, lit(None).cast("string").alias("commune_id"))
        if score_column is not None:
            base_columns.append(col(score_column).cast("double").alias("rating"))
        else:
            base_columns.append(lit(None).cast("double").alias("rating"))
        if source_column is not None:
            base_columns.append(trim(col(source_column)).alias("source"))
        else:
            base_columns.append(lit("unknown").alias("source"))

        prepared = df_reviews.select(*base_columns).dropna(subset=["review_text"])
        prepared = prepared.withColumn(
            "clean_text",
            regexp_replace(lower(col("review_text")), r"[^a-zA-Zàâäçéèêëîïôöùûüÿñæœ' -]", " "),
        ).withColumn(
            "clean_text",
            regexp_replace(col("clean_text"), r"\s+", " "),
        ).withColumn("clean_text", trim(col("clean_text")))

        tokenized = prepared.withColumn("token", explode(split(col("clean_text"), r"\s+")))

        sentiment_scored = tokenized.withColumn(
            "token_score",
            when(col("token").isin(*POSITIVE_WORDS), lit(1))
            .when(col("token").isin(*NEGATIVE_WORDS), lit(-1))
            .otherwise(lit(0)),
        )

        aggregated_sentiment = sentiment_scored.groupBy("commune_id", "source", "review_text", "clean_text", "rating").agg(
            count("token").alias("token_count"),
            spark_sum("token_score").alias("sentiment_score"),
        ).withColumn(
            "sentiment_label",
            when(col("sentiment_score") > 0, lit("positive"))
            .when(col("sentiment_score") < 0, lit("negative"))
            .otherwise(lit("neutral")),
        )

        theme_mentions = build_theme_mentions(prepared)
        theme_sentiments = theme_mentions.join(
            aggregated_sentiment,
            on=["commune_id", "source", "review_text", "clean_text", "rating"],
            how="left",
        ).groupBy(
            "commune_id",
            "source",
            "theme",
            "theme_label",
        ).agg(
            count("theme").alias("mention_count"),
            avg("sentiment_score").alias("avg_sentiment_score"),
            spark_sum(when(col("sentiment_label") == "positive", lit(1)).otherwise(lit(0))).alias("positive_reviews"),
            spark_sum(when(col("sentiment_label") == "negative", lit(1)).otherwise(lit(0))).alias("negative_reviews"),
        ).withColumn(
            "theme_sentiment_label",
            when(col("avg_sentiment_score") > 0, lit("positive"))
            .when(col("avg_sentiment_score") < 0, lit("negative"))
            .otherwise(lit("neutral")),
        )

        wordclouds = tokenized.where(~col("token").isin("", "le", "la", "les", "de", "des", "du", "et", "a", "un", "une")).groupBy(
            "commune_id",
            "source",
            "token",
        ).agg(
            count("token").alias("frequency"),
        ).withColumnRenamed("token", "word")

        write_jsonl_to_minio(aggregated_sentiment, output_root, "sentiments.jsonl")
        write_jsonl_to_minio(wordclouds, output_root, "wordclouds.jsonl")
        write_jsonl_to_minio(theme_mentions, output_root, "themes.jsonl")
        write_jsonl_to_minio(theme_sentiments, output_root, "theme_sentiments.jsonl")

    print("Job NLP terminé avec succès.")
    spark.stop()


if __name__ == "__main__":
    main()