"""
Écran d'import du module Contrôle Qualité.
Reprend le mockup validé : fichier -> domaine de mesure -> tranches d'âge -> import.
"""
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QFileDialog, QDoubleSpinBox, QSpinBox, QLineEdit, QMessageBox, QDialog,
)
from PySide6.QtCore import Signal, Qt

from . import import_logic


class ImportScreen(QWidget):
    import_termine = Signal()  # émis après un import réussi, pour rafraîchir la liste des paramètres

    def __init__(self, conn):
        super().__init__()
        self.conn = conn
        self.filepath: Path | None = None
        self.tranche_rows: list[dict] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # --- En-tête avec bouton d'aide ---
        entete = QHBoxLayout()
        entete.addWidget(self._label("Importer un paramètre", "Heading"))
        entete.addStretch()
        btn_aide = QPushButton("? Mode opératoire")
        btn_aide.clicked.connect(self._afficher_aide)
        entete.addWidget(btn_aide)
        layout.addLayout(entete)

        # --- Étape 1 : fichier ---
        card1 = self._card()
        c1_layout = QVBoxLayout(card1)
        c1_layout.addWidget(self._label("Étape 1 — Fichier à importer", "Heading"))
        file_row = QHBoxLayout()
        self.file_label = QLabel("Aucun fichier sélectionné")
        btn_choisir = QPushButton("Choisir un fichier…")
        btn_choisir.clicked.connect(self.choisir_fichier)
        file_row.addWidget(self.file_label)
        file_row.addStretch()
        file_row.addWidget(btn_choisir)
        c1_layout.addLayout(file_row)
        layout.addWidget(card1)

        # --- Étape 2 : domaine de mesure ---
        card2 = self._card()
        c2_layout = QVBoxLayout(card2)
        c2_layout.addWidget(self._label("Étape 2 — Domaine de mesure", "Heading"))
        c2_layout.addWidget(self._label(
            "Utilisé pour identifier les résultats sous ou au-dessus de la plage mesurable", "Muted"))
        domaine_row = QHBoxLayout()
        self.domaine_min = QDoubleSpinBox()
        self.domaine_min.setRange(0, 100000)
        self.domaine_max = QDoubleSpinBox()
        self.domaine_max.setRange(0, 100000)
        domaine_row.addWidget(QLabel("Valeur min"))
        domaine_row.addWidget(self.domaine_min)
        domaine_row.addWidget(QLabel("Valeur max"))
        domaine_row.addWidget(self.domaine_max)
        domaine_row.addStretch()
        c2_layout.addLayout(domaine_row)
        layout.addWidget(card2)

        # --- Étape 3 : tranches d'âge ---
        card3 = self._card()
        c3_layout = QVBoxLayout(card3)
        c3_layout.addWidget(self._label("Étape 3 — Tranches d'âge", "Heading"))
        self.tranches_layout = QVBoxLayout()
        c3_layout.addLayout(self.tranches_layout)
        btn_ajouter = QPushButton("+ Ajouter une tranche")
        btn_ajouter.clicked.connect(self.ajouter_tranche)
        c3_layout.addWidget(btn_ajouter)
        layout.addWidget(card3)
        self.ajouter_tranche()  # une ligne de départ

        # --- Import ---
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

    def _label(self, text: str, object_name: str = "") -> QLabel:
        lbl = QLabel(text)
        if object_name:
            lbl.setObjectName(object_name)
        return lbl

    def _afficher_aide(self):
        dialogue = QDialog(self)
        dialogue.setWindowTitle("Mode opératoire — Import d'un paramètre")
        dialogue.setMinimumWidth(480)
        layout = QVBoxLayout(dialogue)

        texte = QLabel(
            "<b>1. Fichier attendu</b><br>"
            "Un export Excel (.xlsx) de la machine. Les colonnes fixes habituelles "
            "(sexe, dates, etc.) sont suivies d'une dernière colonne portant le nom "
            "du paramètre analysé (ex. « LH »), détecté automatiquement.<br><br>"

            "<b>2. Domaine de mesure</b><br>"
            "Indiquez la plage de valeurs mesurable par la machine pour ce paramètre "
            "(ex. 0.3 à 250). Les résultats en dehors de cette plage sont identifiés "
            "et mis en évidence automatiquement dans le tableau de bord.<br><br>"

            "<b>3. Tranches d'âge</b><br>"
            "Définissez les tranches applicables à ce paramètre. Chaque tranche va de "
            "son âge minimum <u>inclus</u> à son âge maximum <u>exclu</u> : une tranche "
            "« 2 à 12 ans » couvre les patients de 2 à 11 ans révolus — un patient de "
            "12 ans pile sera rattaché à la tranche suivante, pas à celle-ci. Veillez à "
            "couvrir toute la plage d'âges possible (une borne haute large, ex. 120, "
            "pour la dernière tranche) pour n'oublier aucun patient.<br><br>"

            "<b>4. Résultats particuliers</b><br>"
            "Les résultats comme « &lt;0.3 » (sous le seuil de détection) ou "
            "« Res annulé » sont reconnus et traités automatiquement, sans action de "
            "votre part.<br><br>"

            "<b>5. Réimport d'un paramètre existant</b><br>"
            "Si le paramètre a déjà été importé, une confirmation vous sera demandée : "
            "continuer remplace entièrement ses anciennes données par celles du "
            "nouveau fichier."
        )
        texte.setWordWrap(True)
        texte.setTextFormat(Qt.RichText)
        layout.addWidget(texte)

        btn_fermer = QPushButton("Fermer")
        btn_fermer.setObjectName("PrimaryButton")
        btn_fermer.clicked.connect(dialogue.accept)
        footer = QHBoxLayout()
        footer.addStretch()
        footer.addWidget(btn_fermer)
        layout.addLayout(footer)

        dialogue.exec()

    def choisir_fichier(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choisir un fichier Excel", "", "Fichiers Excel (*.xlsx)")
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            QMessageBox.warning(self, "Fichier invalide", "Veuillez sélectionner un fichier .xlsx valide.")
            return
        self.filepath = Path(path)
        self.file_label.setText(self.filepath.name)

    def ajouter_tranche(self):
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        age_min = QSpinBox(); age_min.setRange(0, 120)
        age_max = QSpinBox(); age_max.setRange(0, 120)
        libelle = QLineEdit()
        libelle.setPlaceholderText("Libellé (ex. 0 à 2 ans)")
        btn_suppr = QPushButton("✕")
        btn_suppr.setFixedWidth(28)

        row_layout.addWidget(QLabel("Âge min")); row_layout.addWidget(age_min)
        row_layout.addWidget(QLabel("Âge max")); row_layout.addWidget(age_max)
        row_layout.addWidget(libelle, stretch=1)
        row_layout.addWidget(btn_suppr)

        entry = {"widget": row_widget, "age_min": age_min, "age_max": age_max, "libelle": libelle}
        self.tranche_rows.append(entry)
        self.tranches_layout.addWidget(row_widget)

        def supprimer():
            self.tranche_rows.remove(entry)
            row_widget.setParent(None)
        btn_suppr.clicked.connect(supprimer)

    def lancer_import(self):
        if not self.filepath:
            QMessageBox.warning(self, "Fichier manquant", "Veuillez sélectionner un fichier avant d'importer.")
            return
        if not self.tranche_rows:
            QMessageBox.warning(self, "Tranches d'âge manquantes", "Ajoutez au moins une tranche d'âge.")
            return

        tranches = [
            (r["age_min"].value(), r["age_max"].value(), r["libelle"].text() or "Sans libellé")
            for r in self.tranche_rows
        ]

        try:
            parametre_detecte = import_logic.detect_parametre(
                __import__("openpyxl").load_workbook(self.filepath, data_only=True).active
            )
        except Exception as e:
            QMessageBox.critical(self, "Erreur de lecture", f"Impossible de lire le fichier : {e}")
            return

        remplace = False
        if import_logic.parametre_existe(self.conn, parametre_detecte):
            reponse = QMessageBox.question(
                self, "Paramètre déjà importé",
                f"Le paramètre « {parametre_detecte} » a déjà été importé précédemment.\n"
                "Continuer va remplacer entièrement ses données existantes (tranches d'âge "
                "et échantillons) par celles de ce nouveau fichier. Voulez-vous continuer ?",
            )
            if reponse != QMessageBox.Yes:
                return
            remplace = True

        try:
            summary = import_logic.import_file(
                self.conn, self.filepath,
                self.domaine_min.value(), self.domaine_max.value(),
                tranches, replace_existing=remplace,
            )
        except Exception as e:
            QMessageBox.critical(self, "Échec de l'import", f"L'import a échoué : {e}")
            return

        QMessageBox.information(
            self, "Import terminé",
            f"{summary.n_importes} échantillons importés\n"
            f"{summary.n_controle_machine} échantillons de contrôle machine ignorés\n"
            f"{summary.n_incomplets} lignes incomplètes ignorées",
        )
        self.import_termine.emit()
