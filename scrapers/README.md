# Scrapers

## DVF Scraper

Scraper pour les données DVF (Demande de Valeurs Foncières) - transactions immobilières publiques.

### Installation

```bash
pip install -r requirements.txt
```

### Configuration

Configurer les variables d'environnement dans `.env` :
```
DB_HOST=localhost
DB_PORT=5432
DB_NAME=casapedia_db
DB_USER=postgres
DB_PASSWORD=postgres
```

### Utilisation

#### Exemple 1 : Scraper un département avec limite (pour tester)

```python
from scrapers.dvf_scraper import DVFScraper

scraper = DVFScraper()
scraper.run(year=2023, department='75', limit=1000)
```

#### Exemple 2 : Scraper un département complet

```python
scraper = DVFScraper()
scraper.run(year=2023, department='75')
```

#### Exemple 3 : Scraper toute la France (attention : gros fichier)

```python
scraper = DVFScraper()
scraper.run(year=2023)
```

### Exécution directe

```bash
cd scrapers
python dvf_scraper.py
```

### Structure du code

Le scraper suit une structure simple en 3 étapes :

1. **`download_data()`** : Télécharge le CSV depuis data.gouv.fr
2. **`parse_csv()`** : Parse le CSV et extrait les données pertinentes
3. **`save_to_database()`** : Insère les données dans PostgreSQL

### Adapter pour créer d'autres scrapers

Pour créer un nouveau scraper, suivre ce pattern :

```python
class MonScraper:
    def __init__(self):
        # Configuration et chemins
        self.data_dir = Path(__file__).parent.parent / "data" / "raw" / "mon_scraper"
        self.data_dir.mkdir(parents=True, exist_ok=True)
    
    def download_data(self):
        # Récupérer les données (API, CSV, scraping web)
        pass
    
    def parse_data(self):
        # Parser et nettoyer les données
        pass
    
    def save_to_database(self):
        # Insérer dans PostgreSQL
        db = get_db_connection()
        db.insert_many('ma_table', columns, data)
        db.disconnect()
    
    def run(self):
        # Orchestrer les étapes
        data = self.download_data()
        parsed = self.parse_data(data)
        self.save_to_database(parsed)
```

### Codes départements utiles

- 75 : Paris
- 69 : Rhône (Lyon)
- 13 : Bouches-du-Rhône (Marseille)
- 31 : Haute-Garonne (Toulouse)
- 33 : Gironde (Bordeaux)
- 59 : Nord (Lille)
- 44 : Loire-Atlantique (Nantes)
