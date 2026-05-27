import html
import json
import re
import os
import sys
import time
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import tempfile

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

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

REVIEWS_CITY_LIMIT = int(os.getenv('CASAPEDIA_REVIEWS_CITY_LIMIT', '250'))
VILLE_IDEALE_SEED_PAGES = [
    'https://www.ville-ideale.fr/',
    'https://www.ville-ideale.fr/villespardepts.php',
    'https://www.ville-ideale.fr/classements.php',
]
VILLES_A_VIVRE_SEED_PAGES = [
    'https://www.villesavivre.fr/',
]
INSEE_REVENUE_URL = os.getenv(
    'CASAPEDIA_INSEE_REVENUE_URL',
    'https://api.insee.fr/melodi/file/DS_ERFS_MENAGE/DS_ERFS_MENAGE_2023_CSV_FR',
)
INSEE_UNEMPLOYMENT_URL = os.getenv(
    'CASAPEDIA_INSEE_UNEMPLOYMENT_URL',
    'https://api.insee.fr/melodi/file/DS_RP_EMPLOI_LR_COMP/DS_RP_EMPLOI_LR_COMP_2022_CSV_FR',
)
INSEE_DENSITY_URL = os.getenv(
    'CASAPEDIA_INSEE_DENSITY_URL',
    'https://static.data.gouv.fr/resources/densite-de-population-1/20260414-112014/densite-population-com.csv',
)
BPE_2024_URL = os.getenv(
    'CASAPEDIA_BPE_2024_URL',
    'https://www.insee.fr/fr/statistiques/fichier/8217527/DS_BPE_CSV_FR.zip',
)
BPE_EVOLUTION_URL = os.getenv(
    'CASAPEDIA_BPE_EVOLUTION_URL',
    'https://www.insee.fr/fr/statistiques/fichier/8217532/DS_BPE_EVOLUTION_CSV_FR.zip',
)
DPE_DATASET_ID = os.getenv('CASAPEDIA_DPE_DATASET_ID', 'meg-83tjwtg8dyz4vv7h1dqe')
DPE_EXPORT_URL = os.getenv(
    'CASAPEDIA_DPE_EXPORT_URL',
    f'https://data.ademe.fr/data-fair/api/v1/datasets/{DPE_DATASET_ID}/lines?size=10000&format=csv',
)
DVF_BASE_URL = os.getenv(
    'CASAPEDIA_DVF_BASE_URL',
    'https://files.data.gouv.fr/geo-dvf/latest/csv',
)
DVF_YEARS = [
    int(year.strip())
    for year in os.getenv('CASAPEDIA_DVF_YEARS', '2021,2022,2023,2024,2025').split(',')
    if year.strip()
]


def get_dpe_total_pages():
    try:
        response = requests.get(f'https://data.ademe.fr/data-fair/api/v1/datasets/{DPE_DATASET_ID}/lines?size=0', timeout=(10, 30))
        response.raise_for_status()
        total_rows = int(response.json().get('total', 0))
        if total_rows > 0:
            return (total_rows + 9999) // 10000
    except Exception as error:
        print(f"Impossible de récupérer le nombre total de pages DPE: {error}")

    return int(os.getenv('CASAPEDIA_DPE_ESTIMATED_TOTAL_PAGES', '1500'))


def dpe_next_url_from_response(response):
    next_link = response.links.get('next', {}).get('url')
    if not next_link:
        return None
    return append_query_param(next_link, 'header', 'false')


def ingest_dpe():
    settings = get_minio_settings()
    client = get_minio_client()
    bucket = ensure_bucket(client, settings["bucket"])

    state_key = 'raw/dpe/_ingestion_state.json'
    page_prefix = 'raw/dpe/dpe_logements_brut_page_'
    existing_pages = [
        key for key in [*list_dpe_page_objects(client, bucket, 'raw/dpe/')]
        if key.startswith(page_prefix) and key.endswith('.csv')
    ]

    state = read_minio_json(client, bucket, state_key) or {
        'next_url': DPE_EXPORT_URL,
        'next_page_index': 1,
    }

    if existing_pages and state.get('next_page_index', 1) == 1:
        state['next_page_index'] = len(existing_pages) + 1

    download_dpe_resumable(client, bucket, state, state_key, page_prefix)

def download_file(url, dest_folder, filename, timeout=None, chunk_size=None):
    """
    Fonction ELT : Téléchargement 'Dumb'.
    """
    # Résilience: session avec retry + backoff
    session = requests.Session()
    retries = Retry(total=5, backoff_factor=1, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=frozenset(['GET', 'POST']))
    adapter = HTTPAdapter(max_retries=retries)
    session.mount('https://', adapter)
    session.mount('http://', adapter)

    settings = get_minio_settings()
    client = get_minio_client()
    bucket = ensure_bucket(client, settings["bucket"])
    object_key = f"raw/{dest_folder}/{filename}"

    print(f"Début du téléchargement : {url}")

    request_timeout = timeout or (10, int(os.getenv('CASAPEDIA_DOWNLOAD_READ_TIMEOUT', '120')))
    request_chunk_size = chunk_size or int(os.getenv('CASAPEDIA_DOWNLOAD_CHUNK_SIZE', str(256 * 1024)))

    attempt = 0
    max_attempts = 5
    while attempt < max_attempts:
        attempt += 1
        try:
            with session.get(url, stream=True, timeout=request_timeout) as r:
                r.raise_for_status()
                with tempfile.NamedTemporaryFile(suffix=f"-{filename}") as temp_file:
                    for chunk in r.iter_content(chunk_size=request_chunk_size):
                        if chunk:
                            temp_file.write(chunk)
                    temp_file.flush()
                    temp_file.seek(0)
                    upload_fileobj(client, bucket, object_key, temp_file.file, content_type=r.headers.get("Content-Type"))

            print(f"Téléchargement terminé avec succès et sauvegardé sous : s3a://{bucket}/{object_key}")
            return
        except Exception as error:
            print(f"Téléchargement échoué (tentative {attempt}/{max_attempts}): {error}")
            if attempt >= max_attempts:
                raise
            sleep_seconds = 2 ** attempt
            print(f"Attente {sleep_seconds}s avant nouvelle tentative...")
            time.sleep(sleep_seconds)


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


def append_query_param(url, key, value):
    parsed = urlsplit(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query[key] = str(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


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


def collect_city_links(seed_pages, pattern):
    city_links = []
    seen_links = set()

    for seed_page in seed_pages:
        try:
            page_html = fetch_html(seed_page)
        except Exception as error:
            print(f"Page ignorée {seed_page} ({error})")
            continue

        for city_link in extract_city_links(page_html, seed_page, pattern):
            if city_link in seen_links:
                continue
            seen_links.add(city_link)
            city_links.append(city_link)

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
    city_links = collect_city_links(VILLE_IDEALE_SEED_PAGES, r"/[a-z0-9\-]+_[0-9]{5}")
    city_links = city_links[:REVIEWS_CITY_LIMIT]

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
    city_links = collect_city_links(VILLES_A_VIVRE_SEED_PAGES, r"/[a-z0-9\-]+-[0-9]{5}/")
    city_links = city_links[:REVIEWS_CITY_LIMIT]

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


def ingest_insee_revenue():
    download_file(
        INSEE_REVENUE_URL,
        'insee',
        'revenu_disponible_menages_2023.zip',
    )


def ingest_insee_unemployment():
    download_file(
        INSEE_UNEMPLOYMENT_URL,
        'insee',
        'population_active_chomage_2022.zip',
        timeout=(10, int(os.getenv('CASAPEDIA_INSEE_UNEMPLOYMENT_READ_TIMEOUT', '900'))),
        chunk_size=int(os.getenv('CASAPEDIA_INSEE_UNEMPLOYMENT_CHUNK_SIZE', str(128 * 1024))),
    )


def ingest_insee_density():
    download_file(
        INSEE_DENSITY_URL,
        'insee',
        'densite_population_communes.csv',
    )


def ingest_bpe_2024():
    download_file(
        BPE_2024_URL,
        'infrastructure',
        'bpe_2024.zip',
    )


def ingest_bpe_evolution():
    download_file(
        BPE_EVOLUTION_URL,
        'infrastructure',
        'bpe_evolution_2019_2024.zip',
    )


def read_minio_json(client, bucket, object_key):
    try:
        response = client.get_object(Bucket=bucket, Key=object_key)
        try:
            return json.loads(response["Body"].read().decode("utf-8"))
        finally:
            response["Body"].close()
    except Exception:
        return None


def write_minio_json(client, bucket, object_key, payload):
    buffer = BytesIO(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    upload_fileobj(client, bucket, object_key, buffer, content_type="application/json")


def list_dpe_page_objects(client, bucket, prefix):
    paginator = client.get_paginator("list_objects_v2")
    keys = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for entry in page.get("Contents", []):
            key = entry.get("Key")
            if key:
                keys.append(key)
    return sorted(keys)


def download_dpe_resumable(client, bucket, state, state_key, page_prefix):
    session = requests.Session()
    retries = Retry(total=5, backoff_factor=1, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=frozenset(['GET']))
    adapter = HTTPAdapter(max_retries=retries)
    session.mount('https://', adapter)
    session.mount('http://', adapter)

    current_url = state.get('next_url') or DPE_EXPORT_URL
    current_page_index = int(state.get('next_page_index', 1))
    total_downloaded_pages = 0
    per_page_sleep = float(os.getenv('CASAPEDIA_DPE_PAGE_SLEEP', '0'))
    max_attempts_per_page = int(os.getenv('CASAPEDIA_DPE_PAGE_ATTEMPTS', '6'))

    existing_objects = set(list_dpe_page_objects(client, bucket, page_prefix))

    while current_url:
        page_object_key = f"{page_prefix}{current_page_index:05d}.csv"
        if page_object_key in existing_objects:
            print(f"DPE page déjà présente, reprise: {page_object_key}")
            response = None
            try:
                response = session.get(current_url, stream=True, timeout=(10, 60), headers={"Accept-Encoding": "gzip"})
                response.raise_for_status()
                current_url = dpe_next_url_from_response(response)
            finally:
                if response is not None:
                    response.close()

            current_page_index += 1
            state['next_page_index'] = current_page_index
            state['next_url'] = current_url
            write_minio_json(client, bucket, state_key, state)
            continue

        for attempt in range(1, max_attempts_per_page + 1):
            response = None
            try:
                print(f"Début du téléchargement DPE: {current_url}")
                response = session.get(current_url, stream=True, timeout=(10, 300), headers={"Accept-Encoding": "gzip"})
                response.raise_for_status()

                buffer = BytesIO()
                page_line_count = 0
                for raw_line in response.iter_lines(chunk_size=64 * 1024, decode_unicode=False):
                    if raw_line is None:
                        continue
                    buffer.write(raw_line)
                    buffer.write(b"\n")
                    page_line_count += 1

                if page_line_count == 0:
                    current_url = None
                    break

                buffer.seek(0)
                upload_fileobj(client, bucket, page_object_key, buffer, content_type='text/csv')

                total_downloaded_pages += 1
                current_page_index += 1
                state['next_page_index'] = current_page_index
                state['next_url'] = dpe_next_url_from_response(response)
                write_minio_json(client, bucket, state_key, state)

                existing_objects.add(page_object_key)
                current_url = state['next_url']
                time.sleep(per_page_sleep)
                break
            except Exception as error:
                print(f"Erreur téléchargement page DPE (tentative {attempt}/{max_attempts_per_page}): {error}")
                if attempt >= max_attempts_per_page:
                    raise
                time.sleep(min(30, 2 ** attempt))
            finally:
                if response is not None:
                    response.close()

    print(f"DPE - pages téléchargées/reprises: {total_downloaded_pages}")
    print(f"DPE écrit dans : s3a://{bucket}/{page_prefix}*")

def ingest_dvf():
    downloaded_years = []
    skipped_years = []

    for year in DVF_YEARS:
        url = f"{DVF_BASE_URL}/{year}/full.csv.gz"
        filename = f"transactions_dvf_{year}.csv.gz"
        try:
            download_file(url, 'dvf', filename)
            downloaded_years.append(str(year))
        except Exception as error:
            skipped_years.append(str(year))
            print(f"DVF {year} indisponible ou non téléchargeable: {error}")

    if not downloaded_years:
        raise RuntimeError("Aucun millésime DVF n'a pu être téléchargé.")

    print(f"DVF - millésimes téléchargés: {', '.join(downloaded_years)}")
    if skipped_years:
        print(f"DVF - millésimes ignorés: {', '.join(skipped_years)}")

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
    ingest_dvf_task = PythonOperator(
        task_id='download_dvf',
        python_callable=ingest_dvf,
    )

    ingest_dpe_task = PythonOperator(
        task_id='download_dpe',
        python_callable=ingest_dpe,
        execution_timeout=timedelta(hours=4),
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

    ingest_insee_revenue_task = PythonOperator(
        task_id='download_insee_revenue',
        python_callable=ingest_insee_revenue,
    )

    ingest_insee_unemployment_task = PythonOperator(
        task_id='download_insee_unemployment',
        python_callable=ingest_insee_unemployment,
    )

    ingest_insee_density_task = PythonOperator(
        task_id='download_insee_density',
        python_callable=ingest_insee_density,
    )

    ingest_bpe_2024_task = PythonOperator(
        task_id='download_bpe_2024',
        python_callable=ingest_bpe_2024,
    )

    ingest_bpe_evolution_task = PythonOperator(
        task_id='download_bpe_evolution',
        python_callable=ingest_bpe_evolution,
    )

    # Les 6 téléchargements en PARALLÈLE, pas l'un après l'autre.
    [
        ingest_communes,
        ingest_insee,
        ingest_dvf_task,
        ingest_dpe_task,
        ingest_ville_ideale_reviews_task,
        ingest_villesavivre_reviews_task,
        ingest_insee_revenue_task,
        ingest_insee_unemployment_task,
        ingest_insee_density_task,
        ingest_bpe_2024_task,
        ingest_bpe_evolution_task,
    ]