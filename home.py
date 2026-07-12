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
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog, QMessageBox,
)
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QPixmap, QIcon

from core import database
from core.version import VERSION
from core.logs import LOG_PATH

ICON_PATH = Path(__file__).parent / "assets" / "icon.png"
ICONE_MODULE_QUALITE = Path(__file__).parent / "assets" / "icone_module_qualite.png"

# Registre des modules disponibles. Un futur module ajoute simplement une entrée ici.
AVAILABLE_MODULES = [
    {
        "id": "qualite",
        "nom": "Contrôle qualité",
        "description": "Centralisation et statistiques des résultats de biologie médicale",
        "icone": ICONE_MODULE_QUALITE,
    },
    # {"id": "modx", "nom": "...", "description": "...", "icone": None},
]


class HomePage(QWidget):
    module_selected = Signal(str)
    demande_fermeture = Signal()  # émis après un import de BDD réussi : l'appli doit redémarrer

    def __init__(self, conn):
        super().__init__()
        self.conn = conn
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 40, 40, 32)
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
        contenu.addSpacing(28)

        for module in AVAILABLE_MODULES:
            bouton = QPushButton(module["nom"])
            bouton.setObjectName("CarteModule")
            bouton.setFixedSize(280, 72)
            bouton.setCursor(Qt.PointingHandCursor)
            icone = module.get("icone")
            if icone and Path(icone).exists():
                bouton.setIcon(QIcon(str(icone)))
                bouton.setIconSize(QSize(32, 32))
            bouton.clicked.connect(lambda checked=False, m=module["id"]: self.module_selected.emit(m))
            contenu.addWidget(bouton, alignment=Qt.AlignCenter)

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
        btn_a_propos = QPushButton("ℹ À propos")
        btn_a_propos.clicked.connect(self._afficher_a_propos)
        ligne_bdd.addWidget(btn_a_propos)
        ligne_bdd.addStretch()
        pied.addLayout(ligne_bdd)

        note = QLabel("Pour sauvegarder vos données ou les transférer sur un autre poste.")
        note.setObjectName("Muted")
        note.setAlignment(Qt.AlignCenter)
        pied.addWidget(note)

        root.addLayout(pied)

    def _afficher_a_propos(self):
        QMessageBox.information(
            self, "À propos",
            f"BioCentral — version {VERSION}\n\n"
            f"Fichier de log :\n{LOG_PATH}\n\n"
            "En cas de problème, transmettez ce fichier pour obtenir de l'aide.",
        )

    def _exporter_bdd(self):
        chemin, _ = QFileDialog.getSaveFileName(
            self, "Extraire la base de données", "biocentral.db", "Base de données (*.db)"
        )
        if not chemin:
            return
        try:
            database.export_database(Path(chemin))
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
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:
                pass
        try:
            database.import_database(Path(chemin))
        except Exception as e:
            QMessageBox.critical(self, "Échec de l'import", f"Impossible d'importer la base : {e}")
            return
        QMessageBox.information(
            self, "Import terminé", "La base a été remplacée. L'application va maintenant se fermer."
        )
        self.demande_fermeture.emit()
