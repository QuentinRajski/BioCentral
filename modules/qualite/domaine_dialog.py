"""
Boîte de dialogue permettant d'ajuster le domaine de mesure (bornes inférieure
et supérieure) d'un paramètre déjà importé, directement depuis le tableau de
bord — sans réimporter le fichier Excel. Même principe que TranchesDialog.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QDoubleSpinBox, QPushButton, QMessageBox,
)

from . import import_logic


class DomaineMesureDialog(QDialog):
    def __init__(self, conn, parametre_id: int, parametre_nom: str, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.parametre_id = parametre_id

        self.setWindowTitle(f"Domaine de mesure — {parametre_nom}")
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Les échantillons dont la valeur numérique brute sort des nouvelles bornes "
            "seront automatiquement signalés comme hors bornes. Les résultats déjà "
            "annotés par la machine (ex. « <0.3 ») ne sont jamais modifiés."
        ))

        domaine_min, domaine_max = import_logic.get_domaine_mesure(conn, parametre_id)

        ligne = QHBoxLayout()
        self.spin_min = QDoubleSpinBox()
        self.spin_min.setRange(-1_000_000, 1_000_000)
        self.spin_min.setDecimals(3)
        self.spin_min.setValue(domaine_min or 0.0)
        self.spin_max = QDoubleSpinBox()
        self.spin_max.setRange(-1_000_000, 1_000_000)
        self.spin_max.setDecimals(3)
        self.spin_max.setValue(domaine_max or 0.0)
        ligne.addWidget(QLabel("Valeur min"))
        ligne.addWidget(self.spin_min)
        ligne.addWidget(QLabel("Valeur max"))
        ligne.addWidget(self.spin_max)
        layout.addLayout(ligne)

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

    def _enregistrer(self):
        nouveau_min, nouveau_max = self.spin_min.value(), self.spin_max.value()
        if nouveau_min >= nouveau_max:
            QMessageBox.warning(self, "Bornes invalides", "La valeur min doit être inférieure à la valeur max.")
            return
        try:
            import_logic.modifier_domaine_mesure(self.conn, self.parametre_id, nouveau_min, nouveau_max)
        except Exception as e:
            QMessageBox.critical(self, "Échec", f"Impossible d'enregistrer le domaine de mesure : {e}")
            return
        self.accept()
