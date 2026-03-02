"""
Scraper pour le référentiel des communes françaises
Source : data.gouv.fr - Code Officiel Géographique de l'INSEE

Ce scraper récupère la liste complète des communes françaises avec leurs codes INSEE,
noms, départements, régions et coordonnées géographiques.
"""
import os
import sys
import requests
import csv
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from database import get_db_connection


class CommunesScraper:
    """Scraper pour le référentiel des communes"""
    
    def __init__(self):
        self.base_url = "https://www.data.gouv.fr/fr/datasets/r"
        self.data_dir = Path(__file__).parent.parent / "data" / "raw" / "communes"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
    def download_data(self):
        """
        Télécharger le fichier des communes avec coordonnées
        
        Returns:
            Path du fichier téléchargé
        """
        # URL du fichier communes avec coordonnées GPS
        url = "https://www.data.gouv.fr/fr/datasets/r/dbe8a621-a9c4-4bc3-9cae-be1699c5ff25"
        local_file = self.data_dir / "communes_france.csv"
        
        print(f"Téléchargement des communes françaises...")
        
        try:
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            
            with open(local_file, 'wb') as f:
                f.write(response.content)
            
            print(f"✓ Fichier téléchargé : {local_file}")
            return local_file
            
        except requests.exceptions.RequestException as e:
            print(f"✗ Erreur de téléchargement : {e}")
            return None
    
    def parse_csv(self, csv_file):
        """
        Parser le fichier CSV des communes
        
        Args:
            csv_file: Chemin du fichier CSV
        
        Returns:
            Liste de tuples prêts pour l'insertion
        """
        communes = []
        
        print(f"Parsing du fichier : {csv_file}")
        
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter=',')
            
            for row in reader:
                try:
                    code_insee = row.get('com_code', '').strip()
                    nom = row.get('com_nom', '').strip()
                    dept = row.get('dep_code', '').strip()
                    region = row.get('reg_nom', '').strip()
                    latitude = row.get('latitude', '').strip()
                    longitude = row.get('longitude', '').strip()
                    
                    # Vérifier les données obligatoires
                    if not code_insee or not nom or not dept:
                        continue
                    
                    # Convertir les coordonnées
                    try:
                        lat = float(latitude) if latitude else None
                        lon = float(longitude) if longitude else None
                    except ValueError:
                        lat, lon = None, None
                    
                    commune = (
                        code_insee,
                        nom,
                        dept,
                        region,
                        lat,
                        lon
                    )
                    
                    communes.append(commune)
                    
                except Exception as e:
                    continue
        
        print(f"✓ {len(communes)} communes extraites")
        return communes
    
    def save_to_database(self, communes):
        """
        Sauvegarder les communes dans PostgreSQL
        
        Args:
            communes: Liste de tuples contenant les données
        
        Returns:
            Nombre de lignes insérées
        """
        if not communes:
            print("Aucune commune à insérer")
            return 0
        
        db = get_db_connection()
        
        try:
            columns = [
                'code_insee', 'nom', 'dept', 'region',
                'latitude', 'longitude'
            ]
            
            # Supprimer les doublons potentiels
            query = "INSERT INTO communes (code_insee, nom, dept, region, latitude, longitude) VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (code_insee) DO UPDATE SET nom = EXCLUDED.nom, dept = EXCLUDED.dept, region = EXCLUDED.region, latitude = EXCLUDED.latitude, longitude = EXCLUDED.longitude"
            
            cursor = db.connection.cursor()
            cursor.executemany(query, communes)
            db.connection.commit()
            count = cursor.rowcount
            cursor.close()
            
            print(f"✓ {count} communes insérées/mises à jour")
            return count
            
        except Exception as e:
            print(f"✗ Erreur lors de l'insertion : {e}")
            db.connection.rollback()
            return 0
        finally:
            db.disconnect()
    
    def run(self):
        """Lancer le scraping complet"""
        print("=== Scraping Référentiel Communes ===\n")
        
        # 1. Télécharger les données
        csv_file = self.download_data()
        if not csv_file:
            print("✗ Téléchargement échoué")
            return
        
        # 2. Parser le CSV
        communes = self.parse_csv(csv_file)
        
        # 3. Sauvegarder en base
        count = self.save_to_database(communes)
        
        print(f"\n✓ Scraping terminé : {count} communes en base")


if __name__ == "__main__":
    scraper = CommunesScraper()
    scraper.run()
