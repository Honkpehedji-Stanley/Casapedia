import html
import json
import re
import os
import sys
import time
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import tempfile

import requests

AIRFLOW_HOME = Path(__file__).resolve().parents[1]
if str(AIRFLOW_HOME) not in sys.path:
    sys.path.insert(0, str(AIRFLOW_HOME))

from storage.minio_utils import ensure_bucket, get_minio_client, get_minio_settings, upload_fileobj

# Configuration par défaut du DAG : "Les règles de production"
default_args = {
    'owner': 'casapedia',
    'depends_on_past': False,
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 3,              
    'retry_delay': timedelta(minutes=5),
}

def download_file(url, dest_folder, filename):
    """
    Fonction ELT : Téléchargement 'Dumb'.
    """
    settings = get_minio_settings()
    client = get_minio_client()
    bucket = ensure_bucket(client, settings["bucket"])
    object_key = f"raw/{dest_folder}/{filename}"

    print(f"Début du téléchargement : {url}")

    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with tempfile.NamedTemporaryFile(suffix=f"-{filename}") as temp_file:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    temp_file.write(chunk)
            temp_file.flush()
            temp_file.seek(0)
            upload_fileobj(client, bucket, object_key, temp_file.file, content_type=r.headers.get("Content-Type"))

    print(f"Téléchargement terminé avec succès et sauvegardé sous : s3a://{bucket}/{object_key}")


def fetch_html(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    }
    candidate_urls = [url]
    if "www." in url:
        candidate_urls.append(url.replace("www.", "", 1))

    last_error = None
    for candidate_url in candidate_urls:
        for attempt in range(3):
            try:
                response = requests.get(candidate_url, headers=headers, timeout=(10, 60))
                response.raise_for_status()
                return response.text
            except Exception as error:
                last_error = error
                if attempt < 2:
                    time.sleep(2 ** attempt)

    raise last_error


def strip_tags(value):
    return re.sub(r"<[^>]+>", " ", html.unescape(value or "")).replace("\xa0", " ").strip()


def normalize_url(url):
    parsed_url = urlsplit(url)
    return urlunsplit((parsed_url.scheme, parsed_url.netloc, parsed_url.path, "", ""))


def write_jsonl_to_minio(records, output_prefix, filename):
    settings = get_minio_settings()
    client = get_minio_client()
    bucket = ensure_bucket(client, settings["bucket"])
    object_key = f"raw/{output_prefix}/{filename}"

    buffer = BytesIO()
    for record in records:
        buffer.write((json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8"))
    buffer.seek(0)
    upload_fileobj(client, bucket, object_key, buffer, content_type="application/x-ndjson")

    print(f"Avis enregistrés dans : s3a://{bucket}/{object_key}")


def extract_city_links(home_html, base_url, pattern):
    city_links = []
    seen_links = set()

    for raw_href in re.findall(r'href="([^"]+)"', home_html):
        absolute_href = normalize_url(urljoin(base_url, html.unescape(raw_href)))
        parsed_path = urlsplit(absolute_href).path
        if re.fullmatch(pattern, parsed_path):
            if absolute_href not in seen_links:
                seen_links.add(absolute_href)
                city_links.append(absolute_href)

    return city_links


def parse_city_name_from_page(page_html):
    match = re.search(r"<h1>([^<]+)</h1>", page_html)
    if not match:
        return None, None

    title = strip_tags(match.group(1))
    city_code_match = re.search(r"\((\d{5})\)", title)
    city_code = city_code_match.group(1) if city_code_match else None
    city_name = re.sub(r"\s*\(\d{5}\)\s*", "", title).strip()
    return city_name, city_code


def scrape_ville_ideale_reviews():
    home_url = "https://www.ville-ideale.fr/"
    home_html = fetch_html(home_url)
    city_links = extract_city_links(home_html, home_url, r"/[a-z0-9\-]+_[0-9]{5}")
    city_links = city_links[: int(os.getenv("CASAPEDIA_REVIEWS_CITY_LIMIT", "12"))]

    records = []
    criteria_names = [
        "Environnement",
        "Transports",
        "Sécurité",
        "Santé",
        "Sports et loisirs",
        "Culture",
        "Enseignement",
        "Commerces",
        "Qualité de vie",
    ]

    for city_url in city_links:
        try:
            page_html = fetch_html(city_url)
        except Exception as error:
            print(f"Ville-Idéale: page ignorée {city_url} ({error})")
            continue

        city_name, city_code = parse_city_name_from_page(page_html)
        review_blocks = re.findall(r'<div class="comm".*?>(.*?)<div class="interact"', page_html, flags=re.S)

        for block in review_blocks:
            author_match = re.search(r'Par <strong>(.*?)</strong>', block)
            date_match = re.search(r'Avis posté le ([^<]+)</span>', block)
            rating_match = re.search(r'<strong class="moyenne"[^>]*>([0-9.,]+)</strong>', block)
            positive_match = re.search(r'Les points positifs : </b>(.*?)</p>', block, flags=re.S)
            negative_match = re.search(r'Les points négatifs : </b>(.*?)</p>', block, flags=re.S)
            criteria_values_match = re.search(r'<table><tr><th>.*?</th></tr><tr>(.*?)</tr></table>', block, flags=re.S)

            criteria_scores = {}
            if criteria_values_match:
                values = [strip_tags(value) for value in re.findall(r'<td[^>]*>(.*?)</td>', criteria_values_match.group(1), flags=re.S)]
                criteria_scores = {
                    criteria_names[index]: values[index]
                    for index in range(min(len(criteria_names), len(values)))
                }

            positive_text = strip_tags(positive_match.group(1)) if positive_match else ""
            negative_text = strip_tags(negative_match.group(1)) if negative_match else ""
            review_text = " ".join([segment for segment in [positive_text, negative_text] if segment]).strip()

            if not review_text:
                continue

            records.append({
                "source": "ville-ideale.fr",
                "site": "ville-ideale",
                "city_name": city_name,
                "city_code": city_code,
                "source_url": city_url,
                "review_date": strip_tags(date_match.group(1)) if date_match else None,
                "author": strip_tags(author_match.group(1)) if author_match else None,
                "rating": float(rating_match.group(1).replace(",", ".")) if rating_match else None,
                "review_text": review_text,
                "positive_text": positive_text,
                "negative_text": negative_text,
                "criteria_scores": criteria_scores,
            })

    return records


def scrape_villesavivre_reviews():
    home_url = "https://www.villesavivre.fr/"
    try:
        home_html = fetch_html(home_url)
    except Exception as error:
        print(f"Villes à Vivre: source indisponible ({error}); aucune review collectée.")
        return []
    city_links = extract_city_links(home_html, home_url, r"/[a-z0-9\-]+-[0-9]{5}/")
    city_links = city_links[: int(os.getenv("CASAPEDIA_REVIEWS_CITY_LIMIT", "12"))]

    records = []

    for city_url in city_links:
        try:
            page_html = fetch_html(city_url)
        except Exception as error:
            print(f"Villes à Vivre: page ignorée {city_url} ({error})")
            continue

        city_name, city_code = parse_city_name_from_page(page_html)
        review_section_match = re.search(r'<section class="comment" id="reviews".*?</section>', page_html, flags=re.S)
        if not review_section_match:
            continue

        review_cards = re.findall(r'<div class="card"><div class="card-body">(.*?)<div class="review-comments">', review_section_match.group(0), flags=re.S)

        for card in review_cards:
            if 'review-pseudo' not in card:
                continue

            author_match = re.search(r'<span class="review-pseudo">(.*?)</span>', card)
            date_match = re.search(r'</span>\s*(il y a [^<]+)</div>', card)
            body_match = re.search(r'<div class="review-body">.*?<p>(.*?)</p>', card, flags=re.S)

            score_matches = re.findall(r'<span class="score-ind__title">(.*?)</span><span class="score-ind__value">(.*?)</span>', card)
            score_details = {strip_tags(name): strip_tags(value) for name, value in score_matches}

            score_values = []
            for _, raw_value in score_matches:
                numeric_value_match = re.search(r'([0-9]+(?:[\.,][0-9]+)?)', raw_value)
                if numeric_value_match:
                    score_values.append(float(numeric_value_match.group(1).replace(",", ".")))

            review_text = strip_tags(body_match.group(1)) if body_match else ""
            if not review_text:
                review_text = " ".join(
                    value for value in score_details.values() if value
                )

            if not review_text:
                continue

            records.append({
                "source": "villesavivre.fr",
                "site": "villesavivre",
                "city_name": city_name,
                "city_code": city_code,
                "source_url": city_url,
                "review_date": strip_tags(date_match.group(1)) if date_match else None,
                "author": strip_tags(author_match.group(1)) if author_match else None,
                "rating": round(sum(score_values) / len(score_values), 2) if score_values else None,
                "review_text": review_text,
                "score_details": score_details,
            })

    return records


def ingest_ville_ideale_reviews():
    records = scrape_ville_ideale_reviews()
    write_jsonl_to_minio(records, "reviews/ville_ideale", "ville_ideale_reviews.jsonl")


def ingest_villesavivre_reviews():
    records = scrape_villesavivre_reviews()
    write_jsonl_to_minio(records, "reviews/villesavivre", "villesavivre_reviews.jsonl")

# Définition du Workflow (DAG)
with DAG(
    '1_ingestion_raw_data',
    default_args=default_args,
    description='Téléchargement asynchrone des sources publiques vers MinIO',
    schedule_interval=timedelta(days=30), 
    start_date=datetime(2026, 4, 3),
    catchup=False,
    tags=['casapedia', 'ingestion', 'minio', 'raw'],
) as dag:

    # Tâche 1 : Ingestion des Communes (Référentiel de base)
    ingest_communes = PythonOperator(
        task_id='download_communes',
        python_callable=download_file,
        op_kwargs={
            'url': 'https://www.data.gouv.fr/fr/datasets/r/dbe8a621-a9c4-4bc3-9cae-be1699c5ff25',
            'dest_folder': 'communes',
            'filename': 'communes.csv'
        }
    )

    # Tâche 2 : Ingestion INSEE (Base zippée très lourde)
    ingest_insee = PythonOperator(
        task_id='download_insee',
        python_callable=download_file,
        op_kwargs={
            'url': 'https://www.insee.fr/fr/statistiques/fichier/6683035/ensemble.zip',
            'dest_folder': 'insee',
            'filename': 'demographie_insee.zip'
        }
    )

    # Tâche 3 : Ingestion DVF (Base consolidée Data.gouv pour toute la France)
    ingest_dvf = PythonOperator(
        task_id='download_dvf',
        python_callable=download_file,
        op_kwargs={
            'url': 'https://files.data.gouv.fr/geo-dvf/latest/csv/2023/full.csv.gz', 
            'dest_folder': 'dvf',
            'filename': 'transactions_dvf_brut.csv.gz'
        }
    )

    # Tâche 4 : Ingestion DPE (Diagnostics de performance énergétique - Échantillon ADEME)
    ingest_dpe = PythonOperator(
        task_id='download_dpe',
        python_callable=download_file,
        op_kwargs={
            'url': 'https://data.ademe.fr/data-fair/api/v1/datasets/dpe03existant/lines?size=10000&format=csv',
            'dest_folder': 'dpe',
            'filename': 'dpe_logements_brut.csv'
        }
    )

    # Tâche 5 : Ingestion des avis Ville-Idéale
    ingest_ville_ideale_reviews_task = PythonOperator(
        task_id='download_ville_ideale_reviews',
        python_callable=ingest_ville_ideale_reviews,
    )

    # Tâche 6 : Ingestion des avis Villes à Vivre
    ingest_villesavivre_reviews_task = PythonOperator(
        task_id='download_villesavivre_reviews',
        python_callable=ingest_villesavivre_reviews,
    )

    # Les 6 téléchargements en PARALLÈLE, pas l'un après l'autre.
    [ingest_communes, ingest_insee, ingest_dvf, ingest_dpe, ingest_ville_ideale_reviews_task, ingest_villesavivre_reviews_task]