# BioCentral — version 2

Application de bureau (Python / PySide6) de centralisation et de statistiques pour
le laboratoire de biologie médicale. Quatre modules, une seule base SQLite locale :

| Module | Ce qu'il fait |
|---|---|
| 🧪 **Études de population** (ex-« Contrôle qualité ») | Import des exports Excel patients, statistiques descriptives, percentiles, tests (normalité, aberrants, F/M), **intervalle de référence CLSI EP28-A3c** avec IC à 90 %, **vérification d'un intervalle fournisseur** (règle des 10 %), rapport PDF |
| 📈 **Contrôle interne de qualité** *(nouveau)* | **Cartes de Levey-Jennings** par niveau et carte multi-niveaux en scores z, **règles de Westgard** (1-2s, 1-3s, 2-2s, R-4s, 4-1s, 10x, 7T, règles inter-niveaux), CV, biais, **sigma**, journal des passages, exclusions tracées, rapport PDF |
| ⚖ **Validation de méthodes** *(nouveau)* | **Comparaison de méthodes** (Passing-Bablok + test Cusum, Deming, moindres carrés, **Bland-Altman** absolu et %, corrélations, tests appariés, biais aux niveaux de décision), **fidélité** (répétabilité, fidélité intermédiaire par ANOVA), **justesse**, **incertitude de mesure** (CIQ + EEQ, Nordtest), rapports PDF |
| 📚 **Base de connaissances** | Recherche sémantique dans des PDF (inchangée sur le fond ; affichage et gestion des documents améliorés) |

## Installer et lancer

```
pip install -r requirements.txt
python main.py
```

ou double-cliquer sur `lancer_biocentral.bat`. Tests automatiques : `lancer_tests.bat`
(ou `python -m unittest discover -s tests -t .`).

PyTorch / sentence-transformers ne servent qu'à la Base de connaissances : sans eux,
l'application démarre quand même (en v1 elle plantait) et seul ce module est indisponible.

## Données : la v1 n'est jamais modifiée

- La v2 range ses données dans `%APPDATA%\BioCentral_v2\` (la v1 utilise `%APPDATA%\BioCentral\`).
- **Au tout premier lancement**, la base de la v1 est recopiée (copie en lecture seule de
  l'original), puis mise à niveau. Les deux versions peuvent cohabiter sur le poste.
  ⚠ Ce qui est saisi dans la v1 *après* ce premier lancement de la v2 n'est pas recopié :
  utiliser ensuite « Extraire la BDD » (v1) puis « Importer une BDD » (v2) si besoin.
- Sauvegarde automatique **avant chaque migration de schéma** et **une fois par jour** au
  lancement, dans `%APPDATA%\BioCentral_v2\sauvegardes\` (les 10 plus récentes sont conservées).
- Le bouton ℹ de l'accueil indique ces chemins et ouvre le dossier.

## Nouveautés et corrections de la v2

### Corrections (module Études de population et socle)
- **Tri des tableaux** : la classe de tri pouvait faire planter l'application (récursion infinie
  de `__lt__` sous PySide6 6.11) dès qu'une colonne contenait une cellule sans clé de tri.
- **Import Excel** : le paramètre était détecté sur la feuille *active* mais les données lues
  dans la feuille « Total » — les deux pouvaient diverger, et un classeur multi-feuilles sans
  « Total » plantait. Désormais une seule règle : « Total » si présente, sinon la 1re feuille.
- **Import transactionnel** : une erreur en cours d'import (sexe inattendu, etc.) pouvait
  laisser un paramètre à moitié importé. Désormais tout ou rien.
- Un nombre saisi en texte (`"4,8"`) était **exclu** des calculs : il est maintenant valide.
- Un résultat numérique **hors domaine de mesure** n'était signalé hors bornes qu'après une
  modification du domaine ; il l'est dès l'import (même règle partout).
- Sexe normalisé (`F`, `Femme`, `M`, `H`…), dates en texte (`13/02/1989`) acceptées ; une ligne
  illisible est comptée « incomplète » au lieu de faire échouer l'import.
- Tranches d'âge **vérifiées** (chevauchements, tranches vides) et âges non couverts signalés.
- Vue d'ensemble : un double-clic sur une ligne de **tranche** ouvrait un tableau de bord
  intitulé « Paramètre : 0 à 2 ans » ; l'export Excel écrivait « 12 (sur 160) » au lieu de nombres.
- « Importer une BDD » : un fichier invalide laissait l'application ouverte avec une base
  déconnectée. Le fichier est désormais **vérifié avant** de toucher à la base active.
- Statistiques sans valeur : « None » s'affichait ; un graphique remplacé restait visible en
  surimpression quelques instants.

### Ajouts au module Études de population
- **Aperçu du fichier** dès sa sélection (paramètre, effectifs, âges, dates) ; le domaine de
  mesure est pré-rempli depuis la colonne « Domaine de mesure » quand le fichier en a une.
  *Remarque : sur le fichier LH, elle indique 0,3 – 250 alors que la base v1 contient 0,03.*
- **Modèles de tranches d'âge**, unité des résultats, suppression d'un paramètre.
- **Intervalle de référence** du filtre en cours (rangs, IC 90 % binomial ou bootstrap,
  limite affichée « ≤ seuil » quand elle tombe sur des résultats « <seuil »).
- **Intervalles à vérifier** (global, par tranche et/ou sexe) avec verdict CLSI.
- Exports : rapport **PDF** et échantillons filtrés en **Excel**.
- Lors d'un réimport, notes, unité et intervalles de référence sont conservés.

## Structure

```
biocentral_v2/
├── main.py, home.py              Fenêtre principale, accueil (registre des modules)
├── schema.sql                    Schéma d'une base neuve (les migrations sont dans core/database.py)
├── core/                         Socle commun, indépendant des modules
│   ├── database.py               Connexion, migrations, sauvegardes, import/export de la base
│   ├── stats.py                  Statistiques descriptives (règles v1 inchangées)
│   ├── tests_statistiques.py     Shapiro-Wilk, Tukey, Mann-Whitney
│   ├── westgard.py               Règles de Westgard (sans interface)
│   ├── comparaison_methodes.py   Passing-Bablok, Deming, Bland-Altman… (sans interface)
│   ├── fidelite.py               Répétabilité, ANOVA, justesse (sans interface)
│   ├── intervalle_reference.py   CLSI EP28-A3c (sans interface)
│   ├── incertitude.py            Nordtest, sigma (sans interface)
│   ├── plot.py                   Graphique générique QPainter (LJ, Bland-Altman, régression…)
│   ├── charts.py                 Graphiques QtCharts du tableau de bord (v1)
│   ├── ui.py, formatage.py       Composants d'interface, formats nombres/dates
│   └── export.py                 PDF (Qt natif) et Excel
├── modules/
│   ├── qualite/                  Études de population (préfixe qc_)
│   ├── ciq/                      Contrôle interne de qualité (préfixe ciq_)
│   ├── validation/               Validation de méthodes (préfixe vm_)
│   └── connaissances/            Base de connaissances (préfixe kb_)
└── tests/                        Tests automatiques (unittest, base temporaire isolée)
```

## Références des méthodes

- Westgard JO et al., *A multi-rule Shewhart chart for quality control in clinical chemistry*, Clin Chem 1981.
- Passing H, Bablok W, J Clin Chem Clin Biochem 1983 ; Linnet K (Deming, jackknife), Clin Chem 1990/1993.
- Bland JM, Altman DG, Lancet 1986 ; Stat Methods Med Res 1999.
- CLSI EP09 (comparaison de méthodes), EP15 (fidélité/justesse), EP28-A3c (intervalles de référence).
- Nordtest TR 537 (incertitude de mesure) ; SH GTA 04 et SH GTA 14 (COFRAC).

Ces outils aident au calcul et à la mise en forme ; l'interprétation et la validation
restent sous la responsabilité du biologiste.

## Ce qu'il reste à faire

- Empaquetage PyInstaller en `.exe` (non fait, non testé).
- Tester l'import avec un deuxième paramètre (structure de colonnes identique à LH supposée).
- Import direct des fichiers d'export CIQ des automates (format propre à chaque fournisseur :
  aujourd'hui, collage depuis Excel ou fichier Date | Valeur).
