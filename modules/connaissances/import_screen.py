"""
Écran d'import du module Base de connaissances : sélection d'un PDF, titre
éditable, puis extraction + calcul des embeddings + insertion en base.
"""
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog,
    QLineEdit, QMessageBox, QProgressDialog, QApplication,
)
from PySide6.QtCore import Signal, Qt

from . import import_logic


class ImportScreen(QWidget):
    import_termine = Signal()  # émis après un import réussi, pour rafraîchir la liste des documents

    def __init__(self, conn):
        super().__init__()
        self.conn = conn
        self.filepath: Path | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        titre_page = QLabel("Importer un document")
        titre_page.setObjectName("Heading")
        layout.addWidget(titre_page)

        card = self._card()
        card_layout = QVBoxLayout(card)

        file_row = QHBoxLayout()
        self.file_label = QLabel("Aucun fichier sélectionné")
        btn_choisir = QPushButton("Choisir un PDF…")
        btn_choisir.clicked.connect(self.choisir_fichier)
        file_row.addWidget(self.file_label)
        file_row.addStretch()
        file_row.addWidget(btn_choisir)
        card_layout.addLayout(file_row)

        titre_row = QHBoxLayout()
        titre_row.addWidget(QLabel("Titre"))
        self.champ_titre = QLineEdit()
        self.champ_titre.setPlaceholderText("Nom du livre/document")
        titre_row.addWidget(self.champ_titre, stretch=1)
        card_layout.addLayout(titre_row)

        layout.addWidget(card)

        btn_import = QPushButton("Importer")
        btn_import.setObjectName("PrimaryButton")
        btn_import.clicked.connect(self.lancer_import)
        footer = QHBoxLayout()
        footer.addStretch()
        footer.addWidget(btn_import)
        layout.addLayout(footer)
        layout.addStretch()

    def _card(self) -> QWidget:
        w = QWidget()
        w.setObjectName("Card")
        w.setAttribute(Qt.WA_StyledBackground, True)
        return w

    def choisir_fichier(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choisir un PDF", "", "Fichiers PDF (*.pdf)")
        if not path:
            return
        self.filepath = Path(path)
        self.file_label.setText(self.filepath.name)
        if not self.champ_titre.text().strip():
            self.champ_titre.setText(self.filepath.stem)

    def lancer_import(self):
        if not self.filepath:
            QMessageBox.warning(self, "Fichier manquant", "Veuillez sélectionner un PDF avant d'importer.")
            return
        titre = self.champ_titre.text().strip()
        if not titre:
            QMessageBox.warning(self, "Titre manquant", "Veuillez donner un titre à ce document.")
            return

        progression = QProgressDialog("Préparation…", None, 0, 100, self)
        progression.setWindowTitle("Import en cours")
        progression.setWindowModality(Qt.WindowModal)
        progression.setMinimumDuration(0)
        progression.setCancelButton(None)  # pas d'annulation à mi-import : éviterait un document à moitié indexé

        def on_progress(etape: str, fraction: float):
            progression.setLabelText(etape)
            progression.setValue(int(fraction * 100))
            QApplication.processEvents()

        try:
            summary = import_logic.import_pdf(self.conn, self.filepath, titre, on_progress=on_progress)
        except Exception as e:
            progression.close()
            QMessageBox.critical(self, "Échec de l'import", f"L'import a échoué : {e}")
            return
        progression.close()

        QMessageBox.information(
            self, "Import terminé",
            f"« {summary.titre} » importé : {summary.nombre_pages} pages, "
            f"{summary.nombre_passages} passages indexés.",
        )
        self.filepath = None
        self.file_label.setText("Aucun fichier sélectionné")
        self.champ_titre.clear()
        self.import_termine.emit()
