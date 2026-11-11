"""
Écran « Comparaison de méthodes » : saisie ou collage des paires de résultats,
puis calcul automatique de Passing-Bablok, Deming, Bland-Altman, corrélation,
tests appariés et biais aux niveaux de décision médicale.
"""
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QSplitter, QTabWidget, QVBoxLayout, QWidget,
)

from core import comparaison_methodes as cm
from core import export, ui
from core.formatage import fmt, fmt_dec, fmt_intervalle, fmt_p, parse_nombre
from core.plot import PlotWidget

from . import logic

DELAI_CALCUL_MS = 400


def _texte(v) -> str:
    return "" if v is None else (fmt(v, 8) if isinstance(v, float) else str(v))


class ComparaisonView(QWidget):
    enregistree = Signal(int)

    def __init__(self, conn):
        super().__init__()
        self.conn = conn
        self.etude_id: int | None = None
        self.analyse: cm.AnalyseComparaison | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 16)
        root.setSpacing(10)

        entete = QHBoxLayout()
        self.titre_page = ui.titre_page("Comparaison de méthodes")
        entete.addWidget(self.titre_page)
        entete.addStretch()
        entete.addWidget(ui.bouton("Nouvelle étude", self.nouvelle))
        entete.addWidget(ui.bouton("💾 Enregistrer", self.enregistrer, principal=True))
        entete.addWidget(ui.bouton("⬇ Rapport PDF", self.exporter_pdf))
        entete.addWidget(ui.bouton("⬇ Excel", self.exporter_excel))
        root.addLayout(entete)

        separateur = QSplitter(Qt.Horizontal)
        separateur.setChildrenCollapsible(False)

        # ===== Colonne de saisie =====
        saisie = QWidget()
        colonne = QVBoxLayout(saisie)
        colonne.setContentsMargins(0, 0, 8, 0)
        colonne.setSpacing(8)
        formulaire = QFormLayout()
        formulaire.setVerticalSpacing(6)
        self.champ_titre = QLineEdit()
        self.champ_titre.setPlaceholderText("ex. Créatinine — nouvel automate vs ancien")
        self.champ_analyte = QLineEdit()
        self.champ_unite = QLineEdit()
        self.champ_unite.setPlaceholderText("ex. µmol/L")
        self.champ_x = QLineEdit()
        self.champ_x.setPlaceholderText("méthode de comparaison (référence)")
        self.champ_y = QLineEdit()
        self.champ_y.setPlaceholderText("méthode évaluée (nouvelle)")
        ligne_limite = QHBoxLayout()
        self.champ_limite = QLineEdit()
        self.champ_limite.setPlaceholderText("facultatif")
        self.mode_limite = QComboBox()
        self.mode_limite.addItem("%", "pourcent")
        self.mode_limite.addItem("unités", "absolu")
        ligne_limite.addWidget(self.champ_limite, 1)
        ligne_limite.addWidget(self.mode_limite)
        self.champ_lambda = QLineEdit("1")
        self.champ_lambda.setToolTip("Rapport des variances d'erreur (méthode évaluée / méthode de comparaison) "
                                     "pour la régression de Deming. 1 = imprécisions comparables.")
        self.champ_niveaux = QLineEdit()
        self.champ_niveaux.setPlaceholderText("ex. 60 ; 120 ; 400")
        self.champ_niveaux.setToolTip("Concentrations auxquelles estimer le biais (niveaux de décision médicale).")
        formulaire.addRow("Titre", self.champ_titre)
        formulaire.addRow("Analyte", self.champ_analyte)
        formulaire.addRow("Unité", self.champ_unite)
        formulaire.addRow("Méthode X", self.champ_x)
        formulaire.addRow("Méthode Y", self.champ_y)
        formulaire.addRow("Limite d'acceptation ±", ligne_limite)
        formulaire.addRow("λ (Deming)", self.champ_lambda)
        formulaire.addRow("Niveaux de décision", self.champ_niveaux)
        colonne.addLayout(formulaire)

        outils = QHBoxLayout()
        outils.addWidget(ui.bouton("📂 Charger un fichier…", self._charger_fichier))
        outils.addWidget(ui.bouton("Exemple", self._charger_exemple, infobulle="Charger un jeu de données fictif"))
        outils.addWidget(ui.bouton("Vider", self._vider))
        colonne.addLayout(outils)
        colonne.addWidget(ui.texte_discret(
            "Collez (Ctrl+V) trois colonnes depuis Excel : identifiant · résultat méthode X · résultat méthode Y. "
            "Les lignes incomplètes sont ignorées. Les calculs se mettent à jour automatiquement."))
        self.table = ui.TableSaisie(["Identifiant", "X", "Y"], numeriques=[1, 2], lignes_initiales=20)
        colonne.addWidget(self.table, 1)
        separateur.addWidget(saisie)

        # ===== Colonne de résultats =====
        resultats = QWidget()
        droite = QVBoxLayout(resultats)
        droite.setContentsMargins(8, 0, 0, 0)
        droite.setSpacing(8)
        self.badge_etat = ui.badge("Saisissez au moins 3 paires de résultats", "neutre")
        self.badge_etat.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        droite.addWidget(self.badge_etat)

        self.onglets = QTabWidget()
        self.plot_regression = PlotWidget()
        self.plot_ba = PlotWidget()
        self.plot_ba_pct = PlotWidget()
        self.table_resultats = ui.table_cle_valeur(("Indicateur", "Valeur [IC 95 %]"))
        self.table_decision = ui.table_cle_valeur(("Niveau X", "Y prédit · biais · biais %"))
        onglet_tableau = QWidget()
        lt = QVBoxLayout(onglet_tableau)
        lt.setContentsMargins(0, 8, 0, 0)
        lt.addWidget(self.table_resultats, 1)
        self.label_decision = ui.sous_titre("Biais aux niveaux de décision (droite de Passing-Bablok)")
        lt.addWidget(self.label_decision)
        lt.addWidget(self.table_decision)
        self.onglets.addTab(self._encadrer(self.plot_regression), "Régression")
        self.onglets.addTab(self._encadrer(self.plot_ba), "Bland-Altman")
        self.onglets.addTab(self._encadrer(self.plot_ba_pct), "Bland-Altman (%)")
        self.onglets.addTab(onglet_tableau, "Résultats détaillés")
        droite.addWidget(self.onglets, 3)

        carte_conclusions, layout_conclusions = ui.carte_titree("Interprétation")
        self.conclusions = QLabel()
        self.conclusions.setWordWrap(True)
        self.conclusions.setTextFormat(Qt.RichText)
        layout_conclusions.addWidget(self.conclusions)
        droite.addWidget(carte_conclusions)
        separateur.addWidget(resultats)
        separateur.setSizes([380, 820])
        saisie.setMinimumWidth(330)
        root.addWidget(separateur, 1)

        self._minuteur = QTimer(self)
        self._minuteur.setSingleShot(True)
        self._minuteur.timeout.connect(self.calculer)
        self.table.modifie.connect(self._planifier)
        for champ in (self.champ_limite, self.champ_lambda, self.champ_niveaux, self.champ_unite,
                      self.champ_x, self.champ_y):
            champ.textChanged.connect(self._planifier)
        self.mode_limite.currentIndexChanged.connect(self._planifier)
        self.calculer()

    @staticmethod
    def _encadrer(plot: PlotWidget) -> QWidget:
        conteneur = QWidget()
        layout = QVBoxLayout(conteneur)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.addWidget(plot)
        return conteneur

    def _planifier(self, *_):
        self._minuteur.start(DELAI_CALCUL_MS)

    # ------------------------------------------------------------------
    # Données
    # ------------------------------------------------------------------
    def _paires(self) -> list[tuple[str, float | None, float | None]]:
        paires = []
        for i, ligne in enumerate(self.table.lignes(), start=1):
            ident = ligne[0] or f"#{i}"
            paires.append((ident, parse_nombre(ligne[1]), parse_nombre(ligne[2])))
        return paires

    def _nombre(self, champ: QLineEdit, defaut=None):
        v = parse_nombre(champ.text())
        return defaut if v is None else v

    def _niveaux_decision(self) -> list[float]:
        morceaux = self.champ_niveaux.text().replace("|", ";").split(";")
        return [v for v in (parse_nombre(m) for m in morceaux) if v is not None]

    def _nom_x(self) -> str:
        return self.champ_x.text().strip() or "Méthode X"

    def _nom_y(self) -> str:
        return self.champ_y.text().strip() or "Méthode Y"

    # ------------------------------------------------------------------
    # Calcul et affichage
    # ------------------------------------------------------------------
    def calculer(self):
        paires = [(i, x, y) for i, x, y in self._paires() if x is not None and y is not None]
        lambda_ = self._nombre(self.champ_lambda, 1.0)
        try:
            if lambda_ <= 0:
                raise ValueError("λ doit être strictement positif.")
            self.analyse = cm.analyser([x for _, x, _ in paires], [y for _, _, y in paires], lambda_)
        except ValueError as e:
            self.analyse = None
            ui.definir_badge(self.badge_etat, str(e), "neutre")
            for plot in (self.plot_regression, self.plot_ba, self.plot_ba_pct):
                plot.effacer()
                plot.message_vide = "Saisissez ou collez au moins 3 paires de résultats"
            self.table_resultats.setRowCount(0)
            self.table_decision.setRowCount(0)
            self.conclusions.setText("")
            return
        self._identifiants = [i for i, _, _ in paires]
        self._dessiner_regression()
        self._dessiner_bland_altman(self.plot_ba, self.analyse.bland_altman)
        if self.analyse.bland_altman_pourcent is not None:
            self._dessiner_bland_altman(self.plot_ba_pct, self.analyse.bland_altman_pourcent)
        else:
            self.plot_ba_pct.effacer()
        self._remplir_resultats()
        self._remplir_decision()
        self._remplir_conclusions()

    def _limite(self) -> tuple[float | None, str]:
        return self._nombre(self.champ_limite), self.mode_limite.currentData()

    def _dessiner_regression(self):
        a = self.analyse
        p = self.plot_regression
        p.effacer()
        unite = self.champ_unite.text().strip()
        p.titre_x = f"{self._nom_x()}" + (f" ({unite})" if unite else "")
        p.titre_y = f"{self._nom_y()}" + (f" ({unite})" if unite else "")
        bas = min(min(a.x), min(a.y))
        haut = max(max(a.x), max(a.y))
        marge = (haut - bas) * 0.05 or 1
        p.definir_limites(bas - marge, haut + marge, bas - marge, haut + marge)
        limite, mode = self._limite()
        if limite:
            xs = [bas - marge, haut + marge]
            if mode == "pourcent":
                p.ajouter_bande(xs, [x * (1 - limite / 100) for x in xs], [x * (1 + limite / 100) for x in xs],
                                "statut_ok", 30)
            else:
                p.ajouter_bande(xs, [x - limite for x in xs], [x + limite for x in xs], "statut_ok", 30)
        p.ajouter_droite(1, 0, "muted", 1.2, tirets=True, nom="y = x")
        if a.deming:
            p.ajouter_droite(a.deming.pente.valeur, a.deming.ordonnee.valeur, "graph_secondaire", 1.6, tirets=True,
                             nom=f"Deming : y = {fmt(a.deming.ordonnee.valeur)} + {fmt(a.deming.pente.valeur)}·x")
        if a.passing_bablok:
            pb = a.passing_bablok
            p.ajouter_droite(pb.pente.valeur, pb.ordonnee.valeur, "accent_graph", 2.0,
                             nom=f"Passing-Bablok : y = {fmt(pb.ordonnee.valeur)} + {fmt(pb.pente.valeur)}·x")
        p.ajouter_points(a.x, a.y, "accent_graph", taille=7,
                         infobulles=[f"{i}\nX = {fmt(x)}  ·  Y = {fmt(y)}\nÉcart = {fmt(y - x)} ({fmt_dec(100 * (y - x) / x if x else None, 1)} %)"
                                     for i, x, y in zip(self._identifiants, a.x, a.y)])

    def _dessiner_bland_altman(self, p: PlotWidget, ba: cm.ResultatBlandAltman):
        p.effacer()
        unite = "%" if ba.mode == "pourcent" else (self.champ_unite.text().strip() or "unités")
        p.titre_x = f"Moyenne des deux méthodes ({self.champ_unite.text().strip() or 'unités'})"
        p.titre_y = f"{self._nom_y()} − {self._nom_x()} ({unite})"
        limite, mode = self._limite()
        if limite and ((mode == "pourcent") == (ba.mode == "pourcent")):
            p.ajouter_bande_h(-limite, limite, "statut_ok", 28)
            p.ajouter_repere_h(limite, "statut_ok", 1.0, etiquette=f"+{fmt(limite)} (limite)")
            p.ajouter_repere_h(-limite, "statut_ok", 1.0, etiquette=f"−{fmt(limite)} (limite)")
        if ba.biais.ic_bas is not None:
            p.ajouter_bande_h(ba.biais.ic_bas, ba.biais.ic_haut, "accent_graph", 35)
        for lim in (ba.limite_basse, ba.limite_haute):
            if lim.ic_bas is not None:
                p.ajouter_bande_h(lim.ic_bas, lim.ic_haut, "statut_alerte", 28)
        p.ajouter_repere_h(0, "muted", 1.0, tirets=False, inclure=True)
        p.ajouter_repere_h(ba.biais.valeur, "accent_graph", 1.6, tirets=False, etiquette=f"Biais {fmt(ba.biais.valeur)}")
        p.ajouter_repere_h(ba.limite_haute.valeur, "statut_alerte", 1.3, etiquette=f"+1.96 s {fmt(ba.limite_haute.valeur)}")
        p.ajouter_repere_h(ba.limite_basse.valeur, "statut_alerte", 1.3, etiquette=f"−1.96 s {fmt(ba.limite_basse.valeur)}")
        if ba.pente_tendance is not None and ba.p_tendance is not None and ba.p_tendance < 0.05:
            moyenne_d = sum(ba.differences) / len(ba.differences)
            moyenne_m = sum(ba.moyennes) / len(ba.moyennes)
            p.ajouter_droite(ba.pente_tendance, moyenne_d - ba.pente_tendance * moyenne_m, "graph_tertiaire", 1.2,
                             tirets=True, nom="Tendance (significative)")
        identifiants = self._identifiants if len(self._identifiants) == ba.n else [""] * ba.n
        couleurs = None
        if limite and ((mode == "pourcent") == (ba.mode == "pourcent")):
            couleurs = ["accent_graph" if abs(d) <= limite else "statut_rejet" for d in ba.differences]
        p.ajouter_points(ba.moyennes, ba.differences, "accent_graph", couleurs=couleurs, taille=7,
                         infobulles=[f"{i}\nMoyenne = {fmt(m)}\nDifférence = {fmt(d)} {unite}"
                                     for i, m, d in zip(identifiants, ba.moyennes, ba.differences)])

    def _lignes_resultats(self) -> list[tuple[str, str, str]]:
        a = self.analyse
        u = self.champ_unite.text().strip()
        lignes = [("Nombre de paires", str(a.n), "Paires de résultats complètes prises en compte.")]
        for reg, info in ((a.passing_bablok, "Régression non paramétrique, robuste, erreurs sur X et Y."),
                          (a.deming, "Régression tenant compte des erreurs sur X et Y (λ = rapport des variances)."),
                          (a.moindres_carres, "Suppose X sans erreur : à titre indicatif seulement.")):
            if reg is None:
                continue
            lignes.append((f"{reg.methode} — pente", f"{fmt(reg.pente.valeur)}  {fmt_intervalle(reg.pente.ic_bas, reg.pente.ic_haut)}", info))
            lignes.append((f"{reg.methode} — ordonnée à l'origine",
                           f"{fmt(reg.ordonnee.valeur)}  {fmt_intervalle(reg.ordonnee.ic_bas, reg.ordonnee.ic_haut)}", info))
            if reg.cusum_p is not None:
                lignes.append(("Linéarité (Cusum)", f"{'linéaire' if reg.lineaire else 'NON linéaire'} ({fmt_p(reg.cusum_p)})",
                               "Test de linéarité de Passing-Bablok : p < 0.05 indique un écart à la linéarité."))
            if reg.r2 is not None:
                lignes.append(("Moindres carrés — r² · s(y/x)", f"{fmt_dec(reg.r2, 4)} · {fmt(reg.ecart_type_residuel)}", info))
        if a.correlation:
            c = a.correlation
            lignes.append(("Corrélation de Pearson r", f"{fmt_dec(c.pearson.valeur, 4)}  {fmt_intervalle(c.pearson.ic_bas, c.pearson.ic_haut)}",
                           "Mesure l'association, PAS la concordance : deux méthodes très corrélées peuvent être biaisées."))
            lignes.append(("Corrélation de Spearman ρ", fmt_dec(c.spearman, 4), "Corrélation des rangs."))
        for ba in (a.bland_altman, a.bland_altman_pourcent):
            if ba is None:
                continue
            unite = "%" if ba.mode == "pourcent" else u
            suffixe = " (%)" if ba.mode == "pourcent" else ""
            lignes.append((f"Biais moyen{suffixe}", f"{fmt(ba.biais.valeur)} {unite}  {fmt_intervalle(ba.biais.ic_bas, ba.biais.ic_haut)}",
                           "Moyenne des différences Y − X."))
            lignes.append((f"Écart-type des différences{suffixe}", f"{fmt(ba.ecart_type)} {unite}", ""))
            lignes.append((f"Limites d'agrément{suffixe}", f"{fmt(ba.limite_basse.valeur)} ; {fmt(ba.limite_haute.valeur)} {unite}",
                           "Biais ± 1.96 écart-type : 95 % des différences attendues entre ces bornes."))
        t = a.tests
        lignes.append(("t de Student apparié", fmt_p(t.p_student), "La moyenne des différences diffère-t-elle de 0 ?"))
        lignes.append(("Wilcoxon (rangs signés)", fmt_p(t.p_wilcoxon), "Équivalent non paramétrique du t apparié."))
        if a.bland_altman.p_normalite is not None:
            lignes.append(("Normalité des différences (Shapiro-Wilk)", fmt_p(a.bland_altman.p_normalite),
                           "Les limites d'agrément supposent des différences à peu près normales."))
        limite, mode = self._limite()
        ba = a.bland_altman_pourcent if mode == "pourcent" else a.bland_altman
        if limite and ba is not None:
            dans, n, ok = cm.conformite_limite(ba, limite)
            lignes.append((f"Différences dans ±{fmt(limite)} {'%' if mode == 'pourcent' else u}",
                           f"{dans} / {n} ({fmt_dec(100 * dans / n, 1)} %) — limites d'agrément {'dans' if ok else 'HORS de'} la limite",
                           "Critère d'acceptation défini par le laboratoire."))
        return lignes

    def _remplir_resultats(self):
        ui.remplir_table_cle_valeur(self.table_resultats, self._lignes_resultats())

    def _lignes_decision(self) -> list[tuple[str, str]]:
        reg = self.analyse.passing_bablok or self.analyse.deming
        if reg is None:
            return []
        lignes = []
        for xc in self._niveaux_decision():
            yc = reg.predire(xc)
            biais = yc - xc
            lignes.append((fmt(xc), f"{fmt(yc)} · {fmt(biais)} · {fmt_dec(100 * biais / xc if xc else None, 2)} %"))
        return lignes

    def _remplir_decision(self):
        lignes = self._lignes_decision()
        ui.remplir_table_cle_valeur(self.table_decision, lignes)
        visible = bool(lignes)
        self.table_decision.setVisible(visible)
        self.label_decision.setVisible(visible)
        if visible:
            ui.ajuster_hauteur_table(self.table_decision, 8)

    def _remplir_conclusions(self):
        a = self.analyse
        morceaux = [f"<p>• {export.echapper(c)}</p>" for c in a.conclusions]
        morceaux += [f"<p style='color:#B07209'>⚠ {export.echapper(w)}</p>" for w in a.avertissements]
        self.conclusions.setText("".join(morceaux) or "—")
        limite, mode = self._limite()
        ba = a.bland_altman_pourcent if mode == "pourcent" else a.bland_altman
        if limite and ba is not None:
            dans, n, ok = cm.conformite_limite(ba, limite)
            ui.definir_badge(self.badge_etat,
                             f"{a.n} paires · {dans}/{n} différences dans ±{fmt(limite)}"
                             f"{' %' if mode == 'pourcent' else ''} · limites d'agrément {'conformes' if ok else 'NON conformes'}",
                             "ok" if ok else "rejet")
        else:
            ui.definir_badge(self.badge_etat, f"{a.n} paires analysées — renseignez une limite d'acceptation pour conclure",
                             "neutre")

    # ------------------------------------------------------------------
    # Outils de saisie
    # ------------------------------------------------------------------
    def _charger_fichier(self):
        chemin = ui.demander_fichier_ouverture(self, "Charger des paires de résultats", "Tableaux (*.xlsx *.csv *.txt)")
        if not chemin:
            return
        try:
            lignes = export.lire_tableau(chemin)
        except Exception as e:
            ui.erreur(self, "Lecture impossible", f"Impossible de lire ce fichier : {e}")
            return
        largeur = max((sum(1 for c in l if c not in (None, "")) for l in lignes), default=0)
        if largeur == 2:
            lignes = [[""] + list(l) for l in lignes]   # deux colonnes seulement : pas d'identifiant
        if lignes and parse_nombre(lignes[0][1] if len(lignes[0]) > 1 else None) is None:
            lignes = lignes[1:]                          # ligne d'en-tête
        self.table.definir_lignes([[_texte(c) for c in l[:3]] for l in lignes])
        if not self.champ_titre.text().strip():
            self.champ_titre.setText(chemin.stem)

    def _charger_exemple(self):
        self.nouvelle()
        self.champ_titre.setText("Exemple — créatinine (données fictives)")
        self.champ_analyte.setText("Créatinine")
        self.champ_unite.setText("µmol/L")
        self.champ_x.setText("Automate actuel")
        self.champ_y.setText("Nouvel automate")
        self.champ_limite.setText("7.4")
        self.champ_niveaux.setText("60 ; 110 ; 350")
        self.table.definir_lignes([list(l) for l in logic.exemple_comparaison()])
        self.champ_titre.setCursorPosition(0)
        self.calculer()

    def _vider(self):
        if self.table.lignes() and not ui.confirmer(self, "Vider le tableau", "Effacer toutes les paires saisies ?", "Vider"):
            return
        self.table.vider()

    def nouvelle(self):
        self.etude_id = None
        for champ in (self.champ_titre, self.champ_analyte, self.champ_unite, self.champ_x, self.champ_y,
                      self.champ_limite, self.champ_niveaux):
            champ.clear()
        self.champ_lambda.setText("1")
        self.mode_limite.setCurrentIndex(0)
        self.table.vider()
        self.titre_page.setText("Comparaison de méthodes")
        self.calculer()

    # ------------------------------------------------------------------
    # Enregistrement
    # ------------------------------------------------------------------
    def charger(self, etude: logic.Etude):
        self.etude_id = etude.id
        self.champ_titre.setText(etude.titre)
        self.champ_analyte.setText(etude.analyte)
        self.champ_unite.setText(etude.unite)
        self.champ_x.setText(etude.methode_x)
        self.champ_y.setText(etude.methode_y)
        p = etude.parametres
        self.champ_limite.setText(_texte(p.get("limite")))
        self.mode_limite.setCurrentIndex(max(self.mode_limite.findData(p.get("mode_limite", "pourcent")), 0))
        self.champ_lambda.setText(_texte(p.get("lambda", 1.0)))
        self.champ_niveaux.setText(" ; ".join(fmt(v, 8) for v in p.get("niveaux_decision", [])))
        self.table.definir_lignes([[ident or "", _texte(x), _texte(y)] for ident, x, y in etude.donnees])
        self.titre_page.setText(f"Comparaison de méthodes — {etude.titre}")
        self.champ_titre.setCursorPosition(0)
        self.calculer()

    def _etude(self) -> logic.Etude:
        return logic.Etude(
            id=self.etude_id, type=logic.TYPE_COMPARAISON, titre=self.champ_titre.text(),
            analyte=self.champ_analyte.text(), unite=self.champ_unite.text(),
            methode_x=self.champ_x.text(), methode_y=self.champ_y.text(),
            parametres={"limite": self._nombre(self.champ_limite), "mode_limite": self.mode_limite.currentData(),
                        "lambda": self._nombre(self.champ_lambda, 1.0), "niveaux_decision": self._niveaux_decision()},
            donnees=self._paires(),
        )

    def enregistrer(self):
        try:
            self.etude_id = logic.enregistrer_etude(self.conn, self._etude())
        except ValueError as e:
            ui.alerte(self, "Enregistrement impossible", str(e))
            return
        self.titre_page.setText(f"Comparaison de méthodes — {self.champ_titre.text().strip()}")
        self.enregistree.emit(self.etude_id)
        ui.information(self, "Étude enregistrée", "L'étude est enregistrée et accessible dans la barre latérale.")

    # ------------------------------------------------------------------
    # Exports
    # ------------------------------------------------------------------
    def _nom_fichier(self, extension: str) -> str:
        base = self.champ_titre.text().strip() or "Comparaison_methodes"
        return "".join(c if c.isalnum() or c in " -_" else "_" for c in base) + extension

    def exporter_excel(self):
        if self.analyse is None:
            ui.alerte(self, "Rien à exporter", "Saisissez d'abord au moins 3 paires de résultats.")
            return
        chemin = ui.demander_fichier_enregistrement(self, "Exporter l'étude", self._nom_fichier(".xlsx"), "Fichiers Excel (*.xlsx)")
        if not chemin:
            return
        a = self.analyse
        donnees = [[i, x, y, y - x, (x + y) / 2, (100 * (y - x) / ((x + y) / 2)) if (x + y) else None]
                   for i, x, y in zip(self._identifiants, a.x, a.y)]
        try:
            export.exporter_excel(chemin, [
                ("Données", ["Identifiant", self._nom_x(), self._nom_y(), "Différence Y−X", "Moyenne", "Différence %"], donnees),
                ("Résultats", ["Indicateur", "Valeur"], [[l[0], l[1]] for l in self._lignes_resultats()]),
                ("Niveaux de décision", ["Niveau X", "Y prédit · biais · biais %"], [list(l) for l in self._lignes_decision()]),
            ])
        except Exception as e:
            ui.erreur(self, "Échec de l'export", f"Impossible d'exporter : {e}")
            return
        ui.information(self, "Export terminé", f"Fichier enregistré : {chemin.name}")

    def exporter_pdf(self):
        if self.analyse is None:
            ui.alerte(self, "Rien à exporter", "Saisissez d'abord au moins 3 paires de résultats.")
            return
        chemin = ui.demander_fichier_enregistrement(self, "Rapport de comparaison", self._nom_fichier(".pdf"),
                                                    "Documents PDF (*.pdf)")
        if not chemin:
            return
        a = self.analyse
        e = export.echapper
        limite, mode = self._limite()
        infos = [("Analyte", self.champ_analyte.text()), ("Unité", self.champ_unite.text()),
                 ("Méthode de comparaison (X)", self._nom_x()), ("Méthode évaluée (Y)", self._nom_y()),
                 ("Limite d'acceptation", f"± {fmt(limite)} {'%' if mode == 'pourcent' else self.champ_unite.text()}" if limite else "non définie")]
        corps = [export.table_html(["Élément", "Valeur"], [[k, v] for k, v in infos])]
        corps.append("<h2>Interprétation</h2>" + export.liste_html(a.conclusions))
        if a.avertissements:
            corps.append("<p class='note'>" + "<br>".join("⚠ " + e(w) for w in a.avertissements) + "</p>")
        images = {"reg.png": self.plot_regression.image(820, 520), "ba.png": self.plot_ba.image(900, 400)}
        corps.append("<h2>Régression</h2>" + export.image_html("reg.png", 520))
        corps.append("<h2>Diagramme de Bland-Altman</h2>" + export.image_html("ba.png", 640))
        if a.bland_altman_pourcent is not None:
            images["ba_pct.png"] = self.plot_ba_pct.image(900, 400)
            corps.append("<h2>Diagramme de Bland-Altman (%)</h2>" + export.image_html("ba_pct.png", 640))
        corps.append("<h2>Résultats détaillés</h2>")
        corps.append(export.table_html(["Indicateur", "Valeur [IC 95 %]"], [[l[0], l[1]] for l in self._lignes_resultats()]))
        if self._lignes_decision():
            corps.append("<h2>Biais aux niveaux de décision médicale</h2>")
            corps.append(export.table_html(["Niveau X", "Y prédit · biais · biais %"], [list(l) for l in self._lignes_decision()]))
        corps.append("<h2>Données</h2>")
        corps.append(export.table_html(["Identifiant", self._nom_x(), self._nom_y(), "Y − X"],
                                       [[i, fmt(x), fmt(y), fmt(y - x)] for i, x, y in zip(self._identifiants, a.x, a.y)],
                                       alignement_droite={1, 2, 3}))
        corps.append("<p class='note'>Méthodes : Passing & Bablok (1983) avec test Cusum ; Deming avec IC par jackknife ; "
                     "Bland & Altman (1986, 1999). Visa : ______________________ Date : ____________</p>")
        try:
            export.exporter_pdf(chemin, f"Comparaison de méthodes — {self.champ_titre.text().strip() or self.champ_analyte.text()}",
                                "".join(corps), images)
        except Exception as ex:
            ui.erreur(self, "Échec de l'export", f"Impossible de créer le PDF : {ex}")
            return
        ui.information(self, "Rapport créé", f"Rapport enregistré : {chemin.name}")
