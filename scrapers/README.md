# Scrapers

Modules de collecte de données immobilières et démographiques à partir de sources publiques françaises.

## Installation

```bash
pip install -r requirements.txt
cp .env.example .env
```

Configurer les variables d'environnement dans `.env` :
```
DB_HOST=localhost
DB_PORT=5432
DB_NAME=casapedia_db
DB_USER=postgres
DB_PASSWORD=postgres
```

## Scrapers disponibles

### 1. Communes Scraper

Récupère le référentiel des communes françaises (codes INSEE, noms, coordonnées GPS).

**Source** : data.gouv.fr - Code Officiel Géographique INSEE

**Usage** :
```python
from scrapers.communes_scraper import CommunesScraper

scraper = CommunesScraper()
scraper.run()
```

**Exécution** :
```bash
python scrapers/communes_scraper.py
```

**Données collectées** : ~35 000 communes avec code INSEE, nom, département, région, latitude, longitude


### 2. DVF Scraper

Récupère les transactions immobilières (Demande de Valeurs Foncières).

**Source** : data.gouv.fr - DVF

**Usage** :
```python
from scrapers.dvf_scraper import DVFScraper

# Scraper un département avec limite (test)
scraper = DVFScraper()
scraper.run(year=2023, department='75', limit=1000)

# Scraper un département complet
scraper.run(year=2023, department='75')

# Scraper toute la France (attention : fichier volumineux)
scraper.run(year=2023)
```

**Exécution** :
```bash
python scrapers/dvf_scraper.py
```

**Données collectées** : prix, surface, type de bien, nombre de pièces, adresse, date de transaction


### 3. INSEE Scraper

Récupère les données démographiques et économiques par commune.

**Source** : INSEE - Données communales

**Usage** :
```python
from scrapers.insee_scraper import INSEEScraper

scraper = INSEEScraper()
scraper.run(year=2021)
```

**Exécution** :
```bash
python scrapers/insee_scraper.py
```

**Données collectées** : population, revenus médians, nombre de ménages


### 4. DPE Scraper

Récupère les diagnostics de performance énergétique des logements.

**Source** : ADEME - Base DPE Logements

**Usage** :
```python
from scrapers.dpe_scraper import DPEScraper

# Scraper un département avec limite (test)
scraper = DPEScraper()
scraper.run(department='75', limit=5000)

# Scraper un département complet
scraper.run(department='75')

# Scraper toute la France (attention : fichier volumineux)
scraper.run()
```

**Exécution** :
```bash
python scrapers/dpe_scraper.py
```

**Données collectées** : classe énergétique (A-G), classe GES, consommation, émissions CO2, type de bâtiment, année de construction


## Ordre d'exécution recommandé

Pour peupler la base de données, exécuter les scrapers dans cet ordre :

```bash
# 1. Référentiel communes (requis pour les clés étrangères)
python scrapers/communes_scraper.py

# 2. Transactions immobilières
python scrapers/dvf_scraper.py

# 3. Données démographiques
python scrapers/insee_scraper.py

# 4. Diagnostics énergétiques
python scrapers/dpe_scraper.py
```

## Structure du code

Chaque scraper suit une architecture en 3 étapes :

1. **`download_data()`** : Télécharge les données depuis la source
2. **`parse_csv()` / `parse_data()`** : Parse et nettoie les données
3. **`save_to_database()`** : Insère dans PostgreSQL

## Codes départements utiles

- 75 : Paris
- 69 : Rhône (Lyon)
- 13 : Bouches-du-Rhône (Marseille)
- 31 : Haute-Garonne (Toulouse)
- 33 : Gironde (Bordeaux)
- 59 : Nord (Lille)
- 44 : Loire-Atlantique (Nantes)
- 06 : Alpes-Maritimes (Nice)
- 67 : Bas-Rhin (Strasbourg)
- 35 : Ille-et-Vilaine (Rennes)

## Notes

- Les scrapers utilisent uniquement des données publiques
- Respect des APIs et rate limiting
- Les fichiers téléchargés sont stockés dans `data/raw/{source}/`
- Les scrapers gèrent les doublons et les erreurs de parsing
