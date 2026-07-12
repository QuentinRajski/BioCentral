# BioCentral

Application de centralisation et de statistiques pour les exports de biologie médicale.
Module actif : Contrôle qualité (LH validé sur données réelles).

## Structure

```
biocentral/
├── main.py                        Point d'entrée. Lance la fenêtre, page d'accueil.
├── home.py                        Page d'accueil : liste des modules disponibles.
├── schema.sql                     Schéma SQLite complet (une base pour toute l'appli).
├── core/                          Socle commun, partagé par tous les modules.
│   ├── database.py                Connexion, persistance AppData, migrations.
│   ├── stats.py                   Moyenne / écart-type / médiane / percentiles.
│   └── theme.py                   Feuille de style (QSS) partagée.
└── modules/
    └── qualite/                   Module Contrôle Qualité (préfixe qc_ en base).
        ├── shell.py                Barre latérale (recherche + paramètres) + contenu.
        ├── import_screen.py        Écran d'import (fichier, domaine, tranches d'âge).
        ├── import_logic.py         Lecture Excel, classification, insertion en base.
        └── dashboard.py            Tableau, statistiques, percentiles par paramètre.
```

## Installer et lancer

```
pip install -r requirements.txt
python main.py
```

## Ce qui est fonctionnel dès maintenant

- Import réel d'un fichier Excel (testé sur votre fichier LH complet : 160 échantillons
  importés, 15 lignes de contrôle machine automatiquement écartées)
- Détection du paramètre en colonne 8 de l'en-tête (pas la dernière cellule non vide,
  pour ignorer une éventuelle colonne d'annotation comme « Domaine de mesure »)
- Classification des résultats (`valide` / `sous_seuil` / `sur_seuil` / `exclu`)
  selon toutes les règles validées ensemble
- Calcul de l'âge à partir de la date de naissance et de la date de prélèvement
- Attribution automatique de la tranche d'âge
- Garde-fou anti-doublon (confirmation si le paramètre existe déjà)
- Filtres tranche d'âge + sexe, tableau détaillé, statistiques descriptives,
  tableau de percentiles (2,5 à 97,5), et graphiques (2 histogrammes + 2
  camemberts, QtCharts) — tous branchés sur la vraie base et sur les mêmes filtres
- Persistance dans `%APPDATA%\BioCentral\biocentral.db`, indépendante de l'exécutable
- Export / import de la base (`core/database.py`, sauvegarde automatique avant remplacement)

## Ce qu'il reste à faire

- **Empaquetage PyInstaller** en `.exe` unique (pas encore fait)
- **Deuxième paramètre** à tester pour confirmer que la structure de colonnes est
  identique à celle de LH (colonne 8 = paramètre, mêmes colonnes fixes)
- Page d'accueil et « Extraire/Importer la BDD » : le bouton retour existe, le
  branchement complet des fonctions `export_database`/`import_database` de
  `core/database.py` à un bouton dans `home.py` reste à faire
