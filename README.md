# Casapedia

## Description

Casapedia est une plateforme d'analyse du marché immobilier français qui fournit des informations détaillées et des insights sur l'évolution du secteur à différents niveaux géographiques (national, régional, départemental et municipal).

Le projet collecte et agrège des données provenant de multiples sources pour offrir une vision complète du paysage immobilier, incluant les tendances de prix, les variations régionales, et les facteurs démographiques et économiques qui influencent le marché.

## Objectifs

L'application permet aux utilisateurs de :

- Explorer les tendances de prix immobiliers à travers différentes échelles géographiques
- Analyser les indicateurs économiques, démographiques et environnementaux liés au logement
- Visualiser les données sur des cartes interactives (choroplèthes, heatmaps, bulles)
- Consulter des analyses textuelles sur la qualité de vie dans les villes
- Accéder à des statistiques actualisées et des prévisions de marché

## Fonctionnalités principales

**Collecte de données**
- Agrégation de données immobilières provenant de sources publiques et privées
- Enrichissement avec des métriques économiques, éducatives, environnementales et infrastructurelles
- Mise à jour régulière des informations

**Analyse multi-niveaux**
- Analyses statistiques à l'échelle nationale, régionale, départementale et communale
- Comparaisons temporelles et géographiques
- Calcul d'indicateurs personnalisés

**Visualisations interactives**
- Tableaux statistiques détaillés
- Cartes géographiques interactives avec plusieurs modes de représentation
- Graphiques dynamiques et personnalisables
- Nuages de mots pour l'analyse de sentiment

**Traitement du langage naturel**
- Analyse de sentiment sur les commentaires et descriptions de villes
- Extraction d'informations qualitatives sur la sécurité, le cadre de vie et les services

## Cas d'usage

Casapedia s'adresse à plusieurs profils d'utilisateurs :

- **Particuliers** : recherche de logement, estimation de biens, connaissance du marché local
- **Professionnels de l'immobilier** : veille marché, aide à la décision, prospection
- **Investisseurs** : identification d'opportunités, analyse de rentabilité potentielle
- **Analystes et chercheurs** : études de marché, recherches académiques, rapports statistiques
- **Collectivités** : planification urbaine, politiques de logement, études territoriales

## Périmètre

Le projet couvre l'ensemble du territoire français métropolitain et propose une granularité d'analyse allant du niveau national jusqu'aux communes individuelles, avec la possibilité d'étendre la couverture à d'autres pays européens.

## Architecture technique

### Stack technologique

**Base de données**
- PostgreSQL : données structurées (transactions, démographie, communes)
- MongoDB : données non-structurées (optionnel, pour analyses textuelles)

**Backend & Orchestration**
- Apache Airflow (Orchestration des DAGs)
- Apache Spark / PySpark (Traitement distribué)
- Python 3.8+
- Base de données : psycopg2, pymongo

**Frontend - Visualisation** (à venir)
- Streamlit : application interactive
- Plotly : graphiques interactifs
- Folium/Pydeck : cartes géographiques
- WordCloud : nuages de mots

**Machine Learning** (à venir)
- Spark MLlib : prédictions et régressions distribuées
- Spark NLP : traitement du langage naturel distribué
- Scikit-learn : analyses statistiques standards

### Structure du projet

```text
Casapedia/
├── dags/                    # Graphes Airflow (Pipelines d'ingestion/processing)
│   ├── dag_ingestion.py     # Extraction asynchrone des APIs vers Datalake
│   └── ...
├── datalake/                # Lac de données local
│   ├── raw/                 # Données brutes téléchargées (CSV, ZIP, JSON)
│   └── processed/           # Données nettoyées (Parquet/Delta) par Spark
├── database/                # Connecteurs aux bases
│   ├── pg_manager.py        # Gestionnaire PostgreSQL
│   └── mongo_manager.py     # Gestionnaire MongoDB
├── spark_jobs/              # Scripts de transformation Big Data
│   └── clean_tabulaires.py  # (en construction)
├── frontend_app/            # Interface Streamlit (à venir)
├── docker-compose.yml       # Infrastructure (Airflow, Spark, Postgres, Mongo)
├── .env                     # Configuration environnement
└── requirements.txt         # Dépendances Python
```

### Schéma de la base de données

**Tables principales**

```sql
communes
├── code_insee (PK)
├── nom
├── dept
├── region
├── latitude
└── longitude

transactions
├── id (PK)
├── commune_id (FK → communes)
├── date_transaction
├── prix
├── surface
├── prix_m2
├── type_bien
└── nombre_pieces

demographics
├── id (PK)
├── commune_id (FK → communes)
├── annee
├── population
├── revenu_median
└── taux_chomage

dpe
├── id (PK)
├── commune_id (FK → communes)
├── classe_energetique (A-G)
├── emissions_co2
├── consommation_energie
└── annee_construction

infrastructure
├── id (PK)
├── commune_id (FK → communes)
├── type_equipement
└── nombre
```

**Vues analytiques**
- `v_prix_median_communes` : prix médians par commune
- `v_dpe_stats_communes` : statistiques énergétiques par commune

## Installation & Démarrage (Docker)

Le projet tourne entièrement via Docker pour garantir la scalabilité (Airflow + Spark + BDDs).

**1. Cloner le dépôt**
```bash
git clone https://github.com/Honkpehedji-Stanley/Casapedia.git
cd Casapedia
```

**2. Lancer l'infrastructure Big Data**
```bash
docker-compose up -d
```
Cela démarrera :
- **Airflow Webserver & Scheduler** (Port 8080)
- **PostgreSQL** (Port 5432)
- **MongoDB** (Port 27017)
- **Spark Master & Worker** (Port 8081 / 8082)

**3. Lancer les DAGs (Collecte)**
Toute la collecte est automatisée en approche ELT (Extract, Load, Transform). Allez sur `http://localhost:8080` (identifiants par défaut selon *docker-compose*), activez le DAG `1_ingestion_raw_data` et lancez-le. Il téléchargera massivement les données dans `datalake/raw/`.

**4. Documentation détaillée**
Pour comprendre l'architecture Big Data complète, veuillez vous référer au fichier détaillé `CASAPEDIA_DOC.md`.


## Sources de données

Toutes les données proviennent de sources publiques françaises :

- **Communes** : data.gouv.fr - Code Officiel Géographique INSEE
- **DVF** : data.gouv.fr - Demandes de Valeurs Foncières
- **INSEE** : insee.fr - Population et revenus
- **DPE** : ADEME - Base des diagnostics de performance énergétique

## Licence

Ce projet est sous licence MIT.

## Contributeurs

- Honkpehedji Stanley ([@Honkpehedji-Stanley](https://github.com/Honkpehedji-Stanley))
