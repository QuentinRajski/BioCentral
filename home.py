"""
Page d'accueil : premier écran affiché au lancement. Liste les modules disponibles
sous forme de boutons-cartes cliquables, et donne accès à l'extraction/import de
la base de données complète (sauvegarde, changement de poste). Ajouter un futur
module = ajouter une entrée dans AVAILABLE_MODULES, rien d'autre à modifier ici.

Note technique : le module est un QPushButton (pas un QWidget personnalisé) —
les boutons se stylisent de façon fiable partout dans l'application, contrairement
à un QWidget custom dont le fond stylé ne s'affichait pas correctement sur Windows.
"""
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QFileDialog, QMessageBox, QGraphicsDropShadowEffect,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap, QColor

from core import database, theme
from core.version import VERSION
from core.logs import LOG_PATH
from core.theme_toggle import ThemeToggleButton

ICON_PATH = Path(__file__).parent / "assets" / "icon.png"

# Registre des modules disponibles. Un futur module ajoute simplement une entrée ici
# (la grille de cartes s'adapte automatiquement au nombre de modules).
AVAILABLE_MODULES = [
    {
        "id": "qualite",
        "nom": "Études de population",
        "description": "Statistiques, percentiles et intervalles de référence à partir des exports patients",
        "emoji": "🧪",
        "accent": theme.ACCENT_BLEU,
    },
    {
        "id": "ciq",
        "nom": "Contrôle interne de qualité",
        "nom_tuile": "Contrôle interne\nde qualité",
        "description": "Cartes de Levey-Jennings, règles de Westgard, sigma",
        "emoji": "📈",
        "accent": theme.ACCENT_ROSE,
    },
    {
        "id": "validation",
        "nom": "Validation de méthodes",
        "description": "Comparaison de méthodes, fidélité, justesse, incertitude de mesure",
        "emoji": "⚖",
        "accent": theme.ACCENT_VIOLET,
    },
    {
        "id": "connaissances",
        "nom": "Base de connaissances",
        "description": "Recherche sémantique dans des documents biologiques (PDF)",
        "emoji": "📚",
        "accent": theme.ACCENT_VERT,
    },
    # {"id": "modx", "nom": "...", "description": "...", "emoji": "...", "accent": theme.ACCENT_VIOLET},
]


class HomePage(QWidget):
    module_selected = Signal(str)
    demande_fermeture = Signal()  # émis après un import de BDD réussi : l'appli doit redémarrer

    def __init__(self, conn):
        super().__init__()
        self.conn = conn
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 32)

        # --- Coin supérieur : réglages de l'appli (à propos, thème), séparés des
        # actions sur les données pour ne pas tout mélanger dans le pied de page ---
        coin_haut = QHBoxLayout()
        coin_haut.addStretch()
        btn_a_propos = QPushButton("ℹ")
        btn_a_propos.setObjectName("ToggleTheme")
        btn_a_propos.setFixedSize(34, 34)
        btn_a_propos.setCursor(Qt.PointingHandCursor)
        btn_a_propos.setToolTip("À propos")
        btn_a_propos.clicked.connect(self._afficher_a_propos)
        coin_haut.addWidget(btn_a_propos)
        coin_haut.addWidget(ThemeToggleButton(self.conn))
        root.addLayout(coin_haut)

        root.addStretch(2)

        contenu = QVBoxLayout()
        contenu.setSpacing(16)
        contenu.setAlignment(Qt.AlignCenter)

        if ICON_PATH.exists():
            logo = QLabel()
            logo.setPixmap(QPixmap(str(ICON_PATH)).scaled(
                150, 150, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            logo.setAlignment(Qt.AlignCenter)
            logo.setTextInteractionFlags(Qt.NoTextInteraction)
            contenu.addWidget(logo)
            contenu.addSpacing(8)

        titre = QLabel("BioCentral")
        titre.setObjectName("TitreAccueil")
        titre.setAlignment(Qt.AlignCenter)
        titre.setTextInteractionFlags(Qt.NoTextInteraction)
        contenu.addWidget(titre)

        sous_titre = QLabel("Vos outils de biologie médicale, centralisés.")
        sous_titre.setObjectName("Muted")
        sous_titre.setAlignment(Qt.AlignCenter)
        contenu.addWidget(sous_titre)
        contenu.addSpacing(32)

        grille_widget = QWidget()
        grille = QGridLayout(grille_widget)
        grille.setHorizontalSpacing(24)
        grille.setVerticalSpacing(24)
        # 4 modules : grille 2 × 2, plus équilibrée qu'une ligne de 3 + 1 carte orpheline.
        colonnes = 2 if len(AVAILABLE_MODULES) == 4 else min(len(AVAILABLE_MODULES), 3)
        for i, module in enumerate(AVAILABLE_MODULES):
            grille.addWidget(self._creer_carte_module(module), i // colonnes, i % colonnes)
        contenu.addWidget(grille_widget, alignment=Qt.AlignCenter)

        root.addLayout(contenu)
        root.addStretch(3)

        # --- Pied de page : extraction/import de la base, toujours en bas ---
        pied = QVBoxLayout()
        pied.setSpacing(6)
        ligne_bdd = QHBoxLayout()
        ligne_bdd.setSpacing(10)
        ligne_bdd.addStretch()
        btn_exporter = QPushButton("⬇ Extraire la BDD")
        btn_exporter.clicked.connect(self._exporter_bdd)
        btn_importer = QPushButton("⬆ Importer une BDD")
        btn_importer.clicked.connect(self._importer_bdd)
        ligne_bdd.addWidget(btn_exporter)
        ligne_bdd.addWidget(btn_importer)
        ligne_bdd.addStretch()
        pied.addLayout(ligne_bdd)

        note = QLabel("Pour sauvegarder vos données ou les transférer sur un autre poste.")
        note.setObjectName("Muted")
        note.setAlignment(Qt.AlignCenter)
        pied.addWidget(note)

        root.addLayout(pied)

    def _creer_carte_module(self, module: dict) -> QWidget:
        """Carte d'un module : tuile cliquable (icône + nom, accent de couleur propre
        à chaque module) surmontée d'une légère ombre portée, avec sa description
        juste en dessous — plus parlant qu'un simple bouton texte."""
        conteneur = QWidget()
        disposition = QVBoxLayout(conteneur)
        disposition.setContentsMargins(0, 0, 0, 0)
        disposition.setSpacing(10)

        # « nom_tuile » : coupure de ligne explicite pour un nom trop long pour la tuile.
        tuile = QPushButton(f"{module['emoji']}\n{module.get('nom_tuile', module['nom'])}")
        tuile.setObjectName("CarteModule")
        tuile.setFixedSize(220, 130)
        tuile.setCursor(Qt.PointingHandCursor)
        tuile.setStyleSheet(f"border-top: 3px solid {module['accent']};")
        ombre = QGraphicsDropShadowEffect(tuile)
        ombre.setBlurRadius(24)
        ombre.setOffset(0, 6)
        ombre.setColor(QColor(0, 0, 0, 60))
        tuile.setGraphicsEffect(ombre)
        tuile.clicked.connect(lambda checked=False, m=module["id"]: self.module_selected.emit(m))
        disposition.addWidget(tuile, alignment=Qt.AlignCenter)

        description = QLabel(module["description"])
        description.setObjectName("Muted")
        description.setWordWrap(True)
        description.setAlignment(Qt.AlignCenter)
        description.setFixedWidth(220)
        disposition.addWidget(description)

        return conteneur

    def _afficher_a_propos(self):
        boite = QMessageBox(self)
        boite.setWindowTitle("À propos")
        boite.setIcon(QMessageBox.Information)
        boite.setText(
            f"BioCentral — version {VERSION}\n\n"
            f"Dossier de données :\n{database.get_data_dir()}\n\n"
            f"Sauvegardes automatiques (une par jour, {database.NOMBRE_SAUVEGARDES_CONSERVEES} conservées) :\n"
            f"{database.get_backup_dir()}\n\n"
            f"Fichier de log :\n{LOG_PATH}\n\n"
            "En cas de problème, transmettez ce fichier pour obtenir de l'aide.")
        ouvrir = boite.addButton("Ouvrir le dossier de données", QMessageBox.ActionRole)
        boite.addButton("Fermer", QMessageBox.AcceptRole)
        boite.exec()
        if boite.clickedButton() is ouvrir:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(database.get_data_dir())))

    def _exporter_bdd(self):
        chemin, _ = QFileDialog.getSaveFileName(
            self, "Extraire la base de données", "biocentral.db", "Base de données (*.db)"
        )
        if not chemin:
            return
        try:
            database.export_database(Path(chemin), self.conn)
        except Exception as e:
            QMessageBox.critical(self, "Échec de l'extraction", f"Impossible d'extraire la base : {e}")
            return
        QMessageBox.information(self, "Extraction terminée", f"Base de données copiée : {Path(chemin).name}")

    def _importer_bdd(self):
        chemin, _ = QFileDialog.getOpenFileName(
            self, "Importer une base de données", "", "Base de données (*.db)"
        )
        if not chemin:
            return
        reponse = QMessageBox.question(
            self, "Remplacer la base actuelle ?",
            "Ceci va remplacer entièrement la base de données actuelle par le fichier choisi.\n\n"
            "Une sauvegarde de l'ancienne base est conservée automatiquement avant le remplacement.\n\n"
            "L'application va ensuite se fermer — relancez-la pour utiliser la base importée.\n\n"
            "Continuer ?",
        )
        if reponse != QMessageBox.Yes:
            return
        # Vérification AVANT de fermer la connexion active : en v1, un fichier
        # invalide laissait l'application ouverte avec une base déconnectée.
        try:
            database.verifier_fichier_base(Path(chemin))
        except ValueError as e:
            QMessageBox.critical(self, "Fichier refusé", str(e))
            return
        if self.conn is not None:
            try:
                self.conn.commit()
                self.conn.close()
            except Exception:
                pass
        try:
            database.import_database(Path(chemin))
        except Exception as e:
            QMessageBox.critical(self, "Échec de l'import",
                                 f"Impossible d'importer la base : {e}\n\nL'application va se fermer ; "
                                 "relancez-la pour retrouver votre base actuelle.")
            self.demande_fermeture.emit()
            return
        QMessageBox.information(
            self, "Import terminé", "La base a été remplacée. L'application va maintenant se fermer."
        )
        self.demande_fermeture.emit()
