"""
Scraper pour les données DPE (Diagnostic de Performance Énergétique)
Source : ADEME - Base DPE Logements

Ce scraper récupère les diagnostics de performance énergétique des logements
par commune avec classes énergétiques et émissions de CO2.
"""
import os
import sys
import requests
import csv
from pathlib import Path
from datetime import datetime

sys.path.append(str(Path(__file__).parent.parent))

from database import get_db_connection


class DPEScraper:
    """Scraper pour les données DPE"""
    
    def __init__(self):
        self.data_dir = Path(__file__).parent.parent / "data" / "raw" / "dpe"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
    def download_data(self, department=None):
        """
        Télécharger les données DPE
        
        Args:
            department: Code département (ex: '75'), None = France entière
        
        Returns:
            Path du fichier téléchargé
        """
        # Base de données DPE ADEME
        if department:
            url = f"https://data.ademe.fr/data-fair/api/v1/datasets/dpe-v2-logements-existants/lines?format=csv&q=Code_postal_BAN:{department}*&size=10000"
            local_file = self.data_dir / f"dpe_{department}.csv"
        else:
            # Pour toute la France, utiliser l'export complet (attention : gros fichier)
            url = "https://data.ademe.fr/data-fair/api/v1/datasets/dpe-v2-logements-existants/lines?format=csv&size=100000"
            local_file = self.data_dir / "dpe_france.csv"
        
        print(f"Téléchargement données DPE...")
        
        try:
            response = requests.get(url, timeout=120, stream=True)
            response.raise_for_status()
            
            with open(local_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            print(f"✓ Fichier téléchargé : {local_file}")
            return local_file
            
        except Exception as e:
            print(f"✗ Erreur de téléchargement : {e}")
            return None
    
    def parse_csv(self, csv_file, limit=None):
        """
        Parser le fichier CSV des DPE
        
        Args:
            csv_file: Chemin du fichier CSV
            limit: Nombre maximum de lignes (pour tester)
        
        Returns:
            Liste de tuples pour insertion
        """
        dpe_data = []
        
        print(f"Parsing DPE : {csv_file}")
        
        try:
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f, delimiter=',')
                
                for i, row in enumerate(reader):
                    if limit and i >= limit:
                        break
                    
                    try:
                        # Extraire les champs importants
                        code_insee = row.get('Code_INSEE_(BAN)', '').strip()
                        classe_energie = row.get('Etiquette_DPE', '').strip().upper()
                        classe_ges = row.get('Etiquette_GES', '').strip().upper()
                        conso_energie = row.get('Conso_5_usages_é_finale', '').strip()
                        emissions = row.get('Emission_GES_5_usages', '').strip()
                        type_bat = row.get('Type_bâtiment', '').strip()
                        annee_construction = row.get('Année_construction', '').strip()
                        surface = row.get('Surface_habitable_logement', '').strip()
                        date_etabl = row.get("Date_établissement_DPE", '').strip()
                        
                        # Vérifier données minimales
                        if not code_insee or not classe_energie:
                            continue
                        
                        # Valider la classe énergétique
                        if classe_energie not in ['A', 'B', 'C', 'D', 'E', 'F', 'G']:
                            continue
                        
                        # Convertir les types
                        try:
                            conso = float(conso_energie) if conso_energie else None
                            ges = float(emissions) if emissions else None
                            surf = float(surface) if surface else None
                            annee = int(annee_construction) if annee_construction else None
                            
                            # Parser la date
                            if date_etabl:
                                date_dpe = datetime.strptime(date_etabl, '%Y-%m-%d').date()
                            else:
                                date_dpe = None
                                
                        except (ValueError, TypeError):
                            conso, ges, surf, annee, date_dpe = None, None, None, None, None
                        
                        # Mapper le type de bâtiment
                        type_batiment = self._map_type_batiment(type_bat)
                        
                        # Valider la classe GES
                        if classe_ges and classe_ges not in ['A', 'B', 'C', 'D', 'E', 'F', 'G']:
                            classe_ges = None
                        
                        dpe = (
                            code_insee,
                            classe_energie,
                            classe_ges,
                            ges,
                            conso,
                            type_batiment,
                            annee,
                            surf,
                            date_dpe
                        )
                        
                        dpe_data.append(dpe)
                        
                    except Exception as e:
                        continue
        
        except Exception as e:
            print(f"✗ Erreur parsing : {e}")
        
        print(f"✓ {len(dpe_data)} DPE extraits")
        return dpe_data
    
    def _map_type_batiment(self, type_bat):
        """Mapper les types de bâtiments DPE"""
        type_lower = type_bat.lower()
        
        if 'appartement' in type_lower:
            return 'appartement'
        elif 'maison' in type_lower or 'individuel' in type_lower:
            return 'maison'
        elif 'immeuble' in type_lower:
            return 'immeuble'
        else:
            return 'autre'
    
    def save_to_database(self, dpe_data):
        """
        Sauvegarder les DPE dans PostgreSQL
        
        Args:
            dpe_data: Liste de tuples
        
        Returns:
            Nombre de lignes insérées
        """
        if not dpe_data:
            print("Aucun DPE à insérer")
            return 0
        
        db = get_db_connection()
        
        try:
            columns = [
                'commune_id', 'classe_energetique', 'classe_ges',
                'emissions_co2', 'consommation_energie', 'type_batiment',
                'annee_construction', 'surface', 'date_etablissement'
            ]
            
            count = db.insert_many('dpe', columns, dpe_data)
            return count
            
        except Exception as e:
            print(f"✗ Erreur lors de l'insertion : {e}")
            return 0
        finally:
            db.disconnect()
    
    def run(self, department=None, limit=None):
        """
        Lancer le scraping complet
        
        Args:
            department: Code département (None = France entière)
            limit: Limiter le nombre de DPE (pour tester)
        """
        print(f"=== Scraping DPE ===\n")
        
        # 1. Télécharger les données
        csv_file = self.download_data(department)
        if not csv_file:
            print("✗ Téléchargement échoué")
            return
        
        # 2. Parser le CSV
        dpe_data = self.parse_csv(csv_file, limit)
        
        # 3. Sauvegarder en base
        count = self.save_to_database(dpe_data)
        
        print(f"\n✓ Scraping terminé : {count} DPE insérés")


if __name__ == "__main__":
    # Test : scraper Paris avec limite
    scraper = DPEScraper()
    scraper.run(department='75', limit=5000)
