"""
Graphique générique dessiné directement avec QPainter : nuages de points,
courbes, droites, lignes de repère, bandes colorées, barres.

Pourquoi ne pas utiliser QtCharts ici (il reste utilisé pour les histogrammes et
anneaux du tableau de bord) : les graphiques de laboratoire — carte de
Levey-Jennings, diagramme de Bland-Altman, droite de Passing-Bablok — demandent
des zones colorées, des repères étiquetés dans la marge, une couleur par point
et des info-bulles par point, que QtCharts ne sait faire qu'au prix de
contorsions. Ce widget les traite tous avec la même mécanique.

Les couleurs peuvent être données sous forme de QColor, de code « #RRGGBB », ou
de clé de la palette du thème (ex. "accent_text") : dans ce dernier cas elles
suivent le thème clair/sombre, y compris à l'export (toujours sur fond clair).
"""
import math
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from core import theme

RAYON_SURVOL = 10  # distance (px) en dessous de laquelle un point est considéré comme survolé


def graduations(vmin: float, vmax: float, nombre: int = 6) -> list[float]:
    """Graduations « rondes » (1, 2, 2.5 ou 5 × 10^k) couvrant [vmin ; vmax]."""
    if not (math.isfinite(vmin) and math.isfinite(vmax)):
        return []
    if vmax <= vmin:
        return [vmin]
    brut = (vmax - vmin) / max(nombre - 1, 1)
    puissance = 10 ** math.floor(math.log10(brut))
    fraction = brut / puissance
    pas = (1 if fraction <= 1 else 2 if fraction <= 2 else 2.5 if fraction <= 2.5 else 5 if fraction <= 5 else 10) * puissance
    debut = math.ceil(vmin / pas - 1e-9) * pas
    valeurs = []
    v = debut
    while v <= vmax + pas * 1e-9:
        valeurs.append(0.0 if abs(v) < pas * 1e-9 else v)
        v += pas
    return valeurs


def etiquette_graduation(v: float, pas: float) -> str:
    decimales = 0 if pas >= 1 else min(8, int(math.ceil(-math.log10(pas) - 1e-9)))
    if pas >= 1 and abs(pas - round(pas)) > 1e-9:
        decimales = 1  # pas de 2.5
    return f"{v:.{decimales}f}"


@dataclass
class _Points:
    xs: list
    ys: list
    couleur: object = "accent_graph"
    couleurs: list | None = None      # une couleur par point (prioritaire sur `couleur`)
    taille: float = 7.0
    forme: str = "o"                  # "o" rond, "s" carré, "^" triangle, "x" croix
    creux: list | bool = False        # point non rempli (bool global ou liste par point)
    infobulles: list | None = None
    ids: list | None = None
    nom: str | None = None
    contour: object = None


@dataclass
class _Ligne:
    xs: list
    ys: list
    couleur: object = "accent_graph"
    epaisseur: float = 1.6
    tirets: bool = False
    nom: str | None = None


@dataclass
class _Droite:
    pente: float
    ordonnee: float
    couleur: object = "accent_graph"
    epaisseur: float = 1.8
    tirets: bool = False
    nom: str | None = None


@dataclass
class _Repere:
    position: float
    couleur: object = "muted"
    epaisseur: float = 1.0
    tirets: bool = True
    etiquette: str | None = None
    inclure: bool = True              # participe au calcul automatique des limites d'axe


@dataclass
class _Barres:
    gauches: list
    droites: list
    hauteurs: list
    couleur: object = "accent_graph"
    infobulles: list | None = None


@dataclass
class _Etat:
    points: list = field(default_factory=list)
    lignes: list = field(default_factory=list)
    droites: list = field(default_factory=list)
    reperes_h: list = field(default_factory=list)
    reperes_v: list = field(default_factory=list)
    bandes_h: list = field(default_factory=list)      # (y0, y1, couleur, alpha)
    bandes: list = field(default_factory=list)        # (xs, ys_bas, ys_haut, couleur, alpha)
    barres: list = field(default_factory=list)


class PlotWidget(QWidget):
    point_clique = Signal(object)   # identifiant (ids) du point cliqué, s'il en a un

    def __init__(self, titre_x: str = "", titre_y: str = "", parent=None):
        super().__init__(parent)
        self.titre_x = titre_x
        self.titre_y = titre_y
        self.message_vide = "Aucune donnée à afficher"
        self._etat = _Etat()
        self._limites_forcees: dict[str, float | None] = {"xmin": None, "xmax": None, "ymin": None, "ymax": None}
        self._grad_x: tuple[list, list] | None = None
        self._grad_y_droite: list[tuple[float, str]] = []
        self._zero_y = False
        self._cibles: list[tuple[float, float, int, int]] = []   # (px, py, index série, index point)
        self._cibles_barres: list[tuple[QRectF, str]] = []
        self._survol: tuple[int, int] | None = None
        self._selection = None
        self._theme_force: str | None = None
        self.setMouseTracking(True)
        self.setMinimumHeight(170)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet("background: transparent;")
        theme.ThemeManager.instance().changed.connect(self._sur_theme)

    def _sur_theme(self, _nom=None):
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(520, 300)

    # ------------------------------------------------------------------
    # Construction du graphique
    # ------------------------------------------------------------------
    def effacer(self) -> None:
        self._etat = _Etat()
        self._limites_forcees = {"xmin": None, "xmax": None, "ymin": None, "ymax": None}
        self._grad_x = None
        self._grad_y_droite = []
        self._zero_y = False
        self._survol = None
        self._selection = None
        self.update()

    def ajouter_points(self, xs, ys, couleur="accent_graph", couleurs=None, taille=7.0, forme="o",
                       creux=False, infobulles=None, ids=None, nom=None, contour=None) -> None:
        self._etat.points.append(_Points(list(xs), list(ys), couleur, couleurs, taille, forme, creux,
                                         infobulles, ids, nom, contour))
        self.update()

    def ajouter_ligne(self, xs, ys, couleur="accent_graph", epaisseur=1.6, tirets=False, nom=None) -> None:
        """Ligne brisée reliant les points (xs, ys), en coordonnées du graphique."""
        self._etat.lignes.append(_Ligne(list(xs), list(ys), couleur, epaisseur, tirets, nom))
        self.update()

    def ajouter_droite(self, pente, ordonnee, couleur="accent_graph", epaisseur=1.8, tirets=False, nom=None) -> None:
        """Droite y = ordonnee + pente·x, tracée sur toute la largeur du graphique."""
        self._etat.droites.append(_Droite(pente, ordonnee, couleur, epaisseur, tirets, nom))
        self.update()

    def ajouter_repere_h(self, y, couleur="muted", epaisseur=1.0, tirets=True, etiquette=None, inclure=True) -> None:
        """Ligne horizontale de repère ; son étiquette s'affiche dans la marge de droite."""
        self._etat.reperes_h.append(_Repere(y, couleur, epaisseur, tirets, etiquette, inclure))
        self.update()

    def ajouter_repere_v(self, x, couleur="muted", epaisseur=1.0, tirets=True, etiquette=None, inclure=True) -> None:
        self._etat.reperes_v.append(_Repere(x, couleur, epaisseur, tirets, etiquette, inclure))
        self.update()

    def ajouter_bande_h(self, y0, y1, couleur, alpha: int = 40) -> None:
        """Bande horizontale colorée entre y0 et y1 (zone d'acceptation, etc.)."""
        self._etat.bandes_h.append((min(y0, y1), max(y0, y1), couleur, alpha))
        self.update()

    def ajouter_bande(self, xs, ys_bas, ys_haut, couleur, alpha: int = 40) -> None:
        """Bande entre deux courbes (intervalle de confiance d'une droite, etc.)."""
        self._etat.bandes.append((list(xs), list(ys_bas), list(ys_haut), couleur, alpha))
        self.update()

    def ajouter_barres(self, gauches, droites, hauteurs, couleur="accent_graph", infobulles=None) -> None:
        """Barres verticales posées sur y = 0 (histogramme)."""
        self._etat.barres.append(_Barres(list(gauches), list(droites), list(hauteurs), couleur, infobulles))
        self._zero_y = True
        self.update()

    def definir_limites(self, xmin=None, xmax=None, ymin=None, ymax=None) -> None:
        self._limites_forcees.update({"xmin": xmin, "xmax": xmax, "ymin": ymin, "ymax": ymax})
        self.update()

    def definir_graduations_x(self, positions, etiquettes) -> None:
        """Graduations personnalisées de l'axe des abscisses (ex. dates d'une carte de contrôle)."""
        self._grad_x = (list(positions), [str(e) for e in etiquettes])
        self.update()

    def definir_graduations_droite(self, paires) -> None:
        """Étiquettes supplémentaires dans la marge de droite : liste de (y, texte)."""
        self._grad_y_droite = [(float(y), str(t)) for y, t in paires]
        self.update()

    def selectionner(self, identifiant) -> None:
        """Met en évidence le point portant cet identifiant (None = aucune sélection)."""
        self._selection = identifiant
        self.update()

    @property
    def vide(self) -> bool:
        e = self._etat
        return not (any(p.xs for p in e.points) or any(l.xs for l in e.lignes) or any(b.hauteurs for b in e.barres))

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    def image(self, largeur: int = 900, hauteur: int = 420, echelle: float = 2.0) -> QImage:
        """Rendu hors écran sur fond blanc, avec les couleurs du thème clair —
        pour un rapport PDF ou un fichier PNG, quel que soit le thème à l'écran."""
        img = QImage(int(largeur * echelle), int(hauteur * echelle), QImage.Format_ARGB32)
        img.setDevicePixelRatio(echelle)
        img.fill(QColor("#FFFFFF"))
        self._theme_force = "light"
        try:
            painter = QPainter(img)
            self._dessiner(painter, float(largeur), float(hauteur), memoriser=False)
            painter.end()
        finally:
            self._theme_force = None
        return img

    # ------------------------------------------------------------------
    # Dessin
    # ------------------------------------------------------------------
    def _couleur(self, couleur, alpha: int | None = None) -> QColor:
        if isinstance(couleur, QColor):
            c = QColor(couleur)
        else:
            pal = theme.palette(self._theme_force)
            c = QColor(pal.get(couleur, couleur))
        if alpha is not None:
            c.setAlpha(alpha)
        return c

    def _limites(self) -> tuple[float, float, float, float]:
        e = self._etat
        xs: list[float] = []
        ys: list[float] = []
        for p in e.points:
            xs += p.xs
            ys += p.ys
        for l in e.lignes:
            xs += l.xs
            ys += l.ys
        for b in e.barres:
            xs += b.gauches + b.droites
            ys += b.hauteurs
        for b in e.bandes:
            xs += b[0]
            ys += b[1] + b[2]
        ys += [r.position for r in e.reperes_h if r.inclure]
        xs += [r.position for r in e.reperes_v if r.inclure]
        for y0, y1, _, _ in e.bandes_h:
            ys += [y0, y1]
        xs = [v for v in xs if v is not None and math.isfinite(v)]
        ys = [v for v in ys if v is not None and math.isfinite(v)]
        if self._zero_y:
            ys.append(0.0)

        def borne(valeurs, marge=0.05, plancher_zero=False):
            if not valeurs:
                return 0.0, 1.0
            vmin, vmax = min(valeurs), max(valeurs)
            if vmin == vmax:
                delta = abs(vmin) * 0.1 or 1.0
                return vmin - delta, vmax + delta
            pad = (vmax - vmin) * marge
            return (vmin if plancher_zero and vmin == 0 else vmin - pad), vmax + pad

        xmin, xmax = borne(xs, 0.04)
        ymin, ymax = borne(ys, 0.07, plancher_zero=self._zero_y)
        f = self._limites_forcees
        xmin = f["xmin"] if f["xmin"] is not None else xmin
        xmax = f["xmax"] if f["xmax"] is not None else xmax
        ymin = f["ymin"] if f["ymin"] is not None else ymin
        ymax = f["ymax"] if f["ymax"] is not None else ymax
        if xmax <= xmin:
            xmax = xmin + 1
        if ymax <= ymin:
            ymax = ymin + 1
        return xmin, xmax, ymin, ymax

    def paintEvent(self, event):
        painter = QPainter(self)
        self._dessiner(painter, float(self.width()), float(self.height()), memoriser=True)

    def _dessiner(self, p: QPainter, largeur: float, hauteur: float, memoriser: bool) -> None:
        p.setRenderHint(QPainter.Antialiasing)
        police = QFont(self.font())
        police.setPointSizeF(8.5)
        p.setFont(police)
        fm = QFontMetricsF(police)
        couleur_texte = self._couleur("muted")
        couleur_grille = self._couleur("table_item_border")
        couleur_axe = self._couleur("btn_border")

        if self.vide:
            p.setPen(couleur_texte)
            p.drawText(QRectF(0, 0, largeur, hauteur), Qt.AlignCenter | Qt.TextWordWrap, self.message_vide)
            if memoriser:
                self._cibles, self._cibles_barres = [], []
            return

        e = self._etat
        xmin, xmax, ymin, ymax = self._limites()

        # --- Légende (séries nommées) : calculée d'abord, elle fixe la marge haute ---
        entrees = [(o.nom, o) for o in (e.points + e.lignes + e.droites) if getattr(o, "nom", None)]
        lignes_legende: list[list[tuple[str, object, float]]] = [[]]
        largeur_dispo = largeur - 24
        courant = 0.0
        for nom, objet in entrees:
            w = 22 + fm.horizontalAdvance(nom) + 16
            if courant + w > largeur_dispo and lignes_legende[-1]:
                lignes_legende.append([])
                courant = 0.0
            lignes_legende[-1].append((nom, objet, w))
            courant += w
        hauteur_legende = (fm.height() + 4) * len(lignes_legende) if entrees else 0

        # --- Graduations ---
        nb_y = max(3, int((hauteur - hauteur_legende - 50) / 38))
        grad_y = graduations(ymin, ymax, nb_y)
        pas_y = (grad_y[1] - grad_y[0]) if len(grad_y) > 1 else 1.0
        etiq_y = [etiquette_graduation(v, pas_y) for v in grad_y]
        if self._grad_x is not None:
            grad_x, etiq_x = self._grad_x
        else:
            grad_x = graduations(xmin, xmax, max(3, int(largeur / 90)))
            pas_x = (grad_x[1] - grad_x[0]) if len(grad_x) > 1 else 1.0
            etiq_x = [etiquette_graduation(v, pas_x) for v in grad_x]

        etiquettes_droite = [(r.position, r.etiquette, r.couleur) for r in e.reperes_h if r.etiquette]
        etiquettes_droite += [(y, t, "muted") for y, t in self._grad_y_droite]

        marge_g = 10 + max([fm.horizontalAdvance(t) for t in etiq_y] + [10]) + (fm.height() + 4 if self.titre_y else 0)
        marge_d = 12 + max([fm.horizontalAdvance(t) for _, t, _ in etiquettes_droite] + [0])
        marge_h = 8 + hauteur_legende
        marge_b = 8 + fm.height() + (fm.height() + 4 if self.titre_x else 0)
        zone = QRectF(marge_g, marge_h, max(largeur - marge_g - marge_d, 20), max(hauteur - marge_h - marge_b, 20))

        def X(x: float) -> float:
            return zone.left() + (x - xmin) / (xmax - xmin) * zone.width()

        def Y(y: float) -> float:
            return zone.bottom() - (y - ymin) / (ymax - ymin) * zone.height()

        # --- Bandes de fond + grille ---
        p.save()
        p.setClipRect(zone)
        for y0, y1, couleur, alpha in e.bandes_h:
            p.fillRect(QRectF(zone.left(), Y(y1), zone.width(), Y(y0) - Y(y1)), self._couleur(couleur, alpha))
        p.restore()

        p.setPen(QPen(couleur_grille, 1))
        for v in grad_y:
            if ymin <= v <= ymax:
                p.drawLine(QPointF(zone.left(), Y(v)), QPointF(zone.right(), Y(v)))
        p.setPen(QPen(couleur_axe, 1))
        p.drawLine(zone.bottomLeft(), zone.bottomRight())
        p.drawLine(zone.bottomLeft(), zone.topLeft())

        # --- Étiquettes des axes ---
        p.setPen(couleur_texte)
        for v, t in zip(grad_y, etiq_y):
            if ymin <= v <= ymax:
                p.drawText(QRectF(0, Y(v) - fm.height() / 2, zone.left() - 6, fm.height()),
                           Qt.AlignRight | Qt.AlignVCenter, t)
        derniere_fin = -1e9
        for v, t in zip(grad_x, etiq_x):
            if not (xmin <= v <= xmax):
                continue
            w = fm.horizontalAdvance(t)
            gauche = min(max(X(v) - w / 2, 0), largeur - w)
            if gauche < derniere_fin + 8:
                continue  # évite le chevauchement d'étiquettes trop serrées
            p.drawLine(QPointF(X(v), zone.bottom()), QPointF(X(v), zone.bottom() + 3))
            p.drawText(QRectF(gauche, zone.bottom() + 5, w + 1, fm.height()), Qt.AlignLeft | Qt.AlignVCenter, t)
            derniere_fin = gauche + w
        if self.titre_x:
            p.drawText(QRectF(zone.left(), hauteur - fm.height() - 4, zone.width(), fm.height()),
                       Qt.AlignCenter, self.titre_x)
        if self.titre_y:
            p.save()
            p.translate(fm.height() / 2 + 4, zone.center().y())
            p.rotate(-90)
            p.drawText(QRectF(-zone.height() / 2, -fm.height() / 2, zone.height(), fm.height()),
                       Qt.AlignCenter, self.titre_y)
            p.restore()

        # --- Données (limitées à la zone de tracé) ---
        p.save()
        p.setClipRect(zone.adjusted(-1, -1, 1, 1))

        for xs, bas, haut, couleur, alpha in e.bandes:
            if len(xs) < 2:
                continue
            polygone = QPolygonF([QPointF(X(x), Y(y)) for x, y in zip(xs, haut)]
                                 + [QPointF(X(x), Y(y)) for x, y in zip(reversed(xs), reversed(bas))])
            p.setPen(Qt.NoPen)
            p.setBrush(self._couleur(couleur, alpha))
            p.drawPolygon(polygone)

        cibles_barres: list[tuple[QRectF, str]] = []
        for b in e.barres:
            p.setPen(QPen(self._couleur("card_bg"), 1))
            p.setBrush(self._couleur(b.couleur, 210))
            for k, (g, d, h) in enumerate(zip(b.gauches, b.droites, b.hauteurs)):
                rect = QRectF(X(g), Y(h), X(d) - X(g), Y(0) - Y(h))
                p.drawRect(rect)
                if b.infobulles:
                    cibles_barres.append((rect, b.infobulles[k]))

        for r in e.reperes_h:
            if ymin <= r.position <= ymax:
                p.setPen(self._stylo(r.couleur, r.epaisseur, r.tirets))
                p.drawLine(QPointF(zone.left(), Y(r.position)), QPointF(zone.right(), Y(r.position)))
        for r in e.reperes_v:
            if xmin <= r.position <= xmax:
                p.setPen(self._stylo(r.couleur, r.epaisseur, r.tirets))
                p.drawLine(QPointF(X(r.position), zone.top()), QPointF(X(r.position), zone.bottom()))

        for d in e.droites:
            p.setPen(self._stylo(d.couleur, d.epaisseur, d.tirets))
            p.drawLine(QPointF(X(xmin), Y(d.ordonnee + d.pente * xmin)),
                       QPointF(X(xmax), Y(d.ordonnee + d.pente * xmax)))

        for l in e.lignes:
            if len(l.xs) < 2:
                continue
            chemin = QPainterPath()
            debut = True
            for x, y in zip(l.xs, l.ys):
                if x is None or y is None:
                    debut = True          # une valeur manquante interrompt la ligne
                    continue
                if debut:
                    chemin.moveTo(X(x), Y(y))
                    debut = False
                else:
                    chemin.lineTo(X(x), Y(y))
            p.setPen(self._stylo(l.couleur, l.epaisseur, l.tirets))
            p.setBrush(Qt.NoBrush)
            p.drawPath(chemin)

        cibles: list[tuple[float, float, int, int]] = []
        fond = self._couleur("card_bg")
        for si, s in enumerate(e.points):
            for pi, (x, y) in enumerate(zip(s.xs, s.ys)):
                if x is None or y is None:
                    continue
                px, py = X(x), Y(y)
                couleur = self._couleur(s.couleurs[pi] if s.couleurs else s.couleur)
                creux = s.creux[pi] if isinstance(s.creux, (list, tuple)) else s.creux
                selectionne = (self._selection is not None and s.ids is not None
                               and s.ids[pi] == self._selection)
                survole = self._survol == (si, pi)
                taille = s.taille + (3 if (survole or selectionne) else 0)
                if selectionne:
                    p.setPen(QPen(self._couleur("text"), 1.6))
                    p.setBrush(Qt.NoBrush)
                    p.drawEllipse(QPointF(px, py), taille / 2 + 4, taille / 2 + 4)
                self._dessiner_marqueur(p, px, py, taille, s.forme, couleur, creux, fond,
                                        self._couleur(s.contour) if s.contour is not None else None)
                cibles.append((px, py, si, pi))
        p.restore()

        # --- Étiquettes de la marge de droite ---
        # Deux repères proches (ex. moyenne et cible) auraient des étiquettes
        # superposées : on les écarte verticalement d'au moins une hauteur de ligne.
        visibles = sorted(((Y(y), texte, couleur) for y, texte, couleur in etiquettes_droite if ymin <= y <= ymax),
                          key=lambda e: e[0])
        positions = []
        for py, _, _ in visibles:
            if positions and py < positions[-1] + fm.height():
                py = positions[-1] + fm.height()
            positions.append(py)
        for py, (_, texte, couleur) in zip(positions, visibles):
            p.setPen(self._couleur(couleur))
            p.drawText(QRectF(zone.right() + 5, py - fm.height() / 2, marge_d, fm.height()),
                       Qt.AlignLeft | Qt.AlignVCenter, texte)

        # --- Légende ---
        if entrees:
            y_legende = 4.0
            for ligne in lignes_legende:
                x_legende = zone.left()
                for nom, objet, w in ligne:
                    milieu = y_legende + fm.height() / 2
                    if isinstance(objet, _Points):
                        self._dessiner_marqueur(p, x_legende + 8, milieu, 7, objet.forme,
                                                self._couleur(objet.couleur), False, fond, None)
                    else:
                        p.setPen(self._stylo(objet.couleur, objet.epaisseur, objet.tirets))
                        p.drawLine(QPointF(x_legende, milieu), QPointF(x_legende + 16, milieu))
                    p.setPen(couleur_texte)
                    p.drawText(QRectF(x_legende + 22, y_legende, w, fm.height()),
                               Qt.AlignLeft | Qt.AlignVCenter, nom)
                    x_legende += w
                y_legende += fm.height() + 4

        if memoriser:
            self._cibles = cibles
            self._cibles_barres = cibles_barres

    def _stylo(self, couleur, epaisseur: float, tirets: bool) -> QPen:
        stylo = QPen(self._couleur(couleur), epaisseur)
        if tirets:
            stylo.setStyle(Qt.DashLine)
        stylo.setCapStyle(Qt.RoundCap)
        stylo.setJoinStyle(Qt.RoundJoin)
        return stylo

    @staticmethod
    def _dessiner_marqueur(p: QPainter, x: float, y: float, taille: float, forme: str,
                           couleur: QColor, creux: bool, fond: QColor, contour: QColor | None) -> None:
        r = taille / 2
        if forme == "x":
            p.setPen(QPen(couleur, 1.8))
            p.drawLine(QPointF(x - r, y - r), QPointF(x + r, y + r))
            p.drawLine(QPointF(x - r, y + r), QPointF(x + r, y - r))
            return
        p.setPen(QPen(contour if contour is not None else couleur, 1.4 if (creux or contour is not None) else 1.0))
        p.setBrush(fond if creux else couleur)
        if forme == "s":
            p.drawRect(QRectF(x - r, y - r, taille, taille))
        elif forme == "^":
            p.drawPolygon(QPolygonF([QPointF(x, y - r * 1.15), QPointF(x + r * 1.1, y + r * 0.9),
                                     QPointF(x - r * 1.1, y + r * 0.9)]))
        else:
            p.drawEllipse(QPointF(x, y), r, r)

    # ------------------------------------------------------------------
    # Interaction
    # ------------------------------------------------------------------
    def _point_proche(self, pos) -> tuple[int, int] | None:
        meilleur, distance = None, RAYON_SURVOL ** 2
        for px, py, si, pi in self._cibles:
            d = (px - pos.x()) ** 2 + (py - pos.y()) ** 2
            if d <= distance:
                meilleur, distance = (si, pi), d
        return meilleur

    def mouseMoveEvent(self, event):
        pos = event.position()
        proche = self._point_proche(pos)
        if proche != self._survol:
            self._survol = proche
            self.update()
        if proche is not None:
            serie = self._etat.points[proche[0]]
            if serie.infobulles:
                QToolTip.showText(event.globalPosition().toPoint(), serie.infobulles[proche[1]], self)
                return
        for rect, texte in self._cibles_barres:
            if rect.contains(pos):
                QToolTip.showText(event.globalPosition().toPoint(), texte, self)
                return
        QToolTip.hideText()

    def leaveEvent(self, event):
        if self._survol is not None:
            self._survol = None
            self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            proche = self._point_proche(event.position())
            if proche is not None:
                serie = self._etat.points[proche[0]]
                if serie.ids is not None:
                    self.point_clique.emit(serie.ids[proche[1]])
        super().mousePressEvent(event)
