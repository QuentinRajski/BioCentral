"""
Boîte de dialogue permettant d'ajuster les tranches d'âge d'un paramètre déjà
importé, directement depuis le tableau de bord — sans réimporter le fichier Excel.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox, QLineEdit, QPushButton,
    QMessageBox, QWidget,
)

from . import import_logic


class TranchesDialog(QDialog):
    def __init__(self, conn, parametre_id: int, parametre_nom: str, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.parametre_id = parametre_id
        self.tranche_rows: list[dict] = []

        self.setWindowTitle(f"Tranches d'âge — {parametre_nom}")
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Les échantillons déjà importés seront automatiquement réattribués "
            "aux nouvelles tranches, à partir de leur âge déjà calculé."
        ))

        self.lignes_layout = QVBoxLayout()
        layout.addLayout(self.lignes_layout)

        for age_min, age_max, libelle in import_logic.get_tranches(conn, parametre_id):
            self._ajouter_ligne(age_min, age_max, libelle)
        if not self.tranche_rows:
            self._ajouter_ligne()

        btn_ajouter = QPushButton("+ Ajouter une tranche")
        btn_ajouter.clicked.connect(lambda: self._ajouter_ligne())
        layout.addWidget(btn_ajouter)

        boutons = QHBoxLayout()
        btn_annuler = QPushButton("Annuler")
        btn_annuler.clicked.connect(self.reject)
        btn_enregistrer = QPushButton("Enregistrer")
        btn_enregistrer.setObjectName("PrimaryButton")
        btn_enregistrer.clicked.connect(self._enregistrer)
        boutons.addStretch()
        boutons.addWidget(btn_annuler)
        boutons.addWidget(btn_enregistrer)
        layout.addLayout(boutons)

    def _ajouter_ligne(self, age_min: int = 0, age_max: int = 0, libelle: str = ""):
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)

        spin_min = QSpinBox(); spin_min.setRange(0, 120); spin_min.setValue(age_min)
        spin_max = QSpinBox(); spin_max.setRange(0, 120); spin_max.setValue(age_max)
        champ_libelle = QLineEdit(libelle)
        champ_libelle.setPlaceholderText("Libellé (ex. 0 à 2 ans)")
        btn_suppr = QPushButton("✕")
        btn_suppr.setFixedWidth(28)

        row_layout.addWidget(QLabel("Âge min")); row_layout.addWidget(spin_min)
        row_layout.addWidget(QLabel("Âge max")); row_layout.addWidget(spin_max)
        row_layout.addWidget(champ_libelle, stretch=1)
        row_layout.addWidget(btn_suppr)

        entry = {"widget": row_widget, "age_min": spin_min, "age_max": spin_max, "libelle": champ_libelle}
        self.tranche_rows.append(entry)
        self.lignes_layout.addWidget(row_widget)

        def supprimer():
            self.tranche_rows.remove(entry)
            row_widget.setParent(None)
        btn_suppr.clicked.connect(supprimer)

    def _enregistrer(self):
        if not self.tranche_rows:
            QMessageBox.warning(self, "Aucune tranche", "Ajoutez au moins une tranche d'âge.")
            return
        tranches = [
            (r["age_min"].value(), r["age_max"].value(), r["libelle"].text() or "Sans libellé")
            for r in self.tranche_rows
        ]
        try:
            import_logic.modifier_tranches(self.conn, self.parametre_id, tranches)
        except Exception as e:
            QMessageBox.critical(self, "Échec", f"Impossible d'enregistrer les tranches : {e}")
            return
        self.accept()
