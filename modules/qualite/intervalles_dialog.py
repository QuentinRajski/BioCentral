"""
Boîte de dialogue des intervalles de référence à vérifier pour un paramètre
(fournisseur, littérature, intervalle actuellement rendu sur les comptes rendus).
Un intervalle peut être global ou propre à une tranche d'âge et/ou à un sexe :
le tableau de bord utilise le plus spécifique qui correspond au filtre en cours.
"""
from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout, QWidget

from core import ui
from core.formatage import fmt, parse_nombre

from . import import_logic

TOUTES = "Toutes les tranches"
TOUS = "Tous"


class IntervallesReferenceDialog(QDialog):
    def __init__(self, conn, parametre_id: int, parametre_nom: str, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.parametre_id = parametre_id
        self.lignes: list[dict] = []
        self.tranches = [libelle for *_, libelle in import_logic.get_tranches(conn, parametre_id)]
        self.setWindowTitle(f"Intervalles de référence à vérifier — {parametre_nom}")
        self.setMinimumWidth(720)

        layout = QVBoxLayout(self)
        layout.addWidget(ui.texte_discret(
            "Saisissez l'intervalle annoncé (notice du fournisseur, littérature, intervalle actuellement rendu). "
            "Le tableau de bord compte la part des résultats de votre population qui en sortent : selon le CLSI "
            "EP28-A3c, l'intervalle est transférable si au plus 10 % des résultats (sur au moins 20 sujets) sont "
            "en dehors. Une borne peut rester vide (ex. intervalle « < 10 »)."))
        self.zone = QVBoxLayout()
        layout.addLayout(self.zone)
        for tranche, sexe, bas, haut, source in import_logic.lister_intervalles_reference(conn, parametre_id):
            self._ajouter(tranche, sexe, bas, haut, source)
        if not self.lignes:
            self._ajouter()
        layout.addWidget(ui.bouton("+ Ajouter un intervalle", lambda: self._ajouter()))
        boutons = QHBoxLayout()
        boutons.addStretch()
        boutons.addWidget(ui.bouton("Annuler", self.reject))
        boutons.addWidget(ui.bouton("Enregistrer", self._enregistrer, principal=True))
        layout.addLayout(boutons)

    def _ajouter(self, tranche: str = "", sexe: str = "", bas=None, haut=None, source: str = ""):
        widget = QWidget()
        ligne = QHBoxLayout(widget)
        ligne.setContentsMargins(0, 0, 0, 0)
        choix_tranche = QComboBox()
        choix_tranche.addItem(TOUTES, "")
        for t in self.tranches:
            choix_tranche.addItem(t, t)
        if tranche and choix_tranche.findData(tranche) < 0:
            choix_tranche.addItem(f"{tranche} (tranche supprimée)", tranche)
        choix_tranche.setCurrentIndex(max(choix_tranche.findData(tranche or ""), 0))
        choix_sexe = QComboBox()
        for libelle, valeur in ((TOUS, ""), ("Féminin", "Féminin"), ("Masculin", "Masculin")):
            choix_sexe.addItem(libelle, valeur)
        choix_sexe.setCurrentIndex(max(choix_sexe.findData(sexe or ""), 0))
        champ_bas = QLineEdit("" if bas is None else fmt(bas, 8))
        champ_bas.setPlaceholderText("borne basse")
        champ_haut = QLineEdit("" if haut is None else fmt(haut, 8))
        champ_haut.setPlaceholderText("borne haute")
        champ_source = QLineEdit(source or "")
        champ_source.setPlaceholderText("source (ex. notice fournisseur)")
        supprimer = QPushButton("✕")
        supprimer.setFixedWidth(32)
        for w, etirement in ((choix_tranche, 2), (choix_sexe, 1), (champ_bas, 1), (champ_haut, 1), (champ_source, 2)):
            ligne.addWidget(w, etirement)
        ligne.addWidget(supprimer)
        entree = {"widget": widget, "tranche": choix_tranche, "sexe": choix_sexe, "bas": champ_bas,
                  "haut": champ_haut, "source": champ_source}
        self.lignes.append(entree)
        self.zone.addWidget(widget)

        def retirer():
            self.lignes.remove(entree)
            widget.setParent(None)
            widget.deleteLater()
        supprimer.clicked.connect(retirer)

    def _enregistrer(self):
        valeurs = []
        for e in self.lignes:
            texte_bas, texte_haut = e["bas"].text().strip(), e["haut"].text().strip()
            if not texte_bas and not texte_haut:
                continue  # ligne laissée vide : ignorée
            bas, haut = parse_nombre(texte_bas), parse_nombre(texte_haut)
            if (texte_bas and bas is None) or (texte_haut and haut is None):
                ui.alerte(self, "Valeur invalide", "Les bornes doivent être des nombres.")
                return
            valeurs.append((e["tranche"].currentData(), e["sexe"].currentData(), bas, haut,
                            e["source"].text().strip() or None))
        try:
            import_logic.enregistrer_intervalles_reference(self.conn, self.parametre_id, valeurs)
        except ValueError as ex:
            ui.alerte(self, "Intervalles invalides", str(ex))
            return
        self.accept()
