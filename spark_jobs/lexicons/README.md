# FEEL — French Expanded Emotion Lexicon

**Source :** http://advanse.lirmm.fr/feel.php  
**Téléchargé le :** 2026-06-26  
**Référence :** Amine Abdaoui, Jérôme Azé, Sandra Bringay, Pascal Poncelet.  
  *FEEL: French Expanded Emotion Lexicon.* Language Resources and Evaluation, LRE 2016, pp 1–23.

## Format observé (feel_fr.csv)

| Colonne   | Type          | Valeurs                       |
|-----------|---------------|-------------------------------|
| id        | entier        | identifiant numérique         |
| word      | texte UTF-8   | mot ou expression française   |
| polarity  | texte         | `positive` ou `negative`      |
| joy       | 0/1           | émotion Ekman : joie          |
| fear      | 0/1           | émotion Ekman : peur          |
| sadness   | 0/1           | émotion Ekman : tristesse     |
| anger     | 0/1           | émotion Ekman : colère        |
| surprise  | 0/1           | émotion Ekman : surprise      |
| disgust   | 0/1           | émotion Ekman : dégoût        |

Séparateur : `;` — Encodage : UTF-8 (fins de ligne CRLF)  
Entrées : 14 127 (8 423 positives / 5 704 négatives)  
Dont 11 979 mots simples et 2 148 expressions multi-mots (2–6 tokens).

## Licence

FEEL ne dispose pas d'une licence CC formelle explicite. Il est dérivé par traduction
automatique et validation manuelle du lexique NRC-EmoLex (Mohammad & Turney, 2013),
dont l'usage est autorisé pour la recherche et l'enseignement à but non commercial.
Ce fichier est utilisé exclusivement dans ce cadre académique.
