## Télécharger

| Système | Fichier |
|---|---|
| **Windows 10 / 11** | **BioCentral.exe** (un seul fichier, rien à installer) |
| **Mac Apple Silicon** (M1, M2, M3, M4) | **BioCentral-mac.zip** |

Les fichiers sont dans la rubrique **Assets** ci-dessous : cliquez sur le nom pour télécharger.

### Windows
1. Téléchargez **BioCentral.exe** et double-cliquez dessus.
2. Si Windows affiche « Windows a protégé votre ordinateur » : *Informations complémentaires* › *Exécuter quand même* (l'application n'est pas signée).
3. Un écran « Démarrage en cours… » s'affiche, l'application s'ouvre en une dizaine de secondes.

### Mac
1. Téléchargez **BioCentral-mac.zip** puis double-cliquez dessus : **BioCentral.app** apparaît.
2. Glissez **BioCentral.app** dans le dossier **Applications**.
3. Premier lancement : **clic droit** sur BioCentral › **Ouvrir** › **Ouvrir** (l'application n'est pas signée par Apple).
   Si macOS refuse encore : *Réglages Système* › *Confidentialité et sécurité* › *Ouvrir quand même*.

## Contenu

- **Études de population** : statistiques, percentiles, intervalles de référence (CLSI EP28-A3c) et vérification d'intervalles fournisseur.
- **Contrôle interne de qualité** : cartes de Levey-Jennings, règles de Westgard, sigma.
- **Validation de méthodes** : Passing-Bablok, Deming, Bland-Altman, fidélité, justesse, incertitude de mesure.
- La **Base de connaissances** n'est pas incluse dans ces exécutables (PyTorch, plusieurs Go) : elle reste disponible en lançant BioCentral depuis les sources.

Les données restent sur l'ordinateur (`%APPDATA%\BioCentral_v2` sous Windows, `~/Library/Application Support/BioCentral_v2` sur Mac). Une base de la version 1 présente sur le poste est reprise automatiquement au premier lancement, sans être modifiée.

Ces outils aident au calcul et à la mise en forme ; l'interprétation et la validation restent sous la responsabilité du biologiste.
