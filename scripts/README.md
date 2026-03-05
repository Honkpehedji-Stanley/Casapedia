# Scripts

Scripts d'orchestration et d'automatisation pour Casapedia.

## Scripts disponibles

### orchestrator.py

Orchestrateur Python qui gère l'exécution automatique des scrapers dans le bon ordre et track les exécutions en base de données.

**Fonctionnalités** :
- Exécution séquentielle des scrapers
- Tracking des exécutions (table `scraping_history`)
- Gestion des erreurs
- Résumé des résultats

**Usage** :

```bash
# Scraper toute la France pour 2023 (par défaut)
python scripts/orchestrator.py

# Scraper une année spécifique
python scripts/orchestrator.py --year 2022

# Scraper des départements spécifiques
python scripts/orchestrator.py --departments 75 69 13

# Ignorer le scraping des communes (si déjà fait)
python scripts/orchestrator.py --skip-communes

# Combinaison
python scripts/orchestrator.py --year 2023 --departments 75 --skip-communes
```

**Options** :
- `--year YYYY` : Année des données à scraper (défaut: 2023)
- `--departments XX YY` : Liste de départements à scraper (défaut: France entière)
- `--skip-communes` : Ne pas scraper le référentiel communes

**Exemple de sortie** :
```
============================================================
🚀 DÉMARRAGE DU PIPELINE DE SCRAPING
============================================================
Année : 2023
Départements : ['75']
============================================================

[2026-03-05 10:30:15] 📊 Démarrage : communes_scraper
[2026-03-05 10:32:45] ✅ Succès : 35000 enregistrements

[2026-03-05 10:32:46] 📊 Démarrage : dvf_scraper
[2026-03-05 10:35:20] ✅ Succès : 45000 enregistrements

============================================================
📈 RÉSUMÉ DU PIPELINE
============================================================
communes             : ✅ SUCCÈS
dvf_75               : ✅ SUCCÈS
insee                : ✅ SUCCÈS
dpe_75               : ✅ SUCCÈS
============================================================
Résultat : 4/4 scrapers réussis
============================================================
🎉 Pipeline terminé avec succès !
```

### run_pipeline.sh

Script Bash qui lance l'orchestrateur avec vérifications préalables.

**Fonctionnalités** :
- Activation automatique de l'environnement virtuel
- Vérification de la connexion PostgreSQL
- Création de la table `scraping_history` si nécessaire
- Affichage avec couleurs

**Usage** :

```bash
# Rendre le script exécutable (une seule fois)
chmod +x scripts/run_pipeline.sh

# Lancer le pipeline
./scripts/run_pipeline.sh

# Avec options
./scripts/run_pipeline.sh --year 2023 --departments 75 69
```

## Table scraping_history

Le système track automatiquement toutes les exécutions dans la table `scraping_history` :

```sql
-- Voir les dernières exécutions
SELECT * FROM scraping_history 
ORDER BY started_at DESC 
LIMIT 10;

-- Voir les exécutions par scraper
SELECT * FROM v_last_scraping_runs;

-- Statistiques de succès
SELECT 
    scraper_name,
    COUNT(*) as total_runs,
    SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as successes,
    AVG(records_processed) as avg_records
FROM scraping_history
GROUP BY scraper_name;
```

## Automatisation (Cron)

Pour automatiser l'exécution périodique :

### Linux/Mac

```bash
# Éditer le crontab
crontab -e

# Ajouter une ligne pour exécution mensuelle (1er du mois à 3h)
0 3 1 * * cd /home/user/Casapedia && ./scripts/run_pipeline.sh --skip-communes >> /var/log/casapedia.log 2>&1

# Exécution hebdomadaire (tous les lundis à 2h)
0 2 * * 1 cd /home/user/Casapedia && ./scripts/run_pipeline.sh --departments 75 >> /var/log/casapedia.log 2>&1
```

### Windows (Task Scheduler)

```powershell
# Créer une tâche planifiée
schtasks /create /tn "Casapedia Scraping" /tr "C:\Casapedia\scripts\run_pipeline.sh" /sc monthly /d 1 /st 03:00
```

## Monitoring

### Vérifier les dernières exécutions

```bash
# Se connecter à PostgreSQL
psql -h localhost -U postgres -d casapedia_db

# Voir les dernières exécutions
SELECT 
    scraper_name,
    started_at,
    status,
    records_processed,
    EXTRACT(EPOCH FROM (completed_at - started_at)) as duration_seconds
FROM scraping_history
WHERE started_at >= NOW() - INTERVAL '7 days'
ORDER BY started_at DESC;
```

### Alertes en cas d'échec

Modifier `orchestrator.py` pour envoyer des notifications :

```python
def log_failure(self, run_id, error_message):
    # ... code existant ...
    
    # Envoyer une alerte email/Slack
    self.send_alert(f"Scraper failed: {error_message}")
```

## Bonnes pratiques

1. **Première exécution** : scraper toutes les communes
   ```bash
   python scripts/orchestrator.py
   ```

2. **Mises à jour** : ignorer les communes (déjà stables)
   ```bash
   python scripts/orchestrator.py --skip-communes
   ```

3. **Tests** : scraper un seul département
   ```bash
   python scripts/orchestrator.py --departments 75 --skip-communes
   ```

4. **Production** : automatiser avec cron
   ```bash
   # Mensuel : toutes les nouvelles données
   0 3 1 * * /path/to/run_pipeline.sh --skip-communes
   ```

## Troubleshooting

**Erreur de connexion PostgreSQL**
```bash
# Vérifier que PostgreSQL est démarré
sudo systemctl status postgresql

# Vérifier les credentials dans .env
cat .env
```

**Permission denied sur le script bash**
```bash
chmod +x scripts/run_pipeline.sh
```

**Module non trouvé**
```bash
# Activer l'environnement virtuel
source venv/bin/activate
pip install -r requirements.txt
```
