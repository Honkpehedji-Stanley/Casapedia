-- Table pour tracker l'historique des exécutions de scraping
CREATE TABLE IF NOT EXISTS scraping_history (
    id SERIAL PRIMARY KEY,
    scraper_name VARCHAR(100) NOT NULL,
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    status VARCHAR(20) NOT NULL, -- 'running', 'success', 'failed'
    records_processed INTEGER DEFAULT 0,
    error_message TEXT,
    metadata JSONB -- Pour stocker des infos supplémentaires (year, department, etc.)
);

-- Index pour rechercher rapidement les exécutions récentes
CREATE INDEX IF NOT EXISTS idx_scraping_history_name ON scraping_history(scraper_name);
CREATE INDEX IF NOT EXISTS idx_scraping_history_started ON scraping_history(started_at);
CREATE INDEX IF NOT EXISTS idx_scraping_history_status ON scraping_history(status);

-- Vue pour voir les dernières exécutions par scraper
CREATE OR REPLACE VIEW v_last_scraping_runs AS
SELECT DISTINCT ON (scraper_name)
    scraper_name,
    started_at,
    completed_at,
    status,
    records_processed,
    EXTRACT(EPOCH FROM (completed_at - started_at)) as duration_seconds
FROM scraping_history
ORDER BY scraper_name, started_at DESC;

-- Commentaire
COMMENT ON TABLE scraping_history IS 'Historique des exécutions des scrapers avec statut et métriques';

SELECT 'Table scraping_history créée avec succès' as status;
