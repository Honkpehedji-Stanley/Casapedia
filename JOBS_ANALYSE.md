# Jobs d'analyse Casapedia

Ce document explique, de façon simple et précise, ce que font exactement les deux jobs Spark d'analyse du projet: `sentiment_analysis.py` et `ML_predictions.py`.

L'idée est de partir des données déjà nettoyées par `clean_tabulaires.py`, puis de produire des résultats exploitables pour le dashboard.

## 1. Ordre général du pipeline

Le pipeline suit cet ordre:

1. Les fichiers bruts sont déposés dans MinIO dans `s3a://casapedia-datalake/raw/...`.
2. `clean_tabulaires.py` nettoie et standardise les données, puis écrit les jeux de données curés dans `s3a://casapedia-datalake/processed/...`.
3. `sentiment_analysis.py` lit une source texte et calcule des indicateurs de sentiment, de thèmes et de mots-clés.
4. `ML_predictions.py` lit les données tabulaires déjà curées et entraîne un modèle de prédiction du prix au m².

## 2. Job `sentiment_analysis.py`

### But

Ce job prend des avis, commentaires ou messages textuels et transforme ce texte en indicateurs de sentiment, de thèmes et de mots-clés exploitables.

### Ce que le job lit

Par défaut, le job attend une source située dans `s3a://casapedia-datalake/raw/reviews`.

Point important: ce dossier n'est pas alimenté par l'ingestion actuelle. Aujourd'hui, le pipeline d'ingestion récupère les sources communes, INSEE, DVF et DPE, mais pas de jeux de données de type avis ou commentaires.

Donc, pour que ce job fonctionne, il faut soit:

- ajouter plus tard une ingestion dédiée aux reviews,
- soit fournir manuellement des fichiers texte dans ce chemin,
- soit changer la variable `CASAPEDIA_SENTIMENT_INPUT` vers une autre source texte existante.

Le format peut être:

- un fichier CSV,
- un fichier JSON,
- un fichier TXT,
- ou un dossier contenant plusieurs fichiers de ce type.

### Ce que le job fait exactement

1. Il lance une session Spark.
2. Il charge la source texte.
3. Il met les noms de colonnes en minuscules et enlève les espaces inutiles.
4. Il cherche automatiquement une colonne de texte parmi `text`, `review`, `comment`, `contenu`, `avis`, `message`.
5. Il cherche aussi, si elles existent, une colonne de commune, une note et une source.
6. Il garde uniquement les lignes qui contiennent un texte exploitable.
7. Il nettoie le texte en minuscules et supprime les caractères qui ne sont pas utiles pour l'analyse.
8. Il découpe le texte en mots.
9. Il compare chaque mot à deux listes fixes:
   - une liste de mots positifs,
   - une liste de mots négatifs.
10. Il attribue un score à chaque mot:
   - `+1` si le mot est positif,
   - `-1` si le mot est négatif,
   - `0` sinon.
11. Il regroupe les résultats par `commune_id`, `source`, `review_text`, `clean_text` et `rating`.
12. Il calcule:
   - le nombre total de mots,
   - le score total de sentiment.
13. Il transforme ce score en étiquette lisible:
   - `positive` si le score est supérieur à 0,
   - `negative` si le score est inférieur à 0,
   - `neutral` sinon.
14. Il construit aussi un tableau de fréquences de mots pour alimenter un nuage de mots.
15. Il détecte quelques thèmes métiers simples dans le texte:
   - sécurité,
   - transports,
   - écoles,
   - propreté,
   - cadre de vie,
   - commerces et services.
16. Il agrège ensuite ces thèmes pour produire des sorties plus explicatives que le score global seul.

### Ce que le job écrit

Il écrit quatre sorties dans MinIO:

- `s3a://casapedia-datalake/processed/nlp/sentiments`
- `s3a://casapedia-datalake/processed/nlp/wordclouds`
- `s3a://casapedia-datalake/processed/nlp/themes`
- `s3a://casapedia-datalake/processed/nlp/theme_sentiments`

### Ce que ce job ne fait pas

Ce job ne fait pas de modèle de langage avancé, pas de BERT, pas de transfert learning et pas d'IA générative.
Il utilise une méthode lexicale simple, donc basée sur des mots connus et un score déterministe.
La partie thèmes reste elle aussi simple et explicable: elle cherche la présence de mots-clés métier dans le texte.

### Résultat concret

À la fin, on obtient des données qui permettent par exemple d'afficher:

- un score de sentiment par avis,
- une répartition positive / négative / neutre,
- les mots les plus fréquents dans les commentaires,
- un tableau par thème pour expliquer pourquoi une ville ressort bien ou mal.

## 3. Job `ML_predictions.py`

### But

Ce job apprend à prédire le prix au m² à partir des données immobilières déjà curées.

### Ce que le job lit

Par défaut, il lit ces jeux de données déjà nettoyés:

- `s3a://casapedia-datalake/processed/transactions`
- `s3a://casapedia-datalake/processed/communes`
- `s3a://casapedia-datalake/processed/demographics`
- `s3a://casapedia-datalake/processed/dpe`

### Ce que le job fait exactement

1. Il lance une session Spark.
2. Il charge les tables curées depuis MinIO.
3. Il prend les transactions comme base principale.
4. Il garde les lignes où `prix_m2` est défini et strictement positif.
5. Il récupère pour chaque commune les coordonnées géographiques depuis la table communes.
6. Il récupère la population depuis la table démographie.
7. Il essaye aussi de récupérer des indicateurs DPE par commune:
   - moyenne des émissions de CO2,
   - moyenne de consommation d'énergie,
   - volume de logements DPE.
8. Si la table DPE n'est pas disponible ou ne peut pas être lue, le job continue avec des valeurs vides pour cette partie.
9. Il construit une base d'entraînement en combinant toutes ces sources.
10. Il extrait deux variables de temps:
    - l'année de transaction,
    - le mois de transaction.
11. Il prépare la partie numérique avec un `Imputer` pour remplacer les valeurs manquantes.
12. Il transforme la variable catégorielle `type_bien` avec:
    - `StringIndexer`,
    - puis `OneHotEncoder`.
13. Il assemble toutes les variables en un seul vecteur de caractéristiques.
14. Il entraîne une régression linéaire pour prédire `prix_m2`.
15. Il coupe les données en deux parties:
    - 80 % pour l'entraînement,
    - 20 % pour le test.
16. Il applique le modèle sur la partie test.
17. Il récupère les prédictions finales.
18. Il calcule les métriques du modèle:
    - `rmse`,
    - `mae`,
    - `r2`.
19. Il sauvegarde aussi le modèle entraîné.

### Ce que le job écrit

Il écrit trois sorties dans MinIO:

- `s3a://casapedia-datalake/processed/ml_predictions/predictions`
- `s3a://casapedia-datalake/processed/ml_predictions/metrics`
- `s3a://casapedia-datalake/processed/ml_predictions/model`

### Ce que ce job ne fait pas

Ce job ne fait pas de deep learning, pas de réseau de neurones et pas de prédiction basée sur un modèle pré-entraîné externe.
Il utilise une régression linéaire Spark MLlib, donc un modèle classique et interprétable.

### Résultat concret

À la fin, on obtient:

- une prédiction du prix au m² pour des biens testés,
- des métriques pour juger la qualité du modèle,
- un modèle sauvegardé pour réutilisation future.

## 4. Résumé très simple

- `sentiment_analysis.py` lit du texte et transforme ce texte en scores de sentiment, en fréquences de mots et en thèmes métier.
- `ML_predictions.py` lit les données immobilières curées et construit un modèle qui prédit le prix au m².

Les deux jobs lisent leurs données dans MinIO et écrivent leurs résultats dans MinIO.