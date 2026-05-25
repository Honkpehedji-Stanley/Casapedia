"""
Module de gestion de la base de données MongoDB.
"""
import os

from dotenv import load_dotenv
from pymongo import MongoClient


load_dotenv()


class MongoDatabaseManager:
    """Gestionnaire de connexion à MongoDB."""

    def __init__(self):
        self.host = os.getenv("MONGO_HOST", "mongodb")
        self.port = os.getenv("MONGO_PORT", "27017")
        self.database = os.getenv("MONGO_DB", "casapedia")
        self.user = os.getenv("MONGO_USER", "root")
        self.password = os.getenv("MONGO_PASSWORD", "examplepassword")
        self.connection = None
        self.db = None

    def connect(self):
        """Établir la connexion à MongoDB."""
        try:
            uri = (
                f"mongodb://{self.user}:{self.password}"
                f"@{self.host}:{self.port}/?authSource=admin"
            )
            self.connection = MongoClient(uri)
            self.db = self.connection[self.database]
            print(f"✓ Connexion établie à MongoDB/{self.database}")
            return self.db
        except Exception as error:
            print(f"✗ Erreur de connexion MongoDB : {error}")
            raise

    def disconnect(self):
        """Fermer la connexion."""
        if self.connection:
            self.connection.close()
            print("✓ Connexion MongoDB fermée")

    def replace_many(self, collection_name, documents):
        """Remplacer le contenu d'une collection par un nouvel ensemble de documents."""
        if self.db is None:
            raise RuntimeError("La connexion MongoDB n'est pas initialisée")

        collection = self.db[collection_name]
        collection.delete_many({})
        if not documents:
            return 0

        result = collection.insert_many(documents)
        return len(result.inserted_ids)


def get_mongo_connection():
    """Retourner une connexion MongoDB prête à l'emploi."""
    mongo = MongoDatabaseManager()
    mongo.connect()
    return mongo