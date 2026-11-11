"""
Coquille du module Base de connaissances : barre latérale (retour accueil,
liste des documents importés avec cases à cocher pour filtrer la recherche,
bouton d'import) + zone de contenu qui bascule entre la recherche et l'import.
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QStackedWidget,
)
from PySide6.QtCore import Signal, Qt

from core.nav_widgets import breadcrumb_label, entete_barre_laterale, section_label

from .import_screen import ImportScreen
from .recherche import RechercheWidget

DOCUMENT_ID_ROLE = Qt.UserRole + 1
FIL_ARIANE_PREFIXE = "BioCentral › Base de connaissances"


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
        side_layout.setSpacing(4)

        side_layout.addWidget(entete_barre_laterale(self.conn, self.retour_accueil.emit))
        side_layout.addSpacing(14)

        side_layout.addWidget(section_label("Navigation"))
        self.btn_recherche = QPushButton("🔎 Recherche")
        self.btn_recherche.setObjectName("BoutonAccueil")
        self.btn_recherche.setCheckable(True)
        self.btn_recherche.setChecked(True)
        self.btn_recherche.clicked.connect(self._ouvrir_recherche)
        side_layout.addWidget(self.btn_recherche)
        side_layout.addSpacing(14)

        side_layout.addWidget(section_label("Documents"))
        self.liste_documents = QListWidget()
        self.liste_documents.itemChanged.connect(self._sur_filtre_change)
        self.liste_documents.setContextMenuPolicy(Qt.CustomContextMenu)
        self.liste_documents.customContextMenuRequested.connect(self._menu_document)
        self.liste_documents.setToolTip("Cochez les documents où chercher · clic droit : renommer, supprimer")
        side_layout.addWidget(self.liste_documents, stretch=1)

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
        self.recherche = RechercheWidget(self.conn)
        self.contenu.addWidget(self.recherche)

        self.import_screen = ImportScreen(self.conn)
        self.import_screen.import_termine.connect(self._sur_import_termine)
        self.contenu.addWidget(self.import_screen)

        colonne_contenu.addWidget(self.contenu, stretch=1)

        contenu_widget = QWidget()
        contenu_widget.setLayout(colonne_contenu)
        root.addWidget(contenu_widget, stretch=1)

        self._charger_documents()
        self._definir_fil_ariane("Recherche")

    def _definir_fil_ariane(self, suffixe: str) -> None:
        self.fil_ariane.setText(f"{FIL_ARIANE_PREFIXE} › {suffixe}")

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

    def _ouvrir_recherche(self):
        self.contenu.setCurrentWidget(self.recherche)
        self.btn_recherche.setChecked(True)
        self._definir_fil_ariane("Recherche")

    def _ouvrir_import(self):
        self.contenu.setCurrentWidget(self.import_screen)
        self.btn_recherche.setChecked(False)
        self._definir_fil_ariane("Importer un document")

    def _sur_import_termine(self):
        self._charger_documents()
        self._ouvrir_recherche()

    # --- v2 : gestion des documents (renommer, supprimer) ---
    def _menu_document(self, position):
        from PySide6.QtWidgets import QMenu
        item = self.liste_documents.itemAt(position)
        if item is None:
            return
        menu = QMenu(self)
        menu.addAction("✎ Renommer…", lambda: self._renommer(item))
        menu.addAction("🗑 Supprimer…", lambda: self._supprimer(item))
        menu.exec(self.liste_documents.viewport().mapToGlobal(position))

    def _renommer(self, item):
        from PySide6.QtWidgets import QInputDialog
        titre, ok = QInputDialog.getText(self, "Renommer le document", "Nouveau titre :", text=item.text())
        if ok and titre.strip():
            self.conn.execute("UPDATE kb_documents SET titre = ? WHERE id = ?",
                              (titre.strip(), item.data(DOCUMENT_ID_ROLE)))
            self.conn.commit()
            self._charger_documents()

    def _supprimer(self, item):
        from core import ui
        if ui.confirmer(self, "Supprimer le document",
                        f"Retirer « {item.text()} » et tous ses passages indexés de la base de connaissances ?\n\n"
                        "Le fichier PDF d'origine n'est pas touché.", "Supprimer", danger=True):
            self.conn.execute("DELETE FROM kb_documents WHERE id = ?", (item.data(DOCUMENT_ID_ROLE),))
            self.conn.commit()
            self._charger_documents()
