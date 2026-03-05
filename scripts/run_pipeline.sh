#!/bin/bash
#
# Script d'orchestration du pipeline de scraping Casapedia
# Usage : ./scripts/run_pipeline.sh [options]
#

set -e  # Arrêter en cas d'erreur

# Couleurs pour les logs
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}   Casapedia - Pipeline de scraping    ${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Vérifier que nous sommes dans le bon répertoire
if [ ! -f "requirements.txt" ]; then
    echo -e "${RED}Erreur : Exécuter depuis le dossier racine du projet${NC}"
    exit 1
fi

# Activer l'environnement virtuel si présent
if [ -d "venv" ]; then
    echo -e "${GREEN}Activation de l'environnement virtuel...${NC}"
    source venv/bin/activate
fi

# Vérifier que PostgreSQL est accessible
if ! PGPASSWORD=$DB_PASSWORD psql -h localhost -U postgres -d casapedia_db -c '\q' 2>/dev/null; then
    echo -e "${RED}Erreur : Impossible de se connecter à PostgreSQL${NC}"
    echo "Vérifiez que PostgreSQL est démarré et que les credentials dans .env sont corrects"
    exit 1
fi

# Créer la table scraping_history si elle n'existe pas
echo -e "${GREEN}Vérification de la table scraping_history...${NC}"
PGPASSWORD=$DB_PASSWORD psql -h localhost -U postgres -d casapedia_db -f database/add_scraping_history.sql > /dev/null 2>&1 || true

# Lancer l'orchestrateur Python
echo ""
echo -e "${GREEN}Lancement de l'orchestrateur...${NC}"
echo ""

python scripts/orchestrator.py "$@"

# Code de sortie
EXIT_CODE=$?

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}   Pipeline terminé avec succès !      ${NC}"
    echo -e "${GREEN}========================================${NC}"
else
    echo -e "${RED}========================================${NC}"
    echo -e "${RED}   Pipeline terminé avec des erreurs   ${NC}"
    echo -e "${RED}========================================${NC}"
fi

exit $EXIT_CODE
