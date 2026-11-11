"""
Point d'entrée de l'application. Lance la fenêtre principale sur la page d'accueil,
et bascule vers le module choisi via un QStackedWidget — voir la conversation de
conception pour le détail de cette architecture (coquille + modules indépendants).
"""
import sys
import logging
from pathlib import Path

# Doit être importé avant PySide6 : sur certaines machines (conflit de DLL Windows
# entre Qt et le runtime CUDA/MKL de PyTorch), charger Qt en premier fait planter
# (accès mémoire invalide) tout chargement ultérieur de sentence-transformers dans
# le module Base de connaissances. Importer torch ici, une seule fois, avant Qt,
# fixe l'ordre de chargement des DLL pour toute la durée du processus.
import torch  # noqa: F401

from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget, QMessageBox
from PySide6.QtGui import QIcon, QGuiApplication
from PySide6.QtCore import Qt

from core import database
from core import theme
from core.logs import configurer_logs, installer_gestionnaire_erreurs_global, LOG_PATH
from home import HomePage
from modules.qualite.shell import QualiteModule
from modules.connaissances.shell import ConnaissancesModule

ICON_PATH = Path(__file__).parent / "assets" / "icon.ico"


def _corriger_icone_barre_des_taches_windows():
    """Tant que l'appli tourne via 'python main.py' (pas encore empaquetée en .exe),
    Windows affiche l'icône de l'interpréteur Python dans la barre des tâches au lieu
    de la nôtre. Lui donner un identifiant d'application propre corrige ça. Une fois
    empaquetée avec PyInstaller (--icon=assets/icon.ico), l'exécutable aura de toute
    façon sa propre icône et cet appel devient superflu mais reste inoffensif."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("biocentral.qualite.app")
        except Exception:
            pass


def _dimensionner_fenetre(window: QMainWindow) -> None:
    """Taille et taille minimale calculées à partir de l'écran réel du poste, pas de
    valeurs fixes : sur un petit écran (portable), la fenêtre restaurée (touche
    « rétablir ») ne dépasse jamais l'espace disponible ; sur un grand écran, elle
    ne reste pas plaquée à une taille ridiculement petite. L'application s'ouvre de
    toute façon maximisée par défaut (voir main()) : ceci ne joue que lorsque
    l'utilisateur quitte le plein écran."""
    ecran = QGuiApplication.primaryScreen()
    disponible = ecran.availableGeometry() if ecran else None
    if disponible is None:
        window.resize(1200, 800)
        return
    largeur = min(1200, int(disponible.width() * 0.85))
    hauteur = min(800, int(disponible.height() * 0.85))
    window.resize(largeur, hauteur)
    window.setMinimumSize(min(1000, disponible.width()), min(650, disponible.height()))


class MainWindow(QMainWindow):
    def __init__(self, conn):
        super().__init__()
        self.setWindowTitle("BioCentral")
        _dimensionner_fenetre(self)

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.home = HomePage(conn)
        self.home.module_selected.connect(self._ouvrir_module)
        self.home.demande_fermeture.connect(self._fermer_apres_import)
        self.stack.addWidget(self.home)

        self.modules = {}
        self.conn = conn

    MODULES_DISPONIBLES = {
        "qualite": QualiteModule,
        "connaissances": ConnaissancesModule,
    }

    def _ouvrir_module(self, module_id: str):
        if module_id not in self.modules:
            classe_module = self.MODULES_DISPONIBLES.get(module_id)
            if classe_module is None:
                return  # futur module non encore implémenté
            module_widget = classe_module(self.conn)
            module_widget.retour_accueil.connect(self._retour_accueil)
            self.modules[module_id] = module_widget
            self.stack.addWidget(module_widget)
        self.stack.setCurrentWidget(self.modules[module_id])

    def _retour_accueil(self):
        self.stack.setCurrentWidget(self.home)

    def _fermer_apres_import(self):
        QApplication.instance().quit()


def main():
    configurer_logs()
    installer_gestionnaire_erreurs_global()
    _corriger_icone_barre_des_taches_windows()

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.stylesheet("light"))  # thème par défaut, avant de connaître la préférence enregistrée
    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))

    try:
        conn = database.get_connection()
    except Exception:
        logging.exception("Échec au tout premier démarrage (connexion à la base)")
        QMessageBox.critical(
            None, "Impossible de démarrer",
            "BioCentral n'a pas pu accéder à sa base de données.\n\n"
            f"Détails enregistrés dans :\n{LOG_PATH}\n\n"
            "Transmettez ce fichier pour obtenir de l'aide.",
        )
        sys.exit(1)

    theme.ThemeManager.instance().load(conn)

    window = MainWindow(conn)
    if ICON_PATH.exists():
        window.setWindowIcon(QIcon(str(ICON_PATH)))
    window.showMaximized()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
