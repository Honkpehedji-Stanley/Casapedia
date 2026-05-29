-- Casapedia Database Schema
-- Base de données : casapedia_db

-- Extension PostGIS pour les données géographiques (optionnel mais recommandé)
CREATE EXTENSION IF NOT EXISTS postgis;

-- Table des communes
CREATE TABLE IF NOT EXISTS communes (
    code_insee VARCHAR(5) PRIMARY KEY,
    nom VARCHAR(255) NOT NULL,
    code_postal VARCHAR(10),
    dept VARCHAR(5) NOT NULL,
    dept_name VARCHAR(255),
    region_code VARCHAR(10),
    region VARCHAR(100) NOT NULL,
    latitude DECIMAL(10, 8),
    longitude DECIMAL(11, 8),
    population_actuelle INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index sur département et région pour les requêtes par zone
CREATE INDEX IF NOT EXISTS idx_communes_dept ON communes(dept);
CREATE INDEX IF NOT EXISTS idx_communes_region ON communes(region);

-- Table des transactions immobilières
CREATE TABLE IF NOT EXISTS transactions (
    id VARCHAR(100) PRIMARY KEY,
    commune_id VARCHAR(5) NOT NULL,
    date_transaction DATE NOT NULL,
    prix DECIMAL(15, 2) NOT NULL,
    surface DECIMAL(15, 4),
    prix_m2 DECIMAL(15, 4),
    type_bien VARCHAR(50) NOT NULL, -- 'appartement', 'maison', 'terrain', etc.
    nombre_pieces INTEGER,
    nature_mutation VARCHAR(100), -- 'Vente', 'Vente en l'état futur d'achèvement', etc.
    adresse VARCHAR(255),
    code_postal VARCHAR(10),
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
    id VARCHAR(100) PRIMARY KEY,
    commune_id VARCHAR(5) NOT NULL,
    classe_energetique VARCHAR(1) NOT NULL CHECK (classe_energetique IN ('A', 'B', 'C', 'D', 'E', 'F', 'G')),
    classe_ges VARCHAR(1) CHECK (classe_ges IN ('A', 'B', 'C', 'D', 'E', 'F', 'G')),
    emissions_co2 DECIMAL(15, 4), -- kg CO2/m²/an
    consommation_energie DECIMAL(15, 4), -- kWh/m²/an
    type_batiment VARCHAR(50), -- 'appartement', 'maison', etc.
    annee_construction INTEGER,
    surface DECIMAL(15, 4),
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

-- Tables source-specific pour les chargements processed
CREATE TABLE IF NOT EXISTS demographics_population (
    id SERIAL PRIMARY KEY,
    commune_id VARCHAR(5) NOT NULL REFERENCES communes(code_insee) ON DELETE CASCADE,
    annee INTEGER NOT NULL,
    population INTEGER,
    UNIQUE(commune_id, annee)
);

CREATE TABLE IF NOT EXISTS demographics_density (
    id SERIAL PRIMARY KEY,
    commune_id VARCHAR(5) NOT NULL REFERENCES communes(code_insee) ON DELETE CASCADE,
    annee INTEGER NOT NULL,
    nom_territoire VARCHAR(255),
    densite_population DECIMAL(15, 4),
    numerateur DECIMAL(15, 4),
    denominateur DECIMAL(15, 4),
    UNIQUE(commune_id, annee)
);

CREATE TABLE IF NOT EXISTS demographics_chomage (
    id SERIAL PRIMARY KEY,
    commune_id VARCHAR(5) NOT NULL REFERENCES communes(code_insee) ON DELETE CASCADE,
    annee INTEGER NOT NULL,
    actifs_15_64 DECIMAL(15, 4),
    chomeurs_15_64 DECIMAL(15, 4),
    taux_chomage DECIMAL(8, 6),
    UNIQUE(commune_id, annee)
);

CREATE TABLE IF NOT EXISTS revenue_disponible (
    id SERIAL PRIMARY KEY,
    age VARCHAR(50),
    mesure VARCHAR(50),
    nb_pers VARCHAR(50),
    nch VARCHAR(50),
    pcs VARCHAR(50),
    tph VARCHAR(50),
    statut_obs VARCHAR(50),
    unite_mesure VARCHAR(50),
    unite_mult VARCHAR(50),
    annee INTEGER,
    valeur DECIMAL(15, 4)
);

CREATE TABLE IF NOT EXISTS bpe_equipment (
    id SERIAL PRIMARY KEY,
    geo VARCHAR(50),
    geo_object VARCHAR(20),
    facility_dom VARCHAR(50),
    facility_dom_label VARCHAR(255),
    facility_sdom VARCHAR(50),
    facility_sdom_label VARCHAR(255),
    facility_type VARCHAR(50),
    facility_type_label VARCHAR(255),
    bpe_measure VARCHAR(50),
    annee INTEGER,
    valeur DECIMAL(15, 4)
);

CREATE TABLE IF NOT EXISTS bpe_rollups (
    id SERIAL PRIMARY KEY,
    annee INTEGER,
    geo VARCHAR(50),
    geo_object VARCHAR(20),
    facility_dom VARCHAR(50),
    facility_dom_label VARCHAR(255),
    facility_sdom VARCHAR(50),
    facility_sdom_label VARCHAR(255),
    equipements_total DECIMAL(15, 4)
);

CREATE TABLE IF NOT EXISTS bpe_evolution (
    id SERIAL PRIMARY KEY,
    geo VARCHAR(50),
    geo_object VARCHAR(20),
    facility_type VARCHAR(50),
    bpe_measure VARCHAR(50),
    annee INTEGER,
    valeur DECIMAL(15, 4)
);

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
WHERE date_transaction >= (
    SELECT MAX(date_transaction) - 365
    FROM transactions
)
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
