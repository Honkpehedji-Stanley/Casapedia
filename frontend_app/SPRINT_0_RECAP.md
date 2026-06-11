# Sprint 0 — Récap & review technique (frontend Streamlit)

Branche : `feat/streamlit-sprint-0` · 3 commits atomiques · **non pushée** · non testée au runtime
(Docker pas encore opérationnel au moment de la rédaction).

Périmètre livré : **couche data réutilisable + dashboard KPI nationaux + navigation multipage**.
Les pages Carte/Comparateur/Fiche/NLP sont des placeholders cadrés par sprint.

---

## 1. Diff par fichier (`main..HEAD`, 15 fichiers)

| Fichier | Statut | Description | Criticité |
|---|---|---|---|
| `requirements.txt` | modifié | Bump `streamlit>=1.40`, ajoute `pydeck` + `streamlit-folium`. | utilitaire (build) |
| `.gitignore` | modifié | Dé-ignore `frontend_app/lib/` (règle venv `lib/`) + ré-exclut son `__pycache__/`. | utilitaire (build) |
| `frontend_app/app.py` | créé | Entrée Streamlit : `set_page_config` + `st.navigation` (groupes Exploration/Analyses/À propos). | **cœur** |
| `frontend_app/lib/__init__.py` | créé | Docstring du package partagé. | utilitaire |
| `frontend_app/lib/config.py` | créé | Lit l'env (Postgres/Mongo/MinIO) + constantes domaine (échelles, classes DPE, token Mapbox optionnel). | **cœur** |
| `frontend_app/lib/connections.py` | créé | Engine SQLAlchemy / MongoClient / client boto3, tous en `@st.cache_resource`. | **cœur** |
| `frontend_app/lib/queries.py` | créé | Requêtes agrégées nationales (KPI, tendances, DPE, santé data) en `@st.cache_data(ttl=1h)`. | **cœur** |
| `frontend_app/lib/formatting.py` | créé | Formatage FR : €, €/m², milliers (espace insécable), compact (k/M). | utilitaire |
| `frontend_app/pages/dashboard.py` | créé | 4 KPI cards (§5.1) + courbe prix/m², barres type de bien, barres DPE ; dégradation si DB KO. | **cœur** |
| `frontend_app/pages/methodologie.py` | créé | Sources, formules, table « santé des données » (lignes/table). | utilitaire |
| `frontend_app/pages/carte.py` | créé | Placeholder Sprint 1 (choroplèthe/bulles/heatmap). | placeholder |
| `frontend_app/pages/comparateur.py` | créé | Placeholder Sprint 4 (comparaison multi-territoires). | placeholder |
| `frontend_app/pages/fiche.py` | créé | Placeholder Sprint 3 (KPI locaux + ML + avis). | placeholder |
| `frontend_app/pages/nlp.py` | créé | Placeholder Sprint 5 (sentiment + word cloud, dépend de `sentiment_reviews.py`). | placeholder |
| `frontend_app/README.md` | créé | Lancement, structure du dossier, stratégie de cache. | doc |

---

## 2. Choix techniques notables

### a) `cache_resource` (connexions) vs `cache_data` (résultats)
- **Choix** : connexions vivantes (engine SQLAlchemy, MongoClient, boto3) en `@st.cache_resource` ; DataFrames en `@st.cache_data(ttl=1h)`. Les fonctions cachées appellent `get_engine()` *à l'intérieur* (jamais la connexion passée en argument).
- **Pourquoi** : un seul pool de connexions partagé entre reruns/sessions ; les résultats sérialisables sont mémorisés par arguments.
- **Alternative non retenue** : tout mettre en `cache_data`, ou recréer la connexion à chaque rerun → fuite de connexions, objets non-sérialisables hashés par erreur.

### b) Médianes en SQL via `percentile_cont(0.5)`
- **Choix** : prix médian et prix/m² médian calculés côté PostgreSQL.
- **Pourquoi** : robuste aux valeurs extrêmes DVF (mieux que la moyenne) ; évite de rapatrier des millions de lignes dans Streamlit.
- **Alternative non retenue** : `AVG()` (sensible aux outliers) ou médiane en pandas (transfert massif + lent).

### c) Dégradation gracieuse (try/except + `st.stop()`)
- **Choix** : `dashboard.py` capture `SQLAlchemyError` → message clair + `st.stop()` ; les graphes testent `df.empty` → `st.info`.
- **Pourquoi** : une démo qui n'affiche jamais d'écran rouge même si la DB est vide/injoignable.
- **Alternative non retenue** : laisser l'exception remonter (stacktrace brut devant la prof).

### d) Stratégie carto token-optionnelle (préparée)
- **Choix** : `config.mapbox_token()` → `None` si pas de clé ; plan Plotly fond `open-street-map` par défaut + bascule Mapbox si token. `pydeck` ajouté (fond Carto sans token).
- **Pourquoi** : démarrer la Carte (Sprint 1) sans dépendre d'une clé API ; Epitech cite Mapbox (les traces Plotly mapbox SONT du Mapbox GL).
- **Alternative non retenue** : Folium comme socle → intégration `streamlit-folium` lourde, perf médiocre sur gros volumes (gardé en fallback uniquement).

### e) `width="stretch"` au lieu de `use_container_width`
- **Choix** : nouvelle API de dimensionnement des charts/dataframes.
- **Pourquoi** : `use_container_width` a été retiré des versions récentes de Streamlit → d'où le pin `>=1.40`.
- **Alternative non retenue** : `use_container_width=True` → casse sur Streamlit récent.

---

## 3. Hypothèses schéma DB (non validées au runtime)

Toutes les requêtes reposent sur le DDL lu dans `dags/dag_load_databases.py` (l.132-282).
Hypothèse globale : **la base réellement chargée correspond exactement à ce DDL.**

> ⚠️ **Aucune jointure SQL n'est exercée en Sprint 0.** Chaque KPI interroge une table isolée
> (`data_health` fait un `UNION ALL`, pas un JOIN). Les FK `commune_id → communes` du DDL
> ne sont donc pas testées avant le Sprint 1.

### Tables présumées exister
`transactions`, `communes`, `dpe`, et les 7 autres tables de publication pour la page Méthodologie :
`demographics_population`, `demographics_density`, `demographics_chomage`, `revenue_disponible`,
`bpe_equipment`, `bpe_rollups`, `bpe_evolution`.

### Colonnes utilisées (nom + type supposé)
| Table | Colonne | Type supposé | Usage |
|---|---|---|---|
| `transactions` | `prix` | DECIMAL | médiane prix |
| `transactions` | `prix_m2` | DECIMAL | médiane €/m², filtre `> 0` |
| `transactions` | `surface` | DECIMAL | (non utilisé Sprint 0, réservé) |
| `transactions` | `date_transaction` | **DATE** | `EXTRACT(YEAR …)` → ⚠️ critique |
| `transactions` | `type_bien` | VARCHAR | répartition par type |
| `communes` | `population_actuelle` | INTEGER | somme population nationale |
| `dpe` | `classe_energetique` | CHAR(1), A-G | répartition DPE |
| `revenue_disponible` | `valeur` | DECIMAL | **désactivé** (voir dette) |

### Jointures (clés étrangères supposées)
- Définies au DDL : `transactions.commune_id → communes.code_insee`, idem `dpe`, `demographics_*`.
- **Non exercées en Sprint 0.** Première utilisation au Sprint 1 (agrégats par `region_code`/`dept`/`code_insee`).

### Ambiguïtés à valider au 1er runtime
1. **`date_transaction` réellement typée `DATE` ?** Le DDL dit `DATE`, mais `ML_predictions.py` parse plusieurs formats (`yyyy-MM-dd`, `dd/MM/yyyy`, `yyyyMMdd`) → signe que la source est sale. Si la colonne est en TEXT, `EXTRACT(YEAR …)` plante.
2. **`population_actuelle` souvent NULL ?** Sinon population nationale sous-estimée.
3. **Valeurs `classe_energetique`** réellement bornées A-G (pas de `''`/`N`/`NULL` parasites) ?
4. **Les 10 tables existent toutes** ? Sinon le `UNION ALL` de `data_health` échoue (mais wrappé en try/except → warning, pas de crash).

---

## 4. Risques principaux au 1er `streamlit run`

1. **Connexion PostgreSQL** : `connections.get_engine()` utilise les défauts `DB_HOST=localhost` etc. Selon que Streamlit tourne sur l'hôte ou dans un conteneur, le host (`localhost` vs `postgres`) doit matcher → sinon timeout de connexion.
2. **`date_transaction` non-DATE** → `transactions_by_year()` lève une erreur SQL (cf. ambiguïté §3.1). Le dashboard tomberait dans le `except SQLAlchemyError` global du bloc KPI seulement si l'erreur survient là ; la courbe annuelle, elle, n'a pas de garde dédiée au-delà du `df.empty`.
3. **Version Streamlit < 1.40** dans l'environnement réel → `st.navigation`/`st.Page` et `width="stretch"` indisponibles. Vérifier `pip show streamlit` après install.
4. **Tables vides** (DAG `3_load_databases` pas encore exécuté) → KPI à `—`, graphes en `st.info`. Pas un crash, mais démo sans données.

---

## 5. Dette technique & points en attente

### Dette identifiée (à traiter Sprint 1)
- **Revenu médian national** : la médiane brute de `revenue_disponible.valeur` mélange plusieurs
  mesures/dimensions INSEE → **pas un vrai revenu médian**. KPI retiré du dashboard, requête conservée
  en commentaire + `TODO` dans `lib/queries.py`. À fiabiliser via les modalités
  (`unite_mesure` / `unite_mult` / filtres niveau géo) avant réintroduction.

### Points en attente (hors Sprint 0, commits séparés à venir)
- **`CASAPEDIA_DOC.md` ligne 117** : indique le sentiment « désactivé », ce qui contredit
  l'exigence Epitech (sentiment + word cloud) et le modèle Mongo (`nlp_*`). À corriger ;
  mentionner aussi que `ML_predictions.py` est fait (la doc le disait « à venir »).
- **Incohérence nom de base MongoDB** : `.env.example` = `casapedia_text`,
  `database/mongo_manager.py` défaut = `casapedia`. À aligner **avant** le branchement Mongo
  (Sprints 3/5), sinon l'UI lira une base vide.

---

## Reste pour Sprint 1 (Carte)
- Sourcer les **GeoJSON** France (régions/départements/communes) → `frontend_app/assets/geojson/` (**bloquant**).
- Choroplèthe Plotly + bulles communales + heatmap Pydeck.
- Ajouter à `lib/queries.py` les agrégats **par échelle** (`GROUP BY region_code/dept/code_insee`) — premières jointures FK.
- Sidebar `FilterState` partagé (préparé Sprint 2, l'échelle démarre ici).
