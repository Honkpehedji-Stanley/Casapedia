# Jobs d'analyse Casapedia

Ce document décrit les deux jobs Spark d'analyse qui restent utiles dans le projet: le nettoyage des reviews et la prédiction du prix au m².

L'objectif est de partir de données déjà nettoyées par `clean_tabulaires.py`, puis de produire des résultats exploitables pour le dashboard et la base.

## 1. Ordre général du pipeline

1. Les fichiers bruts sont déposés dans MinIO dans `s3a://casapedia-datalake/raw/...`.
2. `clean_tabulaires.py` nettoie et standardise les données tabulaires, puis écrit les jeux de données curés dans `s3a://casapedia-datalake/processed/...`.
3. `clean_reviews.py` lit les avis bruts et les remet au propre.
4. `ML_predictions.py` lit les données tabulaires déjà curées et entraîne un modèle de prédiction du prix au m².

## 2. Job `clean_reviews.py`

### But

Ce job prend des avis, commentaires ou messages textuels et les normalise pour produire une version propre, stable et exploitable en base.

### Ce que le job lit

Par défaut, le job lit les avis bruts dans `s3a://casapedia-datalake/raw/reviews`.

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
8. Il conserve les champs utiles tels que `source`, `site`, `city_name`, `commune_id`, `rating`, `review_text`, `score_details` et ajoute `clean_text`.
9. Il écrit le jeu de données nettoyé dans `processed/reviews`.

### Ce que le job ne fait pas

Ce job ne calcule pas de sentiment, ne produit pas de nuage de mots et ne fabrique pas de score métier dérivé.
Il reste volontairement simple: un pré-traitement fiable des avis bruts avant stockage en base.

### Résultat concret

À la fin, on obtient un fichier propre qui permet par exemple d'afficher dans un flux d'actualité:

- la note,
- le commentaire nettoyé,
- la source,
- la ville ou la commune quand elle existe.

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

- `clean_reviews.py` lit les reviews brutes et les normalise pour la base de données.
- `ML_predictions.py` lit les données immobilières curées et construit un modèle qui prédit le prix au m².

Les deux jobs lisent leurs données dans MinIO et écrivent leurs résultats dans MinIO.

Note opérationnelle: le job de nettoyage tabulaire journalise aussi les années vues dans DVF et DPE, fixe le millésime INSEE au moment du traitement, et écrit un petit rapport QA sur les communes dans MinIO pour séparer les codes actifs du COG courant des codes historiques ou non courants.