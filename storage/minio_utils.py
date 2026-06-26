import os

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError


def get_minio_settings():
    return {
        "endpoint_url": os.getenv("MINIO_ENDPOINT", "http://minio:9000"),
        "access_key": os.getenv("MINIO_ROOT_USER", "minioadmin"),
        "secret_key": os.getenv("MINIO_ROOT_PASSWORD", "minioadmin123"),
        "bucket": os.getenv("CASAPEDIA_S3_BUCKET", "casapedia-datalake"),
    }


def get_minio_client():
    settings = get_minio_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings["endpoint_url"],
        aws_access_key_id=settings["access_key"],
        aws_secret_access_key=settings["secret_key"],
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def ensure_bucket(client, bucket_name=None):
    settings = get_minio_settings()
    bucket = bucket_name or settings["bucket"]
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError:
        client.create_bucket(Bucket=bucket)
    return bucket


def upload_fileobj(client, bucket_name, object_key, fileobj, content_type=None):
    extra_args = {}
    if content_type:
        extra_args["ContentType"] = content_type
    if extra_args:
        client.upload_fileobj(fileobj, bucket_name, object_key, ExtraArgs=extra_args)
    else:
        client.upload_fileobj(fileobj, bucket_name, object_key)


def download_to_path(client, bucket_name, object_key, destination_path):
    os.makedirs(os.path.dirname(destination_path), exist_ok=True)
    client.download_file(bucket_name, object_key, destination_path)


def list_objects_with_prefix(client, bucket_name, prefix):
    paginator = client.get_paginator("list_objects_v2")
    object_keys = []

    for page in paginator.paginate(Bucket=bucket_name, Prefix=prefix):
        for entry in page.get("Contents", []):
            key = entry.get("Key")
            if key:
                object_keys.append(key)

    return sorted(object_keys)


def s3_path(prefix):
    settings = get_minio_settings()
    clean_prefix = prefix.lstrip("/")
    return f"s3a://{settings['bucket']}/{clean_prefix}"
