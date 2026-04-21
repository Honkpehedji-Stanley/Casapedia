# Jobs d'analyse Casapedia

Ce document explique simplement ce que font les deux jobs d'analyse ajoutés au projet: `sentiment_analysis.py` et `ML_predictions.py`, comment ils fonctionnent, et ce qu'on peut en tirer pour le dashboard.

## 1. Rôle des jobs

L'objectif du pipeline n'est pas seulement de nettoyer les données. Il faut aussi produire des données analytiques utiles pour l'utilisateur final.

- `clean_tabulaires.py` prépare les jeux de données tabulaires propres dans `datalake/processed`.
- `sentiment_analysis.py` produit des indicateurs textuels à partir d'avis ou de commentaires.
- `ML_predictions.py` construit un modèle de prédiction du prix au m² à partir des données déjà curées.

Les sorties de ces jobs sont d'abord écrites dans `datalake/processed`. Ensuite, lors d'une étape future, les jeux de données les plus utiles pourront être publiés vers PostgreSQL et MongoDB.

## 2. Job `sentiment_analysis.py`

### But

Ce job analyse du texte libre, par exemple des avis de ville, des commentaires ou des notes qualitatives. Il ne cherche pas à comprendre le langage comme un grand modèle de langage moderne. Il calcule plutôt un score simple, stable et lisible.

### Entrées

- Une source texte située par défaut dans `datalake/raw/reviews`.
- Le format attendu peut être `CSV`, `JSON` ou `TXT`.
- Le job essaie d'identifier automatiquement des colonnes comme `text`, `review`, `comment`, `note`, `source` ou `commune_id`.

### Ce que fait le job

1. Il nettoie le texte.
2. Il met tout en minuscules.
3. Il retire les caractères parasites.
4. Il découpe le texte en mots.
5. Il compare les mots à deux listes manuelles:
   - mots positifs
   - mots négatifs
6. Il calcule un score de sentiment par avis.
7. Il produit aussi une base de fréquences de mots pour les nuages de mots.

### Type de méthode utilisée

Ce job n'utilise pas actuellement:

- de transfert learning,
- de modèle de type BERT,
- de modèle open source pré-entraîné,
- de deep learning.

Il s'agit d'une méthode lexicale et déterministe, donc plus simple à interpréter. Le calcul est basé sur la présence de mots positifs ou négatifs dans le texte.

### Sorties produites

- `datalake/processed/nlp/sentiments`
- `datalake/processed/nlp/wordclouds`

### Ce que cela permet d'afficher

- score moyen de sentiment par ville ou par zone,
- répartition positif / neutre / négatif,
- nuages de mots par commune ou par source,
- classement des villes les plus positives ou les plus négatives,
- comparaison de perception entre territoires.

## 3. Job `ML_predictions.py`

### But

Ce job apprend à prédire le prix au m² à partir des données immobilières et territoriales déjà préparées.

### Entrées

- `datalake/processed/transactions`
- `datalake/processed/communes`
- `datalake/processed/demographics`
- `datalake/processed/dpe`

### Variables utilisées

Le modèle exploite notamment:

- la surface,
- le nombre de pièces,
- la latitude et la longitude,
- la population,
- les indicateurs DPE agrégés,
- le type de bien,
- le mois et l'année de transaction.

### Ce que fait le job

1. Il charge les tables curées.
2. Il joint les informations de transaction, de commune, de démographie et de DPE.
3. Il transforme les colonnes pour le modèle.
4. Il remplit les valeurs manquantes avec un `Imputer`.
5. Il encode la variable catégorielle `type_bien`.
6. Il assemble toutes les variables en un vecteur de features.
7. Il entraîne une régression linéaire Spark ML.
8. Il teste le modèle sur une partie des données.
9. Il sort les prédictions et les métriques.

### Type de méthode utilisée

Ce job n'utilise pas de transfert learning non plus.

Il ne réutilise pas un modèle IA open source pré-entraîné. Il entraîne un modèle supervisé classique sur nos propres données, donc on est sur une logique d'apprentissage depuis nos données projet, pas sur un modèle de langage ni sur un réseau profond.

En clair:

- ce n'est pas du deep learning,
- ce n'est pas du from scratch au sens réseau de neurones complexe,
- c'est un modèle Spark ML supervisé, simple, explicable et adapté à un MVP analytique.

### Sorties produites

- `datalake/processed/ml_predictions/predictions`
- `datalake/processed/ml_predictions/metrics`
- `datalake/processed/ml_predictions/model`

### Ce que cela permet d'afficher

- carte des prix au m² prédits,
- comparaison prix réel vs prix prédit,
- évolution estimée du marché,
- zones sous-évaluées ou surévaluées,
- indicateurs de performance du modèle comme `rmse`, `mae` et `r2`.

## 4. Est-ce qu'on peut faire des graphes utiles avec ces données ?

Oui, clairement.

Les données curées + les sorties de prédiction + les sorties sentiment permettent déjà de construire beaucoup de graphiques à forte valeur:

- cartes géographiques,
- courbes temporelles,
- histogrammes de prix et de surface,
- boxplots par région ou département,
- heatmaps de densité de transactions,
- cartes de prix réels et prédits,
- comparaison des performances énergétiques par territoire,
- classement des zones selon le sentiment,
- nuages de mots par ville ou par thème,
- tableaux de synthèse filtrables.

## 5. Les données sont-elles suffisantes pour un dashboard utile ?

Oui, pour un dashboard immobilier solide, les données actuelles sont déjà très utiles.

### Ce que l'on peut déjà faire de concret

- comprendre le niveau de prix d'un territoire,
- comparer plusieurs zones,
- voir l'évolution du marché dans le temps,
- relier les prix au contexte démographique,
- relier les prix à la performance énergétique,
- estimer un prix attendu,
- montrer une perception textuelle d'un quartier ou d'une ville.

### Ce qui donnera le plus de valeur utilisateur

- prix médian et prix au m² par zone,
- évolution temporelle des prix,
- comparaison réel vs prédit,
- part des biens selon leur type,
- classes DPE et impact énergétique,
- population et densité,
- indicateurs textuels si on a de vrais avis.

## 6. Limites actuelles

Le potentiel est bon, mais il faut rester rigoureux sur deux points.

- Le job de sentiment a besoin de vraies données textuelles pour produire un signal vraiment utile.
- Le job de prédiction sera meilleur si on enrichit les variables explicatives et si on valide le modèle sur un historique plus large.

Donc oui, on peut déjà faire des graphes utiles. Mais pour avoir des graphes vraiment robustes et très parlants, il faudra ensuite renforcer la qualité et la diversité des données, surtout pour la partie textuelle.

## 7. Résumé simple

- `sentiment_analysis.py` = score de sentiment et nuages de mots à partir de texte.
- `ML_predictions.py` = prédiction du prix au m² avec Spark ML.
- Les deux jobs écrivent d'abord dans `processed`.
- Les bases de données serviront plus tard pour la publication finale et la consommation applicative.
- Les données actuelles sont déjà suffisantes pour construire un dashboard immobilier utile, à condition de bien choisir les indicateurs.