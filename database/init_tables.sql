-- Casapedia Database Schema
-- Base de données : casapedia_db

-- Extension PostGIS pour les données géographiques (optionnel mais recommandé)
CREATE EXTENSION IF NOT EXISTS postgis;

-- Table des communes
CREATE TABLE IF NOT EXISTS communes (
    code_insee VARCHAR(5) PRIMARY KEY,
    nom VARCHAR(255) NOT NULL,
    dept VARCHAR(3) NOT NULL,
    region VARCHAR(100) NOT NULL,
    latitude DECIMAL(10, 7),
    longitude DECIMAL(10, 7),
    population_actuelle INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index sur département et région pour les requêtes par zone
CREATE INDEX IF NOT EXISTS idx_communes_dept ON communes(dept);
CREATE INDEX IF NOT EXISTS idx_communes_region ON communes(region);

-- Table des transactions immobilières
CREATE TABLE IF NOT EXISTS transactions (
    id SERIAL PRIMARY KEY,
    commune_id VARCHAR(5) NOT NULL,
    date_transaction DATE NOT NULL,
    prix DECIMAL(12, 2) NOT NULL,
    surface DECIMAL(10, 2),
    prix_m2 DECIMAL(10, 2),
    type_bien VARCHAR(50) NOT NULL, -- 'appartement', 'maison', 'terrain', etc.
    nombre_pieces INTEGER,
    nature_mutation VARCHAR(100), -- 'Vente', 'Vente en l'état futur d'achèvement', etc.
    adresse TEXT,
    code_postal VARCHAR(5),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (commune_id) REFERENCES communes(code_insee) ON DELETE CASCADE
);

-- Index pour optimiser les recherches
CREATE INDEX IF NOT EXISTS idx_transactions_commune ON transactions(commune_id);
CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(date_transaction);
CREATE INDEX IF NOT EXISTS idx_transactions_type ON transactions(type_bien);
CREATE INDEX IF NOT EXISTS idx_transactions_prix ON transactions(prix);

-- Table des données démographiques
CREATE TABLE IF NOT EXISTS demographics (
    id SERIAL PRIMARY KEY,
    commune_id VARCHAR(5) NOT NULL,
    annee INTEGER NOT NULL,
    population INTEGER,
    densite DECIMAL(10, 2), -- habitants/km²
    revenu_median DECIMAL(10, 2),
    taux_chomage DECIMAL(5, 2),
    nombre_menages INTEGER,
    taille_moyenne_menage DECIMAL(4, 2),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (commune_id) REFERENCES communes(code_insee) ON DELETE CASCADE,
    UNIQUE(commune_id, annee)
);

-- Index pour les requêtes par commune et année
CREATE INDEX IF NOT EXISTS idx_demographics_commune ON demographics(commune_id);
CREATE INDEX IF NOT EXISTS idx_demographics_annee ON demographics(annee);

-- Table des diagnostics de performance énergétique (DPE)
CREATE TABLE IF NOT EXISTS dpe (
    id SERIAL PRIMARY KEY,
    commune_id VARCHAR(5) NOT NULL,
    classe_energetique VARCHAR(1) NOT NULL CHECK (classe_energetique IN ('A', 'B', 'C', 'D', 'E', 'F', 'G')),
    classe_ges VARCHAR(1) CHECK (classe_ges IN ('A', 'B', 'C', 'D', 'E', 'F', 'G')),
    emissions_co2 DECIMAL(10, 2), -- kg CO2/m²/an
    consommation_energie DECIMAL(10, 2), -- kWh/m²/an
    type_batiment VARCHAR(50), -- 'appartement', 'maison', etc.
    annee_construction INTEGER,
    surface DECIMAL(10, 2),
    date_etablissement DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (commune_id) REFERENCES communes(code_insee) ON DELETE CASCADE
);

-- Index pour analyser les DPE par commune et classe
CREATE INDEX IF NOT EXISTS idx_dpe_commune ON dpe(commune_id);
CREATE INDEX IF NOT EXISTS idx_dpe_classe ON dpe(classe_energetique);
CREATE INDEX IF NOT EXISTS idx_dpe_annee_construction ON dpe(annee_construction);

-- Table des infrastructures et équipements
CREATE TABLE IF NOT EXISTS infrastructure (
    id SERIAL PRIMARY KEY,
    commune_id VARCHAR(5) NOT NULL,
    type_equipement VARCHAR(100) NOT NULL, -- 'ecole_primaire', 'college', 'gare', 'hopital', etc.
    nombre INTEGER NOT NULL DEFAULT 1,
    nom VARCHAR(255),
    adresse TEXT,
    latitude DECIMAL(10, 7),
    longitude DECIMAL(10, 7),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (commune_id) REFERENCES communes(code_insee) ON DELETE CASCADE
);

-- Index pour les requêtes par commune et type d'équipement
CREATE INDEX IF NOT EXISTS idx_infrastructure_commune ON infrastructure(commune_id);
CREATE INDEX IF NOT EXISTS idx_infrastructure_type ON infrastructure(type_equipement);

-- Vues utiles pour les analyses

-- Vue : Prix médian par commune
CREATE OR REPLACE VIEW v_prix_median_communes AS
SELECT 
    commune_id,
    c.nom as commune_nom,
    c.dept,
    c.region,
    COUNT(*) as nb_transactions,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY prix) as prix_median,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY prix_m2) as prix_m2_median,
    AVG(prix) as prix_moyen,
    AVG(surface) as surface_moyenne
FROM transactions t
JOIN communes c ON t.commune_id = c.code_insee
WHERE date_transaction >= CURRENT_DATE - INTERVAL '12 months'
GROUP BY commune_id, c.nom, c.dept, c.region;

-- Vue : Statistiques DPE par commune
CREATE OR REPLACE VIEW v_dpe_stats_communes AS
SELECT 
    commune_id,
    c.nom as commune_nom,
    COUNT(*) as nb_dpe,
    COUNT(CASE WHEN classe_energetique IN ('A', 'B', 'C') THEN 1 END) as nb_bonne_perf,
    COUNT(CASE WHEN classe_energetique IN ('F', 'G') THEN 1 END) as nb_mauvaise_perf,
    ROUND(100.0 * COUNT(CASE WHEN classe_energetique IN ('A', 'B', 'C') THEN 1 END) / COUNT(*), 2) as pct_bonne_perf,
    AVG(consommation_energie) as conso_energie_moyenne,
    AVG(emissions_co2) as emissions_co2_moyenne
FROM dpe d
JOIN communes c ON d.commune_id = c.code_insee
GROUP BY commune_id, c.nom;

-- Commentaires sur les tables
COMMENT ON TABLE communes IS 'Référentiel des communes françaises avec coordonnées géographiques';
COMMENT ON TABLE transactions IS 'Transactions immobilières issues de la base DVF';
COMMENT ON TABLE demographics IS 'Données démographiques et économiques par commune et année';
COMMENT ON TABLE dpe IS 'Diagnostics de Performance Énergétique des logements';
COMMENT ON TABLE infrastructure IS 'Équipements et infrastructures par commune';

-- Afficher un résumé
SELECT 'Tables créées avec succès' as status;
