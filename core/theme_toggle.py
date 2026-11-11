"""
Bouton de bascule clair/sombre, réutilisable partout dans l'application (page
d'accueil, en-tête de barre latérale de chaque module). Icône compacte plutôt
qu'un bouton pleine largeur : dans un coin, comme le réglage d'une vraie appli,
il ne vient pas concurrencer les vrais boutons de navigation/action. Chaque
instance reste synchronisée avec les autres : basculer le thème depuis l'une
met à jour l'icône de toutes les autres, via le signal partagé de ThemeManager.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton

from .theme import ThemeManager

ICONES = {"light": "🌙", "dark": "☀"}
INFOBULLES = {"light": "Passer en mode sombre", "dark": "Passer en mode clair"}
TAILLE = 34


class ThemeToggleButton(QPushButton):
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.setObjectName("ToggleTheme")
        self.setFixedSize(TAILLE, TAILLE)
        self.setCursor(Qt.PointingHandCursor)
        self._rafraichir(ThemeManager.instance().name)
        self.clicked.connect(self._basculer)
        ThemeManager.instance().changed.connect(self._rafraichir)

    def _basculer(self):
        ThemeManager.instance().toggle(self.conn)

    def _rafraichir(self, nom: str):
        self.setText(ICONES[nom])
        self.setToolTip(INFOBULLES[nom])
