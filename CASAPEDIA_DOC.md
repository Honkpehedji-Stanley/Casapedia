# CASAPEDIA_DOC

# 🏠 Casapedia - Documentation Architecture Big Data, Données & Visualisation (V2)

## 1) Vision du projet

**Casapedia** est une plateforme d’exploration Big Data du marché immobilier français. Elle centralise des bases de données massives (Gouvernementales, Notariales, Web Scraping textes) via un traitement distribué (Cluster Spark), et les restitue via une interface interactive pointue.

### Finalité produit

- Donner une vue fiable et prédictive des dynamiques immobilières.
- Traiter d'immenses volumes de données (Big Data) nécessitant des outils à l'échelle.
- Préparer les avis textuels pour une exploitation métier fiable, sans surcharger la phase de traitement.
- Créer des modèles de prédiction sur l'évolution du marché.

## 2) Architecture technique (Le Pipeline Big Data)

Afin d'absorber la charge des Giga-octets d'informations (transactions, recensements, opinions textuelles), Casapedia adopte un **pipeline Big Data** orchestré par **Apache Airflow**.

- Ingestion : collecte des sources publiques et des avis dans MinIO.
- Curation : nettoyage et standardisation Spark vers `processed`.
- Publication : chargement des données tabulaires dans PostgreSQL et des avis nettoyés dans MongoDB.
- Exploitation : jobs ML et analyses qui consomment uniquement la couche curée.

## 4.2 Relations (ERD)

La couche relationnelle finale s'organise autour de `communes`, puis des tables source-specific `transactions`, `demographics_population`, `demographics_density`, `demographics_chomage`, `revenue_disponible`, `dpe`, `bpe_equipment`, `bpe_rollups` et `bpe_evolution`.

**Architecture NoSQL Associée (MongoDB)**
- **Collection `reviews_clean`** : avis nettoyés et normalisés, chargés depuis `processed/reviews/clean_reviews.jsonl`.
- Les collections de sentiment et de thèmes automatiques restent désactivées.

## 4.3 Vues analytiques Machine Learning (Spark)

- `model_predict_m2` : Modèle Spark MLlib de régression sur le prix au m².

---

## 5) Ce qu’on veut afficher (fonctionnel)

## 5.1 KPI prioritaires

- 💶 Prix médian de vente
- 📐 Prix médian au m²
- 🔢 Nombre de transactions
- 🏠 Répartition type de biens (appartement/maison/autres)
- 👥 Population
- 💼 Revenu médian
- 🌱 Répartition des classes DPE (A à G)
- 🏫 Indicateurs d’infrastructure par territoire

## 5.2 Analyses attendues

- **Prédictions avec IA :** Estimer l'évolution à N+5 ans du m² basé sur le DPE et la démographie locale (Spark MLlib).
- **Analyse des avis :** conservation des avis nettoyés et de la note pour un affichage simple des retours récents.
- **DataViz Descriptive :** Croisement du DVF avec les revenus pour calculer l'indice d'accessibilité au logement.

## 5.3 Niveaux de lecture

- National
- Régional
- Départemental
- Communal

---

## 6) Type d’informations sur l’interface

## 6.1 Composants visuels

- **Carte choroplèthe** : intensité d’un indicateur par zone.
- **Carte bulles** : volumes (transactions, équipements, etc.).
- **Heatmap** : concentration des valeurs.
- **Courbes** : tendances temporelles.
- **Barres** : comparaisons inter-zones.
- **Histogrammes** : distribution prix/surface.
- **Tableaux** : détail filtrable/exportable.

## 6.2 Filtres globaux

- Période
- Zone (région/département/commune)
- Type de bien
- Tranche de prix
- Tranche de surface
- Classe énergétique

## 6.3 Informations contextuelles

- Source du KPI
- Date de dernière mise à jour
- Méthodologie de calcul (info-bulle/section dédiée)

---

## 7) Comment ce sera organisé (produit + navigation)

Cette partie reste une future étape produit. Elle n'est pas encore implémentée.

---

## 8) Organisation technique du repository (Nouvelle Ère Big Data & Airflow)

```
Casapedia/
├── dags/                     # Dossier central d'Apache Airflow (Les pipelines orchestrés)
│   ├── dag_ingestion.py      # Tâches asynchrones de scraping vers MinIO
│   ├── dag_processing.py     # Tâches déclenchant les scripts PySpark
│   ├── dag_load_databases.py # Chargement des données curées vers PostgreSQL et MongoDB
│   └── utils/                # Fonctions partagées pour les Sensors et Operators
├── storage/                  # Helpers partagés pour MinIO/S3A
├── MinIO                     # Stockage objet du pipeline (bucket `casapedia-datalake`)
├── docker-compose.yml        # Instanciation de l'infrastructure complète (Postgres, Mongo, Spark, Airflow)
├── database/
│   ├── db_manager.py         # Connecteur pour PostgreSQL
│   └── mongo_manager.py      # Connecteur pour la base de données NoSQL
├── spark_jobs/               # Le Cœur du Traitement Haute Performance
│   ├── clean_tabulaires.py   # Script PySpark pour le nettoyage tabulaire et QA
│   ├── clean_reviews.py      # Script PySpark pour le nettoyage des avis
│   └── ML_predictions.py     # Spark MLlib pour prédiction du prix au m²
├── frontend_app/             # Réservé à une phase future
├── logs/                     # Fichiers de logs générés par Airflow et Spark
├── README.md
└── requirements.txt
```

---

## 9) Gouvernance des données et qualité

### Contrôles déjà présents

- Clés primaires/étrangères.
- Contraintes de domaine (`classe_energetique` A..G).
- Index pour performance.
- Historique des exécutions scraping.

### Contrôles à renforcer

- Détection d’outliers (prix/m² aberrants).
- Standardisation d’adresses plus robuste.
- Validation de fraîcheur des sources.
- Gestion explicite des données manquantes.

## 9.1 Ordre d'exécution cible

L'objectif n'est pas de sauter directement vers les bases de données finales. Le pipeline doit respecter cet enchaînement :

1. **Nettoyage, standardisation et curation** : `clean_tabulaires` transforme les sources brutes en jeux de données cohérents, typés et exploitables.
2. **Enrichissements analytiques** : le job `ML_predictions.py` exploite les données déjà curées pour produire des sorties prédictives ; les avis sont seulement normalisés par `clean_reviews.py`.
3. **Publication en bases** : les jeux de données traités sont ensuite chargés dans PostgreSQL pour le tabulaire et dans MongoDB pour le textuel.

### Statut actuel attendu

- `clean_tabulaires` doit réellement faire le nettoyage métier, pas seulement déplacer les fichiers.
- `clean_reviews` reste le seul traitement textuel actif pour l'instant.
- Le chargement BDD reste l'étape finale, une fois les données traitées validées.

### 9.2 Plan d'enregistrement des données `processed`

La couche `processed` est la source de vérité pour les chargements finaux. Le mapping cible est le suivant :

- `processed/communes/communes.jsonl` -> PostgreSQL `communes`
- `processed/transactions/transactions.jsonl` -> PostgreSQL `transactions`
- `processed/demographics/demographics.jsonl` -> PostgreSQL `demographics_population`
- `processed/demographics/density.jsonl` -> PostgreSQL `demographics_density`
- `processed/demographics/chomage_commune.jsonl` -> PostgreSQL `demographics_chomage`
- `processed/demographics/revenu_disponible.jsonl` -> PostgreSQL `revenue_disponible`
- `processed/dpe/dpe.jsonl` -> PostgreSQL `dpe`
- `processed/infrastructure/bpe_equipment.jsonl` -> PostgreSQL `bpe_equipment`
- `processed/infrastructure/bpe_rollups.jsonl` -> PostgreSQL `bpe_rollups`
- `processed/infrastructure/bpe_evolution.jsonl` -> PostgreSQL `bpe_evolution`
- `processed/reviews/clean_reviews.jsonl` -> MongoDB `reviews_clean`
- `processed/ml_predictions/` -> reste dans MinIO, car ce sont des artefacts analytiques et ML

Le DAG Airflow `3_load_databases` orchestre ce chargement après la curation Spark. Il recrée le schéma cible si besoin, vide les tables de publication, puis recharge les données curées depuis MinIO.

---

## 10) Recommandations opérationnelles (Stratégie d'évolution)

1. **Stabiliser le nettoyage/curation** : faire de `clean_tabulaires` une vraie étape métier avec standardisation, typage, fillna contrôlé et sorties propres dans MinIO.
2. **Conserver les traitements utiles** : garder `clean_reviews.py` pour les avis nettoyés et `ML_predictions.py` pour la prédiction sur les données déjà curées.
3. **Conserver le découpage Airflow/Spark** : Airflow orchestre, Spark traite, puis les sorties validées sont publiées dans MinIO.
4. **Publier en bases de données** : charger les données tabulaires dans PostgreSQL et les données textuelles nettoyées dans MongoDB si besoin plus tard.
5. **Livraison UX** : à traiter dans une phase ultérieure.

---

## 11) Mini glossaire

- **MinIO / Bucket RAW** : Espace de stockage recevant les données brutes dans leur format initial sans modification.
- **Cluster Spark** : Réseau de machines qui travaillent ensemble pour calculer et filtrer des millions de données très vite.
- **NLP (Traitement du Langage Naturel)** : préparation et nettoyage de texte pour exploitation ultérieure.
- **Airflow / DAG** : Outil visuel qui construit des graphes d'ordonnancement complexes (ex: d'abord le code X, s'il réussit tourne le code Y).
- **NoSQL** : Base de données (ex MongoDB) qui n'est pas limitée par un système de tableaux stricts.

---

## 12) Conclusion 🎯

Casapedia est conçu pour encaisser la Big Data avec une scalabilité forte. En scindant la récupération (Data Lake), la structuration (Cluster distribué PySpark) et le stockage selon les besoins (PostgreSQL "Tabulaire" vs MongoDB "Textuel"), la plateforme délivrera des capacités d'Analyse Descriptive (Cartes), Prédictives et Textuelles hautement optimisées rendant un vrai service au milieu de l'immobilier.