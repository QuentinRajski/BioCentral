"""
Coquille du module Validation de méthodes : barre latérale (outils + études
enregistrées) et zone de contenu.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QListWidget, QListWidgetItem, QMenu, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from core import ui
from core.formatage import date_fr
from core.nav_widgets import breadcrumb_label, entete_barre_laterale, section_label

from . import logic
from .comparaison_view import ComparaisonView
from .fidelite_view import FideliteView
from .incertitude_view import IncertitudeView

FIL_ARIANE_PREFIXE = "BioCentral › Validation de méthodes"
ETUDE_ID_ROLE = Qt.UserRole + 1
ICONES = {logic.TYPE_COMPARAISON: "⇄", logic.TYPE_FIDELITE: "◎"}


class ValidationModule(QWidget):
    retour_accueil = Signal()

    def __init__(self, conn):
        super().__init__()
        self.conn = conn
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(250)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(12, 12, 12, 12)
        side.setSpacing(4)
        side.addWidget(entete_barre_laterale(self.conn, self.retour_accueil.emit))
        side.addSpacing(14)
        side.addWidget(section_label("Outils"))

        self.comparaison = ComparaisonView(conn)
        self.fidelite = FideliteView(conn)
        self.incertitude = IncertitudeView(conn)
        self.boutons: dict[QWidget, QPushButton] = {}
        for vue, texte in ((self.comparaison, "⇄ Comparaison de méthodes"), (self.fidelite, "◎ Fidélité et justesse"),
                           (self.incertitude, "± Incertitude et sigma")):
            bouton = QPushButton(texte)
            bouton.setObjectName("BoutonAccueil")
            bouton.setCheckable(True)
            bouton.clicked.connect(lambda _=False, v=vue: self._afficher(v))
            side.addWidget(bouton)
            self.boutons[vue] = bouton
        side.addSpacing(14)
        side.addWidget(section_label("Études enregistrées"))
        self.liste = QListWidget()
        self.liste.itemClicked.connect(self._ouvrir_etude)
        self.liste.setContextMenuPolicy(Qt.CustomContextMenu)
        self.liste.customContextMenuRequested.connect(self._menu_etude)
        self.liste.setToolTip("Clic : ouvrir · clic droit : supprimer")
        side.addWidget(self.liste, 1)
        root.addWidget(sidebar)

        colonne = QVBoxLayout()
        colonne.setContentsMargins(0, 0, 0, 0)
        colonne.setSpacing(0)
        self.fil_ariane = breadcrumb_label()
        colonne.addWidget(self.fil_ariane)
        self.contenu = QStackedWidget()
        for vue in self.boutons:
            self.contenu.addWidget(vue)
        colonne.addWidget(self.contenu, 1)
        conteneur = QWidget()
        conteneur.setLayout(colonne)
        root.addWidget(conteneur, 1)

        self.comparaison.enregistree.connect(lambda _: self._charger_liste())
        self.fidelite.enregistree.connect(lambda _: self._charger_liste())
        self._charger_liste()
        self._afficher(self.comparaison)

    def _afficher(self, vue: QWidget):
        self.contenu.setCurrentWidget(vue)
        for v, bouton in self.boutons.items():
            bouton.setChecked(v is vue)
        noms = {self.comparaison: "Comparaison de méthodes", self.fidelite: "Fidélité et justesse",
                self.incertitude: "Incertitude de mesure et sigma"}
        self.fil_ariane.setText(f"{FIL_ARIANE_PREFIXE} › {noms[vue]}")

    def _charger_liste(self):
        self.liste.clear()
        for etude in logic.lister_etudes(self.conn):
            item = QListWidgetItem(f"{ICONES.get(etude.type, '•')} {etude.titre}")
            item.setToolTip(f"{logic.LIBELLES_TYPE.get(etude.type, etude.type)} · {etude.analyte} · "
                            f"créée le {date_fr(etude.date_creation)}")
            item.setData(ETUDE_ID_ROLE, etude.id)
            self.liste.addItem(item)

    def _ouvrir_etude(self, item: QListWidgetItem):
        etude = logic.charger_etude(self.conn, item.data(ETUDE_ID_ROLE))
        if etude is None:
            self._charger_liste()
            return
        vue = self.comparaison if etude.type == logic.TYPE_COMPARAISON else self.fidelite
        vue.charger(etude)
        self._afficher(vue)
        self.fil_ariane.setText(f"{self.fil_ariane.text()} › {etude.titre}")

    def _menu_etude(self, position):
        item = self.liste.itemAt(position)
        if item is None:
            return
        menu = QMenu(self)
        menu.addAction("Ouvrir", lambda: self._ouvrir_etude(item))
        menu.addAction("🗑 Supprimer…", lambda: self._supprimer(item))
        menu.exec(self.liste.viewport().mapToGlobal(position))

    def _supprimer(self, item: QListWidgetItem):
        etude_id = item.data(ETUDE_ID_ROLE)
        if not ui.confirmer(self, "Supprimer l'étude", f"Supprimer définitivement « {item.text()[2:]} » ?",
                            "Supprimer", danger=True):
            return
        logic.supprimer_etude(self.conn, etude_id)
        for vue in (self.comparaison, self.fidelite):
            if vue.etude_id == etude_id:
                vue.etude_id = None
        self._charger_liste()
