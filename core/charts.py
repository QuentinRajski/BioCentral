"""
Aide à la construction de graphiques natifs, avec QtCharts (module Qt natif,
pas de dépendance matplotlib). Réutilisable par n'importe quel module — ces
fonctions ne connaissent rien du module Contrôle Qualité, elles prennent des
listes/dicts de valeurs déjà calculées et rendent un QChartView prêt à poser
dans une mise en page.
"""
import random

from PySide6.QtCharts import (
    QChart, QChartView, QBarSeries, QBarSet, QBarCategoryAxis, QValueAxis, QPieSeries,
    QAbstractBarSeries, QLineSeries, QDateTimeAxis,
)
from PySide6.QtGui import QPainter, QColor, QCursor, QPen, QFont
from PySide6.QtCore import Qt, QMargins, QRectF, QDateTime, QDate, QTime
from PySide6.QtWidgets import QToolTip, QWidget

COULEUR_PRINCIPALE = QColor("#378ADD")
COULEUR_SECONDAIRE = QColor("#6B9E7C")  # vert doux, pour distinguer l'histogramme des âges
COULEUR_ACCENT = QColor("#0C447C")
PALETTE_CATEGORIES = [QColor(c) for c in ["#378ADD", "#7F77DD", "#D4537E", "#1D9E75", "#D8A930", "#8A887E"]]


def _chart_view(chart: QChart) -> QChartView:
    chart.setBackgroundVisible(False)
    chart.setMargins(QMargins(4, 4, 4, 4))
    chart.setContentsMargins(0, 0, 0, 0)
    view = QChartView(chart)
    view.setRenderHint(QPainter.Antialiasing)
    view.setFixedHeight(160)
    view.setStyleSheet("background: transparent; border: none;")
    return view


def _format_bin_edge(v: float, decimales: bool) -> str:
    return f"{v:.1f}" if decimales else f"{v:.0f}"


def build_histogram(values: list[float], n_bins: int = 8, couleur: QColor = COULEUR_PRINCIPALE) -> QChartView:
    """Histogramme avec les plages de valeurs en abscisse, l'effectif sur chaque
    barre, et une info-bulle au survol rappelant plage + effectif exacts."""
    chart = QChart()
    chart.legend().setVisible(False)
    if not values:
        return _chart_view(chart)

    vmin, vmax = min(values), max(values)
    if vmin == vmax:
        vmax = vmin + 1  # évite une largeur de bin nulle si toutes les valeurs sont identiques
    largeur = (vmax - vmin) / n_bins
    comptes = [0] * n_bins
    for v in values:
        idx = min(int((v - vmin) / largeur), n_bins - 1)
        comptes[idx] += 1

    decimales = (vmax - vmin) < 10  # ex. valeurs de paramètre (0.3–11.2) vs âges (entiers)
    labels_bins = [
        f"{_format_bin_edge(vmin + i * largeur, decimales)}–{_format_bin_edge(vmin + (i + 1) * largeur, decimales)}"
        for i in range(n_bins)
    ]

    bar_set = QBarSet("")
    bar_set.append(comptes)
    bar_set.setColor(couleur)
    bar_set.setBorderColor(couleur)
    bar_set.setLabelColor(QColor("#5F5E5A"))

    series = QBarSeries()
    series.append(bar_set)
    series.setBarWidth(0.9)
    series.setLabelsVisible(True)
    series.setLabelsFormat("@value")
    series.setLabelsPosition(QAbstractBarSeries.LabelsOutsideEnd)

    def _survol(status: bool, index: int, _barset):
        if status and 0 <= index < len(labels_bins):
            QToolTip.showText(QCursor.pos(), f"{labels_bins[index]} : {comptes[index]} échantillon(s)")

    series.hovered.connect(_survol)
    chart.addSeries(series)

    axis_x = QBarCategoryAxis()
    axis_x.append(labels_bins)
    axis_x.setLabelsVisible(True)
    axis_x.setLineVisible(False)
    axis_x.setGridLineVisible(False)
    font_axe = axis_x.labelsFont()
    font_axe.setPointSize(8)
    axis_x.setLabelsFont(font_axe)
    axis_x.setLabelsColor(QColor("#8A887E"))
    chart.addAxis(axis_x, Qt.AlignBottom)
    series.attachAxis(axis_x)

    axis_y = QValueAxis()
    axis_y.setLabelsVisible(False)
    axis_y.setGridLineVisible(False)
    axis_y.setLineVisible(False)
    axis_y.setRange(0, max(1, max(comptes)) * 1.25)  # marge en haut pour les étiquettes de valeur
    chart.addAxis(axis_y, Qt.AlignLeft)
    series.attachAxis(axis_y)

    return _chart_view(chart)


def build_pie(categories: dict) -> QChartView:
    """Camembert (anneau) à partir d'un dict {libellé: effectif}. Légende avec
    effectif ET pourcentage, info-bulle au survol de chaque part."""
    chart = QChart()
    if not categories or not sum(categories.values()):
        chart.legend().setVisible(False)
        return _chart_view(chart)

    total = sum(v for v in categories.values() if v > 0)

    series = QPieSeries()
    series.setHoleSize(0.45)
    for i, (label, valeur) in enumerate(categories.items()):
        if valeur <= 0:
            continue
        pct = round(valeur / total * 100)
        part = series.append(f"{label} ({valeur} | {pct}%)", valeur)
        part.setColor(PALETTE_CATEGORIES[i % len(PALETTE_CATEGORIES)])
        part.setBorderWidth(0)
        part.setLabelVisible(False)

        def _survol(state: bool, slice_=part):
            if state:
                QToolTip.showText(QCursor.pos(), slice_.label())

        part.hovered.connect(_survol)

    chart.addSeries(series)
    chart.legend().setVisible(True)
    chart.legend().setAlignment(Qt.AlignRight)
    chart.legend().setFont(chart.legend().font())

    return _chart_view(chart)


class BoiteAMoustachesHorizontale(QWidget):
    """
    Boîte à moustaches horizontale, dessinée directement (QtCharts ne sait la
    tracer qu'à la verticale) : mieux adaptée à une carte large et courte.
    P5/P95 = moustaches, P25/P75 = boîte, trait épais = médiane. Les valeurs
    individuelles sont superposées en points semi-transparents (léger tremblement
    vertical pour limiter la superposition exacte des points), pour voir la vraie
    répartition des données derrière le résumé statistique.
    """
    def __init__(self):
        super().__init__()
        self.result = None
        self.valeurs: list[float] = []
        self.setMinimumHeight(140)
        self.setStyleSheet("background: transparent;")

    def set_result(self, result, valeurs: list[float] | None = None) -> None:
        self.result = result
        self.valeurs = valeurs or []
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if self.result is None:
            return

        p = self.result.percentiles
        p5, p25, med, p75, p95 = p[5], p[25], self.result.mediane, p[75], p[95]
        etendue = (p95 - p5) or 1

        marge = 42
        largeur = max(self.width() - 2 * marge, 10)
        # La boîte s'adapte à la hauteur réelle du widget (marge haute pour les
        # étiquettes de la boîte, marge basse pour celles des moustaches).
        demi_boite = min(max(int((self.height() - 65) / 2), 15), 90)
        y = 45 + demi_boite  # ancré près du haut (sous le titre), pas centré dans tout le bloc

        def x_de(valeur: float) -> float:
            return marge + (valeur - p5) / etendue * largeur

        # Points individuels, semi-transparents, avec un léger tremblement vertical
        # pour distinguer les valeurs proches — dessinés en premier, sous la boîte.
        if self.valeurs:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(12, 68, 124, 45))
            rng = random.Random(42)  # graine fixe : le nuage de points ne "saute" pas à chaque rafraîchissement
            zone = demi_boite + 22
            for v in self.valeurs:
                v_bornee = min(max(v, p5), p95)
                jitter = rng.uniform(-zone, zone)
                painter.drawEllipse(QRectF(x_de(v_bornee) - 2.5, y + jitter - 2.5, 5, 5))

        font = painter.font()
        font.setPointSize(10)
        painter.setFont(font)

        stylo = QPen(COULEUR_ACCENT)
        stylo.setWidth(2)
        painter.setPen(stylo)

        # Moustaches (P5 -> P25 et P75 -> P95) + butées verticales aux extrémités
        painter.drawLine(int(x_de(p5)), y, int(x_de(p25)), y)
        painter.drawLine(int(x_de(p75)), y, int(x_de(p95)), y)
        painter.drawLine(int(x_de(p5)), y - demi_boite // 2, int(x_de(p5)), y + demi_boite // 2)
        painter.drawLine(int(x_de(p95)), y - demi_boite // 2, int(x_de(p95)), y + demi_boite // 2)

        # Boîte (P25 -> P75)
        painter.setBrush(QColor(181, 212, 244, 235))
        painter.drawRect(QRectF(x_de(p25), y - demi_boite, x_de(p75) - x_de(p25), demi_boite * 2))

        # Médiane
        stylo_median = QPen(COULEUR_ACCENT)
        stylo_median.setWidth(3)
        painter.setPen(stylo_median)
        painter.drawLine(int(x_de(med)), y - demi_boite, int(x_de(med)), y + demi_boite)

        # Étiquettes du haut (P25, médiane, P75) : décalées en cascade si les valeurs
        # sont proches les unes des autres, pour ne jamais se chevaucher.
        painter.setPen(QColor("#8A887E"))
        metriques = painter.fontMetrics()
        hautes = sorted([p25, med, p75])
        fin_precedente = None
        niveau = 0
        for v in hautes:
            texte = str(v)
            largeur_texte = metriques.horizontalAdvance(texte)
            debut = x_de(v) - largeur_texte / 2
            if fin_precedente is not None and debut < fin_precedente + 6:
                niveau += 1
            else:
                niveau = 0
            fin_precedente = debut + largeur_texte
            painter.drawText(int(debut), y - demi_boite - 8 - niveau * 13, texte)

        # Étiquettes du bas (P5, P95), jamais proches l'une de l'autre en pratique
        for v in (p5, p95):
            texte = str(v)
            largeur_texte = metriques.horizontalAdvance(texte)
            painter.drawText(int(x_de(v) - largeur_texte / 2), y + demi_boite + 16, texte)


def build_boxplot(result, valeurs: list[float] | None = None):
    """Retourne un widget prêt à poser dans une mise en page (pas un QChartView)."""
    widget = BoiteAMoustachesHorizontale()
    widget.set_result(result, valeurs)
    return widget


def build_temporal(paires_date_valeur: list[tuple[str, float]]) -> QChartView:
    """
    Évolution du résultat dans le temps (date de prélèvement en abscisse), dans
    l'esprit d'une carte de contrôle — utile pour repérer une dérive progressive,
    ce qu'aucun autre graphique de la page ne montre (tous les autres sont une
    photo à un instant donné du sous-ensemble filtré).
    """
    chart = QChart()
    chart.legend().setVisible(False)
    if not paires_date_valeur:
        return _chart_view(chart)

    paires = sorted(paires_date_valeur, key=lambda pv: pv[0])

    series = QLineSeries()
    pen = QPen(COULEUR_PRINCIPALE)
    pen.setWidth(2)
    series.setPen(pen)
    for date_iso, valeur in paires:
        try:
            annee, mois, jour = (int(x) for x in date_iso.split("-"))
        except (ValueError, AttributeError):
            continue
        instant = QDateTime(QDate(annee, mois, jour), QTime(0, 0, 0))
        series.append(instant.toMSecsSinceEpoch(), valeur)
    chart.addSeries(series)

    axis_x = QDateTimeAxis()
    axis_x.setFormat("dd/MM/yy")
    axis_x.setLabelsColor(QColor("#8A887E"))
    axis_x.setGridLineVisible(False)
    font_axe = axis_x.labelsFont()
    font_axe.setPointSize(8)
    axis_x.setLabelsFont(font_axe)
    chart.addAxis(axis_x, Qt.AlignBottom)
    series.attachAxis(axis_x)

    axis_y = QValueAxis()
    axis_y.setLabelsColor(QColor("#8A887E"))
    axis_y.setGridLineVisible(False)
    chart.addAxis(axis_y, Qt.AlignLeft)
    series.attachAxis(axis_y)

    return _chart_view(chart)
