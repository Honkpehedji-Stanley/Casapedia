"""
Analyse de sentiment et thèmes sur les avis habitants (collection reviews_clean).

Lexique : FEEL (French Expanded Emotion Lexicon, Abdaoui et al., LRE 2016).
Source   : http://advanse.lirmm.fr/feel.php
Usage    : académique/recherche, traduit du NRC-EmoLex (Mohammad & Turney 2013).
           Pas de licence CC formelle ; usage conforme aux conditions NRC-EmoLex
           (recherche, enseignement, non commercial). Voir spark_jobs/lexicons/README.md.
Téléchargé le 2026-06-26.

Script Python pur (pas de SparkSession — volume trop faible pour justifier Spark).

Résultat → 3 collections MongoDB (vidées avant insertion) :
  nlp_sentiments         : un doc par avis (score, label, rating original pour comparaison)
  nlp_themes             : agrégat par thème (mentions totales, villes concernées)
  nlp_theme_sentiments   : croisement thème × sentiment (pour graphique en barres empilées)
"""

import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from storage.minio_utils import ensure_bucket, get_minio_client, get_minio_settings

LEXICON_PATH = SCRIPT_DIR / "lexicons" / "feel_fr.csv"

# Mots déclenchant une inversion de polarité (fenêtre de 2 tokens avant le mot cible).
# "plus" exclu volontairement : trop ambigu hors contexte "ne...plus".
NEGATION_WORDS = {
    "ne", "pas", "jamais", "aucun", "aucune", "ni", "sans", "nul", "nulle",
}

# Mots-clés par thème urbain/immobilier. Formes accentuées attendues dans clean_text.
THEME_KEYWORDS = {
    "securite": {
        "sécurité", "sûreté", "danger", "dangereux", "dangereuse", "violence",
        "délinquance", "crime", "vol", "agression", "agressif", "tranquille",
        "tranquillité", "insécurité", "sécurisé", "policier", "police",
        "cambriolage", "vandalisme", "malveillance",
    },
    "transport": {
        "transport", "bus", "métro", "tramway", "train", "rer", "gare", "tgv",
        "vélo", "voiture", "parking", "circulation", "embouteillage", "autoroute",
        "route", "trajet", "navette", "mobilité", "desserte", "station",
    },
    "commerces": {
        "commerce", "commerces", "magasin", "supermarché", "boulangerie",
        "pharmacie", "restaurant", "bar", "café", "boutique", "marché",
        "épicerie", "alimentation", "enseigne", "shopping",
    },
    "environnement": {
        "parc", "jardin", "vert", "verte", "nature", "arbre", "forêt",
        "verdure", "rivière", "lac", "campagne", "air", "propre", "propreté",
        "pollution", "verdoyant", "paysage", "environnement", "fleuve",
    },
    "bruit": {
        "bruit", "bruyant", "bruyante", "silencieux", "silencieuse", "silence",
        "nuisance", "sonore", "klaxon", "calme",
    },
    "prix": {
        "prix", "cher", "chère", "coûteux", "coûteuse", "abordable", "loyer",
        "immobilier", "coût", "budget", "dépense", "taxe", "impôt", "charge",
        "tarif", "investissement", "achat", "vente",
    },
    "voisinage": {
        "voisin", "voisins", "voisinage", "quartier", "communauté", "convivial",
        "ambiance", "atmosphère", "accueil", "chaleureux", "sympathique",
        "sociable", "solidaire", "animé", "animée", "habitant", "habitants",
    },
}


def _load_feel_lexicon(path=LEXICON_PATH):
    """Charge FEEL.csv. Retourne dict {phrase_lowercase → +1 ou −1}."""
    lexicon = {}
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            word = row["word"].strip().lower()
            polarity = row["polarity"].strip().lower()
            if word and polarity in {"positive", "negative"}:
                lexicon[word] = 1 if polarity == "positive" else -1
    return lexicon


def _tokenize(text):
    """Extrait les tokens d'un clean_text (lettres + accents communs, min 1 char)."""
    return re.findall(r"[a-zàâäçéèêëîïôöùûüÿñæœ]+", (text or "").lower())


def _score_sentiment(tokens, lexicon, max_gram=3):
    """
    Score de sentiment sur une liste de tokens.

    Algorithme :
    - Matching n-gram (jusqu'à max_gram tokens joints par espace) contre le lexique FEEL.
      Priorité au n-gram le plus long pour éviter les recouvrements.
    - Règle de négation : si un mot de NEGATION_WORDS précède le terme dans une fenêtre
      de 2 tokens, son score est inversé.
    - Normalisation : score_brut / nb_mots_reconnus → score dans [-1, 1].

    Retourne (score_normalisé, n_mots_reconnus).
    """
    raw_score = 0
    n_found = 0
    i = 0
    while i < len(tokens):
        matched = False
        for gram_len in range(min(max_gram, len(tokens) - i), 0, -1):
            phrase = " ".join(tokens[i:i + gram_len])
            if phrase in lexicon:
                word_score = lexicon[phrase]
                window = tokens[max(0, i - 2):i]
                if any(w in NEGATION_WORDS for w in window):
                    word_score = -word_score
                raw_score += word_score
                n_found += 1
                i += gram_len
                matched = True
                break
        if not matched:
            i += 1

    normalized = raw_score / n_found if n_found > 0 else 0.0
    return normalized, n_found


def _label_from_score(score):
    if score > 0.1:
        return "Positif"
    if score < -0.1:
        return "Négatif"
    return "Neutre"


def _detect_themes(token_set):
    """Retourne les thèmes dont au moins un mot-clé est présent dans le texte."""
    return [
        theme for theme, keywords in THEME_KEYWORDS.items()
        if token_set & keywords
    ]


def _read_reviews_from_minio():
    """Lit processed/reviews/clean_reviews.jsonl depuis MinIO via boto3."""
    client = get_minio_client()
    settings = get_minio_settings()
    bucket = ensure_bucket(client, settings["bucket"])
    response = client.get_object(Bucket=bucket, Key="processed/reviews/clean_reviews.jsonl")
    body_bytes = response["Body"].read()
    response["Body"].close()
    return [json.loads(line) for line in body_bytes.decode("utf-8").splitlines() if line.strip()]


def _get_mongo_client():
    from pymongo import MongoClient
    host = os.getenv("MONGO_HOST", "mongodb")
    port = os.getenv("MONGO_PORT", "27017")
    user = os.getenv("MONGO_USER", "root")
    password = os.getenv("MONGO_PASSWORD", "examplepassword")
    return MongoClient(f"mongodb://{user}:{password}@{host}:{port}/?authSource=admin")


def run():
    """Point d'entrée principal — appelé par le PythonOperator Airflow."""
    lexicon = _load_feel_lexicon()
    print(f"[FEEL] Lexique chargé : {len(lexicon)} entrées")

    records = _read_reviews_from_minio()
    n_total = len(records)
    print(f"[NLP] Avis chargés depuis MinIO : {n_total}")

    if n_total == 0:
        print("[NLP] Aucun avis à traiter, sortie anticipée.")
        return

    sentiment_docs = []
    total_tokens = 0
    total_found = 0
    label_counts = Counter()
    theme_data = defaultdict(lambda: {"count": 0, "cities": set()})
    theme_sentiment = defaultdict(Counter)

    for idx, record in enumerate(records):
        clean_text = record.get("clean_text") or ""
        tokens = _tokenize(clean_text)
        # Compte uniquement les tokens de 2+ chars pour la statistique de couverture
        total_tokens += sum(1 for t in tokens if len(t) >= 2)

        score, n_found = _score_sentiment(tokens, lexicon)
        total_found += n_found
        label = _label_from_score(score)
        label_counts[label] += 1

        city = record.get("city_name") or ""
        sentiment_docs.append({
            "review_index": idx,
            "city_name": city,
            "commune_id": record.get("commune_id") or "",
            "sentiment_score": round(score, 4),
            "sentiment_label": label,
            "rating": record.get("rating"),
        })

        token_set = set(tokens)
        for theme in _detect_themes(token_set):
            theme_data[theme]["count"] += 1
            if city:
                theme_data[theme]["cities"].add(city)
            theme_sentiment[theme][label] += 1

    # --- Statistiques de couverture (utiles pour la soutenance) ---
    coverage = total_found / max(total_tokens, 1) * 100
    print(f"[NLP] Tokens significatifs (≥2 chars) : {total_tokens}")
    print(f"[NLP] Mots reconnus dans FEEL : {total_found} ({coverage:.1f}% de couverture lexicale)")
    print(f"[NLP] Distribution Positif/Neutre/Négatif : {dict(label_counts)}")

    # --- Agrégats thèmes ---
    theme_docs = [
        {"theme": t, "total_mentions": d["count"], "cities": sorted(d["cities"])}
        for t, d in sorted(theme_data.items())
    ]
    theme_sentiment_docs = [
        {"theme": t, "sentiment_label": lbl, "count": cnt}
        for t, counts in sorted(theme_sentiment.items())
        for lbl, cnt in counts.items()
    ]

    # --- Écriture MongoDB (delete_many + insert_many, comme load_reviews_to_mongo) ---
    mongo_db_name = os.getenv("MONGO_DB", "casapedia")
    client = _get_mongo_client()
    try:
        db = client[mongo_db_name]
        for coll_name, docs in [
            ("nlp_sentiments", sentiment_docs),
            ("nlp_themes", theme_docs),
            ("nlp_theme_sentiments", theme_sentiment_docs),
        ]:
            coll = db[coll_name]
            coll.delete_many({})
            if docs:
                result = coll.insert_many(docs)
                print(f"[MongoDB] {len(result.inserted_ids)} documents insérés dans {coll_name}")
            else:
                print(f"[MongoDB] Aucun document pour {coll_name}")
    finally:
        client.close()


if __name__ == "__main__":
    run()
