"""
Coquille du module Base de connaissances : barre latérale (retour accueil,
liste des documents importés avec cases à cocher pour filtrer la recherche,
bouton d'import) + zone de contenu qui bascule entre la recherche et l'import.
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QStackedWidget,
)
from PySide6.QtCore import Signal, Qt

from .import_screen import ImportScreen
from .recherche import RechercheWidget

DOCUMENT_ID_ROLE = Qt.UserRole + 1


class ConnaissancesModule(QWidget):
    retour_accueil = Signal()

    def __init__(self, conn):
        super().__init__()
        self.conn = conn

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- Barre latérale ---
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(240)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(12, 12, 12, 12)

        btn_accueil = QPushButton("Retour vers Accueil")
        btn_accueil.setObjectName("PrimaryButton")
        btn_accueil.clicked.connect(self.retour_accueil.emit)
        side_layout.addWidget(btn_accueil)
        side_layout.addSpacing(16)

        label_documents = QLabel("Documents")
        label_documents.setObjectName("Muted")
        side_layout.addWidget(label_documents)

        self.liste_documents = QListWidget()
        self.liste_documents.itemChanged.connect(self._sur_filtre_change)
        side_layout.addWidget(self.liste_documents, stretch=1)

        btn_importer = QPushButton("+ Importer")
        btn_importer.setObjectName("PrimaryButton")
        btn_importer.clicked.connect(self._ouvrir_import)
        side_layout.addWidget(btn_importer)

        root.addWidget(sidebar)

        # --- Zone de contenu ---
        self.contenu = QStackedWidget()
        self.recherche = RechercheWidget(self.conn)
        self.contenu.addWidget(self.recherche)

        self.import_screen = ImportScreen(self.conn)
        self.import_screen.import_termine.connect(self._sur_import_termine)
        self.contenu.addWidget(self.import_screen)

        root.addWidget(self.contenu, stretch=1)

        self._charger_documents()

    def _charger_documents(self):
        self.liste_documents.blockSignals(True)
        self.liste_documents.clear()
        rows = self.conn.execute("SELECT id, titre FROM kb_documents ORDER BY titre").fetchall()
        for document_id, titre in rows:
            item = QListWidgetItem(titre)
            item.setData(DOCUMENT_ID_ROLE, document_id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)  # défaut : tous les documents cochés
            self.liste_documents.addItem(item)
        self.liste_documents.blockSignals(False)
        self._sur_filtre_change()

    def _sur_filtre_change(self, _item=None):
        total = self.liste_documents.count()
        coches = {
            self.liste_documents.item(i).data(DOCUMENT_ID_ROLE)
            for i in range(total)
            if self.liste_documents.item(i).checkState() == Qt.Checked
        }
        # Tous cochés (ou aucun document importé) équivaut à "pas de filtre" ;
        # un sous-ensemble coché restreint la recherche à ces documents précis.
        if total == 0 or len(coches) == total:
            self.recherche.definir_filtre_documents(None)
        else:
            self.recherche.definir_filtre_documents(coches)

    def _ouvrir_import(self):
        self.contenu.setCurrentWidget(self.import_screen)

    def _sur_import_termine(self):
        self._charger_documents()
        self.contenu.setCurrentWidget(self.recherche)
