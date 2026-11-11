"""
Coquille du module Contrôle interne de qualité : barre latérale (vue
d'ensemble + liste des analytes suivis) et zone de contenu.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QStackedWidget, QTableWidget, QVBoxLayout, QWidget,
)

from core import theme, ui, westgard
from core.formatage import datetime_fr, fmt_dec
from core.nav_widgets import breadcrumb_label, entete_barre_laterale, section_label

from . import logic
from .analyte_view import LIBELLE_STATUT
from .carte import COULEUR_STATUT
from .dialogs import AnalyteDialog

FIL_ARIANE_PREFIXE = "BioCentral › Contrôle interne de qualité"
ANALYTE_ID_ROLE = Qt.UserRole + 1


class VueEnsembleCIQ(QWidget):
    """Tableau de bord : un lot actif par ligne, statut du dernier passage."""
    analyte_choisi = Signal(int)
    demande_creation = Signal()
    demande_demo = Signal()

    def __init__(self, conn):
        super().__init__()
        self.conn = conn
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        entete = QHBoxLayout()
        entete.addWidget(ui.titre_page("Contrôle interne de qualité"))
        entete.addStretch()
        entete.addWidget(ui.texte_discret("Période", retour_ligne=False))
        self.periode = QComboBox()
        for libelle, jours in (("30 derniers jours", 30), ("3 derniers mois", 91), ("12 derniers mois", 365),
                               ("Tout l'historique", None)):
            self.periode.addItem(libelle, jours)
        self.periode.currentIndexChanged.connect(self.rafraichir)
        entete.addWidget(self.periode)
        layout.addLayout(entete)

        layout.addWidget(ui.texte_discret(
            "Chaque ligne est un niveau de contrôle en cours d'utilisation. Statut = résultat du dernier passage "
            "selon les règles de Westgard de l'analyte. Double-cliquez une ligne pour ouvrir ses cartes de "
            "Levey-Jennings."))

        self.resume = QHBoxLayout()
        self.badge_rejets = ui.badge("", "neutre")
        self.badge_alertes = ui.badge("", "neutre")
        self.badge_ok = ui.badge("", "neutre")
        for b in (self.badge_rejets, self.badge_alertes, self.badge_ok):
            self.resume.addWidget(b)
        self.resume.addStretch()
        layout.addLayout(self.resume)

        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(["Analyte", "Automate", "Niveau / lot", "Dernier passage", "Statut",
                                              "Règles", "n (période)", "CV %", "Rejets (période)"])
        ui.styliser_table(self.table, 32, "CardAccentBleu")
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.itemDoubleClicked.connect(self._sur_double_clic)
        layout.addWidget(self.table, 1)

        self.zone_vide = QWidget()
        vide = QVBoxLayout(self.zone_vide)
        vide.setContentsMargins(0, 20, 0, 0)
        vide.addWidget(ui.sous_titre("Aucun analyte suivi pour l'instant"))
        vide.addWidget(ui.texte_discret(
            "Créez un analyte (ex. Glucose sur votre automate), ajoutez-lui ses lots de contrôle (un par niveau) "
            "avec leurs moyennes et écarts-types cibles, puis saisissez ou importez les passages. Vous pouvez aussi "
            "charger des données fictives pour découvrir le module."))
        boutons = QHBoxLayout()
        boutons.addWidget(ui.bouton("+ Créer un analyte", self.demande_creation.emit, principal=True))
        boutons.addWidget(ui.bouton("Charger des données de démonstration", self.demande_demo.emit))
        boutons.addStretch()
        vide.addLayout(boutons)
        vide.addStretch()
        layout.addWidget(self.zone_vide)

        theme.ThemeManager.instance().changed.connect(self.rafraichir)
        self.rafraichir()

    def rafraichir(self):
        lignes = logic.synthese(self.conn, self.periode.currentData())
        lignes.sort(key=lambda l: ({"rejet": 0, "alerte": 1}.get(l.dernier_statut, 2), l.analyte.nom, l.lot.niveau))
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(lignes))
        for i, l in enumerate(lignes):
            statut = l.dernier_statut
            fond = ui.couleur_ligne(i, surlignee=statut == westgard.REJET, avertissement=statut == westgard.ALERTE)
            couleur = theme.qcolor(COULEUR_STATUT[statut]) if statut in (westgard.ALERTE, westgard.REJET) else None
            texte_statut = LIBELLE_STATUT.get(statut, "Aucun passage")
            niveau = l.lot.libelle + (" (cibles provisoires)" if l.cibles_provisoires else "")
            cellules = [
                ui.cellule(l.analyte.nom, fond=fond, donnee=l.analyte.id),
                ui.cellule(l.analyte.automate, fond=fond),
                ui.cellule(niveau, fond=fond),
                ui.cellule(datetime_fr(l.derniere_date) if l.derniere_date else "—", l.derniere_date or "", fond=fond),
                ui.cellule(texte_statut, fond=fond, couleur=couleur),
                ui.cellule(westgard.libelles(l.dernieres_regles), fond=fond),
                ui.cellule(l.n_periode, l.n_periode, droite=True, fond=fond),
                ui.cellule(fmt_dec(l.cv, 2), l.cv if l.cv is not None else -1, droite=True, fond=fond),
                ui.cellule(l.n_rejets_periode, l.n_rejets_periode, droite=True, fond=fond),
            ]
            for col, item in enumerate(cellules):
                self.table.setItem(i, col, item)
        self.table.setSortingEnabled(True)

        n_rejets = sum(1 for l in lignes if l.dernier_statut == westgard.REJET)
        n_alertes = sum(1 for l in lignes if l.dernier_statut == westgard.ALERTE)
        n_ok = sum(1 for l in lignes if l.dernier_statut == westgard.OK)
        ui.definir_badge(self.badge_rejets, f"{n_rejets} niveau(x) en rejet", "rejet" if n_rejets else "neutre")
        ui.definir_badge(self.badge_alertes, f"{n_alertes} en alerte", "alerte" if n_alertes else "neutre")
        ui.definir_badge(self.badge_ok, f"{n_ok} conforme(s)", "ok" if n_ok else "neutre")
        aucun = not logic.lister_analytes(self.conn)
        self.zone_vide.setVisible(aucun)
        self.table.setVisible(not aucun)
        for b in (self.badge_rejets, self.badge_alertes, self.badge_ok):
            b.setVisible(not aucun)

    def _sur_double_clic(self, item):
        cellule = self.table.item(item.row(), 0)
        if cellule is not None:
            self.analyte_choisi.emit(cellule.data(Qt.UserRole))


class CIQModule(QWidget):
    retour_accueil = Signal()

    def __init__(self, conn):
        super().__init__()
        self.conn = conn
        self.vues: dict[int, QWidget] = {}

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(240)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(12, 12, 12, 12)
        side.setSpacing(4)
        side.addWidget(entete_barre_laterale(self.conn, self.retour_accueil.emit))
        side.addSpacing(14)
        side.addWidget(section_label("Navigation"))
        self.btn_ensemble = QPushButton("⊞ Vue d'ensemble")
        self.btn_ensemble.setObjectName("BoutonAccueil")
        self.btn_ensemble.setCheckable(True)
        self.btn_ensemble.setChecked(True)
        self.btn_ensemble.clicked.connect(self._ouvrir_ensemble)
        side.addWidget(self.btn_ensemble)
        side.addSpacing(14)
        side.addWidget(section_label("Analytes suivis"))
        self.recherche = QLineEdit()
        self.recherche.setPlaceholderText("Rechercher un analyte")
        self.recherche.textChanged.connect(self._filtrer)
        side.addWidget(self.recherche)
        self.liste = QListWidget()
        self.liste.itemClicked.connect(lambda item: self._ouvrir_analyte(item.data(ANALYTE_ID_ROLE)))
        side.addWidget(self.liste, 1)
        side.addWidget(ui.bouton("+ Nouvel analyte", self._creer_analyte, principal=True))
        root.addWidget(sidebar)

        colonne = QVBoxLayout()
        colonne.setContentsMargins(0, 0, 0, 0)
        colonne.setSpacing(0)
        self.fil_ariane = breadcrumb_label()
        colonne.addWidget(self.fil_ariane)
        self.contenu = QStackedWidget()
        self.ensemble = VueEnsembleCIQ(self.conn)
        self.ensemble.analyte_choisi.connect(self._ouvrir_analyte)
        self.ensemble.demande_creation.connect(self._creer_analyte)
        self.ensemble.demande_demo.connect(self._charger_demo)
        self.contenu.addWidget(self.ensemble)
        colonne.addWidget(self.contenu, 1)
        conteneur = QWidget()
        conteneur.setLayout(colonne)
        root.addWidget(conteneur, 1)

        self._charger_liste()
        self.fil_ariane.setText(f"{FIL_ARIANE_PREFIXE} › Vue d'ensemble")

    def _charger_liste(self):
        self.liste.clear()
        for a in logic.lister_analytes(self.conn):
            item = QListWidgetItem(a.libelle)
            item.setData(ANALYTE_ID_ROLE, a.id)
            self.liste.addItem(item)
        self._filtrer(self.recherche.text())

    def _filtrer(self, texte: str):
        texte = texte.lower()
        for i in range(self.liste.count()):
            item = self.liste.item(i)
            item.setHidden(texte not in item.text().lower())

    def _ouvrir_ensemble(self):
        self.ensemble.rafraichir()
        self.contenu.setCurrentWidget(self.ensemble)
        self.btn_ensemble.setChecked(True)
        self.liste.clearSelection()
        self.fil_ariane.setText(f"{FIL_ARIANE_PREFIXE} › Vue d'ensemble")

    def _ouvrir_analyte(self, analyte_id: int):
        from .analyte_view import AnalyteView
        analyte = logic.get_analyte(self.conn, analyte_id)
        if analyte is None:
            return
        if analyte_id not in self.vues:
            vue = AnalyteView(self.conn, analyte_id)
            vue.modifie.connect(self._sur_modification)
            vue.supprime.connect(lambda aid=analyte_id: self._sur_suppression(aid))
            self.vues[analyte_id] = vue
            self.contenu.addWidget(vue)
        else:
            self.vues[analyte_id].rafraichir()
        self.contenu.setCurrentWidget(self.vues[analyte_id])
        self.btn_ensemble.setChecked(False)
        for i in range(self.liste.count()):
            if self.liste.item(i).data(ANALYTE_ID_ROLE) == analyte_id:
                self.liste.setCurrentRow(i)
        self.fil_ariane.setText(f"{FIL_ARIANE_PREFIXE} › {analyte.libelle}")

    def _creer_analyte(self):
        dialogue = AnalyteDialog(self.conn, parent=self)
        if dialogue.exec():
            self._charger_liste()
            self._ouvrir_analyte(dialogue.analyte_id)

    def _charger_demo(self):
        premier = logic.creer_donnees_demo(self.conn)
        self._charger_liste()
        self.ensemble.rafraichir()
        if premier:
            self._ouvrir_analyte(premier)

    def _sur_modification(self):
        actuel = self.contenu.currentWidget()
        self._charger_liste()
        if actuel in self.vues.values():
            for analyte_id, vue in self.vues.items():
                if vue is actuel:
                    analyte = logic.get_analyte(self.conn, analyte_id)
                    if analyte:
                        self.fil_ariane.setText(f"{FIL_ARIANE_PREFIXE} › {analyte.libelle}")

    def _sur_suppression(self, analyte_id: int):
        vue = self.vues.pop(analyte_id, None)
        if vue is not None:
            self.contenu.removeWidget(vue)
            vue.deleteLater()
        self._charger_liste()
        self._ouvrir_ensemble()

    def showEvent(self, event):
        super().showEvent(event)
        if self.contenu.currentWidget() is self.ensemble:
            self.ensemble.rafraichir()
