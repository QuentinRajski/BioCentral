"""
Tableau de bord d'un paramètre.

Disposition (validée avec l'utilisateur — voir la conversation de conception) :
  - Bloc de gauche : tableau des échantillons en haut, puis statistiques
    descriptives (liste verticale) et tableau de percentiles côte à côte.
  - Bloc de droite : les deux histogrammes empilés, puis l'évolution dans le
    temps, puis les notes libres, puis les deux camemberts côte à côte.

Les camemberts (tranches d'âge, sexe) réagissent aux mêmes filtres que le
reste de la page — décision explicite : "tant pis si ça affiche 100%" plutôt
qu'une vue toujours globale indépendante du filtre.
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QStyledItemDelegate, QSizePolicy,
    QCheckBox, QPushButton, QScrollArea, QFrame, QTextEdit, QToolButton, QMenu,
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont

from core import export, intervalle_reference, theme, ui
from core.formatage import date_fr, fmt, fmt_dec
from core.plot import PlotWidget
from core.stats import compute_stats, PERCENTILES
from core.charts import build_histogram, build_pie, build_boxplot, build_temporal, COULEUR_SECONDAIRE
from core.tests_statistiques import test_normalite, detecter_aberrantes, comparer_deux_groupes
from .tranches_dialog import TranchesDialog
from .domaine_dialog import DomaineMesureDialog
from .intervalles_dialog import IntervallesReferenceDialog
from . import import_logic


# Aides communes désormais partagées avec les autres modules (core/ui.py).
_card = ui.carte
_style_table = ui.styliser_table
_couleur_ligne = ui.couleur_ligne
_ItemTriable = ui.ItemTriable  # tri sur clé séparée — version corrigée (plantage PySide6 6.11)


def _right_align(item: QTableWidgetItem) -> QTableWidgetItem:
    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return item


_formater_date_fr = date_fr


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


HAUTEUR_CAMEMBERT = 380  # même hauteur pour les deux camemberts, posés côte à côte
HAUTEUR_LIGNE_COMPACTE = 28  # tableaux clé/valeur (stats, tests, percentiles) : moins de perte d'espace


def _formater_p(p: float) -> str:
    return "p < 0,0001" if p < 0.0001 else f"p = {p}".replace(".", ",")


class DashboardWidget(QWidget):
    supprime = Signal()  # le paramètre a été supprimé : la coquille ferme ce tableau de bord

    def __init__(self, conn, parametre_id: int, parametre_nom: str):
        super().__init__()
        self.conn = conn
        self.parametre_id = parametre_id
        self.parametre_nom = parametre_nom

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 16)
        root.setSpacing(14)

        # --- En-tête + filtres ---
        header = QHBoxLayout()
        header.setSpacing(8)
        self.titre = QLabel()
        self.titre.setObjectName("TitrePage")
        header.addWidget(self.titre)
        self._maj_titre()
        header.addStretch()

        label_tranche = QLabel("Tranche d'âge")
        label_tranche.setObjectName("Muted")
        header.addWidget(label_tranche)
        self.filtre_tranche = QComboBox()
        header.addWidget(self.filtre_tranche)

        header.addSpacing(8)
        label_sexe = QLabel("Sexe")
        label_sexe.setObjectName("Muted")
        header.addWidget(label_sexe)
        self.filtre_sexe = QComboBox()
        self.filtre_sexe.addItems(["Tous", "Féminin", "Masculin"])
        header.addWidget(self.filtre_sexe)

        header.addSpacing(16)
        btn_parametres = QToolButton()
        btn_parametres.setObjectName("ToggleTheme")
        btn_parametres.setFixedSize(34, 34)
        btn_parametres.setCursor(Qt.PointingHandCursor)
        btn_parametres.setText("⚙")
        btn_parametres.setToolTip("Réglages de ce paramètre")
        btn_parametres.setPopupMode(QToolButton.InstantPopup)
        menu_parametres = QMenu(btn_parametres)
        menu_parametres.addAction("✎ Modifier les tranches d'âge…", self._ouvrir_dialogue_tranches)
        menu_parametres.addAction("✎ Modifier le domaine de mesure…", self._ouvrir_dialogue_domaine)
        menu_parametres.addAction("✎ Unité des résultats…", self._modifier_unite)
        menu_parametres.addAction("✎ Intervalles de référence à vérifier…", self._ouvrir_dialogue_intervalles)
        menu_parametres.addSeparator()
        menu_parametres.addAction("⬇ Rapport PDF (filtre en cours)…", self._exporter_pdf)
        menu_parametres.addAction("⬇ Échantillons filtrés (Excel)…", self._exporter_excel)
        menu_parametres.addSeparator()
        menu_parametres.addAction("🗑 Supprimer ce paramètre…", self._supprimer_parametre)
        btn_parametres.setMenu(menu_parametres)
        header.addWidget(btn_parametres)
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
        _style_table(self.stats_table, HAUTEUR_LIGNE_COMPACTE)
        self.stats_table.setObjectName("CardAccentBleu")
        self.stats_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.stats_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        ui.ajuster_hauteur_table(self.stats_table)
        colonne_stats.addWidget(self.stats_table, stretch=0)

        self.tests_table = QTableWidget(3, 2)
        self.tests_table.setHorizontalHeaderLabels(["Test statistique", "Résultat"])
        _style_table(self.tests_table, HAUTEUR_LIGNE_COMPACTE)
        self.tests_table.setObjectName("CardAccentBleu")
        self.tests_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tests_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        ui.ajuster_hauteur_table(self.tests_table)
        colonne_stats.addWidget(self.tests_table, stretch=0)

        self.percentile_table = QTableWidget(len(PERCENTILES), 2)
        self.percentile_table.setHorizontalHeaderLabels(["Percentile", "Valeur"])
        _style_table(self.percentile_table, HAUTEUR_LIGNE_COMPACTE)
        self.percentile_table.setObjectName("CardAccentBleu")
        self.percentile_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.percentile_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.percentile_table.setMinimumHeight(HAUTEUR_LIGNE_COMPACTE * len(PERCENTILES) + 44)
        colonne_stats.addWidget(self.percentile_table, stretch=1)

        colonne_stats.addWidget(self._creer_carte_intervalle())

        boxplot_card, self.layout_boxplot = self._chart_card(
            "Résumé (P5 · P25 · médiane · P75 · P95)", accent="CardAccentBleu", hauteur=300)
        colonne_stats.addWidget(boxplot_card)

        # ===== Colonne 3 : histogrammes empilés, puis camemberts =====
        colonne_droite_widget = QWidget()
        colonne_droite_widget.setMinimumWidth(340)
        colonne_droite = QVBoxLayout(colonne_droite_widget)
        colonne_droite.setContentsMargins(0, 0, 0, 0)
        colonne_droite.setSpacing(10)
        corps.addWidget(colonne_droite_widget, stretch=1)

        graph_param_card, self.layout_graph_parametre = self._chart_card(
            f"Distribution du paramètre ({parametre_nom})", accent="CardAccentBleu")
        graph_ages_card, self.layout_graph_ages = self._chart_card(
            "Distribution des âges", accent="CardAccentBleu")
        for w in (graph_param_card, graph_ages_card):
            colonne_droite.addWidget(w)

        camembert_tranches_card, self.layout_camembert_tranches = self._chart_card(
            "Répartition par tranche d'âge", accent="CardAccentVert", hauteur=HAUTEUR_CAMEMBERT)
        camembert_sexe_card, self.layout_camembert_sexe = self._chart_card(
            "Répartition par sexe", accent="CardAccentViolet", hauteur=HAUTEUR_CAMEMBERT)
        ligne_camemberts = QHBoxLayout()
        ligne_camemberts.setSpacing(12)
        ligne_camemberts.addWidget(camembert_tranches_card, stretch=1)
        ligne_camemberts.addWidget(camembert_sexe_card, stretch=1)
        colonne_droite.addLayout(ligne_camemberts)

        temporel_card, self.layout_temporel = self._chart_card(
            "Évolution dans le temps", accent="CardAccentBleu")
        colonne_droite.addWidget(temporel_card)

        colonne_droite.addWidget(self._creer_carte_notes())

        self.rafraichir()
        theme.ThemeManager.instance().changed.connect(self.rafraichir)

    def _creer_carte_notes(self) -> QWidget:
        """Notes libres propres à ce paramètre — enregistrées en base automatiquement
        après une courte pause de frappe (pas de bouton « Enregistrer » à retenir)."""
        layout = QVBoxLayout()
        layout.setContentsMargins(16, 10, 16, 12)
        layout.setSpacing(6)

        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText(
            "Ajoutez une remarque, une anomalie observée, un rappel…\nEnregistré automatiquement.")
        self.notes_edit.setFixedHeight(90)
        self.notes_edit.setPlainText(self._charger_notes())
        self.notes_edit.textChanged.connect(self._sur_notes_modifiees)
        layout.addWidget(self.notes_edit)

        self._minuteur_notes = QTimer(self)
        self._minuteur_notes.setSingleShot(True)
        self._minuteur_notes.timeout.connect(self._enregistrer_notes)

        card = _card(layout)
        card.setObjectName("CardAccentBleu")
        return card

    def _charger_notes(self) -> str:
        row = self.conn.execute(
            "SELECT notes FROM qc_parametres WHERE id = ?", (self.parametre_id,)
        ).fetchone()
        return row[0] if row and row[0] else ""

    def _sur_notes_modifiees(self):
        self._minuteur_notes.start(600)  # attend une pause de frappe avant d'écrire en base

    def _enregistrer_notes(self):
        self.conn.execute(
            "UPDATE qc_parametres SET notes = ? WHERE id = ?",
            (self.notes_edit.toPlainText(), self.parametre_id),
        )
        self.conn.commit()

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
        # v2 : masqué et détaché immédiatement (sinon l'ancien graphique restait
        # visible en surimpression jusqu'à sa destruction différée).
        ui.vider_layout(layout, a_partir_de=1)
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

        self._afficher_intervalle(stat_rows)
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
            ui.ajuster_hauteur_table(self.stats_table)
            return

        self.stats_table.setRowCount(7)
        ui.ajuster_hauteur_table(self.stats_table)
        champs = [
            ("Échantillons", result.n), ("Moyenne", result.moyenne), ("Médiane", result.mediane),
            ("Écart-type", result.ecart_type), ("CV (%)", result.cv),
            ("Min", result.minimum), ("Max", result.maximum),
        ]
        for row, (label, valeur) in enumerate(champs):
            couleur = _couleur_ligne(row)
            item_label = QTableWidgetItem(label)
            item_valeur = _right_align(QTableWidgetItem(fmt(valeur, 6)))
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
            item_v = _right_align(QTableWidgetItem(fmt(result.percentiles[p], 6)))
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
        ui.ajuster_hauteur_table(self.tests_table)
        self._lignes_tests = [(l, v) for l, v, _ in lignes]
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

    # ------------------------------------------------------------------
    # v2 : unité, intervalle de référence, exports, suppression
    # ------------------------------------------------------------------
    def _maj_titre(self):
        unite = import_logic.get_unite(self.conn, self.parametre_id)
        self.titre.setText(f"Paramètre : {self.parametre_nom}" + (f" ({unite})" if unite else ""))

    def _modifier_unite(self):
        from PySide6.QtWidgets import QInputDialog
        unite, ok = QInputDialog.getText(self, "Unité des résultats", f"Unité de « {self.parametre_nom} » :",
                                         text=import_logic.get_unite(self.conn, self.parametre_id))
        if ok:
            import_logic.definir_unite(self.conn, self.parametre_id, unite)
            self._maj_titre()

    def _creer_carte_intervalle(self) -> QWidget:
        carte, layout = ui.carte_titree("Intervalle de référence (CLSI EP28-A3c) — filtre en cours", "CardAccentVert")
        self.table_intervalle = ui.table_cle_valeur(("Indicateur", "Valeur"), HAUTEUR_LIGNE_COMPACTE, "Card")
        self.table_intervalle.setStyleSheet("QTableWidget { border: none; }")
        layout.addWidget(self.table_intervalle)
        self.badge_verification = ui.badge("", "neutre")
        self.badge_verification.setWordWrap(True)
        layout.addWidget(self.badge_verification)
        self.label_intervalle = ui.texte_discret()
        layout.addWidget(self.label_intervalle)
        lien = ui.bouton("Définir les intervalles à vérifier…", self._ouvrir_dialogue_intervalles)
        lien.setObjectName("LienDiscret")
        lien.setCursor(Qt.PointingHandCursor)
        layout.addWidget(lien, alignment=Qt.AlignLeft)
        self._intervalle = None
        self._verification = None
        return carte

    def _filtre_courant(self) -> tuple[str, str]:
        tranche = self.filtre_tranche.currentText() if self.filtre_tranche.currentData() is not None else ""
        sexe = self.filtre_sexe.currentText() if self.filtre_sexe.currentText() != "Tous" else ""
        return tranche, sexe

    @staticmethod
    def _texte_limite(valeur, ic, censure: bool, seuil) -> str:
        if valeur is None:
            return "—"
        if censure:
            return f"≤ {fmt(seuil)} (sous le seuil de mesure)"
        texte = fmt(valeur)
        if ic:
            texte += f"  IC 90 % [{fmt(ic[0])} ; {fmt(ic[1])}]"
        return texte

    def _afficher_intervalle(self, stat_rows):
        valeurs = [v for v, _ in stat_rows]
        self._intervalle = intervalle_reference.estimer(valeurs)
        r = self._intervalle
        domaine_min, domaine_max = import_logic.get_domaine_mesure(self.conn, self.parametre_id)
        a_sous = any(s == "sous_seuil" for _, s in stat_rows)
        a_sur = any(s == "sur_seuil" for _, s in stat_rows)
        seuil_bas = max((v for v, s in stat_rows if s == "sous_seuil"), default=domaine_min)
        seuil_haut = min((v for v, s in stat_rows if s == "sur_seuil"), default=domaine_max)
        censure_bas = a_sous and r.limite_basse is not None and r.limite_basse <= seuil_bas
        censure_haut = a_sur and r.limite_haute is not None and r.limite_haute >= seuil_haut
        lignes = [("Effectif", str(r.n), "Résultats non exclus du filtre en cours.")]
        if r.limite_basse is not None:
            lignes += [
                ("Limite basse (P2,5)", self._texte_limite(r.limite_basse, r.ic_basse, censure_bas, seuil_bas),
                 "Méthode non paramétrique des rangs : rang 0,025 × (n + 1)."),
                ("Limite haute (P97,5)", self._texte_limite(r.limite_haute, r.ic_haute, censure_haut, seuil_haut),
                 "Rang 0,975 × (n + 1)."),
                ("IC des limites", "rangs (loi binomiale)" if r.methode_ic == "rangs" else "bootstrap (2000 tirages)",
                 "Intervalle de confiance à 90 % de chaque limite, recommandé par le CLSI EP28-A3c."),
            ]
        ui.remplir_table_cle_valeur(self.table_intervalle, lignes)
        ui.ajuster_hauteur_table(self.table_intervalle)

        tranche, sexe = self._filtre_courant()
        ref = import_logic.get_intervalle_reference(self.conn, self.parametre_id, tranche, sexe)
        self._verification = None
        if ref is None:
            ui.definir_badge(self.badge_verification, "Aucun intervalle à vérifier pour ce filtre", "neutre")
        else:
            bas, haut, source, ref_tranche, ref_sexe = ref
            v = intervalle_reference.verifier(valeurs, bas, haut)
            self._verification = (ref, v)
            portee = f"{ref_tranche or 'toutes tranches'} · {ref_sexe or 'tous sexes'}"
            texte = (f"Intervalle {fmt(bas) if bas is not None else '—'} – {fmt(haut) if haut is not None else '—'}"
                     f"{' (' + source + ')' if source else ''} [{portee}] : {v.n_hors}/{v.n} hors intervalle "
                     f"({fmt_dec(v.pourcent_hors, 1)} % ; {v.n_sous} bas, {v.n_sur} haut)")
            if v.verdict is None:
                ui.definir_badge(self.badge_verification,
                                 texte + f" — effectif < {intervalle_reference.EFFECTIF_VERIFICATION}, vérification impossible",
                                 "neutre")
            else:
                ui.definir_badge(self.badge_verification,
                                 texte + (" — VÉRIFIÉ (≤ 10 %)" if v.verdict else " — NON vérifié (> 10 %)"),
                                 "ok" if v.verdict else "rejet")
        notes = list(r.avertissements)
        if censure_bas or censure_haut:
            notes.append("Les résultats rendus « <seuil » comptent au rang du seuil : une limite qui tombe sur ce "
                         "seuil est affichée « ≤ seuil ».")
        self.label_intervalle.setText("\n".join(notes))
        self.label_intervalle.setVisible(bool(notes))

    def _ouvrir_dialogue_intervalles(self):
        dialogue = IntervallesReferenceDialog(self.conn, self.parametre_id, self.parametre_nom, parent=self)
        if dialogue.exec():
            self.rafraichir()

    def _supprimer_parametre(self):
        n = self.conn.execute("SELECT COUNT(*) FROM qc_echantillons WHERE parametre_id = ?",
                              (self.parametre_id,)).fetchone()[0]
        if ui.confirmer(self, "Supprimer le paramètre",
                        f"Supprimer « {self.parametre_nom} », ses {n} échantillon(s), ses tranches d'âge, ses notes et "
                        "ses intervalles de référence ?\n\nCette action est définitive (une sauvegarde automatique de "
                        "la base est faite chaque jour).", "Supprimer", danger=True):
            import_logic.supprimer_parametre(self.conn, self.parametre_id)
            self.supprime.emit()

    def _nom_fichier(self, extension: str) -> str:
        tranche, sexe = self._filtre_courant()
        morceaux = [self.parametre_nom] + [m for m in (tranche, sexe) if m]
        return "_".join("".join(c if c.isalnum() or c == "-" else "_" for c in m) for m in morceaux) + extension

    def _exporter_excel(self):
        chemin = ui.demander_fichier_enregistrement(self, "Exporter les échantillons", self._nom_fichier(".xlsx"),
                                                    "Fichiers Excel (*.xlsx)")
        if not chemin:
            return
        libelles_statut = {"valide": "Valide", "sous_seuil": "Sous la borne", "sur_seuil": "Au-dessus de la borne"}
        lignes = [[numero, sexe, age, tranche or "", date_prelevement, affichee, valeur,
                   libelles_statut.get(statut, statut)]
                  for numero, sexe, age, affichee, valeur, statut, tranche, date_prelevement in self._filtered_rows()]
        try:
            export.exporter_excel(chemin, [(self.parametre_nom, [
                "N° demande", "Sexe", "Âge", "Tranche d'âge", "Date de prélèvement", "Résultat", "Valeur numérique",
                "Statut"], lignes)])
        except Exception as e:
            ui.erreur(self, "Échec de l'export", f"Impossible d'exporter : {e}")
            return
        ui.information(self, "Export terminé", f"{len(lignes)} échantillon(s) exporté(s) : {chemin.name}")

    def _histogramme_impression(self, valeurs: list[float], unite: str) -> PlotWidget:
        """Histogramme redessiné pour le rapport PDF (toujours sur fond clair)."""
        plot = PlotWidget(f"{self.parametre_nom}" + (f" ({unite})" if unite else ""), "Effectif")
        valeurs = sorted(valeurs)
        bas, haut = valeurs[0], valeurs[-1]
        if haut == bas:
            haut = bas + 1
        nb = max(6, min(25, int(len(valeurs) ** 0.5) + 1))
        largeur = (haut - bas) / nb
        comptes = [0] * nb
        for v in valeurs:
            comptes[min(int((v - bas) / largeur), nb - 1)] += 1
        plot.ajouter_barres([bas + i * largeur for i in range(nb)], [bas + (i + 1) * largeur for i in range(nb)],
                            comptes)
        if self._intervalle is not None and self._intervalle.limite_basse is not None:
            plot.ajouter_repere_v(self._intervalle.limite_basse, "statut_ok", 1.6)
            plot.ajouter_repere_v(self._intervalle.limite_haute, "statut_ok", 1.6)
        return plot

    def _exporter_pdf(self):
        lignes = self._filtered_rows()
        stat_rows = [(r[4], r[5]) for r in lignes if r[4] is not None]
        result = compute_stats(stat_rows)
        if result is None:
            ui.alerte(self, "Rien à exporter", "Aucun échantillon pour ce filtre.")
            return
        chemin = ui.demander_fichier_enregistrement(self, "Rapport du paramètre", self._nom_fichier(".pdf"),
                                                    "Documents PDF (*.pdf)")
        if not chemin:
            return
        tranche, sexe = self._filtre_courant()
        unite = import_logic.get_unite(self.conn, self.parametre_id)
        domaine_min, domaine_max = import_logic.get_domaine_mesure(self.conn, self.parametre_id)
        corps = [export.table_html(["Élément", "Valeur"], [
            ["Tranche d'âge", tranche or "Toutes"], ["Sexe", sexe or "Tous"], ["Unité", unite or "—"],
            ["Domaine de mesure", f"{fmt(domaine_min)} – {fmt(domaine_max)}"],
            ["Prélèvements", f"du {date_fr(min(r[7] for r in lignes))} au {date_fr(max(r[7] for r in lignes))}"],
        ])]
        corps.append("<h2>Statistiques descriptives</h2>")
        corps.append(export.table_html(["Statistique", "Valeur"], [
            ["Échantillons", result.n], ["Moyenne", fmt(result.moyenne)], ["Médiane", fmt(result.mediane)],
            ["Écart-type", fmt(result.ecart_type)], ["CV (%)", fmt(result.cv)], ["Min", fmt(result.minimum)],
            ["Max", fmt(result.maximum)]], {1}))
        corps.append("<p class='note'>Moyenne et écart-type : résultats numériques uniquement ; médiane, percentiles "
                     "et effectif incluent les résultats hors domaine de mesure au rang de leur seuil.</p>")
        corps.append("<h2>Percentiles</h2>")
        corps.append(export.table_html(["Percentile", "Valeur"],
                                       [[f"P{p}", fmt(result.percentiles[p])] for p in PERCENTILES], {1}))
        if getattr(self, "_lignes_tests", None):
            corps.append("<h2>Tests statistiques</h2>"
                         + export.table_html(["Test", "Résultat"], [list(l) for l in self._lignes_tests]))
        corps.append("<h2>Intervalle de référence (CLSI EP28-A3c)</h2>")
        corps.append(export.table_html(["Indicateur", "Valeur"], [
            [self.table_intervalle.item(i, 0).text(), self.table_intervalle.item(i, 1).text()]
            for i in range(self.table_intervalle.rowCount())]))
        if self._verification is not None:
            verdict = self._verification[1].verdict
            classe = "ok" if verdict else ("rejet" if verdict is False else "")
            corps.append(f"<p class='{classe}'>{export.echapper(self.badge_verification.text())}</p>")
        if self.label_intervalle.text().strip():
            corps.append(f"<p class='note'>{export.echapper(self.label_intervalle.text())}</p>")
        corps.append("<h2>Distribution</h2>" + export.image_html("histo.png", 620))
        if self.notes_edit.toPlainText().strip():
            corps.append("<h2>Notes</h2><p>" + export.echapper(self.notes_edit.toPlainText()).replace("\n", "<br>") + "</p>")
        try:
            plot = self._histogramme_impression([v for v, _ in stat_rows], unite)
            export.exporter_pdf(chemin, f"Étude de population — {self.parametre_nom}", "".join(corps),
                                {"histo.png": plot.image(900, 380)})
        except Exception as e:
            ui.erreur(self, "Échec de l'export", f"Impossible de créer le PDF : {e}")
            return
        ui.information(self, "Rapport créé", f"Rapport enregistré : {chemin.name}")
