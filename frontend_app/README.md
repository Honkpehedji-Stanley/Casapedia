# frontend_app — Interface Streamlit Casapedia

Interface d'exploration du marché immobilier (multi-échelles, cartographie, NLP).

## Lancer

```bash
pip install -r requirements.txt          # depuis la racine du projet
streamlit run frontend_app/app.py
```

Les connexions lisent les mêmes variables `.env` que le reste du projet
(`DB_*`, `MONGO_*`, `MINIO_*`). `MAPBOX_TOKEN` est optionnel (fonds Carto/OSM par défaut).

## Structure

```
frontend_app/
├── app.py            # entrée st.navigation (>=1.36)
├── lib/
│   ├── config.py     # env + constantes de domaine (échelles, classes DPE)
│   ├── connections.py# engine SQLAlchemy / MongoClient / boto3 (cache_resource)
│   ├── queries.py    # requêtes agrégées (cache_data)
│   └── formatting.py # formatage FR (€, m², milliers)
└── pages/
    ├── dashboard.py     # ✅ Sprint 0 — KPI nationaux + dataviz
    ├── carte.py         # 🚧 Sprint 1
    ├── comparateur.py   # 🚧 Sprint 4
    ├── fiche.py         # 🚧 Sprint 3
    ├── nlp.py           # 🚧 Sprint 5 (dépend de sentiment_reviews.py)
    └── methodologie.py  # ✅ sources + santé des données
```

## Stratégie de cache

- `cache_resource` : connexions vivantes (engine/client), un exemplaire par session.
- `cache_data` (ttl=1h) : résultats de requêtes, indexés par leurs arguments.
- Rafraîchir : `st.cache_data.clear()`.
