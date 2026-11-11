"""
Écran « Incertitude de mesure et sigma » : estimation de l'incertitude élargie
à partir du CIQ (fidélité intermédiaire) et des EEQ (biais), selon l'approche
Nordtest TR 537 ; calcul du nombre de sigma et de l'erreur totale.
Le CV de fidélité peut être repris directement d'un lot suivi dans le module CIQ.
"""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QSplitter, QVBoxLayout, QWidget,
)

from core import export, incertitude, ui
from core.formatage import fmt, fmt_dec, parse_nombre

from modules.ciq import logic as ciq


class _ChoixLotCIQ(QDialog):
    """Choix d'un lot du module CIQ dont on reprend le CV sur 12 mois."""

    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Reprendre le CV depuis le CIQ")
        self.setMinimumWidth(460)
        self.cv: float | None = None
        layout = QVBoxLayout(self)
        layout.addWidget(ui.texte_discret("CV observé sur les 12 derniers mois (mesures non exclues) : "
                                          "c'est l'estimation de la fidélité intermédiaire recommandée."))
        self.choix = QComboBox()
        for analyte in ciq.lister_analytes(conn):
            for carte in ciq.calculer_cartes(conn, analyte, debut=ciq.debut_periode(365)):
                if carte.stats.cv is not None:
                    self.choix.addItem(f"{analyte.libelle} · {carte.lot.libelle} — CV {fmt_dec(carte.stats.cv, 2)} % "
                                       f"(n = {carte.stats.n})", carte.stats.cv)
        if self.choix.count() == 0:
            self.choix.addItem("Aucun lot du CIQ ne compte assez de mesures", None)
        layout.addWidget(self.choix)
        boutons = QHBoxLayout()
        boutons.addStretch()
        boutons.addWidget(ui.bouton("Annuler", self.reject))
        boutons.addWidget(ui.bouton("Reprendre ce CV", self.accept, principal=True))
        layout.addLayout(boutons)

    def accept(self):
        self.cv = self.choix.currentData()
        if self.cv is None:
            self.reject()
            return
        super().accept()


class IncertitudeView(QWidget):
    def __init__(self, conn):
        super().__init__()
        self.conn = conn
        self.resultat: incertitude.ResultatIncertitude | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 16)
        root.setSpacing(10)
        entete = QHBoxLayout()
        entete.addWidget(ui.titre_page("Incertitude de mesure et sigma"))
        entete.addStretch()
        entete.addWidget(ui.bouton("⬇ Rapport PDF", self.exporter_pdf))
        root.addLayout(entete)
        root.addWidget(ui.texte_discret(
            "Approche « CIQ + EEQ » (Nordtest TR 537, principe repris par le SH GTA 14) : la fidélité intermédiaire "
            "vient du contrôle interne, le biais des évaluations externes. Toutes les grandeurs sont relatives (%)."))

        separateur = QSplitter(Qt.Horizontal)
        separateur.setChildrenCollapsible(False)
        saisie = QWidget()
        colonne = QVBoxLayout(saisie)
        colonne.setContentsMargins(0, 0, 8, 0)
        formulaire = QFormLayout()
        self.champ_analyte = QLineEdit()
        ligne_cv = QHBoxLayout()
        self.champ_cv = QLineEdit()
        self.champ_cv.setPlaceholderText("ex. 2.4")
        ligne_cv.addWidget(self.champ_cv, 1)
        ligne_cv.addWidget(ui.bouton("Depuis le CIQ…", self._depuis_ciq))
        self.champ_ucref = QLineEdit("0")
        self.champ_ucref.setToolTip("Incertitude-type moyenne des valeurs assignées des EEQ (souvent fournie par "
                                    "l'organisateur). 0 si inconnue.")
        self.champ_k = QLineEdit("2")
        self.champ_eta = QLineEdit()
        self.champ_eta.setPlaceholderText("facultatif, ex. 6.9")
        self.champ_concentration = QLineEdit()
        self.champ_concentration.setPlaceholderText("facultatif : résultat à illustrer")
        formulaire.addRow("Analyte", self.champ_analyte)
        formulaire.addRow("CV fidélité intermédiaire (%)", ligne_cv)
        formulaire.addRow("u(Cref) des EEQ (%)", self.champ_ucref)
        formulaire.addRow("Facteur k", self.champ_k)
        formulaire.addRow("Erreur totale admissible (%)", self.champ_eta)
        formulaire.addRow("Exemple de résultat", self.champ_concentration)
        colonne.addLayout(formulaire)
        colonne.addWidget(ui.sous_titre("Résultats d'EEQ"))
        colonne.addWidget(ui.texte_discret("Collez trois colonnes : identifiant de l'EEQ · résultat du laboratoire · "
                                           "valeur assignée (cible). Le biais relatif de chaque EEQ est calculé."))
        self.table = ui.TableSaisie(["EEQ", "Résultat", "Valeur assignée"], numeriques=[1, 2], lignes_initiales=10)
        colonne.addWidget(self.table, 1)
        separateur.addWidget(saisie)

        resultats = QWidget()
        droite = QVBoxLayout(resultats)
        droite.setContentsMargins(8, 0, 0, 0)
        carte_u, layout_u = ui.carte_titree("Incertitude élargie")
        self.label_u = QLabel("—")
        self.label_u.setObjectName("ValeurCle")
        self.label_u.setWordWrap(True)
        layout_u.addWidget(self.label_u)
        self.label_exemple = ui.texte_discret()
        layout_u.addWidget(self.label_exemple)
        droite.addWidget(carte_u)
        self.table_resultats = ui.table_cle_valeur(("Composante", "Valeur"))
        droite.addWidget(self.table_resultats, 1)
        formule = QLabel("u(biais) = √(RMS_biais² + u(Cref)²)   RMS_biais = √(Σ biais² / n)\n"
                         "u_c = √(u(Rw)² + u(biais)²)   U = k · u_c\n"
                         "Sigma = (ETa − |biais|) / CV   Erreur totale = |biais| + 1.65 · CV")
        formule.setObjectName("Formule")
        droite.addWidget(formule)
        carte_sigma, layout_sigma = ui.carte_titree("Sigma de la méthode")
        self.badge_sigma = ui.badge("Renseignez l'erreur totale admissible", "neutre")
        self.badge_sigma.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout_sigma.addWidget(self.badge_sigma)
        self.label_sigma = ui.texte_discret()
        layout_sigma.addWidget(self.label_sigma)
        droite.addWidget(carte_sigma)
        separateur.addWidget(resultats)
        separateur.setSizes([420, 780])
        root.addWidget(separateur, 1)

        self._minuteur = QTimer(self)
        self._minuteur.setSingleShot(True)
        self._minuteur.timeout.connect(self.calculer)
        self.table.modifie.connect(lambda: self._minuteur.start(300))
        for champ in (self.champ_cv, self.champ_ucref, self.champ_k, self.champ_eta, self.champ_concentration):
            champ.textChanged.connect(lambda _=None: self._minuteur.start(300))
        self.calculer()

    def _depuis_ciq(self):
        dialogue = _ChoixLotCIQ(self.conn, self)
        if dialogue.exec() and dialogue.cv is not None:
            self.champ_cv.setText(f"{dialogue.cv:.2f}")
            texte = dialogue.choix.currentText()
            if not self.champ_analyte.text().strip():
                self.champ_analyte.setText(texte.split(" · ")[0])

    def _biais_eeq(self) -> list[tuple[str, float, float, float]]:
        lignes = []
        for i, l in enumerate(self.table.lignes(), start=1):
            resultat, cible = parse_nombre(l[1]), parse_nombre(l[2])
            if resultat is None or cible in (None, 0):
                continue
            lignes.append((l[0] or f"EEQ {i}", resultat, cible, 100 * (resultat - cible) / cible))
        return lignes

    def calculer(self):
        cv = parse_nombre(self.champ_cv.text())
        u_cref = parse_nombre(self.champ_ucref.text()) or 0.0
        k = parse_nombre(self.champ_k.text()) or 2.0
        eta = parse_nombre(self.champ_eta.text())
        eeq = self._biais_eeq()
        self.lignes = []
        if cv is None:
            self.resultat = None
            self.label_u.setText("Renseignez le CV de fidélité intermédiaire")
            self.label_exemple.setText("")
            self.table_resultats.setRowCount(0)
        else:
            try:
                self.resultat = incertitude.incertitude_ciq_eeq(cv, [b for *_, b in eeq], u_cref, k)
            except ValueError as e:
                self.resultat = None
                self.label_u.setText(str(e))
                return
            r = self.resultat
            self.label_u.setText(f"U = ± {fmt_dec(r.u_elargie, 2)} %   (k = {fmt(r.k)})")
            concentration = parse_nombre(self.champ_concentration.text())
            if concentration is not None:
                demi = concentration * r.u_elargie / 100
                self.label_exemple.setText(f"Un résultat de {fmt(concentration)} s'exprime {fmt(concentration)} ± {fmt(demi)} "
                                           f"(soit [{fmt(concentration - demi)} ; {fmt(concentration + demi)}], niveau de confiance ≈ 95 %).")
            else:
                self.label_exemple.setText("")
            self.lignes = [
                ("u(Rw) — fidélité intermédiaire", f"{fmt_dec(r.u_fidelite, 2)} %"),
                ("Nombre d'EEQ pris en compte", str(r.n_eeq)),
                ("RMS des biais EEQ", f"{fmt_dec(r.rms_biais, 2)} %"),
                ("u(Cref)", f"{fmt_dec(r.u_cref, 2)} %"),
                ("u(biais)", f"{fmt_dec(r.u_biais, 2)} %"),
                ("Incertitude-type composée u_c", f"{fmt_dec(r.u_composee, 2)} %"),
                ("Incertitude élargie U", f"{fmt_dec(r.u_elargie, 2)} %"),
            ] + [(f"Biais {e}", f"{fmt_dec(b, 2)} %  ({fmt(res)} vs {fmt(c)})") for e, res, c, b in eeq]
            if r.n_eeq == 0:
                self.lignes.insert(2, ("⚠ Aucun EEQ saisi", "la composante de biais est ignorée (sous-estimation probable)"))
            ui.remplir_table_cle_valeur(self.table_resultats, self.lignes)

        biais_moyen = sum(b for *_, b in eeq) / len(eeq) if eeq else 0.0
        sigma = incertitude.sigma(eta, biais_moyen, cv)
        if sigma is None:
            ui.definir_badge(self.badge_sigma, "Renseignez le CV et l'erreur totale admissible", "neutre")
            self.label_sigma.setText("")
        else:
            statut = "ok" if sigma >= 4 else "alerte" if sigma >= 3 else "rejet"
            ui.definir_badge(self.badge_sigma, f"Sigma = {fmt_dec(sigma, 1)}", statut)
            te = incertitude.erreur_totale(biais_moyen, cv)
            self.label_sigma.setText(
                f"Biais moyen des EEQ : {fmt_dec(biais_moyen, 2)} % · CV : {fmt_dec(cv, 2)} % · erreur totale observée "
                f"{fmt_dec(te, 2)} % pour une ETa de {fmt(eta)} %. "
                + ("≥ 6 : excellent. " if sigma >= 6 else "4 à 6 : bon. " if sigma >= 4 else
                   "3 à 4 : limite, contrôle renforcé. " if sigma >= 3 else "< 3 : insuffisant. "))

    def exporter_pdf(self):
        if self.resultat is None:
            ui.alerte(self, "Rien à exporter", "Renseignez au moins le CV de fidélité intermédiaire.")
            return
        chemin = ui.demander_fichier_enregistrement(self, "Rapport d'incertitude",
                                                    f"Incertitude_{self.champ_analyte.text().strip() or 'analyte'}.pdf",
                                                    "Documents PDF (*.pdf)")
        if not chemin:
            return
        corps = (f"<p><b>{export.echapper(self.label_u.text())}</b></p><p>{export.echapper(self.label_exemple.text())}</p>"
                 + "<h2>Composantes</h2>" + export.table_html(["Composante", "Valeur"], [list(l) for l in self.lignes])
                 + "<h2>Sigma</h2><p>" + export.echapper(self.badge_sigma.text() + " — " + self.label_sigma.text()) + "</p>"
                 + "<p class='note'>u(biais) = √(RMS_biais² + u(Cref)²) ; u_c = √(u(Rw)² + u(biais)²) ; U = k·u_c "
                   "(Nordtest TR 537).</p>")
        try:
            export.exporter_pdf(chemin, f"Incertitude de mesure — {self.champ_analyte.text().strip()}", corps)
        except Exception as e:
            ui.erreur(self, "Échec de l'export", f"Impossible de créer le PDF : {e}")
            return
        ui.information(self, "Rapport créé", f"Rapport enregistré : {chemin.name}")
