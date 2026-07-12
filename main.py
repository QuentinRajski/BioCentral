"""
Point d'entrée de l'application. Lance la fenêtre principale sur la page d'accueil,
et bascule vers le module choisi via un QStackedWidget — voir la conversation de
conception pour le détail de cette architecture (coquille + modules indépendants).
"""
import sys
import logging
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget, QMessageBox
from PySide6.QtGui import QIcon, QGuiApplication
from PySide6.QtCore import Qt

from core import database
from core.theme import STYLESHEET
from core.logs import configurer_logs, installer_gestionnaire_erreurs_global, LOG_PATH
from home import HomePage
from modules.qualite.shell import QualiteModule

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


class MainWindow(QMainWindow):
    def __init__(self, conn):
        super().__init__()
        self.setWindowTitle("BioCentral")
        self.resize(1200, 800)

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.home = HomePage(conn)
        self.home.module_selected.connect(self._ouvrir_module)
        self.home.demande_fermeture.connect(self._fermer_apres_import)
        self.stack.addWidget(self.home)

        self.modules = {}
        self.conn = conn

    def _ouvrir_module(self, module_id: str):
        if module_id not in self.modules:
            if module_id == "qualite":
                module_widget = QualiteModule(self.conn)
                module_widget.retour_accueil.connect(self._retour_accueil)
                self.modules[module_id] = module_widget
                self.stack.addWidget(module_widget)
            else:
                return  # futur module non encore implémenté
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
    app.setStyleSheet(STYLESHEET)
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

    window = MainWindow(conn)
    if ICON_PATH.exists():
        window.setWindowIcon(QIcon(str(ICON_PATH)))
    window.showMaximized()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
