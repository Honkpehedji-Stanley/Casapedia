"""
Scraper pour les données DVF (Demande de Valeurs Foncières)
Source : data.gouv.fr - Données publiques des transactions immobilières

Ce scraper récupère les transactions immobilières des 5 dernières années
et les insère dans la base de données PostgreSQL.
"""
import os
import sys
import requests
import csv
from datetime import datetime
from pathlib import Path

# Ajouter le dossier parent au path pour les imports
sys.path.append(str(Path(__file__).parent.parent))

from database import get_db_connection


class DVFScraper:
    """Scraper pour les données DVF"""
    
    def __init__(self):
        self.base_url = "https://files.data.gouv.fr/geo-dvf/latest/csv"
        self.data_dir = Path(__file__).parent.parent / "data" / "raw" / "dvf"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
    def download_data(self, year, department=None):
        """
        Télécharger les données DVF pour une année donnée
        
        Args:
            year: Année des transactions (ex: 2023)
            department: Code département (ex: '75' pour Paris), None = toute la France
        
        Returns:
            Path du fichier téléchargé
        """
        # URL des données par année
        if department:
            filename = f"{year}/departements/{department}.csv"
        else:
            filename = f"{year}/full.csv"
        
        url = f"{self.base_url}/{filename}"
        local_file = self.data_dir / f"dvf_{year}_{department or 'france'}.csv"
        
        print(f"Téléchargement : {url}")
        
        try:
            response = requests.get(url, stream=True, timeout=60)
            response.raise_for_status()
            
            # Télécharger avec barre de progression
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            
            with open(local_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        progress = (downloaded / total_size) * 100
                        print(f"\rProgression : {progress:.1f}%", end='', flush=True)
            
            print(f"\n✓ Fichier téléchargé : {local_file}")
            return local_file
            
        except requests.exceptions.RequestException as e:
            print(f"✗ Erreur de téléchargement : {e}")
            return None
    
    def parse_csv(self, csv_file, limit=None):
        """
        Parser le fichier CSV et extraire les données pertinentes
        
        Args:
            csv_file: Chemin du fichier CSV
            limit: Nombre maximum de lignes à traiter (pour tester)
        
        Returns:
            Liste de tuples prêts pour l'insertion en base
        """
        transactions = []
        
        print(f"Parsing du fichier : {csv_file}")
        
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter='|')
            
            for i, row in enumerate(reader):
                if limit and i >= limit:
                    break
                
                try:
                    # Extraire les informations importantes
                    code_commune = row.get('code_commune', '').strip()
                    date_mutation = row.get('date_mutation', '').strip()
                    valeur_fonciere = row.get('valeur_fonciere', '').strip()
                    type_local = row.get('type_local', '').strip()
                    surface_reelle = row.get('surface_reelle_bati', '').strip()
                    nombre_pieces = row.get('nombre_pieces_principales', '').strip()
                    nature_mutation = row.get('nature_mutation', '').strip()
                    adresse = row.get('adresse_numero', '') + ' ' + row.get('adresse_nom_voie', '')
                    code_postal = row.get('code_postal', '').strip()
                    
                    # Filtrer les données invalides
                    if not code_commune or not date_mutation or not valeur_fonciere:
                        continue
                    
                    # Convertir les types
                    try:
                        prix = float(valeur_fonciere)
                        date = datetime.strptime(date_mutation, '%Y-%m-%d').date()
                        surface = float(surface_reelle) if surface_reelle else None
                        pieces = int(nombre_pieces) if nombre_pieces else None
                        prix_m2 = round(prix / surface, 2) if surface and surface > 0 else None
                    except (ValueError, ZeroDivisionError):
                        continue
                    
                    # Mapper le type de bien
                    type_bien = self._map_type_bien(type_local)
                    
                    # Préparer le tuple pour l'insertion
                    transaction = (
                        code_commune,
                        date,
                        prix,
                        surface,
                        prix_m2,
                        type_bien,
                        pieces,
                        nature_mutation,
                        adresse.strip(),
                        code_postal
                    )
                    
                    transactions.append(transaction)
                    
                except Exception as e:
                    # Ignorer les lignes avec erreurs
                    continue
        
        print(f"✓ {len(transactions)} transactions extraites")
        return transactions
    
    def _map_type_bien(self, type_local):
        """Mapper les types de biens DVF vers nos catégories"""
        mapping = {
            'Maison': 'maison',
            'Appartement': 'appartement',
            'Dépendance': 'dependance',
            'Local industriel. commercial ou assimilé': 'local_commercial'
        }
        return mapping.get(type_local, 'autre')
    
    def save_to_database(self, transactions):
        """
        Sauvegarder les transactions dans PostgreSQL
        
        Args:
            transactions: Liste de tuples contenant les données
        
        Returns:
            Nombre de lignes insérées
        """
        if not transactions:
            print("Aucune transaction à insérer")
            return 0
        
        db = get_db_connection()
        
        try:
            columns = [
                'commune_id', 'date_transaction', 'prix', 'surface',
                'prix_m2', 'type_bien', 'nombre_pieces', 'nature_mutation',
                'adresse', 'code_postal'
            ]
            
            count = db.insert_many('transactions', columns, transactions)
            return count
            
        except Exception as e:
            print(f"✗ Erreur lors de l'insertion : {e}")
            return 0
        finally:
            db.disconnect()
    
    def run(self, year=2023, department=None, limit=None):
        """
        Lancer le scraping complet
        
        Args:
            year: Année à scraper
            department: Code département (None = toute la France)
            limit: Limiter le nombre de transactions (pour tester)
        """
        print(f"=== Scraping DVF {year} ===\n")
        
        # 1. Télécharger les données
        csv_file = self.download_data(year, department)
        if not csv_file:
            print("✗ Téléchargement échoué")
            return
        
        # 2. Parser le CSV
        transactions = self.parse_csv(csv_file, limit)
        
        # 3. Sauvegarder en base
        count = self.save_to_database(transactions)
        
        print(f"\n✓ Scraping terminé : {count} transactions insérées")


if __name__ == "__main__":
    """
    Exemple d'utilisation :
    
    # Scraper toute la France pour 2023 (attention, gros fichier!)
    scraper = DVFScraper()
    scraper.run(year=2023)
    
    # Scraper uniquement Paris (75) avec limite pour tester
    scraper = DVFScraper()
    scraper.run(year=2023, department='75', limit=1000)
    """
    
    # Test : scraper Paris 2023 avec limite de 1000 transactions
    scraper = DVFScraper()
    scraper.run(year=2023, department='75', limit=1000)
