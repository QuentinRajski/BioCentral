"""
Vue d'ensemble : liste tous les paramètres importés avec leurs principaux
indicateurs (aucun filtre appliqué — résumé global). Affichée par défaut à
l'entrée du module, avant la sélection d'un paramètre précis.

Chaque paramètre peut être déplié (comme une matrice PowerBI) pour voir le
même jeu d'indicateurs décomposé par tranche d'âge. Colonnes triables en
cliquant leur en-tête, et export Excel de l'ensemble.
"""
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem,
    QStyledItemDelegate, QAbstractItemView, QHeaderView, QFileDialog, QMessageBox,
)
from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QColor

from core import theme
from core.stats import compute_stats

FRACTION_ROLE = Qt.UserRole + 1
PARAMETRE_ID_ROLE = Qt.UserRole + 2
VALEUR_BRUTE_ROLE = Qt.UserRole + 3  # valeur numérique d'origine, pour l'export Excel

COLONNES = ["Paramètre", "Échantillons", "Hommes", "Femmes", "Moyenne", "Médiane", "Écart-type",
            "CV (%)", "Min", "Max", "Hors bornes", "Sous la borne inf.", "Au-dessus borne sup.",
            "Dernier import"]
COLONNES_BARRE = {10, 11, 12}  # indices des colonnes avec barre de données (sur le nombre d'échantillons)


class _DelegueBarreDonnees(QStyledItemDelegate):
    """Peint la couleur de fond de la ligne, puis une barre de proportion façon
    mise en forme conditionnelle Excel, sous le texte."""
    def paint(self, painter, option, index):
        couleur_fond = index.data(Qt.BackgroundRole)
        if couleur_fond is not None:
            painter.save()
            painter.fillRect(option.rect, couleur_fond)
            painter.restore()
        fraction = index.data(FRACTION_ROLE)
        if fraction:
            painter.save()
            largeur_barre = option.rect.width() * min(max(fraction, 0), 1)
            rect_barre = QRectF(option.rect.x(), option.rect.y(), largeur_barre, option.rect.height())
            painter.fillRect(rect_barre, QColor(55, 138, 221, 90))
            painter.restore()
        super().paint(painter, option, index)


class _ItemArbreTriable(QTreeWidgetItem):
    """Trie numériquement les colonnes qui contiennent des nombres (y compris le
    format 'X (sur N)'), et alphabétiquement sinon — au lieu du tri texte brut
    par défaut de QTreeWidgetItem, qui classerait "10" avant "2"."""
    def __lt__(self, other):
        arbre = self.treeWidget()
        col = arbre.sortColumn() if arbre else 0
        a, b = self.text(col), other.text(col)

        def valeur(texte: str):
            texte = texte.split(" (sur")[0].strip()
            try:
                return float(texte.replace(",", "."))
            except ValueError:
                return None

        va, vb = valeur(a), valeur(b)
        if va is not None and vb is not None:
            return va < vb
        return a < b


class VueEnsemble(QWidget):
    parametre_choisi = Signal(int, str)  # parametre_id, nom

    def __init__(self, conn):
        super().__init__()
        self.conn = conn

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        entete = QHBoxLayout()
        titre = QLabel("Vue d'ensemble")
        titre.setObjectName("TitrePage")
        entete.addWidget(titre)
        entete.addStretch()
        btn_exporter = QPushButton("⬇ Exporter en Excel")
        btn_exporter.clicked.connect(self._exporter)
        entete.addWidget(btn_exporter)
        layout.addLayout(entete)

        sous_titre = QLabel(
            "Tous les paramètres importés, indicateurs globaux (aucun filtre). "
            "Dépliez un paramètre (+) pour voir le détail par tranche d'âge. "
            "Cliquez un en-tête de colonne pour trier. Double-cliquez une ligne pour "
            "ouvrir le tableau de bord correspondant."
        )
        sous_titre.setObjectName("Muted")
        sous_titre.setWordWrap(True)
        layout.addWidget(sous_titre)

        self.arbre = QTreeWidget()
        self.arbre.setColumnCount(len(COLONNES))
        self.arbre.setHeaderLabels(COLONNES)
        self.arbre.setObjectName("CardAccentBleu")
        self.arbre.setAttribute(Qt.WA_StyledBackground, True)
        self.arbre.setRootIsDecorated(True)
        self.arbre.setUniformRowHeights(True)
        self.arbre.setAlternatingRowColors(False)
        self.arbre.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.arbre.setSortingEnabled(True)
        self._appliquer_style_arbre()
        self.arbre.setItemDelegate(_DelegueBarreDonnees(self.arbre))
        self.arbre.itemDoubleClicked.connect(self._sur_double_clic)
        header = self.arbre.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        self.arbre.setColumnWidth(0, 160)
        for col in range(1, len(COLONNES)):
            header.setSectionResizeMode(col, QHeaderView.Stretch)
        layout.addWidget(self.arbre)

        self.rafraichir()
        theme.ThemeManager.instance().changed.connect(self._sur_changement_theme)

    def _appliquer_style_arbre(self) -> None:
        pal = theme.palette()
        self.arbre.setStyleSheet(
            f"QTreeWidget {{ border: 1px solid {pal['card_border']}; border-top: 3px solid #378ADD; "
            f"border-radius: 12px; background-color: {pal['card_bg']}; }}"
            f"QTreeWidget::item {{ border-right: 1px solid {pal['card_border']}; padding: 6px 4px; }}"
            f"QHeaderView::section {{ background-color: {pal['card_bg']}; border: none; "
            f"border-bottom: 1px solid {pal['btn_border']}; border-right: 1px solid {pal['card_border']}; "
            f"padding: 8px 4px; font-weight: 600; font-size: 12px; color: {pal['header_text']}; }}"
        )

    def _sur_changement_theme(self):
        self._appliquer_style_arbre()
        self.rafraichir()

    def _sur_double_clic(self, item: QTreeWidgetItem, colonne: int):
        parametre_id = item.data(0, PARAMETRE_ID_ROLE)
        if parametre_id is not None:
            # Une ligne de tranche d'âge affiche le libellé de la tranche : le nom du
            # paramètre est porté par sa ligne parente (la v1 ouvrait un tableau de
            # bord intitulé « Paramètre : 0 à 2 ans »).
            parent = item.parent()
            self.parametre_choisi.emit(parametre_id, parent.text(0) if parent is not None else item.text(0))

    def _stats_pour(self, parametre_id: int, tranche_age_id: int | None):
        conditions = ["parametre_id = ?", "statut != 'exclu'"]
        params = [parametre_id]
        if tranche_age_id is not None:
            conditions.append("tranche_age_id = ?")
            params.append(tranche_age_id)
        where = " AND ".join(conditions)
        rows = self.conn.execute(
            f"SELECT valeur_numerique, statut, sexe FROM qc_echantillons WHERE {where}", params,
        ).fetchall()
        result = compute_stats([(v, s) for v, s, _ in rows])
        n_hommes = sum(1 for _, _, sexe in rows if sexe == "Masculin")
        n_femmes = sum(1 for _, _, sexe in rows if sexe == "Féminin")
        n_sous = sum(1 for _, s, _ in rows if s == "sous_seuil")
        n_sur = sum(1 for _, s, _ in rows if s == "sur_seuil")
        return result, n_hommes, n_femmes, n_sous, n_sur

    def _valeurs_ligne(self, libelle: str, result, n_hommes, n_femmes, n_sous, n_sur,
                        dernier_import: str) -> list:
        n_hors_bornes = n_sous + n_sur
        if result is None:
            return [libelle] + ["—"] * (len(COLONNES) - 2) + [dernier_import]
        return [libelle, result.n, n_hommes, n_femmes, result.moyenne, result.mediane,
                result.ecart_type, result.cv, result.minimum, result.maximum,
                n_hors_bornes, n_sous, n_sur, dernier_import]

    def _remplir_ligne(self, item: QTreeWidgetItem, valeurs: list, n_total, couleur: QColor):
        for col, v in enumerate(valeurs):
            if isinstance(v, (int, float)):
                item.setData(col, VALEUR_BRUTE_ROLE, v)
            if col in COLONNES_BARRE and n_total:
                item.setText(col, f"{v} (sur {n_total})")
                item.setData(col, FRACTION_ROLE, v / n_total)
            else:
                item.setText(col, str(v))
            item.setTextAlignment(col, Qt.AlignCenter)
            item.setBackground(col, couleur)

    def rafraichir(self):
        self.arbre.setSortingEnabled(False)
        self.arbre.clear()
        parametres = self.conn.execute(
            "SELECT id, nom, date_import FROM qc_parametres ORDER BY nom"
        ).fetchall()
        pal = theme.palette()
        couleur_paire = QColor(pal["table_row_pair"])
        couleur_impaire = QColor(pal["table_row_impair"])

        for i, (parametre_id, nom, date_import) in enumerate(parametres):
            couleur = couleur_impaire if i % 2 else couleur_paire
            result, n_hommes, n_femmes, n_sous, n_sur = self._stats_pour(parametre_id, None)
            date_texte = str(date_import).split(" ")[0] if date_import else "—"
            # AAAA-MM-JJ -> JJ/MM/AAAA
            if date_texte != "—" and "-" in date_texte:
                annee, mois, jour = date_texte.split("-")
                date_texte = f"{jour}/{mois}/{annee}"

            item_parametre = _ItemArbreTriable()
            item_parametre.setData(0, PARAMETRE_ID_ROLE, parametre_id)
            valeurs = self._valeurs_ligne(nom, result, n_hommes, n_femmes, n_sous, n_sur, date_texte)
            self._remplir_ligne(item_parametre, valeurs, result.n if result else None, couleur)
            self.arbre.addTopLevelItem(item_parametre)

            tranches = self.conn.execute(
                "SELECT id, libelle FROM qc_tranches_age WHERE parametre_id = ? ORDER BY age_min",
                (parametre_id,),
            ).fetchall()
            for tranche_id, libelle in tranches:
                r, h, f, s, sup = self._stats_pour(parametre_id, tranche_id)
                item_tranche = _ItemArbreTriable()
                item_tranche.setData(0, PARAMETRE_ID_ROLE, parametre_id)
                valeurs_t = self._valeurs_ligne(libelle, r, h, f, s, sup, "—")
                self._remplir_ligne(item_tranche, valeurs_t, r.n if r else None, QColor(pal["bg"]))
                item_parametre.addChild(item_tranche)

        self.arbre.setSortingEnabled(True)

    def _exporter(self):
        chemin, _ = QFileDialog.getSaveFileName(
            self, "Exporter la vue d'ensemble", "vue_ensemble.xlsx", "Fichiers Excel (*.xlsx)"
        )
        if not chemin:
            return
        try:
            import openpyxl
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Vue d'ensemble"
            entetes = ["Paramètre", "Tranche d'âge"] + COLONNES[1:]
            ws.append(entetes)
            for i in range(self.arbre.topLevelItemCount()):
                item = self.arbre.topLevelItem(i)
                ws.append([item.text(0), "(tous)"] + [self._valeur_export(item, c) for c in range(1, len(COLONNES))])
                for j in range(item.childCount()):
                    enfant = item.child(j)
                    ws.append([item.text(0), enfant.text(0)] +
                              [self._valeur_export(enfant, c) for c in range(1, len(COLONNES))])
            wb.save(chemin)
        except Exception as e:
            QMessageBox.critical(self, "Échec de l'export", f"Impossible d'exporter : {e}")
            return
        QMessageBox.information(self, "Export terminé", f"Vue d'ensemble exportée : {Path(chemin).name}")

    @staticmethod
    def _valeur_export(item: QTreeWidgetItem, col: int):
        """Nombre brut si la cellule en porte un (exploitable dans Excel), sinon le texte affiché."""
        brute = item.data(col, VALEUR_BRUTE_ROLE)
        return brute if brute is not None else item.text(col)
