"""
Module de gestion de la base de données PostgreSQL
"""
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

# Charger les variables d'environnement
load_dotenv()


class DatabaseManager:
    """Gestionnaire de connexion à PostgreSQL"""
    
    def __init__(self):
        self.host = os.getenv('DB_HOST', 'localhost')
        self.port = os.getenv('DB_PORT', '5432')
        self.database = os.getenv('DB_NAME', 'casapedia_db')
        self.user = os.getenv('DB_USER', 'postgres')
        self.password = os.getenv('DB_PASSWORD', 'postgres')
        self.connection = None
    
    def connect(self):
        """Établir la connexion à la base de données"""
        try:
            self.connection = psycopg2.connect(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password
            )
            print(f"✓ Connexion établie à {self.database}")
            return self.connection
        except Exception as e:
            print(f"✗ Erreur de connexion : {e}")
            raise
    
    def disconnect(self):
        """Fermer la connexion"""
        if self.connection:
            self.connection.close()
            print("✓ Connexion fermée")
    
    def execute_query(self, query, params=None, fetch=False):
        """
        Exécuter une requête SQL
        
        Args:
            query: Requête SQL à exécuter
            params: Paramètres de la requête (tuple ou dict)
            fetch: Si True, retourne les résultats
        
        Returns:
            Résultats de la requête si fetch=True, sinon None
        """
        cursor = self.connection.cursor(cursor_factory=RealDictCursor)
        try:
            cursor.execute(query, params)
            if fetch:
                return cursor.fetchall()
            self.connection.commit()
            return cursor.rowcount
        except Exception as e:
            self.connection.rollback()
            print(f"✗ Erreur SQL : {e}")
            raise
        finally:
            cursor.close()
    
    def insert_many(self, table, columns, data):
        """
        Insérer plusieurs lignes en batch
        
        Args:
            table: Nom de la table
            columns: Liste des colonnes
            data: Liste de tuples contenant les valeurs
        
        Returns:
            Nombre de lignes insérées
        """
        if not data:
            return 0
        
        placeholders = ','.join(['%s'] * len(columns))
        columns_str = ','.join(columns)
        query = f"INSERT INTO {table} ({columns_str}) VALUES ({placeholders})"
        
        cursor = self.connection.cursor()
        try:
            cursor.executemany(query, data)
            self.connection.commit()
            print(f"✓ {cursor.rowcount} lignes insérées dans {table}")
            return cursor.rowcount
        except Exception as e:
            self.connection.rollback()
            print(f"✗ Erreur insertion : {e}")
            raise
        finally:
            cursor.close()


# Fonction helper pour obtenir une connexion
def get_db_connection():
    """Retourne une nouvelle connexion à la base de données"""
    db = DatabaseManager()
    db.connect()
    return db
