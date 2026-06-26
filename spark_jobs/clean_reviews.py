import os
import json
import sys
import re
from io import BytesIO
from pathlib import Path

from pyspark.sql import SparkSession
from pyspark.sql.functions import col, lit, lower, regexp_replace, trim
from pyspark.sql.types import DoubleType, StringType, StructField, StructType

AIRFLOW_HOME = Path(__file__).resolve().parents[1]
if str(AIRFLOW_HOME) not in sys.path:
    sys.path.insert(0, str(AIRFLOW_HOME))

from storage.minio_utils import download_to_path, ensure_bucket, get_minio_client, get_minio_settings, upload_fileobj

S3_BUCKET = os.getenv("CASAPEDIA_S3_BUCKET", "casapedia-datalake")
RAW_DIR = f"s3a://{S3_BUCKET}/raw"
PROCESSED_DIR = f"s3a://{S3_BUCKET}/processed"
SHARED_WORK_DIR = AIRFLOW_HOME / "spark_jobs" / "_work" / "clean_reviews"

REVIEW_SCHEMA = StructType([
    StructField("source", StringType(), True),
    StructField("site", StringType(), True),
    StructField("city_name", StringType(), True),
    StructField("commune_id", StringType(), True),
    StructField("city_code", StringType(), True),
    StructField("review_date", StringType(), True),
    StructField("author", StringType(), True),
    StructField("rating", DoubleType(), True),
    StructField("review_text", StringType(), True),
    StructField("positive_text", StringType(), True),
    StructField("negative_text", StringType(), True),
    StructField("criteria_scores", StringType(), True),
    StructField("score_details", StringType(), True),
])


def load_reviews_records_from_minio(prefix):
    client = get_minio_client()
    settings = get_minio_settings()
    bucket = ensure_bucket(client, settings["bucket"])

    records = []
    response = client.list_objects(Bucket=bucket, Prefix=prefix)
    for item in response.get("Contents", []):
        object_key = item["Key"]
        if object_key == prefix:
            continue

        body = client.get_object(Bucket=bucket, Key=object_key)["Body"].read().decode("utf-8")
        for line in body.splitlines():
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))

    return records


def download_reviews_prefix(prefix, destination_dir):
    client = get_minio_client()
    settings = get_minio_settings()
    bucket = ensure_bucket(client, settings["bucket"])

    response = client.list_objects(Bucket=bucket, Prefix=prefix)
    for item in response.get("Contents", []):
        object_key = item["Key"]
        if object_key == prefix:
            continue

        relative_key = object_key[len(prefix):].lstrip("/")
        if not relative_key:
            continue

        local_path = os.path.join(destination_dir, relative_key)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        download_to_path(client, bucket, object_key, local_path)
        os.chmod(local_path, 0o644)

    return destination_dir


def build_clean_text(review_text):
    cleaned_text = re.sub(r"[^a-zA-Zàâäçéèêëîïôöùûüÿñæœ' -]", " ", (review_text or "").lower())
    cleaned_text = re.sub(r"\s+", " ", cleaned_text)
    return cleaned_text.strip()


def write_clean_jsonl_to_minio(records, output_prefix, filename):
    settings = get_minio_settings()
    client = get_minio_client()
    bucket = ensure_bucket(client, settings["bucket"])
    object_key = f"{output_prefix}/{filename}"

    buffer = BytesIO()
    for record in records:
        buffer.write((json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8"))
    buffer.seek(0)

    upload_fileobj(client, bucket, object_key, buffer, content_type="application/x-ndjson")
    print(f"Reviews pré-traités enregistrés dans : s3a://{bucket}/{object_key}")


def normalize_columns(df):
    for column_name in df.columns:
        df = df.withColumnRenamed(column_name, column_name.strip().lower())
    return df


def first_existing_column(columns, candidates):
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def stringify_nested_value(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def normalize_review_record(record):
    return {
        "source": stringify_nested_value(record.get("source")),
        "site": stringify_nested_value(record.get("site")),
        "city_name": stringify_nested_value(record.get("city_name")),
        "commune_id": stringify_nested_value(record.get("commune_id")),
        "city_code": stringify_nested_value(record.get("city_code")),
        "review_date": stringify_nested_value(record.get("review_date")),
        "author": stringify_nested_value(record.get("author")),
        "rating": float(record["rating"]) if record.get("rating") is not None else None,
        "review_text": stringify_nested_value(record.get("review_text")),
        "positive_text": stringify_nested_value(record.get("positive_text")),
        "negative_text": stringify_nested_value(record.get("negative_text")),
        "criteria_scores": stringify_nested_value(record.get("criteria_scores")),
        "score_details": stringify_nested_value(record.get("score_details")),
    }


def main():
    records = load_reviews_records_from_minio("raw/reviews/")
    if not records:
        raise ValueError("Aucun avis brut n'a été trouvé dans MinIO.")

    normalized_records = [normalize_review_record(record) for record in records]
    cleaned_records = []
    for record in normalized_records:
        review_text = (record.get("review_text") or "").strip()
        if not review_text:
            continue

        prepared_record = dict(record)
        prepared_record["clean_text"] = build_clean_text(review_text)
        cleaned_records.append(prepared_record)

    write_clean_jsonl_to_minio(cleaned_records, "processed/reviews", "clean_reviews.jsonl")

    print("Pré-traitement des reviews terminé avec succès !")


if __name__ == "__main__":
    main()