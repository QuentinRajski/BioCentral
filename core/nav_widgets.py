"""
Petits éléments de navigation partagés par les coquilles de module (barre
latérale + fil d'Ariane) — évite de dupliquer ces détails de mise en forme
dans chaque module.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from .theme_toggle import ThemeToggleButton


def section_label(texte: str) -> QLabel:
    """Étiquette de section dans une barre latérale (ex. « NAVIGATION »)."""
    label = QLabel(texte.upper())
    label.setObjectName("SectionSidebar")
    return label


def breadcrumb_label() -> QLabel:
    """Fil d'Ariane affiché en haut de la zone de contenu d'un module — son texte
    est mis à jour par la coquille à chaque changement de vue."""
    label = QLabel()
    label.setObjectName("Breadcrumb")
    return label


def entete_barre_laterale(conn, on_retour) -> QWidget:
    """Ligne d'en-tête commune à toutes les barres latérales de module : icône
    « maison » ronde pour revenir à l'accueil (même langage visuel que le bouton
    de thème, plutôt qu'un gros bouton de couleur ou un lien texte qui détonnent
    à côté des vraies actions du module) + bouton de thème, aligné à droite."""
    conteneur = QWidget()
    conteneur.setStyleSheet("background: transparent;")
    ligne = QHBoxLayout(conteneur)
    ligne.setContentsMargins(0, 0, 0, 0)
    btn_retour = QPushButton("🏠")
    btn_retour.setObjectName("ToggleTheme")
    btn_retour.setFixedSize(34, 34)
    btn_retour.setCursor(Qt.PointingHandCursor)
    btn_retour.setToolTip("Retour à l'accueil")
    btn_retour.clicked.connect(on_retour)
    ligne.addWidget(btn_retour)
    ligne.addStretch()
    ligne.addWidget(ThemeToggleButton(conn))
    return conteneur
