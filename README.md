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

**Backend - Collecte et traitement**
- Python 3.8+
- Scrapers : requests, BeautifulSoup
- Data processing : Pandas, NumPy
- Base de données : psycopg2

**Frontend - Visualisation** (à venir)
- Streamlit : application interactive
- Plotly : graphiques interactifs
- Folium/Pydeck : cartes géographiques
- WordCloud : nuages de mots

**Machine Learning** (à venir)
- Scikit-learn : analyses statistiques
- spaCy : traitement du langage naturel (français)
- TextBlob/NLTK : analyse de sentiment

### Structure du projet

```
Casapedia/
├── data/                    # Données (git-ignored)
│   ├── raw/                 # Données brutes téléchargées
│   ├── processed/           # Données nettoyées
│   └── cache/               # Cache temporaire
│
├── database/                # Gestion base de données
│   ├── init_tables.sql      # Schéma PostgreSQL
│   ├── db_manager.py        # Gestionnaire de connexion
│   └── __init__.py
│
├── scrapers/                # Collecte de données
│   ├── communes_scraper.py  # Référentiel communes
│   ├── dvf_scraper.py       # Transactions immobilières
│   ├── insee_scraper.py     # Données démographiques
│   ├── dpe_scraper.py       # Diagnostics énergétiques
│   └── README.md            # Documentation scrapers
│
├── .env                     # Configuration (git-ignored)
├── .env.example             # Template de configuration
├── requirements.txt         # Dépendances Python
└── README.md
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

## Installation

### Prérequis

- Python 3.8+
- PostgreSQL 12+
- pip ou poetry

### Étapes d'installation

**1. Cloner le dépôt**

```bash
git clone https://github.com/Honkpehedji-Stanley/Casapedia.git
cd Casapedia
```

**2. Créer un environnement virtuel**

```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# ou
venv\Scripts\activate     # Windows
```

**3. Installer les dépendances**

```bash
pip install -r requirements.txt
```

**4. Configurer PostgreSQL**

```bash
# Se connecter à PostgreSQL
sudo -u postgres psql

# Créer la base de données
CREATE DATABASE casapedia_db;

# Quitter psql
\q
```

**5. Initialiser les tables**

```bash
psql -h localhost -U postgres -d casapedia_db -f database/init_tables.sql
```

**6. Configurer les variables d'environnement**

```bash
cp .env.example .env
# Éditer .env avec vos paramètres de connexion
```

Exemple `.env` :
```
DB_HOST=localhost
DB_PORT=5432
DB_NAME=casapedia_db
DB_USER=postgres
DB_PASSWORD=postgres
```

## Utilisation

### 1. Collecter les données

**Ordre d'exécution recommandé** :

```bash
# 1. Référentiel communes (requis en premier)
python scrapers/communes_scraper.py

# 2. Transactions immobilières (DVF)
python scrapers/dvf_scraper.py

# 3. Données démographiques INSEE
python scrapers/insee_scraper.py

# 4. Diagnostics énergétiques
python scrapers/dpe_scraper.py
```

**Exemples d'utilisation** :

```python
# Scraper un département spécifique (ex: Paris)
from scrapers.dvf_scraper import DVFScraper

scraper = DVFScraper()
scraper.run(year=2023, department='75', limit=1000)
```

Voir [scrapers/README.md](scrapers/README.md) pour la documentation complète.

### 2. Vérifier les données

```bash
# Se connecter à la base de données
psql -h localhost -U postgres -d casapedia_db

# Compter les communes
SELECT COUNT(*) FROM communes;

# Compter les transactions
SELECT COUNT(*) FROM transactions;

# Statistiques par département
SELECT dept, COUNT(*) as nb_transactions, AVG(prix) as prix_moyen
FROM transactions t
JOIN communes c ON t.commune_id = c.code_insee
GROUP BY dept
ORDER BY nb_transactions DESC
LIMIT 10;
```

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
