"""
Scraper pour les données démographiques de l'INSEE
Source : INSEE - Données communales

Ce scraper récupère les données démographiques et économiques par commune :
- Population
- Revenus médians
- Taux de chômage
- Nombre de ménages
"""
import os
import sys
import requests
import csv
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from database import get_db_connection


class INSEEScraper:
    """Scraper pour les données INSEE"""
    
    def __init__(self):
        self.data_dir = Path(__file__).parent.parent / "data" / "raw" / "insee"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
    def download_population_data(self, year=2021):
        """
        Télécharger les données de population par commune
        
        Args:
            year: Année des données (2021 par défaut)
        
        Returns:
            Path du fichier téléchargé
        """
        # URL des données de population communale INSEE
        url = f"https://www.insee.fr/fr/statistiques/fichier/6683035/ensemble.zip"
        local_file = self.data_dir / f"population_{year}.zip"
        
        print(f"Téléchargement données population {year}...")
        
        try:
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            
            with open(local_file, 'wb') as f:
                f.write(response.content)
            
            print(f"✓ Fichier téléchargé : {local_file}")
            
            # Dézipper le fichier
            import zipfile
            with zipfile.ZipFile(local_file, 'r') as zip_ref:
                zip_ref.extractall(self.data_dir)
            
            # Chercher le fichier CSV principal
            csv_files = list(self.data_dir.glob("*.csv"))
            if csv_files:
                return csv_files[0]
            
            return None
            
        except Exception as e:
            print(f"✗ Erreur de téléchargement : {e}")
            return None
    
    def download_revenus_data(self, year=2021):
        """
        Télécharger les données de revenus par commune
        
        Args:
            year: Année des données
        
        Returns:
            Path du fichier téléchargé
        """
        # URL des données de revenus (fichier data.gouv.fr)
        url = "https://www.data.gouv.fr/fr/datasets/r/bbe7b18c-c89a-4e28-9b83-e4927b1c82b5"
        local_file = self.data_dir / f"revenus_{year}.csv"
        
        print(f"Téléchargement données revenus {year}...")
        
        try:
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            
            with open(local_file, 'wb') as f:
                f.write(response.content)
            
            print(f"✓ Fichier téléchargé : {local_file}")
            return local_file
            
        except Exception as e:
            print(f"✗ Erreur de téléchargement : {e}")
            return None
    
    def parse_population_csv(self, csv_file, year):
        """
        Parser le fichier CSV de population
        
        Args:
            csv_file: Chemin du fichier CSV
            year: Année des données
        
        Returns:
            Dictionnaire {code_insee: {population, densite, etc.}}
        """
        data = {}
        
        print(f"Parsing population : {csv_file}")
        
        try:
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f, delimiter=';')
                
                for row in reader:
                    try:
                        code_insee = row.get('COM', '').strip()
                        population = row.get('PMUN', '').strip()
                        
                        if not code_insee or not population:
                            continue
                        
                        data[code_insee] = {
                            'population': int(population),
                            'annee': year
                        }
                        
                    except (ValueError, KeyError):
                        continue
        
        except Exception as e:
            print(f"✗ Erreur parsing : {e}")
        
        print(f"✓ {len(data)} communes avec données population")
        return data
    
    def parse_revenus_csv(self, csv_file):
        """
        Parser le fichier CSV de revenus
        
        Args:
            csv_file: Chemin du fichier CSV
        
        Returns:
            Dictionnaire {code_insee: {revenu_median, etc.}}
        """
        data = {}
        
        print(f"Parsing revenus : {csv_file}")
        
        try:
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f, delimiter=';')
                
                for row in reader:
                    try:
                        code_insee = row.get('CODGEO', '').strip()
                        revenu = row.get('MED21', '').strip()
                        
                        if not code_insee or not revenu:
                            continue
                        
                        data[code_insee] = {
                            'revenu_median': float(revenu)
                        }
                        
                    except (ValueError, KeyError):
                        continue
        
        except Exception as e:
            print(f"✗ Erreur parsing : {e}")
        
        print(f"✓ {len(data)} communes avec données revenus")
        return data
    
    def merge_data(self, pop_data, revenus_data, year):
        """
        Fusionner les données de différentes sources
        
        Args:
            pop_data: Données population
            revenus_data: Données revenus
            year: Année
        
        Returns:
            Liste de tuples pour insertion
        """
        demographics = []
        
        # Fusionner sur la base des codes INSEE
        all_codes = set(pop_data.keys()) | set(revenus_data.keys())
        
        for code in all_codes:
            pop = pop_data.get(code, {})
            rev = revenus_data.get(code, {})
            
            # Au moins population ou revenus doit être présent
            if not pop and not rev:
                continue
            
            demo = (
                code,
                year,
                pop.get('population'),
                None,  # densite (à calculer avec surface)
                rev.get('revenu_median'),
                None,  # taux_chomage
                None,  # nombre_menages
                None   # taille_moyenne_menage
            )
            
            demographics.append(demo)
        
        print(f"✓ {len(demographics)} enregistrements démographiques préparés")
        return demographics
    
    def save_to_database(self, demographics):
        """
        Sauvegarder les données démographiques dans PostgreSQL
        
        Args:
            demographics: Liste de tuples
        
        Returns:
            Nombre de lignes insérées
        """
        if not demographics:
            print("Aucune donnée démographique à insérer")
            return 0
        
        db = get_db_connection()
        
        try:
            columns = [
                'commune_id', 'annee', 'population', 'densite',
                'revenu_median', 'taux_chomage', 'nombre_menages',
                'taille_moyenne_menage'
            ]
            
            count = db.insert_many('demographics', columns, demographics)
            return count
            
        except Exception as e:
            print(f"✗ Erreur lors de l'insertion : {e}")
            return 0
        finally:
            db.disconnect()
    
    def run(self, year=2021):
        """
        Lancer le scraping complet
        
        Args:
            year: Année des données à récupérer
        """
        print(f"=== Scraping INSEE {year} ===\n")
        
        # 1. Télécharger les données de population
        pop_file = self.download_population_data(year)
        pop_data = {}
        if pop_file:
            pop_data = self.parse_population_csv(pop_file, year)
        
        # 2. Télécharger les données de revenus
        rev_file = self.download_revenus_data(year)
        rev_data = {}
        if rev_file:
            rev_data = self.parse_revenus_csv(rev_file)
        
        # 3. Fusionner les données
        demographics = self.merge_data(pop_data, rev_data, year)
        
        # 4. Sauvegarder en base
        count = self.save_to_database(demographics)
        
        print(f"\n✓ Scraping terminé : {count} enregistrements insérés")


if __name__ == "__main__":
    scraper = INSEEScraper()
    scraper.run(year=2021)
