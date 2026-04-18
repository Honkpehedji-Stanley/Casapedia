import os
import shutil

from pyspark.sql import SparkSession
from pyspark.sql.functions import (
    col,
    concat_ws,
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


RAW_DIR = "/opt/airflow/datalake/raw"
PROCESSED_DIR = "/opt/airflow/datalake/processed"

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
    "degrade",
    "difficile",
    "sale",
    "stressant",
    "triste",
    "violent",
]


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


def normalize_columns(df):
    for column_name in df.columns:
        df = df.withColumnRenamed(column_name, column_name.strip().lower())
    return df


def first_existing_column(columns, candidates):
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def read_reviews_dataset(spark, input_path):
    if os.path.isfile(input_path):
        lower_path = input_path.lower()
        if lower_path.endswith(".csv"):
            return spark.read.csv(input_path, header=True, inferSchema=True)
        if lower_path.endswith(".json"):
            return spark.read.json(input_path)
        return spark.read.text(input_path).withColumnRenamed("value", "text")

    if os.path.isdir(input_path):
        csv_files = [name for name in os.listdir(input_path) if name.lower().endswith(".csv")]
        json_files = [name for name in os.listdir(input_path) if name.lower().endswith(".json")]
        txt_files = [name for name in os.listdir(input_path) if name.lower().endswith(".txt")]

        if csv_files:
            return spark.read.csv(os.path.join(input_path, "*.csv"), header=True, inferSchema=True)
        if json_files:
            return spark.read.json(os.path.join(input_path, "*.json"))
        if txt_files:
            return spark.read.text(os.path.join(input_path, "*.txt")).withColumnRenamed("value", "text")

    raise FileNotFoundError(
        f"Aucune source texte trouvée dans {input_path}. Ajoute un CSV, JSON ou TXT de reviews avant d'exécuter le job."
    )


def main():
    input_path = os.environ.get("CASAPEDIA_SENTIMENT_INPUT", f"{RAW_DIR}/reviews")
    output_root = os.environ.get("CASAPEDIA_SENTIMENT_OUTPUT", f"{PROCESSED_DIR}/nlp")

    print("Initialisation de SparkSession pour le job NLP...")
    spark = SparkSession.builder.appName("Casapedia_Sentiment_Analysis").getOrCreate()

    df_reviews = normalize_columns(read_reviews_dataset(spark, input_path))

    text_column = first_existing_column(df_reviews.columns, ["text", "review", "comment", "contenu", "avis", "message"])
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

    wordclouds = tokenized.where(~col("token").isin("", "le", "la", "les", "de", "des", "du", "et", "a", "un", "une")).groupBy(
        "commune_id",
        "source",
        "token",
    ).agg(
        count("token").alias("frequency"),
    ).withColumnRenamed("token", "word")

    write_clean_parquet(aggregated_sentiment, f"{output_root}/sentiments")
    write_clean_parquet(wordclouds, f"{output_root}/wordclouds")

    print("Job NLP terminé avec succès.")
    spark.stop()


if __name__ == "__main__":
    main()