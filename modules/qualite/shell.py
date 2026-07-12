"""
Coquille du module Contrôle Qualité : barre latérale (recherche + liste des
paramètres importés) + zone de contenu qui bascule entre l'écran d'import
et le tableau de bord du paramètre sélectionné.
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QStackedWidget,
)
from PySide6.QtCore import Signal

from .import_screen import ImportScreen
from .dashboard import DashboardWidget
from .vue_ensemble import VueEnsemble


class QualiteModule(QWidget):
    retour_accueil = Signal()

    def __init__(self, conn):
        super().__init__()
        self.conn = conn
        self.dashboards: dict[int, DashboardWidget] = {}

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- Barre latérale ---
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(220)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(12, 12, 12, 12)

        btn_accueil = QPushButton("Retour vers Accueil")
        btn_accueil.setObjectName("PrimaryButton")
        btn_accueil.clicked.connect(self.retour_accueil.emit)
        side_layout.addWidget(btn_accueil)
        side_layout.addSpacing(16)

        btn_vue_ensemble = QPushButton("⊞ Vue d'ensemble")
        btn_vue_ensemble.setObjectName("BoutonAccueil")
        btn_vue_ensemble.clicked.connect(self._ouvrir_vue_ensemble)
        side_layout.addWidget(btn_vue_ensemble)
        side_layout.addSpacing(8)

        self.recherche = QLineEdit()
        self.recherche.setPlaceholderText("Rechercher un paramètre")
        self.recherche.textChanged.connect(self._filtrer_liste)
        side_layout.addWidget(self.recherche)

        self.liste_parametres = QListWidget()
        self.liste_parametres.itemClicked.connect(self._ouvrir_parametre)
        side_layout.addWidget(self.liste_parametres, stretch=1)

        btn_importer = QPushButton("+ Importer")
        btn_importer.setObjectName("PrimaryButton")
        btn_importer.clicked.connect(self._ouvrir_import)
        side_layout.addWidget(btn_importer)

        root.addWidget(sidebar)

        # --- Zone de contenu ---
        self.contenu = QStackedWidget()
        self.vue_ensemble = VueEnsemble(self.conn)
        self.vue_ensemble.parametre_choisi.connect(self._ouvrir_parametre_par_id)
        self.contenu.addWidget(self.vue_ensemble)

        self.import_screen = ImportScreen(self.conn)
        self.import_screen.import_termine.connect(self._sur_import_termine)
        self.contenu.addWidget(self.import_screen)

        root.addWidget(self.contenu, stretch=1)

        self._charger_parametres()

    def _charger_parametres(self):
        self.liste_parametres.clear()
        rows = self.conn.execute("SELECT id, nom FROM qc_parametres ORDER BY nom").fetchall()
        for parametre_id, nom in rows:
            item = QListWidgetItem(nom)
            item.setData(1000, parametre_id)  # rôle personnalisé pour retrouver l'id
            self.liste_parametres.addItem(item)

    def _filtrer_liste(self, texte: str):
        texte = texte.lower()
        for i in range(self.liste_parametres.count()):
            item = self.liste_parametres.item(i)
            item.setHidden(texte not in item.text().lower())

    def _ouvrir_parametre(self, item: QListWidgetItem):
        self._ouvrir_parametre_par_id(item.data(1000), item.text())

    def _ouvrir_parametre_par_id(self, parametre_id: int, nom: str):
        if parametre_id not in self.dashboards:
            self.dashboards[parametre_id] = DashboardWidget(self.conn, parametre_id, nom)
            self.contenu.addWidget(self.dashboards[parametre_id])
        self.contenu.setCurrentWidget(self.dashboards[parametre_id])

    def _ouvrir_import(self):
        self.contenu.setCurrentWidget(self.import_screen)

    def _ouvrir_vue_ensemble(self):
        self.vue_ensemble.rafraichir()
        self.contenu.setCurrentWidget(self.vue_ensemble)

    def _sur_import_termine(self):
        self._charger_parametres()
        # Invalide tous les tableaux de bord déjà ouverts : un import a pu changer
        # les tranches d'âge ou les données d'un paramètre déjà consulté, et un
        # widget mis en cache ne se rafraîchit jamais tout seul.
        for widget in self.dashboards.values():
            self.contenu.removeWidget(widget)
            widget.deleteLater()
        self.dashboards.clear()
        self.vue_ensemble.rafraichir()
        self.contenu.setCurrentWidget(self.vue_ensemble)
