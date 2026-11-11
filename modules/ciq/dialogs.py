"""
Boîtes de dialogue du module CIQ : analyte, lot de contrôle, saisie d'une mesure,
saisie en série / import, établissement des cibles.
"""
from datetime import datetime

from PySide6.QtCore import QDate, QDateTime, Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QDateTimeEdit, QDialog, QDoubleSpinBox, QFormLayout, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QSpinBox, QVBoxLayout, QWidget,
)

from core import ui, westgard
from core.export import lire_tableau
from core.formatage import fmt, parse_nombre

from . import logic


def _boutons(dialogue: QDialog, libelle_ok: str = "Enregistrer") -> QHBoxLayout:
    ligne = QHBoxLayout()
    ligne.addStretch()
    ligne.addWidget(ui.bouton("Annuler", dialogue.reject))
    ok = ui.bouton(libelle_ok, dialogue.accept, principal=True)
    ok.setDefault(True)
    ligne.addWidget(ok)
    return ligne


class _ChampNombre(QLineEdit):
    """Champ numérique facultatif : vide = non renseigné ; virgule ou point acceptés."""
    def __init__(self, valeur: float | None = None, indication: str = ""):
        super().__init__("" if valeur is None else fmt(valeur, 8))
        self.setPlaceholderText(indication)

    def valeur(self) -> float | None:
        texte = self.text().strip()
        if not texte:
            return None
        v = parse_nombre(texte)
        if v is None:
            raise ValueError(f"« {texte} » n'est pas un nombre.")
        return v


# ------------------------------------------------------------------
class AnalyteDialog(QDialog):
    def __init__(self, conn, analyte: logic.Analyte | None = None, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.analyte = analyte
        self.analyte_id: int | None = analyte.id if analyte else None
        self.setWindowTitle("Modifier l'analyte" if analyte else "Nouvel analyte")
        self.setMinimumWidth(500)

        layout = QVBoxLayout(self)
        formulaire = QFormLayout()
        self.nom = QLineEdit(analyte.nom if analyte else "")
        self.nom.setPlaceholderText("ex. Glucose, TSH, Hémoglobine")
        self.unite = QLineEdit(analyte.unite if analyte else "")
        self.unite.setPlaceholderText("ex. mmol/L")
        self.automate = QLineEdit(analyte.automate if analyte else "")
        self.automate.setPlaceholderText("ex. Cobas c501 n°2 (facultatif)")
        self.eta = _ChampNombre(analyte.erreur_totale_admissible if analyte else None,
                                "% — facultatif (ex. 6.9 pour le glucose, base Ricos)")
        formulaire.addRow("Nom *", self.nom)
        formulaire.addRow("Unité", self.unite)
        formulaire.addRow("Automate", self.automate)
        formulaire.addRow("Erreur totale admissible (%)", self.eta)
        layout.addLayout(formulaire)
        layout.addWidget(ui.texte_discret(
            "L'erreur totale admissible (ETa) permet de calculer le nombre de sigma de la méthode : "
            "(ETa − |biais|) / CV. Au-delà de 6 sigma la méthode est excellente ; en dessous de 3, "
            "un contrôle plus strict (plus de niveaux, plus de règles) est nécessaire."))

        layout.addWidget(ui.sous_titre("Règles de Westgard appliquées"))
        grille = QGridLayout()
        self.cases: dict[str, QCheckBox] = {}
        actives = set(analyte.regles if analyte else westgard.REGLES_PAR_DEFAUT)
        for i, code in enumerate(westgard.REGLES_INTRA):
            regle = westgard.REGLES[code]
            case = QCheckBox(f"{regle.libelle}  ({'rejet' if regle.gravite == westgard.REJET else 'alerte'})")
            case.setToolTip(regle.description)
            case.setChecked(code in actives)
            self.cases[code] = case
            grille.addWidget(case, i // 2, i % 2)
        layout.addLayout(grille)
        layout.addWidget(ui.texte_discret(
            "Les règles 2-2s et R-4s s'appliquent aussi entre niveaux passés dans la même série "
            "(même jour, même rang de passage)."))
        layout.addLayout(_boutons(self))

    def accept(self):
        try:
            regles = [c for c, case in self.cases.items() if case.isChecked()]
            if not regles:
                raise ValueError("Cochez au moins une règle de Westgard.")
            eta = self.eta.valeur()
            if eta is not None and eta <= 0:
                raise ValueError("L'erreur totale admissible doit être strictement positive.")
            self.analyte_id = logic.enregistrer_analyte(
                self.conn, self.nom.text(), self.unite.text(), self.automate.text(), eta, regles,
                self.analyte.notes if self.analyte else "", self.analyte_id)
        except ValueError as e:
            ui.alerte(self, "Saisie incomplète", str(e))
            return
        super().accept()


# ------------------------------------------------------------------
class LotDialog(QDialog):
    def __init__(self, conn, analyte: logic.Analyte, lot: logic.Lot | None = None, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.analyte = analyte
        self.lot = lot
        self.setWindowTitle(f"{'Modifier le' if lot else 'Nouveau'} lot de contrôle — {analyte.nom}")
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        formulaire = QFormLayout()
        self.niveau = QLineEdit(lot.niveau if lot else "")
        self.niveau.setPlaceholderText("ex. Niveau 1, Normal, Pathologique")
        self.numero = QLineEdit(lot.numero_lot if lot else "")
        self.moyenne = _ChampNombre(lot.cible_moyenne if lot else None, "vide = provisoire (calculée)")
        self.ecart_type = _ChampNombre(lot.cible_ecart_type if lot else None, "vide = provisoire (calculé)")
        self.origine = QComboBox()
        self.origine.setEditable(True)
        self.origine.addItems(["Laboratoire", "Fabricant", "Groupe de pairs"])
        if lot and lot.origine_cible:
            self.origine.setCurrentText(lot.origine_cible)
        self.peremption_active = QCheckBox("Renseigner")
        self.peremption = QDateEdit()
        self.peremption.setCalendarPopup(True)
        self.peremption.setDisplayFormat("dd/MM/yyyy")
        if lot and lot.date_peremption:
            self.peremption.setDate(QDate.fromString(lot.date_peremption[:10], "yyyy-MM-dd"))
            self.peremption_active.setChecked(True)
        else:
            self.peremption.setDate(QDate.currentDate().addYears(1))
        self.peremption.setEnabled(self.peremption_active.isChecked())
        self.peremption_active.toggled.connect(self.peremption.setEnabled)
        ligne_peremption = QHBoxLayout()
        ligne_peremption.addWidget(self.peremption_active)
        ligne_peremption.addWidget(self.peremption, 1)
        self.actif = QCheckBox("Lot en cours d'utilisation")
        self.actif.setChecked(lot.actif if lot else True)

        formulaire.addRow("Niveau *", self.niveau)
        formulaire.addRow("N° de lot", self.numero)
        formulaire.addRow(f"Moyenne cible ({analyte.unite or 'unité'})", self.moyenne)
        formulaire.addRow("Écart-type cible", self.ecart_type)
        formulaire.addRow("Origine des cibles", self.origine)
        formulaire.addRow("Péremption", ligne_peremption)
        formulaire.addRow("", self.actif)
        layout.addLayout(formulaire)
        layout.addWidget(ui.texte_discret(
            "Sans cibles, la carte utilise la moyenne et l'écart-type observés (cibles provisoires). "
            "Après une vingtaine de passages, utilisez « Établir les cibles à partir des données »."))
        layout.addLayout(_boutons(self))

    def accept(self):
        try:
            logic.enregistrer_lot(
                self.conn, self.analyte.id, self.niveau.text(), self.numero.text(),
                self.moyenne.valeur(), self.ecart_type.valeur(), self.origine.currentText(),
                self.peremption.date().toString("yyyy-MM-dd") if self.peremption_active.isChecked() else None,
                self.actif.isChecked(), self.lot.id if self.lot else None)
        except ValueError as e:
            ui.alerte(self, "Saisie invalide", str(e))
            return
        super().accept()


# ------------------------------------------------------------------
class MesureDialog(QDialog):
    """Saisie (ou modification) d'un passage de contrôle, avec retour immédiat
    du score z et des règles déclenchées avant enregistrement."""

    def __init__(self, conn, analyte: logic.Analyte, lots: list[logic.Lot], lot_id: int | None = None,
                 mesure: logic.Mesure | None = None, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.analyte = analyte
        self.mesure = mesure
        self.setWindowTitle(("Modifier" if mesure else "Saisir") + f" un passage de contrôle — {analyte.nom}")
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        formulaire = QFormLayout()
        self.lot = QComboBox()
        for lot in lots:
            self.lot.addItem(lot.libelle, lot.id)
        if lot_id is not None:
            self.lot.setCurrentIndex(max(self.lot.findData(lot_id), 0))
        self.lot.setEnabled(mesure is None)
        self.date = QDateTimeEdit()
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("dd/MM/yyyy HH:mm")
        if mesure:
            self.date.setDateTime(QDateTime.fromString(mesure.date, "yyyy-MM-dd HH:mm"))
        else:
            self.date.setDateTime(QDateTime.currentDateTime())
        self.valeur = _ChampNombre(mesure.valeur if mesure else None, analyte.unite)
        self.operateur = QLineEdit(mesure.operateur if mesure else "")
        self.commentaire = QLineEdit(mesure.commentaire if mesure else "")
        formulaire.addRow("Niveau / lot", self.lot)
        formulaire.addRow("Date et heure", self.date)
        formulaire.addRow(f"Valeur ({analyte.unite or 'unité'}) *", self.valeur)
        formulaire.addRow("Opérateur", self.operateur)
        formulaire.addRow("Commentaire", self.commentaire)
        layout.addLayout(formulaire)

        self.apercu = ui.badge("Saisissez une valeur", "neutre")
        self.apercu.setWordWrap(True)
        layout.addWidget(self.apercu)
        self.valeur.textChanged.connect(self._apercu)
        self.lot.currentIndexChanged.connect(self._apercu)
        layout.addLayout(_boutons(self))
        self.valeur.setFocus()

    def _apercu(self):
        try:
            v = self.valeur.valeur()
        except ValueError:
            ui.definir_badge(self.apercu, "Valeur non numérique", "rejet")
            return
        lot = logic.get_lot(self.conn, self.lot.currentData()) if self.lot.currentData() else None
        if v is None or lot is None:
            ui.definir_badge(self.apercu, "Saisissez une valeur", "neutre")
            return
        carte = logic.calculer_cartes(self.conn, self.analyte, [lot])[0]
        if not carte.ecart_type:
            ui.definir_badge(self.apercu, "Pas encore de cibles : la valeur sera enregistrée sans évaluation", "neutre")
            return
        z = (v - carte.moyenne) / carte.ecart_type
        id_modifie = self.mesure.id if self.mesure else None
        historique = [m.z for m in carte.mesures
                      if not m.exclue and m.z is not None and m.id != id_modifie]
        regles = westgard.evaluer(historique + [z], self.analyte.regles)[-1]
        statut = westgard.statut(regles)
        texte = f"z = {z:+.2f}"
        if regles:
            texte += f" — {westgard.libelles(regles)} ({'REJET' if statut == westgard.REJET else 'alerte'})"
        else:
            texte += " — conforme"
        ui.definir_badge(self.apercu, texte, statut)

    def accept(self):
        try:
            v = self.valeur.valeur()
            if v is None:
                raise ValueError("Saisissez la valeur mesurée.")
            date = self.date.dateTime().toString("yyyy-MM-dd HH:mm")
            if self.mesure:
                logic.modifier_mesure(self.conn, self.mesure.id, date, v, self.operateur.text(), self.commentaire.text())
            else:
                logic.ajouter_mesure(self.conn, self.lot.currentData(), date, v,
                                     self.operateur.text(), self.commentaire.text())
        except ValueError as e:
            ui.alerte(self, "Saisie invalide", str(e))
            return
        super().accept()


# ------------------------------------------------------------------
class SaisieSerieDialog(QDialog):
    """Saisie de nombreux passages d'un coup : collage depuis Excel (Ctrl+V) ou
    import d'un fichier .xlsx/.csv dont les colonnes sont Date | Valeur |
    Opérateur | Commentaire."""

    def __init__(self, conn, analyte: logic.Analyte, lots: list[logic.Lot], lot_id: int | None = None, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.bilan: logic.BilanImport | None = None
        self.setWindowTitle(f"Saisie en série / import — {analyte.nom}")
        self.resize(640, 560)

        layout = QVBoxLayout(self)
        ligne = QHBoxLayout()
        ligne.addWidget(QLabel("Niveau / lot"))
        self.lot = QComboBox()
        for lot in lots:
            self.lot.addItem(lot.libelle, lot.id)
        if lot_id is not None:
            self.lot.setCurrentIndex(max(self.lot.findData(lot_id), 0))
        ligne.addWidget(self.lot, 1)
        ligne.addWidget(ui.bouton("📂 Charger un fichier…", self._charger))
        layout.addLayout(ligne)
        layout.addWidget(ui.texte_discret(
            "Copiez les colonnes depuis Excel puis collez-les ici (Ctrl+V), ou chargez un fichier .xlsx / .csv. "
            "Colonnes attendues : Date (JJ/MM/AAAA [HH:MM]) · Valeur · Opérateur (facultatif) · Commentaire (facultatif). "
            "Une ligne d'en-tête éventuelle est ignorée."))
        self.table = ui.TableSaisie(["Date", "Valeur", "Opérateur", "Commentaire"], numeriques=[1], lignes_initiales=15)
        layout.addWidget(self.table, 1)
        layout.addLayout(_boutons(self, "Importer"))

    def _charger(self):
        chemin = ui.demander_fichier_ouverture(self, "Charger des passages de contrôle",
                                               "Tableaux (*.xlsx *.csv *.txt)")
        if not chemin:
            return
        try:
            lignes = lire_tableau(chemin)
        except Exception as e:
            ui.erreur(self, "Lecture impossible", f"Impossible de lire ce fichier : {e}")
            return

        def texte(v):
            if isinstance(v, datetime):
                return v.strftime("%d/%m/%Y %H:%M")
            return "" if v is None else str(v)
        self.table.definir_lignes([[texte(c) for c in l[:4]] for l in lignes])

    def accept(self):
        lignes = self.table.lignes()
        if not lignes:
            ui.alerte(self, "Rien à importer", "Collez ou chargez au moins une ligne.")
            return
        try:
            self.bilan = logic.importer_lignes(self.conn, self.lot.currentData(), lignes)
        except Exception as e:
            ui.erreur(self, "Échec de l'import", f"Aucune mesure n'a été importée : {e}")
            return
        if self.bilan.erreurs:
            details = "\n".join(self.bilan.erreurs[:15])
            if len(self.bilan.erreurs) > 15:
                details += f"\n… et {len(self.bilan.erreurs) - 15} autre(s)."
            ui.alerte(self, "Import partiel",
                      f"{self.bilan.n_importees} mesure(s) importée(s), {len(self.bilan.erreurs)} ligne(s) ignorée(s) :\n\n{details}")
        super().accept()


# ------------------------------------------------------------------
class CiblesDialog(QDialog):
    """Établit la moyenne et l'écart-type cibles d'un lot à partir de ses premières mesures."""

    def __init__(self, conn, lot: logic.Lot, unite: str = "", parent=None):
        super().__init__(parent)
        self.conn = conn
        self.lot = lot
        self.unite = unite
        self.setWindowTitle(f"Établir les cibles — {lot.libelle}")
        self.setMinimumWidth(440)
        self.total = sum(1 for m in logic.lister_mesures(conn, lot.id) if not m.exclue)

        layout = QVBoxLayout(self)
        layout.addWidget(ui.texte_discret(
            "Les cibles sont calculées sur les premières mesures non exclues du lot (période probatoire). "
            f"Au moins {logic.MESURES_RECOMMANDEES_CIBLES} valeurs, obtenues sur plusieurs jours, sont recommandées."))
        ligne = QHBoxLayout()
        ligne.addWidget(QLabel("Nombre de mesures à utiliser"))
        self.nombre = QSpinBox()
        self.nombre.setRange(2, max(self.total, 2))
        self.nombre.setValue(min(max(self.total, 2), logic.MESURES_RECOMMANDEES_CIBLES))
        ligne.addWidget(self.nombre)
        ligne.addWidget(QLabel(f"sur {self.total} disponibles"))
        ligne.addStretch()
        layout.addLayout(ligne)
        self.resultat = QLabel()
        self.resultat.setObjectName("ValeurCle")
        layout.addWidget(self.resultat)
        self.nombre.valueChanged.connect(self._calculer)
        layout.addLayout(_boutons(self, "Appliquer ces cibles"))
        self._calculer()

    def _calculer(self):
        try:
            m, s, n = logic.cibles_depuis_donnees(self.conn, self.lot.id, self.nombre.value())
        except ValueError as e:
            self.resultat.setText(str(e))
            self._valeurs = None
            return
        self._valeurs = (m, s)
        cv = 100 * s / abs(m) if m else None
        self.resultat.setText(f"Moyenne {fmt(m)}  ·  Écart-type {fmt(s)} {self.unite}  ·  CV {fmt(cv, 3)} %  (n = {n})")

    def accept(self):
        if not self._valeurs:
            ui.alerte(self, "Calcul impossible", "Pas assez de mesures pour établir des cibles.")
            return
        logic.definir_cibles(self.conn, self.lot.id, *self._valeurs, origine="Laboratoire")
        super().accept()
