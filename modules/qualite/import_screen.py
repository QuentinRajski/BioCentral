"""
Écran d'import du module Études de population.
Reprend le mockup validé : fichier -> domaine de mesure -> tranches d'âge -> import,
avec en plus : aperçu du fichier dès sa sélection (paramètre détecté, effectifs,
âges), domaine pré-rempli quand le fichier l'indique, modèles de tranches d'âge,
contrôle des tranches (chevauchements, âges non couverts) avant l'import.
"""
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDoubleSpinBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from core import ui
from core.formatage import date_fr, fmt

from . import import_logic

MODELES_TRANCHES = {
    "Pédiatrie / adulte (0-2, 2-18, 18+)": [(0, 2, "0 à 2 ans"), (2, 18, "2 à 18 ans"), (18, 120, "18 ans et plus")],
    "Enfant / adulte (0-18, 18+)": [(0, 18, "Moins de 18 ans"), (18, 120, "18 ans et plus")],
    "Pédiatrie détaillée (<1, 1-5, 5-10, 10-14, 14-18, 18+)": [
        (0, 1, "Moins de 1 an"), (1, 5, "1 à 5 ans"), (5, 10, "5 à 10 ans"), (10, 14, "10 à 14 ans"),
        (14, 18, "14 à 18 ans"), (18, 120, "18 ans et plus")],
    "Adultes par âge (18-40, 40-60, 60+)": [
        (0, 18, "Moins de 18 ans"), (18, 40, "18 à 40 ans"), (40, 60, "40 à 60 ans"), (60, 120, "60 ans et plus")],
    "Une seule tranche (tous âges)": [(0, 120, "Tous âges")],
}


class ImportScreen(QWidget):
    import_termine = Signal()  # émis après un import réussi, pour rafraîchir la liste des paramètres

    def __init__(self, conn):
        super().__init__()
        self.conn = conn
        self.filepath: Path | None = None
        self.apercu: import_logic.ApercuFichier | None = None
        self.tranche_rows: list[dict] = []

        contenu = QWidget()
        layout = QVBoxLayout(contenu)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        entete = QHBoxLayout()
        entete.addWidget(ui.titre_page("Importer un paramètre"))
        entete.addStretch()
        entete.addWidget(ui.bouton("? Mode opératoire", self._afficher_aide))
        layout.addLayout(entete)

        # --- Étape 1 : fichier ---
        card1, c1 = ui.carte_titree("", "Card")
        c1.addWidget(self._heading("Étape 1 — Fichier à importer"))
        file_row = QHBoxLayout()
        self.file_label = QLabel("Aucun fichier sélectionné")
        file_row.addWidget(self.file_label)
        file_row.addStretch()
        file_row.addWidget(ui.bouton("Choisir un fichier…", self.choisir_fichier))
        c1.addLayout(file_row)
        self.label_apercu = ui.texte_discret()
        self.label_apercu.setTextFormat(Qt.RichText)
        self.label_apercu.hide()
        c1.addWidget(self.label_apercu)
        layout.addWidget(card1)

        # --- Étape 2 : domaine de mesure ---
        card2, c2 = ui.carte_titree("", "Card")
        c2.addWidget(self._heading("Étape 2 — Domaine de mesure et unité"))
        c2.addWidget(ui.texte_discret("Utilisé pour identifier les résultats sous ou au-dessus de la plage mesurable"))
        domaine_row = QHBoxLayout()
        self.domaine_min = self._spin_domaine()
        self.domaine_max = self._spin_domaine()
        self.unite = QLineEdit()
        self.unite.setPlaceholderText("ex. UI/L (facultatif)")
        self.unite.setMaximumWidth(180)
        domaine_row.addWidget(QLabel("Valeur min"))
        domaine_row.addWidget(self.domaine_min)
        domaine_row.addWidget(QLabel("Valeur max"))
        domaine_row.addWidget(self.domaine_max)
        domaine_row.addSpacing(16)
        domaine_row.addWidget(QLabel("Unité"))
        domaine_row.addWidget(self.unite)
        domaine_row.addStretch()
        c2.addLayout(domaine_row)
        self.label_domaine = ui.texte_discret()
        self.label_domaine.hide()
        c2.addWidget(self.label_domaine)
        layout.addWidget(card2)

        # --- Étape 3 : tranches d'âge ---
        card3, c3 = ui.carte_titree("", "Card")
        c3.addWidget(self._heading("Étape 3 — Tranches d'âge"))
        modele_row = QHBoxLayout()
        modele_row.addWidget(QLabel("Partir d'un modèle"))
        self.modele = QComboBox()
        self.modele.addItem("— choisir —", None)
        for nom in MODELES_TRANCHES:
            self.modele.addItem(nom, nom)
        self.modele.currentIndexChanged.connect(self._appliquer_modele)
        modele_row.addWidget(self.modele, 1)
        c3.addLayout(modele_row)
        self.tranches_layout = QVBoxLayout()
        c3.addLayout(self.tranches_layout)
        c3.addWidget(ui.bouton("+ Ajouter une tranche", lambda: self.ajouter_tranche()), alignment=Qt.AlignLeft)
        self.label_tranches = ui.avertissement()
        self.label_tranches.hide()
        c3.addWidget(self.label_tranches)
        layout.addWidget(card3)
        self.ajouter_tranche()  # une ligne de départ

        footer = QHBoxLayout()
        footer.addStretch()
        footer.addWidget(ui.bouton("Importer", self.lancer_import, principal=True))
        layout.addLayout(footer)
        layout.addStretch()

        racine = QVBoxLayout(self)
        racine.setContentsMargins(0, 0, 0, 0)
        racine.addWidget(ui.zone_defilante(contenu))

    @staticmethod
    def _heading(texte: str) -> QLabel:
        label = QLabel(texte)
        label.setObjectName("Heading")
        return label

    @staticmethod
    def _spin_domaine() -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(0, 1_000_000)
        spin.setDecimals(3)
        return spin

    def _afficher_aide(self):
        dialogue = QDialog(self)
        dialogue.setWindowTitle("Mode opératoire — Import d'un paramètre")
        dialogue.setMinimumWidth(520)
        layout = QVBoxLayout(dialogue)
        texte = QLabel(
            "<b>1. Fichier attendu</b><br>"
            "Un export Excel (.xlsx) de la machine. Si le classeur contient une feuille « Total », c'est elle qui "
            "est importée ; sinon la première feuille. Les 7 colonnes fixes (Patient, Né(e) le, Sexe, N° demande, "
            "Date de prél., Corres., Docteur) sont suivies de la colonne du paramètre (ex. « LH »), détecté "
            "automatiquement. Les noms des patients, correspondants et médecins ne sont jamais importés.<br><br>"
            "<b>2. Domaine de mesure</b><br>"
            "Plage de valeurs mesurable par la machine (ex. 0.3 à 250). Les résultats hors de cette plage — "
            "annotés « &lt;0.3 » par la machine ou simplement numériques — sont identifiés et mis en évidence. "
            "Si le fichier comporte une colonne « Domaine de mesure », elle pré-remplit ces champs.<br><br>"
            "<b>3. Tranches d'âge</b><br>"
            "Chaque tranche va de son âge minimum <u>inclus</u> à son âge maximum <u>exclu</u> : une tranche "
            "« 2 à 12 ans » couvre les patients de 2 à 11 ans révolus. Les tranches ne doivent pas se chevaucher ; "
            "l'écran signale les âges présents dans le fichier qui ne seraient couverts par aucune tranche.<br><br>"
            "<b>4. Résultats particuliers</b><br>"
            "« &lt;0.3 », « &gt;250 » : comptés dans l'effectif, la médiane et les percentiles (au rang du seuil), "
            "exclus de la moyenne et de l'écart-type. « Res annulé », « VCOM » : exclus de tout calcul.<br><br>"
            "<b>5. Réimport d'un paramètre existant</b><br>"
            "Une confirmation est demandée : continuer remplace ses anciens échantillons et tranches par ceux du "
            "nouveau fichier (les notes, l'unité et les intervalles de référence sont conservés).")
        texte.setWordWrap(True)
        texte.setTextFormat(Qt.RichText)
        layout.addWidget(texte)
        footer = QHBoxLayout()
        footer.addStretch()
        footer.addWidget(ui.bouton("Fermer", dialogue.accept, principal=True))
        layout.addLayout(footer)
        dialogue.exec()

    # ------------------------------------------------------------------
    def choisir_fichier(self):
        chemin = ui.demander_fichier_ouverture(self, "Choisir un fichier Excel", "Fichiers Excel (*.xlsx)")
        if chemin:
            self.charger_fichier(chemin)

    def charger_fichier(self, chemin: Path):
        if chemin.suffix.lower() != ".xlsx":
            ui.alerte(self, "Fichier invalide", "Veuillez sélectionner un fichier .xlsx valide.")
            return
        try:
            apercu = import_logic.apercu_fichier(chemin)
        except Exception as e:
            ui.erreur(self, "Fichier illisible", f"Impossible de lire ce fichier :\n{e}")
            return
        self.filepath, self.apercu = chemin, apercu
        self.file_label.setText(chemin.name)
        deja = import_logic.parametre_existe(self.conn, apercu.parametre)
        lignes = [
            f"Paramètre détecté : <b>{apercu.parametre}</b> (feuille « {apercu.feuille} »)"
            + (" — <b>déjà importé : il sera remplacé</b>" if deja else ""),
            f"{apercu.n_patients} échantillon(s) patient · {apercu.n_controle_machine} ligne(s) de contrôle machine "
            f"écartée(s) · {apercu.n_incomplets} ligne(s) incomplète(s)",
            f"Femmes : {apercu.n_feminin} · Hommes : {apercu.n_masculin}",
        ]
        if apercu.age_min is not None:
            lignes.append(f"Âges de {apercu.age_min} à {apercu.age_max} ans · prélèvements du "
                          f"{date_fr(apercu.date_min)} au {date_fr(apercu.date_max)}")
        self.label_apercu.setText("<br>".join(lignes))
        self.label_apercu.show()
        if apercu.domaine_suggere:
            bas, haut = apercu.domaine_suggere
            self.domaine_min.setValue(bas)
            self.domaine_max.setValue(haut)
            self.label_domaine.setText(f"Pré-rempli d'après la colonne « Domaine de mesure » du fichier : "
                                       f"{fmt(bas)} – {fmt(haut)}. Vérifiez ces valeurs.")
            self.label_domaine.show()
        else:
            self.label_domaine.hide()
        if deja:
            # Réimport : on repart des tranches et de l'unité actuelles du paramètre.
            parametre_id = self.conn.execute("SELECT id FROM qc_parametres WHERE nom = ?",
                                             (apercu.parametre,)).fetchone()[0]
            self._definir_tranches(import_logic.get_tranches(self.conn, parametre_id))
            self.unite.setText(import_logic.get_unite(self.conn, parametre_id))
            if not apercu.domaine_suggere:
                dmin, dmax = import_logic.get_domaine_mesure(self.conn, parametre_id)
                self.domaine_min.setValue(dmin or 0)
                self.domaine_max.setValue(dmax or 0)
        self._verifier_tranches()

    # ------------------------------------------------------------------
    def ajouter_tranche(self, age_min: int = 0, age_max: int = 0, libelle: str = ""):
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        spin_min = QSpinBox()
        spin_min.setRange(0, 120)
        spin_min.setValue(age_min)
        spin_max = QSpinBox()
        spin_max.setRange(0, 130)
        spin_max.setValue(age_max)
        champ = QLineEdit(libelle)
        champ.setPlaceholderText("Libellé (vide = « min à max ans »)")
        btn_suppr = QPushButton("✕")
        btn_suppr.setFixedWidth(32)
        row_layout.addWidget(QLabel("Âge min"))
        row_layout.addWidget(spin_min)
        row_layout.addWidget(QLabel("Âge max (exclu)"))
        row_layout.addWidget(spin_max)
        row_layout.addWidget(champ, stretch=1)
        row_layout.addWidget(btn_suppr)
        entry = {"widget": row_widget, "age_min": spin_min, "age_max": spin_max, "libelle": champ}
        self.tranche_rows.append(entry)
        self.tranches_layout.addWidget(row_widget)
        spin_min.valueChanged.connect(self._verifier_tranches)
        spin_max.valueChanged.connect(self._verifier_tranches)

        def supprimer():
            self.tranche_rows.remove(entry)
            row_widget.setParent(None)
            row_widget.deleteLater()
            self._verifier_tranches()
        btn_suppr.clicked.connect(supprimer)

    def _definir_tranches(self, tranches):
        for entry in list(self.tranche_rows):
            entry["widget"].setParent(None)
            entry["widget"].deleteLater()
        self.tranche_rows.clear()
        for age_min, age_max, libelle in tranches:
            self.ajouter_tranche(age_min, age_max, libelle)
        self._verifier_tranches()

    def _appliquer_modele(self):
        nom = self.modele.currentData()
        if nom:
            self._definir_tranches(MODELES_TRANCHES[nom])
            self.modele.blockSignals(True)
            self.modele.setCurrentIndex(0)
            self.modele.blockSignals(False)

    def _tranches(self) -> list[tuple[int, int, str]]:
        return [
            (r["age_min"].value(), r["age_max"].value(),
             r["libelle"].text().strip() or import_logic.libelle_tranche_auto(r["age_min"].value(), r["age_max"].value()))
            for r in self.tranche_rows
        ]

    def _verifier_tranches(self) -> list[str]:
        tranches = self._tranches()
        messages = import_logic.valider_tranches(tranches)
        if self.apercu and tranches and not messages:
            non_couverts = import_logic.ages_non_couverts(self.apercu.ages, tranches)
            if non_couverts:
                n = sum(1 for a in self.apercu.ages if a in set(non_couverts))
                messages.append(f"Attention : {n} échantillon(s) d'âge non couvert par les tranches "
                                f"({', '.join(map(str, non_couverts[:12]))}{'…' if len(non_couverts) > 12 else ''} ans) "
                                "— ils seront importés mais n'apparaîtront dans aucune tranche.")
        self.label_tranches.setText("\n".join(messages))
        self.label_tranches.setVisible(bool(messages))
        return messages

    # ------------------------------------------------------------------
    def lancer_import(self):
        if not self.filepath:
            ui.alerte(self, "Fichier manquant", "Veuillez sélectionner un fichier avant d'importer.")
            return
        if not self.tranche_rows:
            ui.alerte(self, "Tranches d'âge manquantes", "Ajoutez au moins une tranche d'âge.")
            return
        tranches = self._tranches()
        erreurs = import_logic.valider_tranches(tranches)
        if erreurs:
            ui.alerte(self, "Tranches d'âge invalides", "\n".join(erreurs))
            return
        if self.domaine_max.value() <= self.domaine_min.value():
            if not ui.confirmer(self, "Domaine de mesure non renseigné",
                                "La valeur max du domaine n'est pas supérieure à la valeur min : aucun résultat "
                                "numérique ne sera signalé hors bornes (seules les annotations « < » et « > » de "
                                "la machine le seront). Importer quand même ?", "Importer"):
                return

        try:
            parametre_detecte = import_logic.lire_parametre(self.filepath)
        except Exception as e:
            ui.erreur(self, "Erreur de lecture", f"Impossible de lire le fichier : {e}")
            return

        remplace = False
        if import_logic.parametre_existe(self.conn, parametre_detecte):
            if not ui.confirmer(
                self, "Paramètre déjà importé",
                f"Le paramètre « {parametre_detecte} » a déjà été importé précédemment.\n"
                "Continuer va remplacer ses échantillons et ses tranches d'âge par ceux de ce nouveau fichier "
                "(notes, unité et intervalles de référence conservés). Voulez-vous continuer ?", "Remplacer"):
                return
            remplace = True

        try:
            summary = import_logic.import_file(
                self.conn, self.filepath, self.domaine_min.value(), self.domaine_max.value(),
                tranches, replace_existing=remplace, unite=self.unite.text().strip() or None,
            )
        except Exception as e:
            ui.erreur(self, "Échec de l'import", f"L'import a échoué, aucune donnée n'a été modifiée :\n{e}")
            return

        details = [
            f"{summary.n_importes} échantillon(s) importé(s) pour « {summary.parametre} »",
            f"  dont {summary.n_sous_seuil} sous la borne inférieure, {summary.n_sur_seuil} au-dessus de la borne "
            f"supérieure, {summary.n_exclus} exclu(s) des calculs (Res annulé, VCOM…)",
            f"{summary.n_controle_machine} ligne(s) de contrôle machine ignorée(s)",
            f"{summary.n_incomplets} ligne(s) incomplète(s) ignorée(s)",
        ]
        if summary.n_hors_tranches:
            details.append(f"⚠ {summary.n_hors_tranches} échantillon(s) sans tranche d'âge correspondante")
        ui.information(self, "Import terminé", "\n".join(details))
        self._reinitialiser()
        self.import_termine.emit()

    def _reinitialiser(self):
        self.filepath, self.apercu = None, None
        self.file_label.setText("Aucun fichier sélectionné")
        self.label_apercu.hide()
        self.label_domaine.hide()
        self.domaine_min.setValue(0)
        self.domaine_max.setValue(0)
        self.unite.clear()
        self._definir_tranches([(0, 0, "")])
        self.label_tranches.hide()  # une ligne vierge n'est pas une erreur à signaler
