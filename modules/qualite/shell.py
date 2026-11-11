"""
Coquille du module Études de population (anciennement « Contrôle qualité ») : barre latérale (recherche + liste des
paramètres importés) + zone de contenu qui bascule entre l'écran d'import
et le tableau de bord du paramètre sélectionné.
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QStackedWidget,
)
from PySide6.QtCore import Signal

from core.nav_widgets import breadcrumb_label, entete_barre_laterale, section_label

from .import_screen import ImportScreen
from .dashboard import DashboardWidget
from .vue_ensemble import VueEnsemble

FIL_ARIANE_PREFIXE = "BioCentral › Études de population"


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
        side_layout.setSpacing(4)

        side_layout.addWidget(entete_barre_laterale(self.conn, self.retour_accueil.emit))
        side_layout.addSpacing(14)

        side_layout.addWidget(section_label("Navigation"))
        self.btn_vue_ensemble = QPushButton("⊞ Vue d'ensemble")
        self.btn_vue_ensemble.setObjectName("BoutonAccueil")
        self.btn_vue_ensemble.setCheckable(True)
        self.btn_vue_ensemble.setChecked(True)
        self.btn_vue_ensemble.clicked.connect(self._ouvrir_vue_ensemble)
        side_layout.addWidget(self.btn_vue_ensemble)
        side_layout.addSpacing(14)

        side_layout.addWidget(section_label("Paramètres importés"))
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

        # --- Zone de contenu : fil d'Ariane + contenu qui bascule ---
        colonne_contenu = QVBoxLayout()
        colonne_contenu.setContentsMargins(0, 0, 0, 0)
        colonne_contenu.setSpacing(0)

        self.fil_ariane = breadcrumb_label()
        colonne_contenu.addWidget(self.fil_ariane)

        self.contenu = QStackedWidget()
        self.vue_ensemble = VueEnsemble(self.conn)
        self.vue_ensemble.parametre_choisi.connect(self._ouvrir_parametre_par_id)
        self.contenu.addWidget(self.vue_ensemble)

        self.import_screen = ImportScreen(self.conn)
        self.import_screen.import_termine.connect(self._sur_import_termine)
        self.contenu.addWidget(self.import_screen)

        colonne_contenu.addWidget(self.contenu, stretch=1)

        contenu_widget = QWidget()
        contenu_widget.setLayout(colonne_contenu)
        root.addWidget(contenu_widget, stretch=1)

        self._charger_parametres()
        self._definir_fil_ariane("Vue d'ensemble")

    def _definir_fil_ariane(self, suffixe: str) -> None:
        self.fil_ariane.setText(f"{FIL_ARIANE_PREFIXE} › {suffixe}")

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

    def _selectionner_parametre_dans_liste(self, parametre_id: int) -> None:
        for i in range(self.liste_parametres.count()):
            item = self.liste_parametres.item(i)
            if item.data(1000) == parametre_id:
                self.liste_parametres.setCurrentItem(item)
                return

    def _ouvrir_parametre(self, item: QListWidgetItem):
        self._ouvrir_parametre_par_id(item.data(1000), item.text())

    def _ouvrir_parametre_par_id(self, parametre_id: int, nom: str):
        if parametre_id not in self.dashboards:
            tableau = DashboardWidget(self.conn, parametre_id, nom)
            tableau.supprime.connect(lambda pid=parametre_id: self._sur_suppression(pid))
            self.dashboards[parametre_id] = tableau
            self.contenu.addWidget(tableau)
        self.contenu.setCurrentWidget(self.dashboards[parametre_id])
        # Le tableau de bord peut être ouvert depuis la vue d'ensemble (double-clic) :
        # on aligne l'état de la barre latérale (case cochée + sélection) dans tous les cas.
        self.btn_vue_ensemble.setChecked(False)
        self._selectionner_parametre_dans_liste(parametre_id)
        self._definir_fil_ariane(nom)

    def _ouvrir_import(self):
        self.contenu.setCurrentWidget(self.import_screen)
        self.btn_vue_ensemble.setChecked(False)
        self.liste_parametres.clearSelection()
        self._definir_fil_ariane("Importer un paramètre")

    def _ouvrir_vue_ensemble(self):
        self.vue_ensemble.rafraichir()
        self.contenu.setCurrentWidget(self.vue_ensemble)
        self.btn_vue_ensemble.setChecked(True)
        self.liste_parametres.clearSelection()
        self._definir_fil_ariane("Vue d'ensemble")

    def _sur_import_termine(self):
        self._charger_parametres()
        # Invalide tous les tableaux de bord déjà ouverts : un import a pu changer
        # les tranches d'âge ou les données d'un paramètre déjà consulté, et un
        # widget mis en cache ne se rafraîchit jamais tout seul.
        for widget in self.dashboards.values():
            self.contenu.removeWidget(widget)
            widget.deleteLater()
        self.dashboards.clear()
        self._ouvrir_vue_ensemble()

    def _sur_suppression(self, parametre_id: int):
        tableau = self.dashboards.pop(parametre_id, None)
        if tableau is not None:
            self.contenu.removeWidget(tableau)
            tableau.deleteLater()
        self._charger_parametres()
        self._ouvrir_vue_ensemble()
