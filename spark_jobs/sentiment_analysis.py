import os
import json
import re
import sys
import tempfile
import unicodedata
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
    udf,
)
from pyspark.sql.types import DoubleType, IntegerType, StructField, StructType

AIRFLOW_HOME = Path(__file__).resolve().parents[1]
if str(AIRFLOW_HOME) not in sys.path:
    sys.path.insert(0, str(AIRFLOW_HOME))

from storage.minio_utils import download_to_path, ensure_bucket, get_minio_client, get_minio_settings, upload_fileobj

S3_BUCKET = os.getenv("CASAPEDIA_S3_BUCKET", "casapedia-datalake")
RAW_DIR = f"s3a://{S3_BUCKET}/raw"
PROCESSED_DIR = f"s3a://{S3_BUCKET}/processed"
SHARED_WORK_DIR = AIRFLOW_HOME / "spark_jobs" / "_work" / "sentiment_analysis"

POSITIVE_PATTERNS = [
    r"agreabl(e|es|ement)?",
    r"beau(x|s|se|ses)?",
    r"calm(e|es|ement)?",
    r"charmant(e|es|s)?",
    r"clair(e|es|s)?",
    r"convivial(e|es|s)?",
    r"sain(e|es|s)?",
    r"satisfaisant(e|es|s)?",
    r"satisfait(e|es|s)?",
    r"seren(e|es|ite|ites)?",
    r"stable(s)?",
    r"sympa(s)?",
    r"sympathique(s)?",
    r"tranquill(e|es|ite|ites)?",
    r"vivable(s)?",
    r"positif(ve|ves|s)?",
    r"bon(ne|nes|s)?",
    r"super(s)?",
    r"parfait(e|es|s)?",
]

NEGATIVE_PATTERNS = [
    r"agressif(ve|ves|s)?",
    r"bruyant(e|es|s)?",
    r"cher(e|es|s)?",
    r"dangereux(se|ses)?",
    r"degrad(e|ee|ees|es|ation|ations)?",
    r"difficil(e|es|ite|ites)?",
    r"sale(s)?",
    r"stressant(e|es|s)?",
    r"trist(e|es|esse|esses)?",
    r"violent(e|es|s)?",
    r"mauvais(e|es|s)?",
    r"nul(le|les|s)?",
    r"horribl(e|es|ement|ements)?",
    r"deplorable(s)?",
    r"pollu(e|ee|ees|es|ant|ants|ante|antes)?",
]

POSITIVE_PHRASE_PATTERNS = [
    r"\bplutot bien\b",
    r"\btres bien\b",
    r"\bc[’']?est bien\b",
    r"\bje vous conseille\b",
    r"\bje recommande\b",
    r"\bbonne ville\b",
    r"\bville sympa\b",
]

NEGATIVE_PHRASE_PATTERNS = [
    r"\bne vous conseille pas\b",
    r"\bne conseille pas\b",
    r"\bpas bien\b",
    r"\bbien pire\b",
    r"\bje deconseille\b",
    r"\bje ne recommande pas\b",
]

CONTRAST_MARKERS = [
    "mais",
    "cependant",
    "pourtant",
    "neanmoins",
    "en revanche",
    "malgre tout",
    "au final",
    "finalement",
    "sauf que",
]

CONTRAST_SPLIT_PATTERN = r"(?i)(\b(?:mais|cependant|pourtant|neanmoins|en revanche|malgre tout|au final|finalement|sauf que)\b|[.!?;:]+)"

SENTIMENT_FEATURE_SCHEMA = StructType([
    StructField("sentiment_score", DoubleType(), False),
    StructField("matched_positive_tokens", IntegerType(), False),
    StructField("matched_negative_tokens", IntegerType(), False),
    StructField("matched_token_count", IntegerType(), False),
    StructField("matched_segment_count", IntegerType(), False),
    StructField("sentiment_confidence", DoubleType(), False),
])

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


def strip_accents(value):
    if not value:
        return ""

    normalized = unicodedata.normalize("NFKD", value)
    return "".join(character for character in normalized if not unicodedata.combining(character))


def normalize_sentiment_text(value):
    return strip_accents(value).lower()


def tokenize_for_sentiment(value):
    normalized = normalize_sentiment_text(value)
    return re.findall(r"[a-z]+(?:'[a-z]+)?", normalized)


def token_score(token):
    for pattern in POSITIVE_PATTERNS:
        if re.fullmatch(pattern, token):
            return 1

    for pattern in NEGATIVE_PATTERNS:
        if re.fullmatch(pattern, token):
            return -1

    return 0


def phrase_score(text):
    score = 0
    for pattern in POSITIVE_PHRASE_PATTERNS:
        if re.search(pattern, text):
            score += 2

    for pattern in NEGATIVE_PHRASE_PATTERNS:
        if re.search(pattern, text):
            score -= 2

    return score


def split_sentiment_segments(value):
    normalized = normalize_sentiment_text(value)
    parts = re.split(CONTRAST_SPLIT_PATTERN, normalized)
    segments = []
    has_contrast_marker = False
    after_contrast_marker = False

    for part in parts:
        if not part or not part.strip():
            continue

        cleaned_part = part.strip()
        if re.fullmatch(r"[.!?;:]+", cleaned_part):
            continue

        if cleaned_part in CONTRAST_MARKERS:
            has_contrast_marker = True
            after_contrast_marker = True
            continue

        if after_contrast_marker:
            weight = 1.4
        elif has_contrast_marker:
            weight = 0.75
        else:
            weight = 1.0

        segments.append((cleaned_part, weight))

    if not segments:
        return [(normalized, 1.0)] if normalized else []

    return segments


def score_review_text(value):
    segments = split_sentiment_segments(value)
    if not segments:
        return {
            "sentiment_score": 0.0,
            "matched_positive_tokens": 0,
            "matched_negative_tokens": 0,
            "matched_token_count": 0,
            "matched_segment_count": 0,
            "sentiment_confidence": 0.0,
        }

    weighted_score_sum = 0.0
    weighted_segments_sum = 0.0
    positive_token_count = 0
    negative_token_count = 0
    matched_token_count = 0
    matched_segment_count = 0

    for segment_text, weight in segments:
        tokens = tokenize_for_sentiment(segment_text)
        positive_matches = 0
        negative_matches = 0
        segment_bonus = phrase_score(segment_text)

        for token in tokens:
            score = token_score(token)
            if score > 0:
                positive_matches += 1
            elif score < 0:
                negative_matches += 1

        if positive_matches or negative_matches:
            matched_segment_count += 1

        segment_matches = positive_matches + negative_matches
        if segment_matches == 0 and segment_bonus == 0:
            continue

        raw_segment_score = positive_matches - negative_matches + segment_bonus
        segment_score = raw_segment_score / max(segment_matches + abs(segment_bonus), 1)
        weighted_score_sum += segment_score * weight
        weighted_segments_sum += weight
        positive_token_count += positive_matches
        negative_token_count += negative_matches
        matched_token_count += segment_matches

    if weighted_segments_sum == 0:
        return {
            "sentiment_score": 0.0,
            "matched_positive_tokens": positive_token_count,
            "matched_negative_tokens": negative_token_count,
            "matched_token_count": matched_token_count,
            "matched_segment_count": matched_segment_count,
            "sentiment_confidence": 0.0,
        }

    sentiment_score = weighted_score_sum / weighted_segments_sum
    sentiment_confidence = abs(sentiment_score) * max(matched_segment_count, 1)

    return {
        "sentiment_score": float(round(sentiment_score, 4)),
        "matched_positive_tokens": int(positive_token_count),
        "matched_negative_tokens": int(negative_token_count),
        "matched_token_count": int(matched_token_count),
        "matched_segment_count": int(matched_segment_count),
        "sentiment_confidence": float(round(sentiment_confidence, 4)),
    }


score_review_text_udf = udf(score_review_text, SENTIMENT_FEATURE_SCHEMA)


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

        scored_reviews = prepared.withColumn("sentiment_features", score_review_text_udf(col("review_text"))).select(
            "commune_id",
            "source",
            "review_text",
            "clean_text",
            "rating",
            col("sentiment_features.sentiment_score").alias("sentiment_score"),
            col("sentiment_features.matched_positive_tokens").alias("matched_positive_tokens"),
            col("sentiment_features.matched_negative_tokens").alias("matched_negative_tokens"),
            col("sentiment_features.matched_token_count").alias("matched_token_count"),
            col("sentiment_features.matched_segment_count").alias("matched_segment_count"),
            col("sentiment_features.sentiment_confidence").alias("sentiment_confidence"),
        ).withColumn(
            "sentiment_label",
            when(col("sentiment_score") > 0, lit("positive"))
            .when(col("sentiment_score") < 0, lit("negative"))
            .otherwise(lit("neutral")),
        )

        tokenized = prepared.withColumn("token", explode(split(col("clean_text"), r"\s+")))

        theme_mentions = build_theme_mentions(prepared)
        theme_sentiments = theme_mentions.join(
            scored_reviews,
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

        write_jsonl_to_minio(scored_reviews, output_root, "sentiments.jsonl")
        write_jsonl_to_minio(wordclouds, output_root, "wordclouds.jsonl")
        write_jsonl_to_minio(theme_mentions, output_root, "themes.jsonl")
        write_jsonl_to_minio(theme_sentiments, output_root, "theme_sentiments.jsonl")

    print("Job NLP terminé avec succès.")
    spark.stop()


if __name__ == "__main__":
    main()