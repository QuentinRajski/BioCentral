"""
Petits composants d'interface partagés par tous les modules : cartes, tableaux
stylés, pastilles de statut, boîtes de dialogue en français, tableau de saisie
acceptant le collage depuis Excel.

Tout ce qui était dupliqué d'un écran à l'autre (carte, style de tableau,
délégué de couleur de fond...) vit ici, pour que les modules gardent le même
aspect sans recopier ces détails.
"""
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QFrame, QHeaderView, QLabel, QLayout, QMessageBox,
    QPushButton, QScrollArea, QStyledItemDelegate, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from core import theme
from core.formatage import parse_nombre


# ------------------------------------------------------------------
# Cartes et textes
# ------------------------------------------------------------------
def carte(layout: QLayout | None = None, accent: str = "Card") -> QWidget:
    """Bloc à fond blanc et coins arrondis. accent : "Card", "CardAccentBleu",
    "CardAccentVert", "CardAccentViolet" ou "CardAccentRose" (liseré coloré en haut)."""
    w = QWidget()
    w.setObjectName(accent)
    w.setAttribute(Qt.WA_StyledBackground, True)
    if layout is not None:
        w.setLayout(layout)
    return w


def carte_titree(titre: str, accent: str = "CardAccentBleu", marges=(16, 10, 16, 12)) -> tuple[QWidget, QVBoxLayout]:
    """Carte dont la première ligne est un petit titre gris. Retourne (carte, layout)."""
    layout = QVBoxLayout()
    layout.setContentsMargins(*marges)
    layout.setSpacing(6)
    if titre:
        layout.addWidget(texte_discret(titre, retour_ligne=False))
    return carte(layout, accent), layout


def titre_page(texte: str) -> QLabel:
    label = QLabel(texte)
    label.setObjectName("TitrePage")
    return label


def sous_titre(texte: str) -> QLabel:
    label = QLabel(texte)
    label.setObjectName("SousTitre")
    return label


def texte_discret(texte: str = "", retour_ligne: bool = True) -> QLabel:
    label = QLabel(texte)
    label.setObjectName("Muted")
    label.setWordWrap(retour_ligne)
    return label


def avertissement(texte: str = "") -> QLabel:
    label = QLabel(texte)
    label.setObjectName("Avertissement")
    label.setWordWrap(True)
    return label


BADGES = {"ok": "BadgeOk", "alerte": "BadgeAlerte", "rejet": "BadgeRejet", "neutre": "BadgeNeutre"}


def badge(texte: str = "", statut: str = "neutre") -> QLabel:
    """Pastille colorée : statut "ok" (vert), "alerte" (orange), "rejet" (rouge), "neutre" (gris)."""
    label = QLabel()
    label.setAlignment(Qt.AlignCenter)
    definir_badge(label, texte, statut)
    return label


def definir_badge(label: QLabel, texte: str, statut: str) -> None:
    label.setText(texte)
    label.setObjectName(BADGES.get(statut, "BadgeNeutre"))
    # Changer d'objectName ne suffit pas : il faut redemander au style de s'appliquer.
    label.style().unpolish(label)
    label.style().polish(label)


def bouton_rond(texte: str, infobulle: str = "", au_clic=None) -> QPushButton:
    """Petit bouton rond à icône (même langage visuel que le bouton de thème)."""
    bouton = QPushButton(texte)
    bouton.setObjectName("ToggleTheme")
    bouton.setFixedSize(34, 34)
    bouton.setCursor(Qt.PointingHandCursor)
    bouton.setToolTip(infobulle)
    if au_clic is not None:
        bouton.clicked.connect(au_clic)
    return bouton


def bouton(texte: str, au_clic=None, principal: bool = False, danger: bool = False, infobulle: str = "") -> QPushButton:
    b = QPushButton(texte)
    if principal:
        b.setObjectName("PrimaryButton")
    elif danger:
        b.setObjectName("DangerButton")
    if infobulle:
        b.setToolTip(infobulle)
    if au_clic is not None:
        b.clicked.connect(au_clic)
    return b


def zone_defilante(contenu: QWidget) -> QScrollArea:
    """Enveloppe `contenu` dans une zone de défilement sans cadre : sur petit écran,
    une barre de défilement apparaît plutôt que d'écraser le contenu."""
    zone = QScrollArea()
    zone.setWidgetResizable(True)
    zone.setFrameShape(QFrame.NoFrame)
    zone.setWidget(contenu)
    return zone


def vider_layout(layout: QLayout, a_partir_de: int = 0) -> None:
    """Retire et détruit les éléments d'un layout à partir de l'index donné."""
    while layout.count() > a_partir_de:
        element = layout.takeAt(a_partir_de)
        if element.widget():
            # Masqué et détaché tout de suite : sinon l'ancien widget reste visible
            # (en surimpression) jusqu'à sa destruction différée.
            element.widget().hide()
            element.widget().setParent(None)
            element.widget().deleteLater()
        elif element.layout():
            vider_layout(element.layout())


# ------------------------------------------------------------------
# Tableaux
# ------------------------------------------------------------------
class DelegueCouleurFond(QStyledItemDelegate):
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


def styliser_table(table: QTableWidget, hauteur_ligne: int = 34, accent: str = "Card") -> None:
    """Polish commun à tous les tableaux : évite le look « tableur » par défaut de Qt.
    L'alternance de couleur est gérée ligne par ligne (voir couleur_ligne), pour
    pouvoir la combiner avec un surlignage ponctuel sans conflit de priorité."""
    table.verticalHeader().setVisible(False)
    table.setShowGrid(False)
    table.setAlternatingRowColors(False)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.horizontalHeader().setHighlightSections(False)
    table.verticalHeader().setDefaultSectionSize(hauteur_ligne)
    table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
    # En-tête un peu plus haut que les lignes : son padding QSS (9 px) rognait le texte.
    table.horizontalHeader().setFixedHeight(max(hauteur_ligne + 6, 34))
    table.setObjectName(accent)
    table.setItemDelegate(DelegueCouleurFond(table))


def couleur_ligne(index: int, surlignee: bool = False, avertissement: bool = False) -> QColor:
    pal = theme.palette()
    if surlignee:
        return QColor(pal["table_highlight"])
    if avertissement:
        return QColor(pal["table_warning"])
    return QColor(pal["table_row_impair"]) if index % 2 else QColor(pal["table_row_pair"])


class ItemTriable(QTableWidgetItem):
    """QTableWidgetItem dont le tri se base sur une clé séparée du texte affiché —
    évite le piège de setData(Qt.EditRole, ...) qui écraserait le texte
    personnalisé (« 50 ans », « <0.3 ») avec la valeur numérique brute."""
    def __init__(self, texte: str, cle_tri=None):
        super().__init__(texte)
        self._cle_tri = cle_tri

    def __lt__(self, other):
        # Ne JAMAIS appeler super().__lt__ ici : avec PySide6 6.11, l'opérateur C++
        # virtuel renvoie vers cette même méthode Python -> récursion infinie et
        # plantage (violation d'accès). On compare donc nous-mêmes les textes.
        cle_autre = getattr(other, "_cle_tri", None)
        if self._cle_tri is not None and cle_autre is not None:
            try:
                return self._cle_tri < cle_autre
            except TypeError:
                pass
        return self.text().casefold() < other.text().casefold()


def cellule(texte, cle_tri=None, droite: bool = False, centre: bool = False, infobulle: str = "",
            fond: QColor | None = None, couleur: QColor | None = None, donnee=None) -> QTableWidgetItem:
    """Fabrique une cellule de tableau en une ligne (texte, tri, alignement, info-bulle, couleurs)."""
    item = ItemTriable(str(texte), cle_tri)
    if droite:
        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    elif centre:
        item.setTextAlignment(Qt.AlignCenter)
    if infobulle:
        item.setToolTip(infobulle)
    if fond is not None:
        item.setBackground(fond)
    if couleur is not None:
        item.setForeground(couleur)
    if donnee is not None:
        item.setData(Qt.UserRole, donnee)
    return item


def remplir_table_cle_valeur(table: QTableWidget, lignes: list[tuple]) -> None:
    """Remplit un tableau à deux colonnes à partir de (libellé, valeur[, info-bulle])."""
    table.setRowCount(len(lignes))
    for i, ligne in enumerate(lignes):
        libelle, valeur = ligne[0], ligne[1]
        infobulle = ligne[2] if len(ligne) > 2 else ""
        fond = couleur_ligne(i)
        table.setItem(i, 0, cellule(libelle, infobulle=infobulle, fond=fond))
        table.setItem(i, 1, cellule(valeur, droite=True, infobulle=infobulle, fond=fond))


def table_cle_valeur(entetes=("Indicateur", "Valeur"), hauteur_ligne: int = 28,
                     accent: str = "CardAccentBleu") -> QTableWidget:
    table = QTableWidget(0, 2)
    table.setHorizontalHeaderLabels(list(entetes))
    styliser_table(table, hauteur_ligne, accent)
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
    table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
    table.setSelectionMode(QAbstractItemView.NoSelection)
    table.setFocusPolicy(Qt.NoFocus)
    return table


def ajuster_hauteur_table(table: QTableWidget, lignes_max: int | None = None) -> None:
    """Fixe la hauteur d'un tableau à son contenu (pas de barre de défilement interne)."""
    lignes = table.rowCount() if lignes_max is None else min(table.rowCount(), lignes_max)
    hauteur = table.horizontalHeader().height() + lignes * table.verticalHeader().defaultSectionSize() + 6
    table.setFixedHeight(hauteur)


# ------------------------------------------------------------------
# Boîtes de dialogue (libellés en français, un seul point de passage)
# ------------------------------------------------------------------
def confirmer(parent, titre: str, message: str, libelle_oui: str = "Continuer", danger: bool = False) -> bool:
    boite = QMessageBox(parent)
    boite.setWindowTitle(titre)
    boite.setText(message)
    boite.setIcon(QMessageBox.Warning if danger else QMessageBox.Question)
    oui = boite.addButton(libelle_oui, QMessageBox.AcceptRole)
    non = boite.addButton("Annuler", QMessageBox.RejectRole)
    boite.setDefaultButton(non)
    boite.exec()
    return boite.clickedButton() is oui


def information(parent, titre: str, message: str) -> None:
    QMessageBox.information(parent, titre, message)


def alerte(parent, titre: str, message: str) -> None:
    QMessageBox.warning(parent, titre, message)


def erreur(parent, titre: str, message: str) -> None:
    QMessageBox.critical(parent, titre, message)


def demander_fichier_enregistrement(parent, titre: str, nom_defaut: str, filtre: str) -> Path | None:
    chemin, _ = QFileDialog.getSaveFileName(parent, titre, nom_defaut, filtre)
    return Path(chemin) if chemin else None


def demander_fichier_ouverture(parent, titre: str, filtre: str) -> Path | None:
    chemin, _ = QFileDialog.getOpenFileName(parent, titre, "", filtre)
    return Path(chemin) if chemin else None


# ------------------------------------------------------------------
# Tableau de saisie (collage depuis Excel)
# ------------------------------------------------------------------
def decouper_presse_papiers(texte: str) -> list[list[str]]:
    """Découpe un texte collé (Excel, CSV) en lignes et colonnes. Séparateur de
    colonnes : tabulation (copie depuis Excel), sinon point-virgule ; la virgule
    n'est jamais un séparateur, c'est la décimale des nombres français."""
    lignes = [l for l in texte.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    while lignes and not lignes[-1].strip():
        lignes.pop()
    separateur = "\t" if any("\t" in l for l in lignes) else ";"
    return [[c.strip() for c in l.split(separateur)] for l in lignes]


class TableSaisie(QTableWidget):
    """
    Grille de saisie libre : on tape ou on colle (Ctrl+V) des colonnes copiées
    depuis Excel. Une ligne vide reste toujours disponible en bas. Les colonnes
    déclarées numériques signalent en rouge une cellule qui n'est pas un nombre.
    """
    modifie = Signal()

    def __init__(self, colonnes: list[str], numeriques: list[int] | None = None, lignes_initiales: int = 12):
        super().__init__(lignes_initiales, len(colonnes))
        self._numeriques = set(numeriques if numeriques is not None else range(len(colonnes)))
        self._lignes_min = lignes_initiales
        self.setHorizontalHeaderLabels(colonnes)
        self.verticalHeader().setDefaultSectionSize(28)
        self.verticalHeader().setFixedWidth(38)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.horizontalHeader().setHighlightSections(False)
        self.setShowGrid(True)
        self.setObjectName("Card")
        self.setItemDelegate(DelegueCouleurFond(self))
        self.itemChanged.connect(self._sur_modification)

    # --- lecture / écriture ---
    def definir_colonnes(self, colonnes: list[str]) -> None:
        self.setHorizontalHeaderLabels(colonnes)

    def lignes(self) -> list[list[str]]:
        """Toutes les lignes non entièrement vides, sous forme de textes."""
        resultat = []
        for r in range(self.rowCount()):
            ligne = [(self.item(r, c).text().strip() if self.item(r, c) else "") for c in range(self.columnCount())]
            if any(ligne):
                resultat.append(ligne)
        return resultat

    def definir_lignes(self, lignes: list[list]) -> None:
        self.blockSignals(True)
        self.clearContents()
        self.setRowCount(max(self._lignes_min, len(lignes) + 1))
        for r, ligne in enumerate(lignes):
            for c, valeur in enumerate(ligne[: self.columnCount()]):
                if valeur is not None and str(valeur) != "":
                    self.setItem(r, c, QTableWidgetItem(str(valeur)))
        self.blockSignals(False)
        self._valider_tout()
        self.modifie.emit()

    def vider(self) -> None:
        self.definir_lignes([])

    # --- interaction ---
    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Paste):
            self._coller()
        elif event.matches(QKeySequence.Copy):
            self._copier()
        elif event.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.state() != QAbstractItemView.EditingState:
            self.blockSignals(True)
            for item in self.selectedItems():
                item.setText("")
            self.blockSignals(False)
            self._valider_tout()
            self.modifie.emit()
        else:
            super().keyPressEvent(event)

    def _copier(self) -> None:
        plages = self.selectedRanges()
        if not plages:
            return
        p = plages[0]
        lignes = []
        for r in range(p.topRow(), p.bottomRow() + 1):
            lignes.append("\t".join(
                self.item(r, c).text() if self.item(r, c) else ""
                for c in range(p.leftColumn(), p.rightColumn() + 1)))
        QGuiApplication.clipboard().setText("\n".join(lignes))

    def _coller(self) -> None:
        self.coller_texte(QGuiApplication.clipboard().text())

    def coller_texte(self, texte: str) -> None:
        """Colle un bloc de texte à partir de la cellule courante (ou de la première)."""
        blocs = decouper_presse_papiers(texte)
        if not blocs:
            return
        ligne0 = max(self.currentRow(), 0)
        colonne0 = max(self.currentColumn(), 0)
        self.blockSignals(True)
        if ligne0 + len(blocs) + 1 > self.rowCount():
            self.setRowCount(ligne0 + len(blocs) + 1)
        for dr, ligne in enumerate(blocs):
            for dc, valeur in enumerate(ligne):
                c = colonne0 + dc
                if c >= self.columnCount():
                    break
                self.setItem(ligne0 + dr, c, QTableWidgetItem(valeur))
        self.blockSignals(False)
        self._valider_tout()
        self.modifie.emit()

    def _sur_modification(self, item: QTableWidgetItem) -> None:
        self._valider(item)
        if item.row() >= self.rowCount() - 1 and item.text().strip():
            self.setRowCount(self.rowCount() + 1)   # garde toujours une ligne vide en bas
        self.modifie.emit()

    def _valider(self, item: QTableWidgetItem) -> None:
        texte = item.text().strip()
        invalide = bool(texte) and item.column() in self._numeriques and parse_nombre(texte) is None
        self.blockSignals(True)
        item.setForeground(theme.qcolor("statut_rejet") if invalide else theme.qcolor("text"))
        item.setToolTip("Cette valeur n'est pas un nombre : elle sera ignorée." if invalide else "")
        self.blockSignals(False)

    def _valider_tout(self) -> None:
        for r in range(self.rowCount()):
            for c in range(self.columnCount()):
                item = self.item(r, c)
                if item is not None:
                    self._valider(item)
