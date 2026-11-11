"""
Écran « Fidélité et justesse » : répétabilité (une série) ou fidélité
intermédiaire (plusieurs séries, ANOVA à un facteur), comparaison à une limite
de CV et, si une valeur cible est fournie, estimation du biais (justesse).
"""
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QFormLayout, QHBoxLayout, QLabel, QLineEdit, QSplitter, QVBoxLayout, QWidget

from core import export, fidelite, ui
from core.formatage import fmt, fmt_dec, fmt_p, parse_nombre
from core.plot import PlotWidget

from . import logic


class FideliteView(QWidget):
    enregistree = Signal(int)

    def __init__(self, conn):
        super().__init__()
        self.conn = conn
        self.etude_id: int | None = None
        self.lignes_resultats: list[tuple[str, str, str]] = []
        self.verdicts: list[tuple[str, str]] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 16)
        root.setSpacing(10)
        entete = QHBoxLayout()
        self.titre_page = ui.titre_page("Fidélité et justesse")
        entete.addWidget(self.titre_page)
        entete.addStretch()
        entete.addWidget(ui.bouton("Nouvelle étude", self.nouvelle))
        entete.addWidget(ui.bouton("💾 Enregistrer", self.enregistrer, principal=True))
        entete.addWidget(ui.bouton("⬇ Rapport PDF", self.exporter_pdf))
        root.addLayout(entete)

        separateur = QSplitter(Qt.Horizontal)
        separateur.setChildrenCollapsible(False)
        saisie = QWidget()
        colonne = QVBoxLayout(saisie)
        colonne.setContentsMargins(0, 0, 8, 0)
        formulaire = QFormLayout()
        self.champ_titre = QLineEdit()
        self.champ_titre.setPlaceholderText("ex. TSH — fidélité intermédiaire niveau bas")
        self.champ_analyte = QLineEdit()
        self.champ_unite = QLineEdit()
        self.champ_echantillon = QLineEdit()
        self.champ_echantillon.setPlaceholderText("ex. Contrôle niveau 1, pool de sérums")
        self.champ_limite = QLineEdit()
        self.champ_limite.setPlaceholderText("CV maximal admissible, ex. 5")
        self.champ_cible = QLineEdit()
        self.champ_cible.setPlaceholderText("facultatif : valeur assignée / cible")
        self.champ_limite_biais = QLineEdit()
        self.champ_limite_biais.setPlaceholderText("biais maximal admissible, ex. 4")
        formulaire.addRow("Titre", self.champ_titre)
        formulaire.addRow("Analyte", self.champ_analyte)
        formulaire.addRow("Unité", self.champ_unite)
        formulaire.addRow("Échantillon", self.champ_echantillon)
        formulaire.addRow("Limite CV (%)", self.champ_limite)
        formulaire.addRow("Valeur cible", self.champ_cible)
        formulaire.addRow("Limite biais (%)", self.champ_limite_biais)
        colonne.addLayout(formulaire)
        outils = QHBoxLayout()
        outils.addWidget(ui.bouton("📂 Charger un fichier…", self._charger_fichier))
        outils.addWidget(ui.bouton("Exemple", self._charger_exemple, infobulle="Plan 5 jours × 5 répétitions fictif"))
        outils.addWidget(ui.bouton("Vider", lambda: self.table.vider()))
        colonne.addLayout(outils)
        colonne.addWidget(ui.texte_discret(
            "Deux colonnes : série (jour, run…) · valeur. Laissez la série vide pour une simple étude de "
            "répétabilité. Avec plusieurs séries, l'écart-type est décomposé en répétabilité (intra-série) et "
            "inter-séries ; leur combinaison donne la fidélité intermédiaire (CLSI EP15 / SH GTA 04)."))
        self.table = ui.TableSaisie(["Série", "Valeur"], numeriques=[1], lignes_initiales=25)
        colonne.addWidget(self.table, 1)
        separateur.addWidget(saisie)

        resultats = QWidget()
        droite = QVBoxLayout(resultats)
        droite.setContentsMargins(8, 0, 0, 0)
        droite.setSpacing(8)
        self.badges = QHBoxLayout()
        self.badge_cv = ui.badge("Saisissez au moins 2 valeurs", "neutre")
        self.badge_biais = ui.badge("", "neutre")
        self.badges.addWidget(self.badge_cv)
        self.badges.addWidget(self.badge_biais)
        self.badges.addStretch()
        droite.addLayout(self.badges)
        carte_graph, layout_graph = ui.carte_titree("Valeurs par série (trait : moyenne de la série)")
        self.plot = PlotWidget()
        self.plot.setMinimumHeight(260)
        layout_graph.addWidget(self.plot)
        droite.addWidget(carte_graph, 3)
        self.table_resultats = ui.table_cle_valeur(("Indicateur", "Valeur"))
        droite.addWidget(self.table_resultats, 2)
        self.formule = QLabel()
        self.formule.setObjectName("Formule")
        self.formule.setWordWrap(True)
        droite.addWidget(self.formule)
        separateur.addWidget(resultats)
        separateur.setSizes([360, 840])
        saisie.setMinimumWidth(320)
        root.addWidget(separateur, 1)

        self._minuteur = QTimer(self)
        self._minuteur.setSingleShot(True)
        self._minuteur.timeout.connect(self.calculer)
        self.table.modifie.connect(lambda: self._minuteur.start(400))
        for champ in (self.champ_limite, self.champ_cible, self.champ_limite_biais, self.champ_unite):
            champ.textChanged.connect(lambda _=None: self._minuteur.start(400))
        self.calculer()

    # ------------------------------------------------------------------
    def _donnees(self) -> list[tuple[str, float | None]]:
        return [((l[0] or "").strip(), parse_nombre(l[1])) for l in self.table.lignes()]

    def calculer(self):
        donnees = [(s, v) for s, v in self._donnees() if v is not None]
        unite = self.champ_unite.text().strip()
        limite_cv = parse_nombre(self.champ_limite.text())
        cible = parse_nombre(self.champ_cible.text())
        limite_biais = parse_nombre(self.champ_limite_biais.text())
        self.plot.effacer()
        self.lignes_resultats, self.verdicts = [], []
        self.formule.setText("")
        ui.definir_badge(self.badge_biais, "", "neutre")
        self.badge_biais.setVisible(False)
        if len(donnees) < 2:
            ui.definir_badge(self.badge_cv, "Saisissez au moins 2 valeurs", "neutre")
            self.table_resultats.setRowCount(0)
            self.plot.message_vide = "Saisissez ou collez les valeurs mesurées"
            return

        series: dict[str, list[float]] = {}
        for s, v in donnees:
            series.setdefault(s or "Série unique", []).append(v)
        valeurs = [v for _, v in donnees]
        globale = fidelite.statistiques_serie(valeurs)
        lignes = [("Nombre de valeurs · séries", f"{globale.n} · {len(series)}", ""),
                  ("Moyenne", f"{fmt(globale.moyenne)} {unite}", ""),
                  ("Étendue", f"{fmt(globale.minimum)} – {fmt(globale.maximum)} {unite}", "")]
        cv_retenu, libelle_cv = globale.cv, "CV global"

        if len(series) >= 2:
            try:
                comp = fidelite.composantes_variance(series)
            except ValueError as e:
                comp = None
                lignes.append(("Décomposition impossible", str(e), ""))
            if comp is not None:
                lignes += [
                    ("Répétabilité (intra-série) : s · CV",
                     f"{fmt(comp.s_repetabilite)} {unite} · {fmt_dec(comp.cv_repetabilite, 2)} %",
                     f"Écart-type intra-série, {comp.ddl_repetabilite} degrés de liberté."),
                    ("Inter-séries : s · CV", f"{fmt(comp.s_inter_series)} {unite} · {fmt_dec(comp.cv_inter_series, 2)} %",
                     "Variabilité supplémentaire d'une série à l'autre (0 si non mise en évidence)."),
                    ("Fidélité intermédiaire : s · CV",
                     f"{fmt(comp.s_fidelite_intermediaire)} {unite} · {fmt_dec(comp.cv_fidelite_intermediaire, 2)} %",
                     "√(s répétabilité² + s inter-séries²) — imprécision « au quotidien » du laboratoire."),
                ]
                cv_retenu, libelle_cv = comp.cv_fidelite_intermediaire, "CV de fidélité intermédiaire"
                self.formule.setText("s_FI = √(s_r² + s_inter²) ; s_r² = CM intra ; s_inter² = (CM inter − CM intra) / n₀  "
                                     "(analyse de variance à un facteur)")
        else:
            lignes += [
                ("Écart-type", f"{fmt(globale.ecart_type)} {unite}  IC 95 % [{fmt(globale.ecart_type_ic[0])} ; {fmt(globale.ecart_type_ic[1])}]", ""),
                ("CV (répétabilité)", f"{fmt_dec(globale.cv, 2)} %  IC 95 % [{fmt_dec(globale.cv_ic[0], 2)} ; {fmt_dec(globale.cv_ic[1], 2)}]"
                 if globale.cv_ic else "—", "IC calculé par la loi du χ²."),
            ]
            libelle_cv = "CV de répétabilité"
            self.formule.setText("CV = s / moyenne × 100 ; IC(s) = s·√((n−1)/χ²)")

        conforme = fidelite.conforme(cv_retenu, limite_cv)
        if conforme is None:
            ui.definir_badge(self.badge_cv, f"{libelle_cv} : {fmt_dec(cv_retenu, 2)} %", "neutre")
        else:
            ui.definir_badge(self.badge_cv, f"{libelle_cv} : {fmt_dec(cv_retenu, 2)} % — "
                             f"{'conforme' if conforme else 'NON conforme'} (limite {fmt(limite_cv)} %)",
                             "ok" if conforme else "rejet")
        self.verdicts.append((self.badge_cv.text(), "ok" if conforme else ("rejet" if conforme is False else "")))

        if cible is not None:
            j = fidelite.justesse(valeurs, cible)
            lignes += [("Valeur cible", f"{fmt(cible)} {unite}", ""),
                       ("Biais (justesse)", f"{fmt(j.biais)} {unite} · {fmt_dec(j.biais_pourcent, 2)} %",
                        "Moyenne observée − valeur cible."),
                       ("Test t (moyenne = cible)", fmt_p(j.p_student), "")]
            self.badge_biais.setVisible(True)
            if limite_biais is not None and j.biais_pourcent is not None:
                ok = abs(j.biais_pourcent) <= limite_biais
                ui.definir_badge(self.badge_biais, f"Biais {fmt_dec(j.biais_pourcent, 2)} % — "
                                 f"{'conforme' if ok else 'NON conforme'} (limite ± {fmt(limite_biais)} %)",
                                 "ok" if ok else "rejet")
                self.verdicts.append((self.badge_biais.text(), "ok" if ok else "rejet"))
            else:
                ui.definir_badge(self.badge_biais, f"Biais {fmt_dec(j.biais_pourcent, 2)} %", "neutre")
            if cv_retenu is not None and j.biais_pourcent is not None:
                lignes.append(("Erreur totale |biais| + 1.65·CV", f"{fmt_dec(abs(j.biais_pourcent) + 1.65 * cv_retenu, 2)} %",
                               "À comparer à l'erreur totale admissible de l'analyte."))

        self.lignes_resultats = lignes
        ui.remplir_table_cle_valeur(self.table_resultats, lignes)
        self._dessiner(series, cible)

    def _dessiner(self, series: dict[str, list[float]], cible: float | None):
        p = self.plot
        p.titre_y = self.champ_unite.text().strip()
        noms = list(series)
        xs, ys, infos = [], [], []
        for k, nom in enumerate(noms, start=1):
            vals = series[nom]
            for j, v in enumerate(vals):
                decalage = (j - (len(vals) - 1) / 2) * min(0.08, 0.6 / max(len(vals), 1))
                xs.append(k + decalage)
                ys.append(v)
                infos.append(f"{nom}\n{fmt(v)}")
            moyenne = sum(vals) / len(vals)
            p.ajouter_ligne([k - 0.3, k + 0.3], [moyenne, moyenne], "graph_tertiaire", 2.2)
        tout = [v for vals in series.values() for v in vals]
        moyenne = sum(tout) / len(tout)
        p.ajouter_repere_h(moyenne, "text", 1.0, tirets=False, etiquette=f"Moy. {fmt(moyenne)}")
        if cible is not None:
            p.ajouter_repere_h(cible, "statut_ok", 1.4, etiquette=f"Cible {fmt(cible)}")
        p.ajouter_points(xs, ys, "accent_graph", taille=7, infobulles=infos)
        etiquettes = [n if len(n) <= 10 else n[:9] + "…" for n in noms]
        pas = max(1, len(noms) // 10)
        p.definir_graduations_x(list(range(1, len(noms) + 1))[::pas], etiquettes[::pas])
        p.definir_limites(xmin=0.4, xmax=len(noms) + 0.6)

    # ------------------------------------------------------------------
    def _charger_fichier(self):
        chemin = ui.demander_fichier_ouverture(self, "Charger des valeurs", "Tableaux (*.xlsx *.csv *.txt)")
        if not chemin:
            return
        try:
            lignes = export.lire_tableau(chemin)
        except Exception as e:
            ui.erreur(self, "Lecture impossible", f"Impossible de lire ce fichier : {e}")
            return
        if lignes and max(len([c for c in l if c not in (None, "")]) for l in lignes) == 1:
            lignes = [["", l[0]] for l in lignes]
        self.table.definir_lignes([["" if c is None else str(c) for c in l[:2]] for l in lignes])

    def _charger_exemple(self):
        self.nouvelle()
        self.champ_titre.setText("Exemple — TSH niveau bas (données fictives)")
        self.champ_analyte.setText("TSH")
        self.champ_unite.setText("mUI/L")
        self.champ_echantillon.setText("Contrôle niveau 1")
        self.champ_limite.setText("5")
        self.champ_cible.setText("2.1")
        self.champ_limite_biais.setText("4")
        self.table.definir_lignes([list(l) for l in logic.exemple_fidelite()])
        self.calculer()

    def nouvelle(self):
        self.etude_id = None
        for champ in (self.champ_titre, self.champ_analyte, self.champ_unite, self.champ_echantillon,
                      self.champ_limite, self.champ_cible, self.champ_limite_biais):
            champ.clear()
        self.table.vider()
        self.titre_page.setText("Fidélité et justesse")
        self.calculer()

    def charger(self, etude: logic.Etude):
        self.etude_id = etude.id
        self.champ_titre.setText(etude.titre)
        self.champ_analyte.setText(etude.analyte)
        self.champ_unite.setText(etude.unite)
        self.champ_echantillon.setText(etude.methode_x)
        p = etude.parametres
        for champ, cle in ((self.champ_limite, "limite_cv"), (self.champ_cible, "cible"),
                           (self.champ_limite_biais, "limite_biais")):
            champ.setText("" if p.get(cle) is None else fmt(p[cle], 8))
        self.table.definir_lignes([[ident or "", "" if x is None else fmt(x, 10)] for ident, x, _ in etude.donnees])
        self.titre_page.setText(f"Fidélité et justesse — {etude.titre}")
        self.calculer()

    def enregistrer(self):
        etude = logic.Etude(
            id=self.etude_id, type=logic.TYPE_FIDELITE, titre=self.champ_titre.text(),
            analyte=self.champ_analyte.text(), unite=self.champ_unite.text(), methode_x=self.champ_echantillon.text(),
            parametres={"limite_cv": parse_nombre(self.champ_limite.text()), "cible": parse_nombre(self.champ_cible.text()),
                        "limite_biais": parse_nombre(self.champ_limite_biais.text())},
            donnees=[(s, v, None) for s, v in self._donnees()],
        )
        try:
            self.etude_id = logic.enregistrer_etude(self.conn, etude)
        except ValueError as e:
            ui.alerte(self, "Enregistrement impossible", str(e))
            return
        self.titre_page.setText(f"Fidélité et justesse — {etude.titre.strip()}")
        self.enregistree.emit(self.etude_id)
        ui.information(self, "Étude enregistrée", "L'étude est enregistrée et accessible dans la barre latérale.")

    def exporter_pdf(self):
        if not self.lignes_resultats:
            ui.alerte(self, "Rien à exporter", "Saisissez d'abord au moins 2 valeurs.")
            return
        base = self.champ_titre.text().strip() or "Fidelite"
        chemin = ui.demander_fichier_enregistrement(
            self, "Rapport de fidélité", "".join(c if c.isalnum() or c in " -_" else "_" for c in base) + ".pdf",
            "Documents PDF (*.pdf)")
        if not chemin:
            return
        infos = [["Analyte", self.champ_analyte.text()], ["Échantillon", self.champ_echantillon.text()],
                 ["Unité", self.champ_unite.text()], ["Limite CV", f"{self.champ_limite.text() or '—'} %"],
                 ["Valeur cible", self.champ_cible.text() or "—"], ["Limite biais", f"{self.champ_limite_biais.text() or '—'} %"]]
        corps = export.table_html(["Élément", "Valeur"], infos)
        corps += "<h2>Conclusion</h2>" + "".join(
            f"<p class='{classe}'>{export.echapper(texte)}</p>" for texte, classe in self.verdicts)
        corps += "<h2>Résultats</h2>" + export.table_html(["Indicateur", "Valeur"], [[l[0], l[1]] for l in self.lignes_resultats])
        corps += "<h2>Graphique</h2>" + export.image_html("fid.png", 620)
        corps += "<h2>Données</h2>" + export.table_html(["Série", "Valeur"], [[s, fmt(v)] for s, v in self._donnees() if v is not None], {1})
        try:
            export.exporter_pdf(chemin, f"Fidélité — {self.champ_titre.text().strip() or self.champ_analyte.text()}",
                                corps, {"fid.png": self.plot.image(900, 400)})
        except Exception as e:
            ui.erreur(self, "Échec de l'export", f"Impossible de créer le PDF : {e}")
            return
        ui.information(self, "Rapport créé", f"Rapport enregistré : {chemin.name}")
