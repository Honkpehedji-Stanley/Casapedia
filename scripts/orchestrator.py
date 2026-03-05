"""
Orchestrateur de scrapers
Automatise l'exécution des scrapers dans le bon ordre et track les exécutions.
"""
import sys
import json
from datetime import datetime
from pathlib import Path

# Ajouter le dossier parent au path
sys.path.append(str(Path(__file__).parent.parent))

from database import get_db_connection
from scrapers.communes_scraper import CommunesScraper
from scrapers.dvf_scraper import DVFScraper
from scrapers.insee_scraper import INSEEScraper
from scrapers.dpe_scraper import DPEScraper


class ScraperOrchestrator:
    """Orchestrateur pour gérer l'exécution des scrapers"""
    
    def __init__(self):
        self.db = None
        self.current_run_id = None
    
    def log_start(self, scraper_name, metadata=None):
        """
        Enregistrer le début d'exécution d'un scraper
        
        Args:
            scraper_name: Nom du scraper
            metadata: Dictionnaire avec infos supplémentaires (year, department, etc.)
        
        Returns:
            ID de l'exécution
        """
        self.db = get_db_connection()
        
        query = """
            INSERT INTO scraping_history (scraper_name, status, metadata)
            VALUES (%s, %s, %s)
            RETURNING id
        """
        
        metadata_json = json.dumps(metadata) if metadata else None
        result = self.db.execute_query(query, (scraper_name, 'running', metadata_json), fetch=True)
        
        run_id = result[0]['id'] if result else None
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 📊 Démarrage : {scraper_name}")
        
        return run_id
    
    def log_success(self, run_id, records_count):
        """
        Enregistrer la réussite d'un scraper
        
        Args:
            run_id: ID de l'exécution
            records_count: Nombre d'enregistrements traités
        """
        if not self.db:
            self.db = get_db_connection()
        
        query = """
            UPDATE scraping_history
            SET status = 'success',
                completed_at = CURRENT_TIMESTAMP,
                records_processed = %s
            WHERE id = %s
        """
        
        self.db.execute_query(query, (records_count, run_id))
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ✅ Succès : {records_count} enregistrements")
    
    def log_failure(self, run_id, error_message):
        """
        Enregistrer l'échec d'un scraper
        
        Args:
            run_id: ID de l'exécution
            error_message: Message d'erreur
        """
        if not self.db:
            self.db = get_db_connection()
        
        query = """
            UPDATE scraping_history
            SET status = 'failed',
                completed_at = CURRENT_TIMESTAMP,
                error_message = %s
            WHERE id = %s
        """
        
        self.db.execute_query(query, (error_message, run_id))
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ❌ Échec : {error_message}")
    
    def run_scraper(self, scraper_name, scraper_func, metadata=None):
        """
        Exécuter un scraper avec tracking
        
        Args:
            scraper_name: Nom du scraper
            scraper_func: Fonction à exécuter
            metadata: Métadonnées supplémentaires
        
        Returns:
            True si succès, False sinon
        """
        run_id = self.log_start(scraper_name, metadata)
        
        try:
            records_count = scraper_func()
            self.log_success(run_id, records_count or 0)
            return True
        except Exception as e:
            error_msg = str(e)
            self.log_failure(run_id, error_msg)
            print(f"Erreur détaillée : {e}")
            return False
        finally:
            if self.db:
                self.db.disconnect()
                self.db = None
    
    def run_all(self, year=2023, departments=None, skip_communes=False):
        """
        Exécuter tous les scrapers dans le bon ordre
        
        Args:
            year: Année pour les données DVF et INSEE
            departments: Liste de départements (None = France entière)
            skip_communes: Ignorer le scraping des communes (si déjà fait)
        """
        print("=" * 60)
        print("🚀 DÉMARRAGE DU PIPELINE DE SCRAPING")
        print("=" * 60)
        print(f"Année : {year}")
        print(f"Départements : {departments or 'France entière'}")
        print("=" * 60)
        print()
        
        results = {}
        
        # 1. Communes (requis pour les clés étrangères)
        if not skip_communes:
            def run_communes():
                scraper = CommunesScraper()
                scraper.run()
                return self._count_records('communes')
            
            results['communes'] = self.run_scraper(
                'communes_scraper',
                run_communes,
                metadata={'source': 'data.gouv.fr'}
            )
            print()
        else:
            print("[INFO] Scraping des communes ignoré (skip_communes=True)")
            print()
        
        # 2. Transactions DVF
        if departments:
            for dept in departments:
                def run_dvf():
                    scraper = DVFScraper()
                    scraper.run(year=year, department=dept)
                    return self._count_records('transactions')
                
                results[f'dvf_{dept}'] = self.run_scraper(
                    f'dvf_scraper',
                    run_dvf,
                    metadata={'year': year, 'department': dept}
                )
                print()
        else:
            def run_dvf():
                scraper = DVFScraper()
                scraper.run(year=year)
                return self._count_records('transactions')
            
            results['dvf'] = self.run_scraper(
                'dvf_scraper',
                run_dvf,
                metadata={'year': year, 'scope': 'france'}
            )
            print()
        
        # 3. Données INSEE
        def run_insee():
            scraper = INSEEScraper()
            scraper.run(year=year)
            return self._count_records('demographics')
        
        results['insee'] = self.run_scraper(
            'insee_scraper',
            run_insee,
            metadata={'year': year}
        )
        print()
        
        # 4. DPE
        if departments:
            for dept in departments:
                def run_dpe():
                    scraper = DPEScraper()
                    scraper.run(department=dept, limit=10000)
                    return self._count_records('dpe')
                
                results[f'dpe_{dept}'] = self.run_scraper(
                    'dpe_scraper',
                    run_dpe,
                    metadata={'department': dept}
                )
                print()
        else:
            def run_dpe():
                scraper = DPEScraper()
                scraper.run(limit=50000)
                return self._count_records('dpe')
            
            results['dpe'] = self.run_scraper(
                'dpe_scraper',
                run_dpe,
                metadata={'scope': 'france', 'limit': 50000}
            )
            print()
        
        # Résumé
        self._print_summary(results)
    
    def _count_records(self, table):
        """Compter les enregistrements dans une table"""
        try:
            db = get_db_connection()
            result = db.execute_query(f"SELECT COUNT(*) as count FROM {table}", fetch=True)
            count = result[0]['count'] if result else 0
            db.disconnect()
            return count
        except:
            return 0
    
    def _print_summary(self, results):
        """Afficher un résumé des exécutions"""
        print()
        print("=" * 60)
        print("📈 RÉSUMÉ DU PIPELINE")
        print("=" * 60)
        
        success_count = sum(1 for v in results.values() if v)
        total_count = len(results)
        
        for scraper, success in results.items():
            status = "✅ SUCCÈS" if success else "❌ ÉCHEC"
            print(f"{scraper:20} : {status}")
        
        print("=" * 60)
        print(f"Résultat : {success_count}/{total_count} scrapers réussis")
        print("=" * 60)
        
        if success_count == total_count:
            print("🎉 Pipeline terminé avec succès !")
        else:
            print("⚠️  Pipeline terminé avec des erreurs")


if __name__ == "__main__":
    """
    Usage :
    
    # Tout scraper pour 2023 (France entière)
    python scripts/orchestrator.py
    
    # Scraper des départements spécifiques
    python scripts/orchestrator.py --departments 75 69 13
    
    # Scraper en ignorant les communes (déjà faites)
    python scripts/orchestrator.py --skip-communes
    """
    import argparse
    
    parser = argparse.ArgumentParser(description='Orchestrateur de scrapers Casapedia')
    parser.add_argument('--year', type=int, default=2023, help='Année des données (défaut: 2023)')
    parser.add_argument('--departments', nargs='+', help='Départements à scraper (ex: 75 69 13)')
    parser.add_argument('--skip-communes', action='store_true', help='Ignorer le scraping des communes')
    
    args = parser.parse_args()
    
    orchestrator = ScraperOrchestrator()
    orchestrator.run_all(
        year=args.year,
        departments=args.departments,
        skip_communes=args.skip_communes
    )
