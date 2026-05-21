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

- `s3a://casapedia-datalake/processed/transactions/transactions.jsonl`
- `s3a://casapedia-datalake/processed/communes/communes.jsonl`
- `s3a://casapedia-datalake/processed/demographics/demographics.jsonl`
- `s3a://casapedia-datalake/processed/demographics/density.jsonl`
- `s3a://casapedia-datalake/processed/demographics/chomage_commune.jsonl`
- `s3a://casapedia-datalake/processed/dpe/dpe.jsonl`

### Ce que le job fait exactement

1. Il lance une session Spark et lit les fichiers JSONL curés depuis MinIO.
2. Il prend `transactions` comme table principale, parce que c'est elle qui porte la cible `prix_m2`.
3. Il écarte les lignes inutilisables, notamment celles où `prix_m2` est nul, négatif ou absent.
4. Il ajoute les variables de contexte par jointure sur `commune_id`:
   - coordonnées depuis `communes`,
   - population depuis `demographics`,
   - densité depuis `density`,
   - chômage depuis `chomage_commune`,
   - agrégats DPE depuis `dpe`.
5. Il construit les variables temporelles `transaction_year` et `transaction_month` à partir de `date_transaction`.
6. Il transforme les champs numériques avec un `Imputer` pour remplacer les valeurs manquantes par une valeur cohérente calculée sur le train.
7. Il encode `type_bien` avec `StringIndexer` puis `OneHotEncoder`, afin que Spark puisse utiliser cette catégorie dans une régression.
8. Il assemble toutes les colonnes explicatives dans un seul vecteur `features`.
9. Il sépare les données en deux jeux:
   - 80 % pour l'entraînement,
   - 20 % pour le test.
10. Il entraîne un modèle de régression linéaire pour apprendre la relation entre les variables explicatives et `prix_m2`.
11. Il applique le modèle sur le jeu de test pour obtenir `predicted_prix_m2`.
12. Il calcule les métriques de qualité:
   - `rmse` mesure l'erreur moyenne au carré,
   - `mae` mesure l'erreur moyenne absolue,
   - `r2` mesure la part de variance expliquée.
13. Il sauvegarde enfin les prédictions, les métriques et le modèle entraîné dans MinIO.

### Pourquoi cette approche

Le choix de la régression linéaire est volontaire: il donne un modèle simple à relire, rapide à entraîner et facile à expliquer.

Le but n'est pas de prédire un prix futur magique, mais d'estimer le prix au m² attendu d'un bien à partir des caractéristiques observées dans l'historique. Le modèle compare donc toujours du réel connu à du prédit sur des données passées, ce qui permet de juger sa qualité.

### Lecture du résultat

À la fin, une ligne de prédiction contient notamment:

- la commune,
- la date de transaction,
- le type de bien,
- la surface,
- le prix réel,
- le prix réel au m²,
- le prix au m² prédit,
- la population,
- la densité,
- le taux de chômage,
- les indicateurs DPE.

Ces sorties servent ensuite à faire:

- des comparaisons réel vs prédit sur l'historique,
- des cartes par territoire,
- des courbes d'erreur du modèle,
- des vues de contexte autour du marché immobilier.

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
- `ML_predictions.py` lit les données immobilières curées, ajoute les variables de contexte utiles et construit un modèle qui prédit le prix au m².

Les deux jobs lisent leurs données dans MinIO et écrivent leurs résultats dans MinIO.

Note opérationnelle: le job de nettoyage tabulaire journalise aussi les années vues dans DVF et DPE, fixe le millésime INSEE au moment du traitement, et écrit un petit rapport QA sur les communes dans MinIO pour séparer les codes actifs du COG courant des codes historiques ou non courants.