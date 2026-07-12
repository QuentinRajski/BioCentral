"""
Tableau de bord d'un paramètre.

Disposition (validée avec l'utilisateur — voir la conversation de conception) :
  - Bloc de gauche : tableau des échantillons en haut, puis statistiques
    descriptives (liste verticale) et tableau de percentiles côte à côte.
  - Bloc de droite : les deux histogrammes empilés, puis les deux camemberts.

Les camemberts (tranches d'âge, sexe) réagissent aux mêmes filtres que le
reste de la page — décision explicite : "tant pis si ça affiche 100%" plutôt
qu'une vue toujours globale indépendante du filtre.
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QStyledItemDelegate, QSizePolicy,
    QCheckBox, QPushButton, QScrollArea, QFrame,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont

from core.stats import compute_stats, PERCENTILES
from core.charts import build_histogram, build_pie, build_boxplot, build_temporal, COULEUR_SECONDAIRE
from core.tests_statistiques import test_normalite, detecter_aberrantes, comparer_deux_groupes
from .tranches_dialog import TranchesDialog
from .domaine_dialog import DomaineMesureDialog


class _DelegueCouleurFond(QStyledItemDelegate):
    """Les styles QSS ciblant ::item désactivent le rendu normal de Qt::BackgroundRole,
    même sans propriété background-color explicite. Ce délégué peint la couleur de
    fond lui-même avant de laisser le style habituel gérer texte/bordures/padding."""
    def paint(self, painter, option, index):
        couleur = index.data(Qt.BackgroundRole)
        if couleur is not None:
            painter.save()
            painter.fillRect(option.rect, couleur)
            painter.restore()
        super().paint(painter, option, index)


def _card(inner_layout) -> QWidget:
    w = QWidget()
    w.setObjectName("Card")
    w.setAttribute(Qt.WA_StyledBackground, True)
    w.setLayout(inner_layout)
    return w


COULEUR_LIGNE_PAIRE = QColor("#FFFFFF")
COULEUR_LIGNE_IMPAIRE = QColor("#FAF9F5")
COULEUR_HORS_BORNES = QColor("#FBEAEA")  # rouge pâle : résultat sous/sur le domaine de mesure


def _style_table(table: QTableWidget) -> None:
    """Polish commun à tous les tableaux : évite le look 'tableur' par défaut de Qt.
    L'alternance de couleur est gérée manuellement ligne par ligne (pas via QSS),
    pour pouvoir la combiner avec un surlignage ponctuel sans conflit de priorité."""
    table.verticalHeader().setVisible(False)
    table.setShowGrid(False)
    table.setAlternatingRowColors(False)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.horizontalHeader().setHighlightSections(False)
    table.verticalHeader().setDefaultSectionSize(34)
    table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
    table.horizontalHeader().setFixedHeight(34)
    table.setObjectName("Card")
    table.setItemDelegate(_DelegueCouleurFond(table))


def _couleur_ligne(index: int, surlignee: bool = False) -> QColor:
    if surlignee:
        return COULEUR_HORS_BORNES
    return COULEUR_LIGNE_IMPAIRE if index % 2 else COULEUR_LIGNE_PAIRE


class _ItemTriable(QTableWidgetItem):
    """QTableWidgetItem dont le tri se base sur une clé numérique séparée du texte
    affiché — évite le piège de setData(Qt.EditRole, ...) qui écraserait le texte
    personnalisé ("50 ans", "<0.3") avec la valeur numérique brute."""
    def __init__(self, texte: str, cle_tri):
        super().__init__(texte)
        self._cle_tri = cle_tri

    def __lt__(self, other):
        if isinstance(other, _ItemTriable) and self._cle_tri is not None and other._cle_tri is not None:
            return self._cle_tri < other._cle_tri
        return super().__lt__(other)


def _right_align(item: QTableWidgetItem) -> QTableWidgetItem:
    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return item


def _formater_date_fr(iso_date: str) -> str:
    try:
        annee, mois, jour = iso_date.split("-")
        return f"{jour}/{mois}/{annee}"
    except (ValueError, AttributeError):
        return iso_date or ""


INFOBULLES_STATS = {
    "Échantillons": "Nombre de résultats valides pris en compte pour ce filtre (les résultats annulés sont exclus).",
    "Moyenne": "Somme des valeurs divisée par le nombre de résultats.\nFormule : Σx / n",
    "Médiane": "Valeur centrale une fois les résultats triés (équivaut au percentile 50).",
    "Écart-type": "Mesure la dispersion des valeurs autour de la moyenne.\nFormule : √(Σ(x − moyenne)² / (n − 1))",
    "CV (%)": "Coefficient de variation : dispersion relative à la moyenne, utile pour comparer deux paramètres entre eux.\nFormule : (écart-type / moyenne) × 100",
    "Min": "Plus petite valeur de l'ensemble filtré (inclut les résultats sous le seuil de détection, ex. <0.3).",
    "Max": "Plus grande valeur de l'ensemble filtré.",
}


def _infobulle_percentile(p) -> str:
    return f"{p} % des résultats filtrés sont inférieurs ou égaux à cette valeur."


def _formater_p(p: float) -> str:
    return "p < 0,0001" if p < 0.0001 else f"p = {p}".replace(".", ",")


class DashboardWidget(QWidget):
    def __init__(self, conn, parametre_id: int, parametre_nom: str):
        super().__init__()
        self.conn = conn
        self.parametre_id = parametre_id
        self.parametre_nom = parametre_nom

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(14)

        # --- En-tête + filtres ---
        header = QHBoxLayout()
        titre = QLabel(f"Paramètre : {parametre_nom}")
        titre.setObjectName("TitrePage")
        header.addWidget(titre)
        header.addStretch()

        self.filtre_tranche = QComboBox()
        self.filtre_sexe = QComboBox()
        self.filtre_sexe.addItems(["Tous", "Féminin", "Masculin"])
        btn_modifier_tranches = QPushButton("✎ Modifier les tranches")
        btn_modifier_tranches.clicked.connect(self._ouvrir_dialogue_tranches)
        header.addWidget(btn_modifier_tranches)
        btn_modifier_domaine = QPushButton("✎ Modifier le domaine")
        btn_modifier_domaine.clicked.connect(self._ouvrir_dialogue_domaine)
        header.addWidget(btn_modifier_domaine)
        header.addWidget(self.filtre_tranche)
        header.addWidget(self.filtre_sexe)
        root.addLayout(header)

        self._charger_tranches()
        self.filtre_tranche.currentIndexChanged.connect(self.rafraichir)
        self.filtre_sexe.currentIndexChanged.connect(self.rafraichir)

        # --- Corps : tableau (pleine hauteur) + stats/percentiles + graphiques ---
        # Enveloppé dans un QScrollArea : sur petit écran, une barre de défilement
        # apparaît plutôt que d'écraser le contenu des colonnes.
        corps_container = QWidget()
        corps = QHBoxLayout(corps_container)
        corps.setContentsMargins(0, 0, 0, 0)
        corps.setSpacing(16)

        corps_scroll = QScrollArea()
        corps_scroll.setWidgetResizable(True)
        corps_scroll.setFrameShape(QFrame.NoFrame)
        corps_scroll.setWidget(corps_container)
        root.addWidget(corps_scroll, stretch=1)

        # ===== Colonne 1 : tableau des échantillons, pleine hauteur =====
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["N° demande", "Sexe", "Âge", "Date de prélèvement", "Résultat"])
        _style_table(self.table)
        self.table.setObjectName("CardAccentBleu")
        table_header = self.table.horizontalHeader()
        for col in range(5):
            table_header.setSectionResizeMode(col, QHeaderView.Interactive)
        self.table.setColumnWidth(0, 140)
        self.table.setColumnWidth(1, 110)
        self.table.setColumnWidth(2, 90)
        self.table.setColumnWidth(3, 150)
        self.table.setColumnWidth(4, 110)
        # Largeur fixée à la somme des colonnes + bordure/ascenseur (pas de vide interne).
        self.table.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.table.setFixedWidth(140 + 110 + 90 + 150 + 110 + 24)

        colonne_table = QVBoxLayout()
        colonne_table.setSpacing(8)
        colonne_table.addWidget(self.table, stretch=1)

        self.case_hors_bornes = QCheckBox("Afficher uniquement les résultats hors bornes")
        self.case_hors_bornes.stateChanged.connect(self.rafraichir)
        colonne_table.addWidget(self.case_hors_bornes)

        self.label_sous_borne = QLabel("")
        self.label_sous_borne.setObjectName("Muted")
        self.label_sur_borne = QLabel("")
        self.label_sur_borne.setObjectName("Muted")
        colonne_table.addWidget(self.label_sous_borne)
        colonne_table.addWidget(self.label_sur_borne)

        corps.addLayout(colonne_table, stretch=0)

        # ===== Colonne 2 : statistiques descriptives, puis percentiles en dessous =====
        colonne_stats_widget = QWidget()
        colonne_stats_widget.setMinimumWidth(320)
        colonne_stats = QVBoxLayout(colonne_stats_widget)
        colonne_stats.setContentsMargins(0, 0, 0, 0)
        colonne_stats.setSpacing(12)
        corps.addWidget(colonne_stats_widget, stretch=1)

        self.stats_table = QTableWidget(7, 2)
        self.stats_table.setHorizontalHeaderLabels(["Statistique", "Valeur"])
        _style_table(self.stats_table)
        self.stats_table.setObjectName("CardAccentBleu")
        self.stats_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.stats_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.stats_table.setFixedHeight(34 * 8 + 4)
        colonne_stats.addWidget(self.stats_table, stretch=0)

        self.tests_table = QTableWidget(3, 2)
        self.tests_table.setHorizontalHeaderLabels(["Test statistique", "Résultat"])
        _style_table(self.tests_table)
        self.tests_table.setObjectName("CardAccentBleu")
        self.tests_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tests_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tests_table.setFixedHeight(34 * 4 + 4)
        colonne_stats.addWidget(self.tests_table, stretch=0)

        self.percentile_table = QTableWidget(len(PERCENTILES), 2)
        self.percentile_table.setHorizontalHeaderLabels(["Percentile", "Valeur"])
        _style_table(self.percentile_table)
        self.percentile_table.setObjectName("CardAccentBleu")
        self.percentile_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.percentile_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.percentile_table.setMinimumHeight(34 * (len(PERCENTILES) + 1) + 4)
        colonne_stats.addWidget(self.percentile_table, stretch=1)

        boxplot_card, self.layout_boxplot = self._chart_card(
            "Résumé (P5 · P25 · médiane · P75 · P95)", accent="CardAccentBleu", hauteur=400)
        colonne_stats.addWidget(boxplot_card)

        # ===== Colonne 3 : histogrammes empilés, puis camemberts =====
        colonne_droite_widget = QWidget()
        colonne_droite_widget.setMinimumWidth(340)
        colonne_droite = QVBoxLayout(colonne_droite_widget)
        colonne_droite.setContentsMargins(0, 0, 0, 0)
        colonne_droite.setSpacing(12)
        corps.addWidget(colonne_droite_widget, stretch=1)

        graph_param_card, self.layout_graph_parametre = self._chart_card(
            f"Distribution du paramètre ({parametre_nom})", accent="CardAccentBleu")
        graph_ages_card, self.layout_graph_ages = self._chart_card(
            "Distribution des âges", accent="CardAccentBleu")
        camembert_tranches_card, self.layout_camembert_tranches = self._chart_card(
            "Répartition par tranche d'âge", accent="CardAccentBleu")
        camembert_sexe_card, self.layout_camembert_sexe = self._chart_card(
            "Répartition par sexe", accent="CardAccentBleu")
        temporel_card, self.layout_temporel = self._chart_card(
            "Évolution dans le temps", accent="CardAccentBleu")
        for w in (graph_param_card, graph_ages_card, camembert_tranches_card,
                  camembert_sexe_card, temporel_card):
            colonne_droite.addWidget(w)

        self.rafraichir()

    def _chart_card(self, titre: str, accent: str = "Card", hauteur: int = 210):
        """Carte contenant un titre fixe + un graphique remplacé à chaque rafraîchissement."""
        layout = QVBoxLayout()
        layout.setContentsMargins(16, 8, 16, 10)
        layout.setSpacing(6)
        label_titre = QLabel(titre)
        label_titre.setObjectName("Muted")
        label_titre.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        layout.addWidget(label_titre)
        card = _card(layout)
        card.setObjectName(accent)
        card.setFixedHeight(hauteur)
        return card, layout

    def _set_chart(self, layout: QVBoxLayout, chart_view) -> None:
        # Le premier élément du layout est toujours le titre : on ne retire que le reste.
        while layout.count() > 1:
            item = layout.takeAt(1)
            if item.widget():
                item.widget().deleteLater()
        layout.addWidget(chart_view)

    def _ouvrir_dialogue_tranches(self):
        dialogue = TranchesDialog(self.conn, self.parametre_id, self.parametre_nom, parent=self)
        if dialogue.exec():
            self._charger_tranches()
            self.rafraichir()

    def _ouvrir_dialogue_domaine(self):
        dialogue = DomaineMesureDialog(self.conn, self.parametre_id, self.parametre_nom, parent=self)
        if dialogue.exec():
            self.rafraichir()

    def _charger_tranches(self):
        self.filtre_tranche.clear()
        self.filtre_tranche.addItem("Toutes les tranches", None)
        rows = self.conn.execute(
            "SELECT id, libelle FROM qc_tranches_age WHERE parametre_id = ? ORDER BY age_min",
            (self.parametre_id,),
        ).fetchall()
        for tranche_id, libelle in rows:
            self.filtre_tranche.addItem(libelle, tranche_id)

    def _filtered_rows(self):
        conditions = ["e.parametre_id = ?", "e.statut != 'exclu'"]
        params = [self.parametre_id]

        tranche_id = self.filtre_tranche.currentData()
        if tranche_id is not None:
            conditions.append("e.tranche_age_id = ?")
            params.append(tranche_id)

        sexe = self.filtre_sexe.currentText()
        if sexe != "Tous":
            conditions.append("e.sexe = ?")
            params.append(sexe)

        where = " AND ".join(conditions)
        return self.conn.execute(
            f"""SELECT e.numero_demande, e.sexe, e.age_annees, e.valeur_affichee,
                       e.valeur_numerique, e.statut, t.libelle, e.date_prelevement
                FROM qc_echantillons e
                LEFT JOIN qc_tranches_age t ON t.id = e.tranche_age_id
                WHERE {where} ORDER BY e.date_prelevement""",
            params,
        ).fetchall()

    def _valeurs_par_sexe(self):
        """Toujours les deux groupes (Féminin/Masculin), indépendamment du filtre
        sexe actif — nécessaire puisque le test compare justement ces deux groupes.
        Respecte en revanche le filtre de tranche d'âge, comme le reste de la page."""
        conditions = ["parametre_id = ?", "statut != 'exclu'", "valeur_numerique IS NOT NULL"]
        params = [self.parametre_id]
        tranche_id = self.filtre_tranche.currentData()
        if tranche_id is not None:
            conditions.append("tranche_age_id = ?")
            params.append(tranche_id)
        where = " AND ".join(conditions)
        rows = self.conn.execute(
            f"SELECT sexe, valeur_numerique FROM qc_echantillons WHERE {where}", params,
        ).fetchall()
        feminin = [v for s, v in rows if s == "Féminin"]
        masculin = [v for s, v in rows if s == "Masculin"]
        return feminin, masculin

    def rafraichir(self):
        toutes_les_lignes = self._filtered_rows()

        n_sous_borne = sum(1 for r in toutes_les_lignes if r[5] == "sous_seuil")
        n_sur_borne = sum(1 for r in toutes_les_lignes if r[5] == "sur_seuil")
        self.label_sous_borne.setText(f"{n_sous_borne} résultat(s) sous la borne inférieure")
        self.label_sur_borne.setText(f"{n_sur_borne} résultat(s) au-dessus de la borne supérieure")

        if self.case_hors_bornes.isChecked():
            rows = [r for r in toutes_les_lignes if r[5] in ("sous_seuil", "sur_seuil")]
        else:
            rows = toutes_les_lignes

        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for i, (numero, sexe, age, affichee, valeur, statut, tranche_libelle, date_prelevement) in enumerate(rows):
            hors_bornes = statut in ("sous_seuil", "sur_seuil")
            couleur = _couleur_ligne(i, hors_bornes)

            item_numero = QTableWidgetItem(numero)
            item_sexe = QTableWidgetItem(sexe)
            item_age = _right_align(_ItemTriable(f"{age} ans", age))
            # date ISO (AAAA-MM-JJ) comme clé de tri : trie correctement en chaîne, sans conversion
            item_date = _ItemTriable(_formater_date_fr(date_prelevement), date_prelevement)
            item_resultat = _right_align(_ItemTriable(affichee, valeur))

            for item in (item_numero, item_sexe, item_age, item_date, item_resultat):
                item.setBackground(couleur)

            self.table.setItem(i, 0, item_numero)
            self.table.setItem(i, 1, item_sexe)
            self.table.setItem(i, 2, item_age)
            self.table.setItem(i, 3, item_date)
            self.table.setItem(i, 4, item_resultat)
        self.table.setSortingEnabled(True)

        stat_rows = [(v, s) for _, _, _, _, v, s, _, _ in toutes_les_lignes if v is not None]
        result = compute_stats(stat_rows)
        valeurs_toutes = [v for v, _ in stat_rows]
        valeurs_valides = [v for v, s in stat_rows if s == "valide"]
        self._afficher_stats(result, valeurs_toutes, valeurs_valides)

        stat_rows_graphiques = [(v, s) for _, _, _, _, v, s, _, _ in rows if v is not None]
        self._rafraichir_graphiques(rows, stat_rows_graphiques)

    def _afficher_stats(self, result, valeurs_toutes=None, valeurs_valides=None):
        if result is None:
            self.stats_table.setRowCount(1)
            self.stats_table.setItem(0, 0, QTableWidgetItem("Aucune donnée"))
            self.stats_table.setItem(0, 1, QTableWidgetItem(""))
            self.percentile_table.setRowCount(0)
            self.tests_table.setRowCount(0)
            self._set_chart(self.layout_boxplot, build_boxplot(None))
            return

        self.stats_table.setRowCount(7)
        champs = [
            ("Échantillons", result.n), ("Moyenne", result.moyenne), ("Médiane", result.mediane),
            ("Écart-type", result.ecart_type), ("CV (%)", result.cv),
            ("Min", result.minimum), ("Max", result.maximum),
        ]
        for row, (label, valeur) in enumerate(champs):
            couleur = _couleur_ligne(row)
            item_label = QTableWidgetItem(label)
            item_valeur = _right_align(QTableWidgetItem(str(valeur)))
            item_label.setBackground(couleur)
            item_valeur.setBackground(couleur)
            infobulle = INFOBULLES_STATS.get(label, "")
            item_label.setToolTip(infobulle)
            item_valeur.setToolTip(infobulle)
            self.stats_table.setItem(row, 0, item_label)
            self.stats_table.setItem(row, 1, item_valeur)

        self.percentile_table.setRowCount(len(PERCENTILES))
        for i, p in enumerate(PERCENTILES):
            couleur = _couleur_ligne(i)
            item_p = QTableWidgetItem(f"P{p}")
            item_v = _right_align(QTableWidgetItem(str(result.percentiles[p])))
            item_p.setBackground(couleur)
            item_v.setBackground(couleur)
            infobulle = _infobulle_percentile(p)
            item_p.setToolTip(infobulle)
            item_v.setToolTip(infobulle)
            self.percentile_table.setItem(i, 0, item_p)
            self.percentile_table.setItem(i, 1, item_v)

        self._afficher_tests_statistiques(result, valeurs_valides or [], valeurs_toutes or [])
        self._set_chart(self.layout_boxplot, build_boxplot(result, valeurs_toutes))

    def _afficher_tests_statistiques(self, result, valeurs_valides, valeurs_toutes):
        lignes = []

        normalite = test_normalite(valeurs_valides)
        if normalite is None:
            lignes.append(("Normalité (Shapiro-Wilk)", "Échantillon trop petit",
                            "Il faut au moins 3 résultats numériques valides pour ce test."))
        else:
            texte = "Normale" if normalite.normale else "Non normale"
            lignes.append((
                "Normalité (Shapiro-Wilk)", f"{texte} ({_formater_p(normalite.p_valeur)})",
                "Si p > 0,05, on ne peut pas rejeter l'hypothèse que la distribution suit une loi "
                "normale — dans ce cas, la moyenne et l'écart-type sont représentatifs. Sinon, "
                "préférez la médiane et les percentiles.",
            ))

        if result.percentiles.get(25) is not None and result.percentiles.get(75) is not None:
            aberrantes = detecter_aberrantes(valeurs_toutes, result.percentiles[25], result.percentiles[75])
            n_total = aberrantes.n_sous + aberrantes.n_sur
            lignes.append((
                "Valeurs aberrantes (IQR)", f"{n_total} détectée(s)",
                f"Méthode de Tukey : une valeur est aberrante si elle sort de "
                f"[{aberrantes.borne_basse} ; {aberrantes.borne_haute}] ({aberrantes.n_sous} en dessous, "
                f"{aberrantes.n_sur} au-dessus). Différent du statut « hors bornes », qui se base sur le "
                "domaine de mesure de la machine, pas sur la distribution observée.",
            ))
        else:
            lignes.append(("Valeurs aberrantes (IQR)", "—", ""))

        feminin, masculin = self._valeurs_par_sexe()
        comparaison = comparer_deux_groupes(feminin, masculin)
        if comparaison is None:
            lignes.append(("Comparaison F/M (Mann-Whitney)", "Un groupe est vide",
                            "Il faut au moins un résultat dans chaque sexe, pour la tranche d'âge sélectionnée."))
        else:
            texte = "Significative" if comparaison.significatif else "Non significative"
            lignes.append((
                "Comparaison F/M (Mann-Whitney)", f"{texte} ({_formater_p(comparaison.p_valeur)})",
                f"Compare Féminin (n={comparaison.n_a}) et Masculin (n={comparaison.n_b}) sur la tranche "
                "d'âge actuellement sélectionnée, indépendamment du filtre sexe. Si p < 0,05, la "
                "différence entre les deux groupes est jugée statistiquement significative.",
            ))

        self.tests_table.setRowCount(len(lignes))
        for i, (label, valeur, infobulle) in enumerate(lignes):
            item_label = QTableWidgetItem(label)
            item_valeur = _right_align(QTableWidgetItem(valeur))
            item_label.setToolTip(infobulle)
            item_valeur.setToolTip(infobulle)
            self.tests_table.setItem(i, 0, item_label)
            self.tests_table.setItem(i, 1, item_valeur)

    def _rafraichir_graphiques(self, rows, stat_rows):
        valeurs_parametre = [v for v, _ in stat_rows]
        self._set_chart(self.layout_graph_parametre, build_histogram(valeurs_parametre))

        ages = [age for _, _, age, *_ in rows]
        self._set_chart(self.layout_graph_ages, build_histogram(ages, couleur=COULEUR_SECONDAIRE))

        compte_tranches = {}
        for row in rows:
            libelle = row[6]
            if libelle:
                compte_tranches[libelle] = compte_tranches.get(libelle, 0) + 1
        self._set_chart(self.layout_camembert_tranches, build_pie(compte_tranches))

        compte_sexe = {}
        for row in rows:
            sexe = row[1]
            compte_sexe[sexe] = compte_sexe.get(sexe, 0) + 1
        self._set_chart(self.layout_camembert_sexe, build_pie(compte_sexe))

        paires_temporel = [(row[7], row[4]) for row in rows if row[4] is not None and row[7]]
        self._set_chart(self.layout_temporel, build_temporal(paires_temporel))
